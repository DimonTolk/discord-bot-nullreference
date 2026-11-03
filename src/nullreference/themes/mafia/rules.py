"""Pure Mafia rules. No Discord, SQL or deployment dependencies."""

import secrets
from datetime import datetime, timezone

from nullreference.core.theme import RuleError
from .casino import MafiaCasino

DAY = 86400
FAMILIES = {
    "mafia": "Мафия",
    "yakuza": "Якудза",
    "cartel": "Картель",
    "russian": "Русская мафия",
    "triad": "Триада",
    "police": "Полиция",
}
DISTRICTS = {"bank": "Банк", "casino": "Казино", "docks": "Доки"}


def require(condition, message):
    if not condition:
        raise RuleError(message)


def week(now):
    date = datetime.fromtimestamp(now, timezone.utc).isocalendar()
    return f"{date.year}-{date.week}"


def reply(key, **values):
    return {"key": key, "values": values}


class MafiaSeason:
    def __init__(self, roll=None):
        self.roll = roll or secrets.randbelow
        self.casino = MafiaCasino(self.roll)

    def initial_state(self):
        return {
            "players": {},
            "families": {
                key: {"money": 0, "influence": 0, "earned": 0, "weeks": {}, "leader": None}
                for key in FAMILIES
            },
            "operations": {},
            "bribes": {},
            "transfers": {},
            "districts": {
                key: {"owner": None, "until": 0, "cooldown": 0, "contest": None}
                for key in DISTRICTS
            },
            "clues": {},
            "police_actions": {},
            "raid_cooldowns": {},
            "reward_refs": [],
            "district_weeks": [],
            "next_id": 1,
            "district_income": {},
        }

    def apply(self, state, actor, action, now, **args):
        self.expire(state, now)
        handler = getattr(self, f"do_{action}", None)
        require(handler is not None, "Неизвестное действие")
        return handler(state, actor, now, **args)

    def do_slots(self, s, actor, now, amount):
        return self.casino.slots(self, s, actor, now, amount)

    def do_blackjack(self, s, actor, now, amount):
        return self.casino.start(self, s, actor, now, amount)

    def do_blackjack_move(self, s, actor, now, **args):
        return self.casino.move(self, s, actor, now, **args)

    def do_blackjack_table(self, s, actor, now):
        return self.casino.result(self.player(s, actor), actor)

    def expire(self, s, now):
        self.casino.expire(s, now)
        for b in s["bribes"].values():
            if b["status"] == "pending" and b["until"] <= now:
                s["players"][b["sender"]]["money"] += b["amount"]
                b["status"] = "expired"
        for d in s["districts"].values():
            if d["owner"] and d["until"] <= now:
                d["owner"] = None

    def identifier(self, s):
        value = str(s["next_id"])
        s["next_id"] += 1
        return value

    def player(self, s, actor):
        require(
            actor in s["players"] and s["players"][actor]["family"] in FAMILIES,
            "Для участия нужна ровно одна настроенная роль семьи или полиции",
        )
        return s["players"][actor]

    def family(self, s, actor):
        return s["families"][self.player(s, actor)["family"]]

    def leader(self, s, actor):
        require(
            self.family(s, actor)["leader"] == actor,
            "Решение принимает глава семьи. Организатор может назначить главу: /leader_set",
        )

    def do_leader_set(self, s, actor, now, member):
        p = self.player(s, member)
        self.family(s, member)["leader"] = member
        return reply("leader_set", family=FAMILIES[p["family"]])

    def officer(self, s, actor, now):
        p = self.player(s, actor)
        require(p["family"] == "police", "Действие доступно только полиции")
        require(p.get("suspended", 0) <= now, "Вы временно отстранены")
        elapsed = int((now - p.get("clean_since", now)) // (7 * DAY))
        if elapsed:
            p["suspicion"] = max(0, p.get("suspicion", 0) - elapsed)
            p["clean_since"] += elapsed * 7 * DAY
        return p

    def earn(self, s, family, amount, now):
        f = s["families"][family]
        f["influence"] += amount
        f["earned"] += amount
        w = week(now)
        f["weeks"][w] = f["weeks"].get(w, 0) + amount

    def spend(self, account, currency, amount):
        require(amount >= 0, "Неверная сумма")
        require(account[currency] >= amount, "Недостаточно средств")
        account[currency] -= amount

    def do_tick(self, s, actor, now):
        return {"ok": True}

    def sync_members(self, s, identities, now):
        for actor, family in identities.items():
            require(family is None or family in FAMILIES, "Неизвестная сторона")
            p = s["players"].get(actor)
            if p is None:
                if family is None:
                    continue
                p = {
                    "family": None,
                    "money": 0,
                    "work": {},
                    "suspicion": 0,
                    "clean_since": now,
                    "dirty": 0,
                }
                s["players"][actor] = p
            if p["family"] != family:
                # Preserve wallet, cooldowns and corruption record across role changes.
                for f in s["families"].values():
                    if f["leader"] == actor:
                        f["leader"] = None
                for o in s["operations"].values():
                    if o["status"] == "open" and o["family"] != family:
                        o["members"] = [uid for uid in o["members"] if uid != actor]
                p["family"] = family
            if family is not None and s["families"][family]["leader"] is None:
                s["families"][family]["leader"] = actor

    def do_sync(self, s, actor, now):
        self.player(s, actor)
        return {"ok": True}

    def do_work(self, s, actor, now):
        p = self.player(s, actor)
        date = datetime.fromtimestamp(now, timezone.utc).date().isoformat()
        w = week(now)
        require(p.get("last_work") != date, "Подработка доступна раз в сутки (UTC)")
        require(p["work"].get(w, 0) < 3, "Лимит: три подработки в неделю (UTC)")
        amount = 20 + self.roll(11)
        p["money"] += amount
        p["last_work"] = date
        p["work"][w] = p["work"].get(w, 0) + 1
        return reply("work", amount=amount, balance=p["money"])

    def do_donate(self, s, actor, now, amount):
        require(amount > 0, "Сумма должна быть положительной")
        p = self.player(s, actor)
        self.spend(p, "money", amount)
        self.family(s, actor)["money"] += amount
        return reply("donated", amount=amount, balance=p["money"])

    def do_reward(self, s, actor, now, family, influence, money, reference):
        # Only exposed by an admin-checked Discord command.
        require(family in FAMILIES, "Неизвестная сторона")
        require(0 <= influence <= 10 and 0 <= money <= 200, "Награда вне лимитов")
        require(3 <= len(reference) <= 80, "Укажите номер/ключ задания (3–80 символов)")
        require(
            reference not in s["reward_refs"],
            "Это задание уже оплачено; используйте уникальный ключ",
        )
        s["reward_refs"].append(reference)
        self.earn(s, family, influence, now)
        s["families"][family]["money"] += money
        return reply("reward", family=FAMILIES[family], influence=influence, money=money)

    def do_operation_start(self, s, actor, now, prepared=False):
        self.leader(s, actor)
        p = self.player(s, actor)
        require(p["family"] != "police", "Полиция расследует дела через /investigate")
        require(
            not any(
                o["family"] == p["family"] and o["status"] == "open"
                for o in s["operations"].values()
            ),
            "У семьи уже есть открытое дело",
        )
        require(
            not any(
                o["family"] == p["family"] and o["week"] == week(now)
                for o in s["operations"].values()
            ),
            "Одно дело семьи в неделю",
        )
        if prepared:
            self.spend(self.family(s, actor), "money", 40)
        oid = self.identifier(s)
        s["operations"][oid] = {
            "family": p["family"],
            "members": [actor],
            "until": now + DAY,
            "status": "open",
            "week": week(now),
            "prepared": prepared,
            "raid": None,
            "response": None,
        }
        s["clues"][p["family"]] = min(3, s["clues"].get(p["family"], 0) + 2)
        return reply("operation_started", id=oid)

    def operation(self, s, oid):
        require(oid in s["operations"], "Дело не найдено")
        o = s["operations"][oid]
        require(o["status"] == "open", "Дело уже завершено")
        return o

    def do_operation_join(self, s, actor, now, operation):
        o = self.operation(s, operation)
        require(self.player(s, actor)["family"] == o["family"], "Это дело другой семьи")
        require(now < o["until"], "Набор завершён")
        require(actor not in o["members"], "Вы уже участвуете")
        require(len(o["members"]) < 12, "Лимит операции: 12 участников")
        o["members"].append(actor)
        return reply("operation_joined", id=operation)

    def do_operation_resolve(self, s, actor, now, operation):
        o = self.operation(s, operation)
        require(self.player(s, actor)["family"] == o["family"], "Это дело другой семьи")
        require(now >= o["until"], "Дело ещё не завершилось")
        raid = o["raid"]
        require(not raid or o["response"] or now >= raid["until"], "Ожидается решение об облаве")
        count = len(o["members"])
        success = count >= 2 and self.roll(100) < 60 + 10 * o["prepared"] + 5 * (count >= 3)
        if o["response"] == "cancel":
            influence, money, outcome = 0, 20 if o["prepared"] else 0, "дело отменено"
        else:
            influence = (4 if success else 2) if count >= 2 else 0
            money = 40 if success else 0
            outcome = "успех" if success else "неудача"
            if o["response"] == "reroute":
                money //= 2
            elif raid and o["response"] != "bribed":
                money //= 2
                outcome += "; часть груза конфискована"
                self.earn(s, "police", 1, now)
                s["families"]["police"]["money"] += 20
        self.earn(s, o["family"], influence, now)
        s["families"][o["family"]]["money"] += money
        if o["response"] != "cancel":
            for uid in o["members"]:
                s["players"][uid]["money"] += 25 if count >= 2 else 0
        o["status"] = "resolved"
        result = reply(
            "operation_resolved", id=operation, outcome=outcome, money=money, influence=influence
        )
        result["news"] = {
            "key": "news_operation",
            "values": {"family": FAMILIES[o["family"]], "id": operation, "outcome": outcome},
        }
        return result

    def do_investigate(self, s, actor, now, family):
        self.officer(s, actor, now)
        require(family in FAMILIES and family != "police", "Выберите семью")
        w = week(now)
        used = s["police_actions"].get(w, 0)
        require(used < 3, "Отдел использовал три действия на этой неделе")
        require(
            any(
                o["family"] == family and o["status"] == "open" and not o["raid"]
                for o in s["operations"].values()
            ),
            "Нет открытого дела для проверки",
        )
        s["police_actions"][w] = used + 1
        s["clues"][family] = min(3, s["clues"].get(family, 0) + 1)
        return reply("investigated", clues=s["clues"][family], remaining=2 - used)

    def do_raid(self, s, actor, now, operation):
        self.officer(s, actor, now)
        o = self.operation(s, operation)
        require(now < o["until"], "Поздно назначать облаву")
        require(not o["raid"], "Облава уже назначена")
        require(s["clues"].get(o["family"], 0) >= 3, "Нужно три улики")
        require(
            s["raid_cooldowns"].get(o["family"], 0) <= now, "Семья защищена от повторной облавы"
        )
        s["clues"][o["family"]] = 0
        s["raid_cooldowns"][o["family"]] = now + 7 * DAY
        o["raid"] = {"officer": actor, "until": now + DAY, "evidence": False}
        self.earn(s, "police", 2, now)
        result = reply("raid", id=operation)
        result["news"] = {
            "key": "news_raid",
            "values": {"id": operation, "family": FAMILIES[o["family"]]},
        }
        return result

    def do_raid_response(self, s, actor, now, operation, decision):
        self.leader(s, actor)
        o = self.operation(s, operation)
        require(self.player(s, actor)["family"] == o["family"], "Это дело другой семьи")
        require(o["raid"] and now < o["raid"]["until"], "Нет активной облавы")
        require(o["response"] is None, "Решение уже принято")
        require(decision in ("cancel", "reroute", "continue"), "Неизвестное решение")
        if decision == "reroute":
            self.spend(self.family(s, actor), "money", 40)
        o["response"] = decision
        return reply("raid_response", decision=decision)

    def do_bribe_offer(self, s, actor, now, operation, amount):
        p = self.player(s, actor)
        o = self.operation(s, operation)
        require(p["family"] == o["family"], "Это дело другой семьи")
        require(o["raid"] and now < o["raid"]["until"], "Нет активной облавы")
        self.officer(s, o["raid"]["officer"], now)
        require(o["response"] is None, "Решение по облаве уже принято")
        require(20 <= amount <= 200, "Взятка: 20–200 личных денег")
        require(
            not any(
                b["operation"] == operation and b["status"] == "pending"
                for b in s["bribes"].values()
            ),
            "Предложение по этому делу уже ожидает ответа",
        )
        self.spend(p, "money", amount)
        bid = self.identifier(s)
        s["bribes"][bid] = {
            "sender": actor,
            "officer": o["raid"]["officer"],
            "operation": operation,
            "amount": amount,
            "until": min(now + DAY, o["raid"]["until"]),
            "status": "pending",
        }
        return reply("bribe_offered", id=bid)

    def do_bribe_decide(self, s, actor, now, bribe, decision):
        p = self.officer(s, actor, now)
        require(bribe in s["bribes"], "Предложение не найдено")
        b = s["bribes"][bribe]
        require(b["officer"] == actor, "Предложение адресовано другому сотруднику")
        require(b["status"] == "pending", "Предложение уже закрыто")
        require(decision in ("accept", "reject", "evidence"), "Неизвестное решение")
        o = self.operation(s, b["operation"])
        require(
            s["players"][b["sender"]]["family"] == o["family"],
            "Отправитель сменил сторону. Конверт вернётся после истечения срока.",
        )
        require(o["response"] is None, "По облаве уже принято решение; дождитесь возврата конверта")
        result = reply("bribe_decided", id=bribe, decision=decision)
        if decision == "accept":
            p["money"] += b["amount"]
            p["dirty"] += b["amount"]
            p["suspicion"] += 1
            p["clean_since"] = now
            o["response"] = "bribed"
            if p["suspicion"] >= 3:
                p["money"] -= min(p["money"], p["dirty"] // 2)
                p.update(dirty=0, suspicion=0, suspended=now + 3 * DAY)
                result["news"] = {"key": "news_corruption", "values": {}}
        else:
            s["players"][b["sender"]]["money"] += b["amount"]
            if decision == "evidence" and not o["raid"]["evidence"]:
                o["raid"]["evidence"] = True
                s["clues"][o["family"]] = min(3, s["clues"].get(o["family"], 0) + 1)
        b["status"] = decision
        return result

    def do_district_open(self, s, actor, now, district):
        require(district in DISTRICTS, "Неизвестный район")
        d = s["districts"][district]
        require(not d["contest"], "Борьба за район уже идёт")
        require(week(now) not in s["district_weeks"], "Один район разыгрывается в неделю")
        d["contest"] = {"until": now + 2 * DAY, "bids": {}, "week": week(now)}
        s["district_weeks"].append(week(now))
        result = reply("district_opened", district=DISTRICTS[district])
        result["news"] = {"key": "district_opened", "values": result["values"]}
        return result

    def owned_count(self, s, family):
        return sum(d["owner"] == family for d in s["districts"].values())

    def do_district_bid(self, s, actor, now, district, support=False, supply=False):
        self.leader(s, actor)
        require(district in DISTRICTS, "Неизвестный район")
        d = s["districts"][district]
        c = d["contest"]
        require(c and now < c["until"], "Нет открытого приёма заявок")
        family = self.player(s, actor)["family"]
        require(family not in c["bids"], "Семья уже подала заявку")
        require(d["owner"] == family or self.owned_count(s, family) < 2, "Лимит: два района")
        f = s["families"][family]
        self.spend(f, "influence", 5 + 2 * support)
        self.spend(f, "money", 60 * supply)
        c["bids"][family] = {
            "support": support,
            "supply": supply,
            "score": min(4, f["weeks"].get(c["week"], 0)) + support + supply,
            "at": now,
        }
        return reply("district_bid", support=int(support), supply=int(supply))

    def do_district_resolve(self, s, actor, now, district):
        require(district in DISTRICTS, "Неизвестный район")
        self.player(s, actor)
        d = s["districts"][district]
        c = d["contest"]
        require(c and now >= c["until"], "Розыгрыш ещё не завершён")
        bids = {f: b for f, b in c["bids"].items() if f == d["owner"] or self.owned_count(s, f) < 2}
        if bids:
            # Ties: incumbent first; otherwise earliest bid. No hidden randomness.
            winner = max(bids, key=lambda f: (bids[f]["score"], f == d["owner"], -bids[f]["at"]))
            d.update(owner=winner, until=now + 21 * DAY)
        d["contest"] = None
        name = FAMILIES.get(d["owner"], "город (нет заявок)")
        result = reply("district_resolved", district=DISTRICTS[district], family=name)
        result["news"] = {
            "key": "news_district",
            "values": {"district": DISTRICTS[district], "family": name},
        }
        return result

    def do_district_transfer(self, s, actor, now, district, family):
        self.leader(s, actor)
        require(district in DISTRICTS and family in FAMILIES, "Неизвестный район или сторона")
        d = s["districts"][district]
        owner = self.player(s, actor)["family"]
        require(d["owner"] == owner and owner != family, "Нельзя передать этот район")
        require(not d["contest"], "Во время борьбы передача недоступна")
        require(d["cooldown"] <= now, "Передача доступна раз в семь дней")
        tid = self.identifier(s)
        s["transfers"][tid] = {
            "district": district,
            "from": owner,
            "to": family,
            "until": min(now + DAY, d["until"]),
            "status": "pending",
        }
        return reply("transfer_offered", id=tid)

    def do_district_accept(self, s, actor, now, transfer):
        self.leader(s, actor)
        require(transfer in s["transfers"], "Предложение не найдено")
        t = s["transfers"][transfer]
        family = self.player(s, actor)["family"]
        d = s["districts"][t["district"]]
        require(t["status"] == "pending" and now < t["until"], "Предложение закрыто")
        require(t["to"] == family, "Предложение другой семье")
        require(
            d["owner"] == t["from"] and not d["contest"] and d["cooldown"] <= now,
            "Район уже нельзя передать",
        )
        require(self.owned_count(s, family) < 2, "Лимит: два района")
        self.spend(self.family(s, actor), "influence", 3)
        d.update(owner=family, cooldown=now + 7 * DAY)
        t["status"] = "accepted"
        result = reply(
            "transfer_accepted", district=DISTRICTS[t["district"]], family=FAMILIES[family]
        )
        result["news"] = {
            "key": "news_district",
            "values": {"district": DISTRICTS[t["district"]], "family": FAMILIES[family]},
        }
        return result

    def do_district_income(self, s, actor, now):
        family = self.player(s, actor)["family"]
        key = f"{family}:{week(now)}"
        require(key not in s["district_income"], "Доход районов уже получен на этой неделе")
        count = self.owned_count(s, family)
        require(count > 0, "У семьи нет районов")
        s["district_income"][key] = True
        # Districts themselves track payment, so transfers cannot duplicate this week's income.
        paid = 0
        for d in s["districts"].values():
            if d["owner"] == family and d.get("paid_week") != week(now):
                d["paid_week"] = week(now)
                paid += 20
        s["families"][family]["money"] += paid
        return reply("district_income", amount=paid)
