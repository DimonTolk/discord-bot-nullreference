"""Production Workers Builds command. Runtime secrets are configured separately."""

import os
import sys

from build import main as build
from migrate import migrate
from register_commands import register
from prepare_worker import package, verify_vendor, wrangler


def main():
    required = ("DATABASE_URL", "DISCORD_TOKEN", "DISCORD_APPLICATION_ID", "DISCORD_GUILD_ID")
    if any(not os.environ.get(key) for key in required):
        print(
            "Missing build secrets/settings: "
            + ", ".join(k for k in required if not os.environ.get(k)),
            file=sys.stderr,
        )
        return 1
    try:
        build()
        verify_vendor()
        package()
        migrate()
        # Publish only after migrations succeed. shell=False; no secrets in process arguments.
        # Packaging is already complete and verified. Do not let a second
        # pywrangler sync replace the SDK directory before the actual upload.
        wrangler("deploy")
        register()
    except Exception as exc:
        print(
            f"Deploy failed ({type(exc).__name__}). No secret values are printed.", file=sys.stderr
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
