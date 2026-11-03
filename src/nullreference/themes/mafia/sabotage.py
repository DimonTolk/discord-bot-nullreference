"""Sealed influence campaigns: outside actions never alter the success probability."""

from nullreference.core.theme import RuleError

DAY = 86400


def require(ok, text):
    if not ok:
        raise RuleError(text)


def reply(key, **values):
    return {"key": key, "values": values}


def success_chance(operation):
    count = len(operation["members"])
    if count < 2:
        return 0
    return max(10, min(85, 60 + 8 * (count - 2) - 2 * operation["target_influence"]))


class MafiaSabotage:
    def __init__(self, season):
        self.season = season

    def start(self, state, actor, now, family, beneficiary=None):
        from .rules import FAMILIES, week

        t = self.season
        t.leader(state, actor)
        own = t.player(state, actor)["family"]
        beneficiary = beneficiary or own
        require(own != "police", "Полиция не организует подрыв влияния")
        require(
            family in FAMILIES and family not in (own, "police"), "Выберите другую преступную семью"
        )
        require(
            beneficiary in FAMILIES and beneficiary not in (family, "police"),
            "Получателем должна быть другая преступная семья",
        )
        require(state["families"][family]["influence"] > 0, "У цели пока нет влияния")
        operations = state.setdefault("sabotages", {})
        require(
            not any(op["family"] == own and op["status"] == "open" for op in operations.values()),
            "У семьи уже есть незавершённый подрыв влияния",
        )
        require(
            not any(op["family"] == own and op["week"] == week(now) for op in operations.values()),
            "Один подрыв влияния семьи в неделю",
        )
        t.spend(t.family(state, actor), "money", 40)
        operation = t.identifier(state)
        operations[operation] = {
            "organizer": actor,
            "family": own,
            "target": family,
            "beneficiary": beneficiary,
            "target_influence": state["families"][family]["influence"],
            "members": [actor],
            "until": now + DAY,
            "week": week(now),
            "status": "open",
            "outcome": "",
            "transferred": 0,
            "exposed": False,
        }
        return reply(
            "sabotage_started",
            id=operation,
            target=FAMILIES[family],
            beneficiary=FAMILIES[beneficiary],
            until=int(now + DAY),
        )

    def get(self, state, operation):
        require(operation in state.get("sabotages", {}), "Секретная операция недоступна")
        return state["sabotages"][operation]

    def join(self, state, actor, now, operation):
        op = self.get(state, operation)
        require(
            self.season.player(state, actor)["family"] == op["family"],
            "Секретная операция недоступна",
        )
        require(op["status"] == "open" and now < op["until"], "Сбор закрыт")
        require(actor not in op["members"], "Вы уже присоединились")
        require(len(op["members"]) < 12, "Максимум 12 участников")
        op["members"].append(actor)
        # No RNG, clues or news during recruitment. Participants receive no target/roster.
        return reply("sabotage_joined")

    def status(self, state, actor, now, operation):
        from .rules import FAMILIES

        op = self.get(state, operation)
        require(op["organizer"] == actor, "Статус доступен только организатору")
        return reply(
            "sabotage_status",
            id=operation,
            target=FAMILIES[op["target"]],
            beneficiary=FAMILIES[op["beneficiary"]],
            influence=op["target_influence"],
            chance=success_chance(op),
            members=", ".join(f"<@{uid}>" for uid in op["members"]),
            until=int(op["until"]),
            status=op["status"],
            outcome=op["outcome"] or "ожидается",
            amount=op["transferred"],
            exposure="раскрыта семья-организатор" if op["exposed"] else "нет раскрытия",
        )

    def resolve(self, state, actor, now, operation):
        from .rules import FAMILIES

        t = self.season
        op = self.get(state, operation)
        require(op["organizer"] == actor, "Итог подводит только организатор")
        require(op["status"] == "open", "Операция уже завершена")
        require(now >= op["until"], "До окончания срока операция засекречена")
        require(
            t.player(state, actor)["family"] == op["family"],
            "Для подведения итога вернитесь в исходную семью",
        )
        # Intentionally do not refresh/filter the committed roster or target influence snapshot.
        chance = success_chance(op)
        success = chance > 0 and t.roll(100) < chance
        exposed = not success and t.roll(100) < 42
        amount = 0
        if success:
            target = state["families"][op["target"]]
            amount = min(target["influence"], op["target_influence"], 2 + len(op["members"]))
            target["influence"] -= amount
            t.earn(state, op["beneficiary"], amount, now)
        outcome = "успех" if success else "неудача"
        op.update(status="resolved", outcome=outcome, transferred=amount, exposed=exposed)
        exposure = (
            f"Источники связывают операцию с семьёй «{FAMILIES[op['family']]}»."
            if exposed
            else "Организаторы остались неизвестны."
        )
        result = reply(
            "sabotage_resolved", id=operation, outcome=outcome, amount=amount, exposure=exposure
        )
        variant = t.roll(10) + 1
        suffix = "success" if success else "failure"
        key = f"news_sabotage_{op['target']}_{suffix}_{variant:02d}"
        values = (
            {"beneficiary": FAMILIES[op["beneficiary"]], "amount": amount}
            if success
            else {"exposure": exposure}
        )
        result["news"] = {"key": key, "values": values}
        return result
