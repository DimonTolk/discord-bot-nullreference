"""Real PostgreSQL tests for the same parameterized SQL used over Neon HTTP."""

import asyncio
import os
import re
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from nullreference.core.database import Database
from nullreference.application import Application, message
from nullreference.core.config import Config
from nullreference.core.http import ServiceError
from nullreference.core.flavour import FlavourCatalog
from nullreference.core.theme import RuleError
from nullreference.themes.mafia.membership import MafiaMembership
from nullreference.themes.mafia.rules import MafiaSeason
from nullreference.themes.mafia.weekly import MafiaWeeklyTasks

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="Requires disposable PostgreSQL"
)


class PostgresSQL:
    """Test-only libpq adapter. Production uses NeonHTTP and has no native dependencies."""

    def __init__(self, url):
        self.url = url

    async def query(self, sql, params=()):
        import psycopg
        from psycopg.rows import dict_row
        from psycopg.types.json import Jsonb

        ordered = []

        def parameter(match):
            value = params[int(match.group(1)) - 1]
            ordered.append(Jsonb(value) if isinstance(value, (dict, list)) else value)
            return "%s"

        # Convert via explicit PREPARE parameters to preserve PostgreSQL parameter inference,
        # including repeated $n placeholders (the HTTP API uses that exact protocol).
        sql = re.sub(r"\$(\d+)", parameter, sql)
        async with await psycopg.AsyncConnection.connect(self.url, row_factory=dict_row) as conn:
            cursor = await conn.execute(sql, ordered)
            return await cursor.fetchall() if cursor.description else []


def test_migrations_optimistic_concurrency_replay_rollback_and_live_settings():
    async def scenario():
        sys.path.insert(0, str(ROOT / "scripts"))
        from migrate import migrate

        url = os.environ["TEST_DATABASE_URL"]
        await asyncio.to_thread(migrate, url)
        await asyncio.to_thread(migrate, url)
        sql = PostgresSQL(url)
        db, theme = Database(sql), MafiaSeason(roll=lambda n: 0)
        guild, season = "999", f"test-{uuid.uuid4()}"

        async def act(request, action, **kwargs):
            return await db.execute(guild, season, theme, "1", request, action, **kwargs)

        try:
            await act("identity", "sync", identities={"1": "mafia"})
            results = await asyncio.gather(*(act("same-work", "work") for _ in range(5)))
            assert all(result == results[0] for result in results)
            assert (await db.snapshot(guild, season, theme))["players"]["1"]["money"] == 20
            results = await asyncio.gather(
                act("donate-a", "donate", amount=20),
                act("donate-b", "donate", amount=20),
                return_exceptions=True,
            )
            assert sum(isinstance(r, RuleError) for r in results) == 1
            assert (await db.snapshot(guild, season, theme))["families"]["mafia"]["money"] == 20
            await act("reward", "reward", family="mafia", influence=10, money=0, reference="task")
            await act("open", "district_open", district="bank")
            with pytest.raises(RuleError):
                await act("bad-bid", "district_bid", district="bank", supply=True)
            assert (await db.snapshot(guild, season, theme))["families"]["mafia"]["influence"] == 10
            news = await sql.query(
                "SELECT id FROM news_outbox WHERE guild_id=$1 AND season_id=$2", [guild, season]
            )
            assert len(news) == 1
            membership = MafiaMembership(sql, guild, season)
            await membership.set("mafia", 101, 1)
            assert await membership.bindings() == {"mafia": 101}
            await membership.set("mafia", None, 1)
            assert await membership.bindings() == {}
            a, b = FlavourCatalog(sql, guild, season), FlavourCatalog(sql, guild, season)
            await a.set("work", "Доход $amount, остаток $balance", 1)
            assert await b.render("work", amount=2, balance=3) == "Доход 2, остаток 3"
            await a.set("work", None, 1)
            assert await b.get("work") == b.defaults["work"]
            discord = SimpleNamespace(respond=AsyncMock(), request=AsyncMock())
            app = Application(
                Config("test", "00" * 32, "111", guild, "unused", season), sql, discord
            )
            app.dispatch = AsyncMock(return_value=message("done"))
            payload = {
                "id": f"job-{season}",
                "guild_id": guild,
                "application_id": "111",
                "token": "test-only",
            }
            await app.process(payload)
            await app.process(payload)
            assert app.dispatch.await_count == 1
            row = (
                await sql.query(
                    "SELECT status,payload FROM interaction_jobs WHERE id=$1", [payload["id"]]
                )
            )[0]
            assert row == {"status": "done", "payload": {}}
            payload["id"] += "-retry"
            discord.respond.side_effect = [ServiceError("temporary"), None]
            await app.process(payload)
            calls = app.dispatch.await_count
            await sql.query(
                "UPDATE interaction_jobs SET lease_until=now()-interval '1 second' WHERE id=$1",
                [payload["id"]],
            )
            await app.run_job(payload["id"])
            assert app.dispatch.await_count == calls
            row = (
                await sql.query(
                    "SELECT status,payload FROM interaction_jobs WHERE id=$1", [payload["id"]]
                )
            )[0]
            assert row == {"status": "done", "payload": {}}
        finally:
            for table in (
                "game_state",
                "game_events",
                "flavour_overrides",
                "flavour_history",
                "news_outbox",
                "mafia_role_bindings",
                "mafia_role_history",
                "interaction_jobs",
            ):
                await sql.query(
                    f"DELETE FROM {table} WHERE guild_id=$1 AND season_id=$2", [guild, season]
                )

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(scenario())


