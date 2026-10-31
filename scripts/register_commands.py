import json
import os
import sys
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def register():
    from nullreference.themes.mafia.commands import manifest

    token, app, guild = (
        os.environ.get(k, "")
        for k in ("DISCORD_TOKEN", "DISCORD_APPLICATION_ID", "DISCORD_GUILD_ID")
    )
    if not token or not app.isdecimal() or not guild.isdecimal():
        raise ValueError("Set Discord build secrets/settings")
    request = Request(
        f"https://discord.com/api/v10/applications/{app}/guilds/{guild}/commands",
        data=json.dumps(manifest(), ensure_ascii=False).encode(),
        method="PUT",
        headers={
            "Authorization": "Bot " + token,
            "Content-Type": "application/json",
            "User-Agent": "NullreferenceBot/0.2",
        },
    )
    with urlopen(request, timeout=30) as result:
        if result.status != 200:
            raise ValueError("Command registration failed")
    print("Discord commands registered.")


if __name__ == "__main__":
    try:
        register()
    except Exception as exc:
        print(
            f"Command registration failed ({type(exc).__name__}); check build settings.",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
