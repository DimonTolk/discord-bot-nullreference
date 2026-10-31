import hashlib
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def migrate(url=None):
    import psycopg

    url = url or os.environ.get("DATABASE_URL")
    if not url:
        raise ValueError("Set DATABASE_URL in build secrets/environment")
    with psycopg.connect(url, connect_timeout=20) as conn:
        conn.execute("SELECT pg_advisory_xact_lock(92472101)")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations(name TEXT PRIMARY KEY, applied_at TIMESTAMPTZ DEFAULT now(), checksum TEXT)"
        )
        conn.execute("ALTER TABLE schema_migrations ADD COLUMN IF NOT EXISTS checksum TEXT")
        for path in sorted((ROOT / "src/nullreference/migrations").glob("*.sql")):
            sql = path.read_text("utf-8")
            checksum = hashlib.sha256(sql.encode()).hexdigest()
            row = conn.execute(
                "SELECT checksum FROM schema_migrations WHERE name=%s", [path.name]
            ).fetchone()
            if row:
                if row[0] is not None and row[0] != checksum:
                    raise ValueError("Applied migration was modified: " + path.name)
                conn.execute(
                    "UPDATE schema_migrations SET checksum=%s WHERE name=%s AND checksum IS NULL",
                    [checksum, path.name],
                )
                continue
            conn.execute(sql, prepare=False)
            conn.execute(
                "INSERT INTO schema_migrations(name,checksum) VALUES (%s,%s)", [path.name, checksum]
            )
            print("Applied " + path.name)


if __name__ == "__main__":
    try:
        migrate()
    except Exception as exc:
        print(
            f"Migration failed ({type(exc).__name__}); check database access and migration files.",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
