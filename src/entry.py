import asyncio
import json
from urllib.parse import urlsplit

from workers import Response, WorkerEntrypoint, fetch, wait_until

from nullreference.application import Application
from nullreference.core.config import Config
from nullreference.core.http import DiscordHTTP, NeonHTTP
from nullreference.core.theme import RuleError
from nullreference.security import modal, signature_parts
from nullreference.themes.mafia.commands import authorize
from nullreference.themes.mafia.texts import DEFAULTS
from nullreference.visibility import deferred_response
from nullreference.themes.mafia.casino import component_action
from nullreference.themes.mafia.night_shift import button_action


def response(data, status=200):
    return Response(
        json.dumps(data, ensure_ascii=False),
        status=status,
        headers={"Content-Type": "application/json", "Cache-Control": "no-store"},
    )


async def verify(key, timestamp, signature, body):
    from js import crypto
    from pyodide.ffi import to_js

    try:
        raw_key, sig, signed = signature_parts(key, timestamp, signature, body)
        public_key = await crypto.subtle.importKey(
            "raw", to_js(memoryview(raw_key)), "Ed25519", False, to_js(["verify"])
        )
        return bool(
            await crypto.subtle.verify(
                "Ed25519", public_key, to_js(memoryview(sig)), to_js(memoryview(signed))
            )
        )
    except Exception:
        return False


class Default(WorkerEntrypoint):
    def application(self):
        config = Config.from_env(self.env)
        return Application(
            config, NeonHTTP(config.database_url, fetch), DiscordHTTP(config.token, fetch)
        )

    async def fetch(self, request):
        path = urlsplit(request.url).path
        if request.method == "GET" and path in ("/", "/health"):
            return response({"service": "nullreference-discord", "status": "ok"})
        if path != "/interactions":
            return response({"error": "not found"}, 404)
        if request.method != "POST":
            return response({"error": "method not allowed"}, 405)
        body = (await request.text()).encode("utf-8")
        if len(body) > 128000:
            return response({"error": "payload too large"}, 413)
        if not await verify(
            str(getattr(self.env, "DISCORD_PUBLIC_KEY", "")),
            request.headers.get("X-Signature-Timestamp", ""),
            request.headers.get("X-Signature-Ed25519", ""),
            body,
        ):
            return response({"error": "invalid signature"}, 401)
        try:
            payload = json.loads(body)
            if str(payload.get("application_id")) != str(
                getattr(self.env, "DISCORD_APPLICATION_ID", "")
            ):
                return response({"error": "wrong application"}, 403)
            if payload["type"] == 1:
                return response({"type": 1})
            if str(payload.get("guild_id")) != str(getattr(self.env, "DISCORD_GUILD_ID", "")):
                return response(
                    {
                        "type": 4,
                        "data": {
                            "content": "Команды доступны только на настроенном сервере.",
                            "flags": 64,
                        },
                    }
                )
            if payload["type"] == 3:
                if payload.get("data", {}).get("custom_id", "").startswith("blackjack:"):
                    component_action(payload)
                elif payload.get("data", {}).get("custom_id", "").startswith("night:"):
                    button_action(payload)
                else:
                    return response(modal(payload, DEFAULTS))
            elif payload["type"] == 2:
                authorize(payload, payload["data"]["name"])
            elif payload["type"] == 5:
                authorize(payload, "flavour_edit")
            else:
                return response({"error": "unsupported interaction"}, 400)
            app = self.application()
            wait_until(asyncio.ensure_future(self.background(app, payload)))
            return response(deferred_response(payload))
        except (RuleError, ValueError, KeyError):
            return response(
                {
                    "type": 4,
                    "data": {
                        "content": "Проверьте права, параметры команды и настройки сервера.",
                        "flags": 64,
                    },
                }
            )

    async def background(self, app, payload):
        try:
            await app.process(payload)
            await app.deliver_news()
        except Exception:
            # Don't expose private interaction payloads or secret-bearing transport exceptions.
            try:
                await app.discord.respond(
                    app.config.application_id,
                    payload["token"],
                    {
                        "content": "Сервис временно недоступен. Проверьте /profile или повторите позже."
                    },
                )
            except Exception:
                pass

    async def scheduled(self, *args):
        try:
            await self.application().maintenance()
        except Exception:
            print("Scheduled maintenance failed; check settings and database availability.")