def test_weekly_schedule_minsk_random_selection_and_duplicate_prevention():
    async def scenario():
        sys.path.insert(0, str(ROOT / "scripts"))
        from migrate import migrate

        url = os.environ["TEST_DATABASE_URL"]
        await asyncio.to_thread(migrate, url)
        sql = PostgresSQL(url)
        guild, season = "998", f"weekly-test-{uuid.uuid4()}"
        tasks = MafiaWeeklyTasks(sql, guild, season)
        try:
            await sql.query(
                "INSERT INTO guild_settings(guild_id,news_channel_id,weekly_tasks_enabled_since) "
                "VALUES ($1,999,'2026-10-30T00:00:00Z') ON CONFLICT(guild_id) DO UPDATE "
                "SET news_channel_id=999,weekly_tasks_enabled_since='2026-10-30T00:00:00Z',weekly_tasks_enabled=true",
                [guild],
            )
            assert (await tasks.settings())["weekly_tasks_timezone"] == "Europe/Minsk"
            assert len(await tasks.presets()) >= 8
            assert not await tasks.publish(now="2026-11-02T08:59:00Z")
            results = await asyncio.gather(
                *(tasks.publish(now="2026-11-02T09:00:00Z") for _ in range(4))
            )
            selected = [row for rows in results for row in rows]
            assert len(selected) == 1
            assert selected[0]["week"] == "2026-W45"
            news = await sql.query(
                "SELECT payload FROM news_outbox WHERE guild_id=$1 AND season_id=$2",
                [guild, season],
            )
            assert len(news) == 1
            assert news[0]["payload"]["reference"] == "weekly-2026-W45"
            rendered = await FlavourCatalog(sql, guild, season).render(
                "weekly_task", **news[0]["payload"]
            )
            assert len(rendered.encode("utf-16-le")) // 2 <= 2000
            following = await tasks.publish(now="2026-11-09T09:00:00Z")
            assert following[0]["preset_key"] != selected[0]["preset_key"]
            await tasks.configure("disable")
            assert not await tasks.publish(now="2026-11-16T09:00:00Z")
            assert await tasks.publish(force=True, now="2026-11-16T09:00:00Z")
            assert not await tasks.publish(force=True, now="2026-11-16T09:00:00Z")
            await sql.query(
                "UPDATE guild_settings SET weekly_tasks_enabled=true, "
                "weekly_tasks_enabled_since='2026-11-24T00:00:00Z' WHERE guild_id=$1",
                [guild],
            )
            assert not await tasks.publish(now="2026-11-24T09:00:00Z")
            assert await tasks.publish(now="2026-11-30T09:00:00Z")
        finally:
            for table in ("weekly_task_assignments", "news_outbox"):
                await sql.query(
                    f"DELETE FROM {table} WHERE guild_id=$1 AND season_id=$2", [guild, season]
                )
            await sql.query("DELETE FROM guild_settings WHERE guild_id=$1", [guild])

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(scenario())
