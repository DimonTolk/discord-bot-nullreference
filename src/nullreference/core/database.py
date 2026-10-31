import time

from .theme import RuleError


class Database:
    def __init__(self, sql):
        self.sql = sql

    async def snapshot(self, guild, season, theme):
        rows = await self.sql.query(
            "SELECT state,version FROM game_state WHERE guild_id=$1 AND season_id=$2",
            [guild, season],
        )
        return rows[0]["state"] if rows else theme.initial_state()

    async def execute(self, guild, season, theme, actor, request, action, identities=None, **args):
        await self.sql.query(
            "INSERT INTO game_state(guild_id,season_id,state) VALUES ($1,$2,$3::jsonb) "
            "ON CONFLICT DO NOTHING",
            [guild, season, theme.initial_state()],
        )
        for _ in range(6):
            rows = await self.sql.query(
                "SELECT state,version,(SELECT result FROM game_events "
                "WHERE guild_id=$1 AND season_id=$2 AND request_id=$3) AS previous "
                "FROM game_state WHERE guild_id=$1 AND season_id=$2",
                [guild, season, request],
            )
            if rows[0]["previous"] is not None:
                return rows[0]["previous"]
            state, version = rows[0]["state"], rows[0]["version"]
            now = time.time()
            if identities:
                theme.sync_members(state, identities, now)
            result = theme.apply(state, str(actor), action, now, **args)
            news = result.get("news", {})
            committed = await self.sql.query(
                """
                WITH updated AS (
                  UPDATE game_state SET state=$4::jsonb,version=version+1
                  WHERE guild_id=$1 AND season_id=$2 AND version=$5
                    AND NOT EXISTS (SELECT 1 FROM game_events
                      WHERE guild_id=$1 AND season_id=$2 AND request_id=$3)
                  RETURNING guild_id
                ), event AS (
                  INSERT INTO game_events(guild_id,season_id,request_id,actor_id,action,result)
                  SELECT $1,$2,$3,$6,$7,$8::jsonb FROM updated RETURNING result
                ), news AS (
                  INSERT INTO news_outbox(guild_id,season_id,text_key,payload)
                  SELECT $1,$2,$9,$10::jsonb FROM event WHERE $9::text IS NOT NULL
                ) SELECT result FROM event
            """,
                [
                    guild,
                    season,
                    request,
                    state,
                    version,
                    actor,
                    action,
                    result,
                    news.get("key"),
                    news.get("values", {}),
                ],
            )
            if committed:
                return committed[0]["result"]
        raise RuleError("Город занят другим действием. Попробуйте ещё раз.")
