"""Database-backed presets and exactly-once weekly task enqueueing."""

from nullreference.core.theme import RuleError


class MafiaWeeklyTasks:
    def __init__(self, sql, guild, season):
        self.sql, self.guild, self.season = sql, guild, season

    async def settings(self):
        rows = await self.sql.query(
            "SELECT news_channel_id,weekly_tasks_enabled,weekly_tasks_day,"
            "weekly_tasks_hour,weekly_tasks_minute,weekly_tasks_timezone FROM guild_settings WHERE guild_id=$1",
            [self.guild],
        )
        if not rows:
            raise RuleError("Сначала подключите канал через /news_channel")
        return rows[0]

    async def configure(self, action, day=None, hour=None, minute=None):
        await self.settings()
        if action == "schedule":
            if day is None and hour is None and minute is None:
                raise RuleError("Укажите хотя бы один параметр: day, hour или minute")
            await self.sql.query(
                "UPDATE guild_settings SET weekly_tasks_day=COALESCE($2::integer,weekly_tasks_day),"
                "weekly_tasks_hour=COALESCE($3::integer,weekly_tasks_hour),"
                "weekly_tasks_minute=COALESCE($4::integer,weekly_tasks_minute),weekly_tasks_enabled_since=now() "
                "WHERE guild_id=$1",
                [self.guild, day, hour, minute],
            )
        elif action in ("enable", "disable"):
            await self.sql.query(
                "UPDATE guild_settings SET weekly_tasks_enabled=$2::boolean, "
                "weekly_tasks_enabled_since=CASE WHEN $2::boolean AND NOT weekly_tasks_enabled THEN now() "
                "ELSE weekly_tasks_enabled_since END WHERE guild_id=$1",
                [self.guild, action == "enable"],
            )
        else:
            raise RuleError("Неизвестное действие")
        return await self.settings()

    async def presets(self):
        return await self.sql.query(
            "SELECT key,title,body,enabled FROM mafia_weekly_task_presets ORDER BY key"
        )

    async def publish(self, force=False, now=None):
        # The clock argument is test-only. Production always uses PostgreSQL now().
        return await self.sql.query(
            """
            WITH clock AS (
              SELECT COALESCE($3::timestamptz,now()) AS instant
            ), settings AS (
              SELECT g.*,clock.instant,
                clock.instant AT TIME ZONE g.weekly_tasks_timezone AS local_now
              FROM guild_settings g CROSS JOIN clock
              WHERE g.guild_id=$1 AND g.news_channel_id IS NOT NULL
            ), schedule AS (
              SELECT *,to_char(local_now,'IYYY-"W"IW') AS week,
                (date_trunc('week',local_now)+(weekly_tasks_day-1)*interval '1 day'
                  +weekly_tasks_hour*interval '1 hour'+weekly_tasks_minute*interval '1 minute')
                  AT TIME ZONE weekly_tasks_timezone AS scheduled_at,
                (date_trunc('week',local_now)+interval '7 days'-interval '1 second')
                  AT TIME ZONE weekly_tasks_timezone AS deadline
              FROM settings
            ), candidate AS (
              SELECT s.week,p.key,p.title,p.body,extract(epoch FROM s.deadline)::bigint AS deadline
              FROM schedule s CROSS JOIN LATERAL (
                SELECT p.* FROM mafia_weekly_task_presets p WHERE p.enabled
                ORDER BY (p.key IS DISTINCT FROM (SELECT preset_key FROM weekly_task_assignments
                  WHERE guild_id=$1 AND season_id=$2 ORDER BY week DESC LIMIT 1)) DESC,random()
                LIMIT 1
              ) p
              WHERE $4::boolean OR (s.weekly_tasks_enabled AND s.instant>=s.scheduled_at
                AND s.scheduled_at>=s.weekly_tasks_enabled_since)
            ), assignment AS (
              INSERT INTO weekly_task_assignments(guild_id,season_id,week,preset_key,payload)
              SELECT $1,$2,week,key,jsonb_build_object('title',title,'body',body,
                'reference','weekly-'||week,'deadline',deadline,'influence',3,'money',20)
              FROM candidate ON CONFLICT(guild_id,season_id,week) DO NOTHING
              RETURNING week,preset_key,payload
            ), news AS (
              INSERT INTO news_outbox(guild_id,season_id,text_key,payload)
              SELECT $1,$2,'weekly_task',payload FROM assignment
            ) SELECT week,preset_key,payload FROM assignment
        """,
            [self.guild, self.season, now, force],
        )
