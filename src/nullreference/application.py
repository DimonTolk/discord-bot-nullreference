import json
import time

from .core.database import Database
from .core.flavour import FlavourCatalog
from .core.theme import RuleError
from .themes.mafia.commands import authorize, manifest, parse_options
from .themes.mafia.membership import MafiaMembership
from .themes.mafia.rules import DISTRICTS, FAMILIES, MafiaSeason
from .themes.mafia.help import render_help
from .themes.mafia.casino import component_action, render as render_casino
from .themes.mafia.weekly import MafiaWeeklyTasks
from .themes.mafia.underworld import restriction
from .themes.mafia.policing import police_profile


def message(text, **extra):
    return {"content": str(text)[:2000], "allowed_mentions": {"parse": []}, **extra}


class Application:
    def __init__(self, config, sql, discord):
        self.config, self.sql, self.discord = config, sql, discord
        self.guild, self.season = config.guild_id, config.season_id
        self.theme = MafiaSeason()
        self.db = Database(sql)
        self.flavour = FlavourCatalog(sql, self.guild, self.season)
        self.membership = MafiaMembership(sql, self.guild, self.season)
        self.weekly = MafiaWeeklyTasks(sql, self.guild, self.season)

    async def state(self):
        return await self.db.snapshot(self.guild, self.season, self.theme)

    async def identities(self, payload, name, args):
        if name in {"reward", "district_open"}:
            return {}
        bindings = await self.membership.bindings()
        if name == "leader_set":
            member = await self.discord.member(self.guild, args["member"])
            if not member:
                raise RuleError("Участник покинул сервер")
            return {args["member"]: self.membership.resolve(member["roles"], bindings)}
        actor = payload["member"]["user"]["id"]
        # Fetch current membership: queued retries must not use roles from an old interaction.
        member = await self.discord.member(self.guild, actor)
        if not member:
            raise RuleError("Участник покинул сервер")
        result = {actor: self.membership.resolve(member["roles"], bindings)}
        others = set()
        if name in {"plot_start", "arrest"}:
            others.add(args["target"] if name == "plot_start" else args["member"])
        if name == "plot_resolve":
            state = await self.state()
            plot = state.get("plots", {}).get(args.get("plot"))
            if plot and plot["organizer"] == actor:
                others.update(plot["members"])
                others.add(plot["target"])
        if name in {"operation_resolve", "bribe_offer", "bribe_decide"}:
            state = await self.state()
            operation = state["operations"].get(args.get("operation"))
            if name == "operation_resolve" and operation:
                others.update(operation["members"])
            if name == "bribe_offer" and operation and operation["raid"]:
                others.add(operation["raid"]["officer"])
            if name == "bribe_decide" and (bribe := state["bribes"].get(args.get("bribe"))):
                others.add(bribe["sender"])
        if len(others - result.keys()) > 12:
            raise RuleError("В деле слишком много участников для одного запроса")
        for uid in others - result.keys():
            other = await self.discord.member(self.guild, uid)
            try:
                result[uid] = self.membership.resolve(other["roles"], bindings) if other else None
            except RuleError:
                result[uid] = None
        return result

    async def act(self, payload, name, args):
        result = await self.db.execute(
            self.guild,
            self.season,
            self.theme,
            payload["member"]["user"]["id"],
            payload["id"],
            name,
            identities=await self.identities(payload, name, args),
            **args,
        )
        return result

    async def casino_channel(self, payload):
        rows = await self.sql.query(
            "SELECT casino_channel_id FROM guild_settings WHERE guild_id=$1", [self.guild]
        )
        if not rows or str(rows[0]["casino_channel_id"]) != str(payload.get("channel_id")):
            raise RuleError("Играть можно только в настроенном канале казино")

    async def dispatch(self, payload):
        actor = payload["member"]["user"]["id"]
        if payload["type"] == 3:
            args = component_action(payload)
            await self.casino_channel(payload)
            return {
                **render_casino(await self.act(payload, "blackjack_move", args)),
                "allowed_mentions": {"parse": []},
            }
        if payload["type"] == 5:
            _, operation, key, owner = payload["data"]["custom_id"].split(":", 3)
            authorize(payload, "flavour_edit")
            if operation != "save" or owner != actor:
                raise RuleError("Это чужая форма")
            value = payload["data"]["components"][0]["components"][0]["value"]
            await self.flavour.set(key, value, actor)
            return message("Сохранено. Новый текст уже используется.")
        name = payload["data"]["name"]
        authorize(payload, name)
        args = parse_options(payload, name)
        if name in {"slots", "blackjack", "blackjack_table"}:
            await self.casino_channel(payload)
            return {
                **render_casino(await self.act(payload, name, args)),
                "allowed_mentions": {"parse": []},
            }
        if name == "casino_channel":
            channel = await self.discord.request("GET", f"/channels/{args['channel']}")
            if not channel or channel.get("guild_id") != self.guild or channel.get("type") != 0:
                raise RuleError("Выберите текстовый канал этого сервера")
            await self.sql.query(
                "INSERT INTO guild_settings(guild_id,casino_channel_id) VALUES ($1,$2) "
                "ON CONFLICT(guild_id) DO UPDATE SET casino_channel_id=EXCLUDED.casino_channel_id",
                [self.guild, args["channel"]],
            )
            return message("Канал казино сохранён.")
        if name == "weekly_tasks":
            action = args["action"]
            if action != "schedule" and any(
                args.get(key) is not None for key in ("day", "hour", "minute")
            ):
                raise RuleError("Параметры времени используются только с action:schedule")
            if action == "presets":
                rows = await self.weekly.presets()
                return message(
                    "## Пресеты еженедельных заданий\n"
                    + "\n".join(
                        f"• `{p['key']}` — {p['title']}"
                        + (" (отключён)" if not p["enabled"] else "")
                        for p in rows
                    )
                )
            if action == "publish":
                await self.weekly.settings()
                rows = await self.weekly.publish(force=True)
                return message(
                    "Задание добавлено в очередь новостей."
                    if rows
                    else "Задание этой недели уже выбрано, нет активных пресетов или не подключён канал новостей."
                )
            settings = (
                await self.weekly.settings()
                if action == "status"
                else await self.weekly.configure(action, args["day"], args["hour"], args["minute"])
            )
            days = (
                "понедельник",
                "вторник",
                "среда",
                "четверг",
                "пятница",
                "суббота",
                "воскресенье",
            )
            return message(
                f"## Еженедельные задания\nАвтопубликация: {'включена' if settings['weekly_tasks_enabled'] else 'выключена'}\n"
                f"Расписание: {days[settings['weekly_tasks_day'] - 1]}, {settings['weekly_tasks_hour']:02d}:{settings['weekly_tasks_minute']:02d} "
                f"({settings['weekly_tasks_timezone']}).\nКанал: <#{settings['news_channel_id']}>\n"
                "Проверка раз в 10 минут. Новое расписание действует со следующего наступления выбранного времени."
            )
        if name == "start":
            return message(await self.flavour.render("welcome"))
        if name == "help":
            return message(render_help(args["topic"]))
        if name in {"profile", "inbox"}:
            await self.act(payload, "sync", {})
            state = await self.state()
            player = state["players"][actor]
            family = state["families"][player["family"]]
            if name == "profile":
                if player["family"] == "police":
                    return police_profile(state, actor, time.time())
                return message(
                    f"**{FAMILIES[player['family']]}**\nЛичные деньги: {player['money']}\n"
                    f"Касса: {family['money']}\nВлияние: {family['influence']}\n"
                    f"Всего влияния: {family['earned']}\nГлава: <@{family['leader']}>\n"
                    f"Подозрение (до снижения за чистые недели): {player['suspicion']}\n"
                    + restriction(player, time.time())
                    + "\nВаши незавершённые покушения: "
                    + (
                        ", ".join(
                            pid
                            for pid, p in state.get("plots", {}).items()
                            if p["organizer"] == actor and p["status"] == "open"
                        )
                        or "нет"
                    )
                )
            lines = []
            for bid, b in state["bribes"].items():
                if (
                    b["status"] == "pending"
                    and b["until"] > time.time()
                    and actor in (b["sender"], b["officer"])
                ):
                    lines.append(
                        f"Конверт №{bid}: {b['amount']}, дело №{b['operation']}, до <t:{int(b['until'])}:f>"
                    )
            for tid, t in state["transfers"].items():
                if (
                    t["status"] == "pending"
                    and t["until"] > time.time()
                    and t["to"] == player["family"]
                ):
                    lines.append(
                        f"Передача №{tid}: {DISTRICTS[t['district']]}, до <t:{int(t['until'])}:f>"
                    )
            return message("\n".join(lines) or "Нет предложений.")
        if name == "leaderboard":
            state = await self.state()
            rows = sorted(state["families"].items(), key=lambda kv: kv[1]["earned"], reverse=True)
            return message(
                "\n".join(
                    f"{i}. {FAMILIES[k]}: {f['earned']} (доступно {f['influence']})"
                    for i, (k, f) in enumerate(rows, 1)
                )
            )
        if name == "status":
            state = await self.state()
            lines = []
            for key, d in state["districts"].items():
                owner = FAMILIES.get(d["owner"], "город") if d["until"] > time.time() else "город"
                lines.append(
                    f"**{DISTRICTS[key]}**: {owner}"
                    + (
                        f"; контроль до <t:{int(d['until'])}:f>"
                        if d["owner"] and d["until"] > time.time()
                        else ""
                    )
                    + (f"; розыгрыш до <t:{int(d['contest']['until'])}:f>" if d["contest"] else "")
                )
            for oid, o in state["operations"].items():
                if o["status"] == "open":
                    lines.append(
                        f"Дело №{oid}: {FAMILIES[o['family']]}; {len(o['members'])} участников, до <t:{int(o['until'])}:f>"
                    )
            return message("\n".join(lines))
        if name == "family_role":
            role = args["role"]
            if role:
                roles = payload["data"].get("resolved", {}).get("roles", {})
                if role == self.guild or role not in roles:
                    raise RuleError("Выберите игровую роль этого сервера, кроме @everyone")
            await self.membership.set(args["family"], role, actor)
            return message(
                f"{FAMILIES[args['family']]}: " + (f"<@&{role}>" if role else "привязка снята")
            )
        if name == "family_roles":
            bindings = await self.membership.bindings()
            return message(
                "\n".join(
                    f"{label}: " + (f"<@&{bindings[key]}>" if key in bindings else "не настроено")
                    for key, label in FAMILIES.items()
                )
            )
        if name == "news_channel":
            channel = await self.discord.request("GET", f"/channels/{args['channel']}")
            if not channel or channel.get("guild_id") != self.guild or channel.get("type") != 0:
                raise RuleError("Выберите текстовый канал этого сервера")
            # Test write also proves that the bot has permission before saving configuration.
            await self.discord.request(
                "POST",
                f"/channels/{args['channel']}/messages",
                message("📰 Канал городской газеты подключён."),
            )
            await self.sql.query(
                "INSERT INTO guild_settings(guild_id,news_channel_id) VALUES ($1,$2) "
                "ON CONFLICT(guild_id) DO UPDATE SET news_channel_id=EXCLUDED.news_channel_id",
                [self.guild, args["channel"]],
            )
            return message("Канал новостей сохранён.")
        if name == "flavour_edit":
            key = args["key"]
            value = await self.flavour.get(key)
            return message(
                "Нажмите кнопку, чтобы открыть форму. Изменения применяются сразу.",
                embeds=[{"title": key, "description": value}],
                components=[
                    {
                        "type": 1,
                        "components": [
                            {
                                "type": 2,
                                "style": 1,
                                "label": "Редактировать",
                                "custom_id": f"flavour:open:{key}:{actor}",
                            }
                        ],
                    }
                ],
            )
        if name == "flavour_reset":
            await self.flavour.set(args["key"], None, actor)
            return message("Стандартный текст восстановлен.")
        if name == "flavour_export":
            # One DB request instead of one request per key (Free plan subrequest budget).
            rows = await self.sql.query(
                "SELECT key,value FROM flavour_overrides WHERE guild_id=$1 AND season_id=$2",
                [self.guild, self.season],
            )
            values = {**self.flavour.defaults, **{r["key"]: r["value"] for r in rows}}
            return message(
                "Тематические тексты:", _file=json.dumps(values, ensure_ascii=False, indent=2)
            )
        if name == "setup":
            await self.sql.query("SELECT version FROM game_state LIMIT 1")
            await self.discord.request(
                "PUT",
                f"/applications/{self.config.application_id}/guilds/{self.guild}/commands",
                manifest(),
            )
            return message(
                "Схема доступна, команды зарегистрированы. Настройте /family_role и /news_channel."
            )
        result = await self.act(payload, name, args)
        return message(await self.flavour.render(result["key"], **result["values"]))

    async def process(self, payload):
        if (
            str(payload.get("guild_id")) != self.guild
            or str(payload.get("application_id")) != self.config.application_id
        ):
            return
        await self.sql.query(
            "INSERT INTO interaction_jobs(id,guild_id,season_id,payload) VALUES ($1,$2,$3,$4::jsonb) "
            "ON CONFLICT DO NOTHING",
            [payload["id"], self.guild, self.season, payload],
        )
        await self.run_job(payload["id"])

    async def run_job(self, job_id):
        rows = await self.sql.query(
            "UPDATE interaction_jobs SET status='running',attempts=attempts+1, "
            "lease_until=now()+interval '40 seconds' WHERE id=$1 AND guild_id=$2 AND season_id=$3 "
            "AND status IN ('pending','running') AND lease_until<=now() AND expires_at>now() AND attempts<3 "
            "RETURNING payload,response",
            [job_id, self.guild, self.season],
        )
        if not rows:
            return
        payload, response = rows[0]["payload"], rows[0]["response"]
        try:
            if response is None:
                try:
                    response = await self.dispatch(payload)
                except (RuleError, ValueError) as exc:
                    response = message(str(exc))
                await self.sql.query(
                    "UPDATE interaction_jobs SET response=$2::jsonb WHERE id=$1", [job_id, response]
                )
            await self.discord.respond(self.config.application_id, payload["token"], response)
            await self.sql.query(
                "UPDATE interaction_jobs SET status='done',payload='{}',response=NULL WHERE id=$1",
                [job_id],
            )
        except Exception:
            # Keep the job for retry; don't print interaction tokens, private payloads or SQL errors.
            await self.sql.query(
                "UPDATE interaction_jobs SET status='pending',lease_until=now()+interval '30 seconds' WHERE id=$1",
                [job_id],
            )

    async def deliver_news(self, limit=1):
        for _ in range(limit):
            rows = await self.sql.query(
                """
                UPDATE news_outbox SET lease_until=now()+interval '40 seconds'
                WHERE id=(SELECT o.id FROM news_outbox o JOIN guild_settings g USING(guild_id)
                  WHERE o.guild_id=$1 AND o.season_id=$2 AND o.sent_at IS NULL
                    AND g.news_channel_id IS NOT NULL AND (o.lease_until IS NULL OR o.lease_until<=now())
                  ORDER BY o.id LIMIT 1 FOR UPDATE OF o SKIP LOCKED)
                RETURNING id,text_key,payload,(SELECT news_channel_id FROM guild_settings WHERE guild_id=$1) AS channel
            """,
                [self.guild, self.season],
            )
            if not rows:
                return
            row = rows[0]
            text = await self.flavour.render(row["text_key"], **row["payload"])
            await self.discord.request(
                "POST", f"/channels/{row['channel']}/messages", message(text)
            )
            await self.sql.query("UPDATE news_outbox SET sent_at=now() WHERE id=$1", [row["id"]])

    async def maintenance(self):
        # No Gateway heartbeat and no persistent connection keeping Neon awake.
        state = await self.state()
        now = time.time()
        expired = any(
            b["status"] == "pending" and b["until"] <= now for b in state["bribes"].values()
        )
        expired |= any(
            p.get("blackjack", {}).get("status") == "active" and p["blackjack"]["until"] <= now
            for p in state["players"].values()
        )
        expired |= any(d["owner"] and d["until"] <= now for d in state["districts"].values())
        if expired:
            await self.db.execute(
                self.guild, self.season, self.theme, "0", f"tick:{int(now // 600)}", "tick"
            )
        rows = await self.sql.query(
            "SELECT id FROM interaction_jobs WHERE guild_id=$1 AND season_id=$2 "
            "AND status IN ('pending','running') AND lease_until<=now() AND expires_at>now() AND attempts<3 "
            "ORDER BY created_at LIMIT 1",
            [self.guild, self.season],
        )
        for row in rows:
            await self.run_job(row["id"])
        await self.sql.query(
            "UPDATE interaction_jobs SET status='expired',payload='{}',response=NULL "
            "WHERE guild_id=$1 AND season_id=$2 AND status IN ('pending','running') AND expires_at<=now()",
            [self.guild, self.season],
        )
        await self.weekly.publish()
        await self.deliver_news(limit=3)
