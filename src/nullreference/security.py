import time

from .core.theme import RuleError
from .themes.mafia.commands import authorize


def signature_parts(public_key, timestamp, signature, body, now=None):
    now = time.time() if now is None else now
    if abs(now - int(timestamp)) > 300:
        raise ValueError("Expired signature")
    key, sig = bytes.fromhex(public_key), bytes.fromhex(signature)
    if len(key) != 32 or len(sig) != 64:
        raise ValueError("Invalid signature")
    return key, sig, timestamp.encode() + body


def modal(payload, defaults):
    authorize(payload, "flavour_edit")
    _, operation, key, owner = payload["data"]["custom_id"].split(":", 3)
    if operation != "open" or owner != payload["member"]["user"]["id"] or key not in defaults:
        raise RuleError("Это чужая или устаревшая форма")
    # The original ephemeral message comes from a signed Discord interaction.
    # Its embed carries the template so opening a modal never waits for a cold DB.
    embed = payload["message"]["embeds"][0]
    if embed.get("title") != key:
        raise RuleError("Неверная форма")
    return {
        "type": 9,
        "data": {
            "title": "Редактирование текста",
            "custom_id": f"flavour:save:{key}:{owner}",
            "components": [
                {
                    "type": 1,
                    "components": [
                        {
                            "type": 4,
                            "custom_id": "text",
                            "style": 2,
                            "label": key[:45],
                            "value": embed["description"][:1400],
                            "required": True,
                            "min_length": 1,
                            "max_length": 1400,
                        }
                    ],
                }
            ],
        },
    }
