"""Private assassination plots, incapacitation and police custody."""

from nullreference.core.theme import RuleError

DAY = 86400


def require(ok, text):
    if not ok:
        raise RuleError(text)


def reply(key, **values):
    return {"key": key, "values": values}


def available(player, now):
    return max(player.get("injured_until", 0), player.get("jail_until", 0)) <= now


def restriction(player, now):
    parts = []
    if player.get("injured_until", 0) > now:
        parts.append(f"🏥 Восстановление до <t:{int(player['injured_until'])}:f>")
    if player.get("jail_until", 0) > now:
        parts.append(f"🔒 Под арестом до <t:{int(player['jail_until'])}:f>")
    return "\n".join(parts) or "Ограничений нет"


class MafiaUnderworld:
    def __init__(self, season):
        self.season = season

    def disable(self, state, actor, now, kind):
        player = state["players"][actor]
        # Settle escrow first: a pending hand cannot shelter the victim's wallet.
        hand = player.get("blackjack")
        if hand and hand["status"] == "active":
            self.season.casino.settle(player, hand)
            hand["outcome"] += " Раздача вскрыта из-за ограничения активности."
        player[kind + "_until"] = now + DAY
        for operation in state["operations"].values():
            if operation["status"] == "open":
                operation["members"] = [uid for uid in operation["members"] if uid != actor]
        for plot in state.get("plots", {}).values():
            if plot["status"] == "open":
                if plot["organizer"] == actor:
                    plot["status"] = "cancelled"
                else:
                    plot["members"] = [uid for uid in plot["members"] if uid != actor]

    def start(self, state, actor, now, target):
        t = self.season
        t.leader(state, actor)
        player, victim = t.player(state, actor), t.player(state, target)
        require(player["family"] != "police", "Полиция не организует покушения")
        require(
            actor != target and victim["family"] != player["family"],
            "Выберите участника другой стороны",
        )
        require(available(victim, now), "Этот участник уже временно выбыл из события")
        plots = state.setdefault("plots", {})
        require(
            not any(
                p["family"] == player["family"] and p["status"] == "open" for p in plots.values()
            ),
            "У семьи уже есть незавершённое покушение",
        )
        # Import only at call time to keep theme dependencies acyclic.
        from .rules import week

        require(
            not any(
                p["family"] == player["family"] and p["week"] == week(now) for p in plots.values()
            ),
            "Одно покушение семьи в неделю",
        )
        t.spend(t.family(state, actor), "money", 40)
        plot_id = t.identifier(state)
        plots[plot_id] = {
            "family": player["family"],
            "organizer": actor,
            "target": target,
            "members": [actor],
            "until": now + DAY,
            "status": "open",
            "week": week(now),
            "leaks": 0,
            "named": False,
            "outcome": "",
            "lost": 0,
        }
        return reply("plot_started", id=plot_id, target=f"<@{target}>", until=int(now + DAY))

    def get(self, state, plot_id):
        require(plot_id in state.get("plots", {}), "Покушение недоступно")
        return state["plots"][plot_id]

    def join(self, state, actor, now, plot):
        t = self.season
        p = self.get(state, plot)
        # Same denial for unknown and another family's IDs; no target/details in acknowledgement.
        require(t.player(state, actor)["family"] == p["family"], "Покушение недоступно")
        require(p["status"] == "open" and now < p["until"], "Набор закрыт")
        require(actor not in p["members"], "Вы уже присоединились")
        require(len(p["members"]) < 12, "Максимум 12 участников")
        p["members"].append(actor)
        result = reply("plot_joined")
        if t.roll(100) < 21:
            p["leaks"] += 1
            if t.roll(100) < 25:
                p["named"] = True
                state["clues"][p["family"]] = state["clues"].get(p["family"], 0) + 3
                result["news"] = {
                    "key": "news_plot_named",
                    "values": {"target": f"<@{p['target']}>", "organizer": f"<@{p['organizer']}>"},
                }
            else:
                result["news"] = {
                    "key": "news_plot_leak",
                    "values": {"target": f"<@{p['target']}>"},
                }
        return result

    def status(self, state, actor, now, plot):
        p = self.get(state, plot)
        require(p["organizer"] == actor, "Статус доступен только организатору")
        chance = min(90, 30 + 15 * (len(p["members"]) - 1))
        return reply(
            "plot_status",
            id=plot,
            target=f"<@{p['target']}>",
            members=", ".join(f"<@{uid}>" for uid in p["members"]) or "—",
            chance=chance if len(p["members"]) >= 2 else 0,
            until=int(p["until"]),
            status=p["status"],
            leaks=p["leaks"],
            named="да" if p["named"] else "нет",
            outcome=p["outcome"] or "ожидается",
        )

    def resolve(self, state, actor, now, plot):
        t = self.season
        p = self.get(state, plot)
        require(p["organizer"] == actor, "Итог подводит только организатор")
        require(p["status"] == "open", "Покушение уже закрыто")
        require(now >= p["until"], "Сбор ещё не завершён")
        require(t.player(state, actor)["family"] == p["family"], "Вы сменили сторону")
        victim = state["players"].get(p["target"])
        valid_target = (
            victim
            and victim["family"]
            and victim["family"] != p["family"]
            and available(victim, now)
        )
        eligible = [
            uid
            for uid in p["members"]
            if state["players"][uid]["family"] == p["family"]
            and available(state["players"][uid], now)
        ]
        p["members"] = eligible
        chance = min(90, 30 + 15 * (len(eligible) - 1))
        success = bool(valid_target and len(eligible) >= 2 and t.roll(100) < chance)
        p["status"] = "resolved"
        if success:
            self.disable(state, p["target"], now, "injured")
            lost = victim["money"] // 2
            victim["money"] -= lost
            p.update(lost=lost, outcome="успех")
        else:
            p["outcome"] = "неудача" if valid_target else "цель недоступна"
        # No automatic public outcome: secrecy ends only through a recruitment leak.
        return reply("plot_resolved", id=plot, outcome=p["outcome"], lost=p["lost"])

    def arrest(self, state, actor, now, member):
        t = self.season
        t.officer(state, actor, now)
        target = t.player(state, member)
        family = target["family"]
        require(family != "police", "Арест доступен только против преступных семей")
        require(available(target, now), "Участник уже временно выбыл из события")
        require(state["clues"].get(family, 0) >= 4, "Для ареста нужно минимум 4 улики")
        require(
            not any(
                p.get("jail_family") == family and p.get("jail_until", 0) > now
                for p in state["players"].values()
            ),
            "От этой семьи уже есть заключённый",
        )
        state["clues"][family] -= 4
        self.disable(state, member, now, "jail")
        target.update(jail_family=family, jail_bail_attempted=False)
        result = reply("arrested", member=f"<@{member}>", until=int(now + DAY))
        result["news"] = {"key": "news_arrest", "values": result["values"]}
        return result

    def prisoner(self, state, actor, now, member):
        t = self.season
        t.leader(state, actor)
        family = t.player(state, actor)["family"]
        require(family != "police", "Выберите преступную семью")
        target = state["players"].get(member)
        require(
            target and target.get("jail_family") == family and target.get("jail_until", 0) > now,
            "Нет заключённого вашей семьи",
        )
        return target

    def bail(self, state, actor, now, member):
        target = self.prisoner(state, actor, now, member)
        require(not target.get("jail_bail_attempted"), "Залог по этому аресту уже пробовали")
        self.season.spend(self.season.family(state, actor), "money", 60)
        target["jail_bail_attempted"] = True
        success = self.season.roll(100) < 50
        if success:
            target["jail_until"] = now
        # No injuries, corruption suspensions or other restrictions are removed by bail.
        return reply(
            "bail_result",
            member=f"<@{member}>",
            outcome="освобождён досрочно" if success else "остаётся под арестом",
        )

    def cooperate(self, state, actor, now, family):
        t = self.season
        t.leader(state, actor)
        own = t.player(state, actor)["family"]
        from .rules import FAMILIES

        require(
            own != "police" and family in FAMILIES and family not in (own, "police"),
            "Выберите другую преступную семью",
        )
        require(
            any(
                p.get("jail_family") == own and p.get("jail_until", 0) > now
                for p in state["players"].values()
            ),
            "Сотрудничество возможно, пока член семьи под арестом",
        )
        t.spend(t.family(state, actor), "influence", 2)
        state["clues"][family] = state["clues"].get(family, 0) + 1
        return reply("cooperation", family=FAMILIES[family], clues=state["clues"][family])
