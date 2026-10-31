"""Exercise a running workerd with RFC 8032 test credentials, never production secrets."""

import json
import os
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

KEY = bytes.fromhex("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60")
BASE = os.environ.get("WORKER_TEST_URL", "http://127.0.0.1:8787")


def send(payload, signed=True, timestamp=None):
    body = json.dumps(payload, ensure_ascii=False).encode()
    stamp = timestamp or str(int(time.time()))
    signature = Ed25519PrivateKey.from_private_bytes(KEY).sign(stamp.encode() + body).hex()
    request = Request(
        BASE + "/interactions",
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-Signature-Timestamp": stamp,
            "X-Signature-Ed25519": signature if signed else "00" * 64,
        },
    )
    try:
        with urlopen(request, timeout=30) as result:
            return result.status, json.load(result)
    except HTTPError as exc:
        return exc.code, json.load(exc)


if __name__ == "__main__":
    with urlopen(BASE + "/health", timeout=30) as result:
        assert result.status == 200
    ping = {"type": 1, "application_id": "123"}
    assert send(ping) == (200, {"type": 1})
    assert send(ping, signed=False)[0] == 401
    assert send(ping, timestamp="1000")[0] == 401
    assert send({"type": 1, "application_id": "999"})[0] == 403
    unauthorized = {
        "id": "1",
        "application_id": "123",
        "guild_id": "456",
        "type": 2,
        "member": {"user": {"id": "1"}, "permissions": "0"},
        "data": {"name": "reward"},
    }
    assert send(unauthorized)[1]["type"] == 4
    print(
        "workerd smoke checks passed: health, Ed25519 PING, bad signature, replay, app and admin checks."
    )
