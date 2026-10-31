import asyncio
import json
import secrets
from urllib.parse import urlsplit


class ServiceError(Exception):
    """Sanitized transport failure; no URLs, tokens or response bodies."""


class NeonHTTP:
    """Neon SQL-over-HTTP protocol; no sockets, pools or native packages."""

    def __init__(self, url, fetch):
        parsed = urlsplit(url)
        if (
            parsed.scheme not in ("postgres", "postgresql")
            or not parsed.hostname
            or not parsed.hostname.endswith(".neon.tech")
            or not parsed.username
            or not parsed.password
            or not parsed.path.strip("/")
        ):
            raise ValueError("DATABASE_URL must be a Neon PostgreSQL connection URI")
        self.url, self.fetch = url, fetch
        self.endpoint = "https://api." + parsed.hostname.split(".", 1)[1] + "/sql"

    async def query(self, sql, params=()):
        headers = {
            "Content-Type": "application/json",
            "Neon-Connection-String": self.url,
            "Neon-Raw-Text-Output": "true",
            "Neon-Array-Mode": "true",
        }
        params = [
            json.dumps(p, ensure_ascii=False)
            if isinstance(p, (dict, list))
            else None
            if p is None
            else str(p)
            for p in params
        ]
        try:
            response = await asyncio.wait_for(
                self.fetch(
                    self.endpoint,
                    method="POST",
                    headers=headers,
                    body=json.dumps({"query": sql, "params": params}),
                ),
                timeout=12,
            )
            if response.status != 200:
                error = await response.json()
                raise ServiceError("Database query failed: " + str(error.get("code", "unknown")))
            result = await response.json()
            fields = result["fields"]

            def convert(value, oid):
                if value is None:
                    return None
                if oid in (114, 3802):
                    return json.loads(value)
                if oid in (20, 21, 23):
                    return int(value)
                if oid == 16:
                    return value == "t"
                return value

            return [
                {f["name"]: convert(value, f["dataTypeID"]) for f, value in zip(fields, row)}
                for row in result["rows"]
            ]
        except ServiceError:
            raise
        except Exception:
            raise ServiceError("Database transport unavailable") from None


class DiscordHTTP:
    def __init__(self, token, fetch):
        self.token, self.fetch = token, fetch

    async def request(self, method, path, data=None, webhook=False):
        headers = {"Content-Type": "application/json"}
        if not webhook:
            headers["Authorization"] = "Bot " + self.token
        kwargs = {"method": method, "headers": headers}
        if data is not None:
            kwargs["body"] = json.dumps(data, ensure_ascii=False)
        try:
            response = await asyncio.wait_for(
                self.fetch("https://discord.com/api/v10" + path, **kwargs), timeout=8
            )
            if response.status == 404 and method == "GET":
                return None
            if response.status not in (200, 201, 204):
                raise ServiceError(f"Discord request failed ({response.status})")
            return await response.json() if response.status != 204 else None
        except ServiceError:
            raise
        except Exception:
            raise ServiceError("Discord transport unavailable") from None

    async def member(self, guild, user):
        return await self.request("GET", f"/guilds/{guild}/members/{user}")

    async def respond(self, application, token, data):
        data = {**data, "allowed_mentions": {"parse": []}}
        if attachment := data.pop("_file", None):
            boundary = "nullreference-" + secrets.token_hex(12)
            data["attachments"] = [{"id": 0, "filename": "flavour.json"}]
            body = (
                f'--{boundary}\r\nContent-Disposition: form-data; name="payload_json"\r\n'
                "Content-Type: application/json\r\n\r\n"
                + json.dumps(data, ensure_ascii=False)
                + f'\r\n--{boundary}\r\nContent-Disposition: form-data; name="files[0]"; '
                'filename="flavour.json"\r\nContent-Type: application/json\r\n\r\n'
                + attachment
                + f"\r\n--{boundary}--\r\n"
            ).encode("utf-8")
            try:
                result = await asyncio.wait_for(
                    self.fetch(
                        f"https://discord.com/api/v10/webhooks/{application}/{token}/messages/@original",
                        method="PATCH",
                        headers={"Content-Type": "multipart/form-data; boundary=" + boundary},
                        body=body,
                    ),
                    timeout=8,
                )
                if result.status != 200:
                    raise ServiceError("Discord attachment upload failed")
                return None
            except Exception:
                raise ServiceError("Discord attachment transport unavailable") from None
        return await self.request(
            "PATCH", f"/webhooks/{application}/{token}/messages/@original", data, webhook=True
        )
