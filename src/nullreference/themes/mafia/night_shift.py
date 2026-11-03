"""Versioned asynchronous cargo operations with hidden routes and opposed decisions."""

from nullreference.core.theme import RuleError
from .underworld import available

DAY = 86400
ROUND = 6 * 3600
ROUTES = {"port": "⚓ Порт", "station": "🚂 Вокзал", "highway": "🛣️ Шоссе"}
RISKS = {"low": "🟢 Тихая доставка", "normal": "🟡 Серая сделка", "high": "🔴 Горячий груз"}
TASKS = {"scout": "🔭 Разведка", "papers": "📋 Документы", "load": "📦 Погрузка"}
TACTICS = {"inspect": "🔎 Досмотр", "pursue": "🚓 Погоня", "block": "🚧 Блокада"}
DECISIONS = {"cancel": "🏳️ Сдать груз", "reroute": "🚚 Ложный конвой · 20", "continue": "💨 Прорыв"}
PLANS = {
    "low": {"money": 40, "personal": 15, "influence": 2, "chance": 75, "loss": 0, "injury": 0},
    "normal": {"money": 70, "personal": 25, "influence": 4, "chance": 60, "loss": 1, "injury": 15},
    "high": {"money": 110, "personal": 35, "influence": 6, "chance": 45, "loss": 2, "injury": 30},
}


def require(ok, text):
    if not ok:
        raise RuleError(text)


def is_night(op):
    return op.get("kind") == "night_shift"


def button_action(payload):
    parts = payload.get("data", {}).get("custom_id", "").split(":")
    require(len(parts) == 5 and parts[0] == "night", "Некорректная кнопка дела")
    _, owner, operation, action, choice = parts
    require(owner == payload["member"]["user"]["id"], "Это чужой пульт")
    require(operation.isdecimal(), "Некорректный номер дела")
    allowed = {
        "task": TASKS,
        "raid": ROUTES,
        "family": DECISIONS,
        "tactic": TACTICS,
        "board": {"view": ""},
        "join": {"join": ""},
        "resolve": {"resolve": ""},
    }
    require(action in allowed and choice in allowed[action], "Неизвестное действие")
    names = {
        "task": ("operation_task", "task"),
        "raid": ("raid", "route"),
        "family": ("raid_response", "decision"),
        "tactic": ("raid_tactic", "tactic"),
        "board": ("operation_board", None),
        "join": ("operation_join", None),
        "resolve": ("operation_resolve", None),
    }
    name, argument = names[action]
    args = {"operation": operation}
    if argument:
        args[argument] = choice
    return name, args


class NightShift:
    def __init__(self, season):
        self.season = season

    def start(self, state, actor, now, risk, route, cargo=1, prepared=False):
        from .rules import week

        t = self.season
        t.leader(state, actor)
        family = t.player(state, actor)["family"]
        require(family != "police", "Полиция выбирает место облавы")
        require(risk in PLANS and route in ROUTES, "Выберите риск и скрытый маршрут")
        require(type(cargo) is int and 1 <= cargo <= 6, "Номер груза: 1–6, см. /operation_catalog")
        require(
            not any(
                op["family"] == family and op["status"] == "open"
                for op in state["operations"].values()
            ),
            "У семьи уже есть открытое дело",
        )
        require(
            not any(
                op["family"] == family and op["week"] == week(now)
                for op in state["operations"].values()
            ),
            "Одно дело семьи в неделю",
        )
        if prepared:
            t.spend(t.family(state, actor), "money", 40)
        oid = t.identifier(state)
        state["operations"][oid] = {
            "kind": "night_shift",
            "family": family,
            "organizer": actor,
            "members": [actor],
            "tasks": {},
            "risk": risk,
            "route": route,
            "cargo": cargo,
            "until": now + DAY,
            "status": "open",
            "stage": "recruiting",
            "week": week(now),
            "prepared": prepared,
            "raid": None,
            "response": None,
            "tactic": None,
            "decision_until": 0,
            "outcome": "",
            "money": 0,
            "influence": 0,
        }
        state["clues"][family] = state["clues"].get(family, 0) + 2
        result = self.board(state, actor, now, oid)
        result["news"] = {
            "key": "news_night_started",
            "values": {"family": self.family_name(family), "id": oid},
        }
        return result

    @staticmethod
    def family_name(family):
        from .rules import FAMILIES

        return FAMILIES[family]

    def get(self, state, operation):
        op = self.season.operation(state, operation)
        require(is_night(op), "Это старое дело: используйте прежние команды")
        return op

    def join(self, state, actor, now, operation):
        op = self.get(state, operation)
        require(self.season.player(state, actor)["family"] == op["family"], "Это дело другой семьи")
        require(op["stage"] == "recruiting" and now < op["until"], "Набор завершён")
        require(
            actor not in op["members"], "Вы уже участвуете; выберите подготовку в /operation_board"
        )
        require(len(op["members"]) < 6, "Лимит: 6 участников")
        op["members"].append(actor)
        return {"key": "night_joined", "values": {"id": operation}}

    def task(self, state, actor, now, operation, task):
        op = self.get(state, operation)
        require(
            actor in op["members"] and self.season.player(state, actor)["family"] == op["family"],
            "Сначала присоединитесь к делу своей семьи",
        )
        require(op["stage"] == "recruiting" and now < op["until"], "Подготовка закрыта")
        require(task in TASKS, "Неизвестная задача")
        previous = op["tasks"].get(actor)
        require(previous is None or previous == task, "Задача уже выбрана; изменить её нельзя")
        op["tasks"][actor] = task
        return self.board(state, actor, now, operation)

    def raid(self, state, actor, now, operation, route):
        t = self.season
        t.officer(state, actor, now)
        op = self.get(state, operation)
        require(now < op["until"] and op["stage"] == "recruiting", "Поздно ставить заслон")
        require(route in ROUTES, "Выберите место облавы: порт, вокзал или шоссе")
        require(not op["raid"], "Облава уже назначена")
        require(state["clues"].get(op["family"], 0) >= 2, "Для «Ночной смены» нужно 2 улики")
        require(
            state["raid_cooldowns"].get(op["family"], 0) <= now,
            "Действует защита от повторной облавы",
        )
        state["clues"][op["family"]] -= 2
        state["raid_cooldowns"][op["family"]] = now + 7 * DAY
        op["raid"] = {
            "officer": actor,
            "route": route,
            "until": op["until"] + ROUND,
            "evidence": False,
        }
        # No points for guessing a checkpoint. Police rewards require actual interception.
        return self.board(state, actor, now, operation)

    def family_decision(self, state, actor, now, operation, decision):
        t = self.season
        t.leader(state, actor)
        op = self.get(state, operation)
        require(t.player(state, actor)["family"] == op["family"], "Это дело другой семьи")
        require(
            op["stage"] == "intercept" and now < op["decision_until"],
            "Нет открытого раунда решений",
        )
        require(decision in DECISIONS, "Неизвестное решение")
        if op["response"] == decision:
            return self.board(state, actor, now, operation)
        require(op["response"] is None, "Решение уже принято")
        if decision == "reroute":
            t.spend(t.family(state, actor), "money", 20)
        op["response"] = decision
        return self.board(state, actor, now, operation)

    def tactic(self, state, actor, now, operation, tactic):
        self.season.officer(state, actor, now)
        op = self.get(state, operation)
        require(op["raid"] and op["raid"]["officer"] == actor, "Вы не руководите этой облавой")
        require(
            op["stage"] == "intercept" and now < op["decision_until"],
            "Нет открытого раунда решений",
        )
        require(tactic in TACTICS, "Неизвестная тактика")
        require(op["tactic"] is None or op["tactic"] == tactic, "Тактика уже выбрана")
        op["tactic"] = tactic
        return self.board(state, actor, now, operation)

    def ready_members(self, state, op, now):
        return [
            uid
            for uid in op["members"]
            if state["players"][uid]["family"] == op["family"]
            and available(state["players"][uid], now)
            and uid in op["tasks"]
        ]

    def chance(self, op, members):
        base = PLANS[op["risk"]]["chance"]
        bonus = (
            5 * (len(members) - 3)
            + 5 * len({op["tasks"][uid] for uid in members})
            + 10 * op["prepared"]
        )
        modifiers = {
            "reroute": {"inspect": 20, "pursue": -15, "block": 5},
            "continue": {"inspect": 10, "pursue": -5, "block": -20},
        }
        return max(
            10,
            min(
                95,
                base + bonus + modifiers[op["response"] or "continue"][op["tactic"] or "inspect"],
            ),
        )

    def resolve(self, state, actor, now, operation):
        t = self.season
        op = self.get(state, operation)
        family_actor = t.player(state, actor)["family"] == op["family"]
        officer = op["raid"] and op["raid"]["officer"] == actor
        require(family_actor or officer, "Итог доступен семье или назначенному полицейскому")
        if officer:
            t.officer(state, actor, now)
        require(now >= op["until"], "Сбор ещё идёт")
        members = self.ready_members(state, op, now)
        if len(members) < 3:
            return self.finish(
                state,
                op,
                operation,
                now,
                [],
                False,
                "отмена: меньше трёх подготовленных участников",
                False,
            )
        matched = bool(op["raid"] and op["raid"]["route"] == op["route"])
        if not matched or op["response"] == "bribed":
            return self.finish(
                state,
                op,
                operation,
                now,
                members,
                True,
                "груз прошёл: " + ("облава отменена за конверт" if matched else "маршрут свободен"),
                False,
            )
        if op["stage"] == "recruiting":
            op.update(stage="intercept", decision_until=now + ROUND)
            op["raid"]["until"] = now + ROUND
            result = {
                "key": "night_intercept",
                "values": {"id": operation, "until": int(now + ROUND)},
            }
            result["news"] = {"key": "news_night_intercept", "values": result["values"]}
            return result
        if op["response"] == "cancel":
            return self.finish(
                state, op, operation, now, [], False, "груз сдан без сопротивления", True
            )
        require(
            (op["response"] and op["tactic"]) or now >= op["decision_until"],
            "Ожидаются решения сторон; откройте /operation_board",
        )
        probability = self.chance(op, members)
        success = t.roll(100) < probability
        outcome = "груз вырвался из облавы" if success else "груз конфискован"
        outcome += f"; шанс {probability}%; {DECISIONS[op['response'] or 'continue']} / {TACTICS[op['tactic'] or 'inspect']}"
        return self.finish(state, op, operation, now, members, success, outcome, True)

    def finish(self, state, op, oid, now, members, success, outcome, intercepted):
        t = self.season
        plan = PLANS[op["risk"]]
        money, influence = (plan["money"], plan["influence"]) if success else (0, 0)
        if op["response"] == "cancel" and intercepted:
            money = 20 if op["prepared"] else 0
        if success:
            for uid in members:
                state["players"][uid]["money"] += plan["personal"]
            t.earn(state, op["family"], influence, now)
        elif intercepted and op["response"] != "cancel":
            lost = min(state["families"][op["family"]]["influence"], plan["loss"])
            state["families"][op["family"]]["influence"] -= lost
            state["clues"][op["family"]] = state["clues"].get(op["family"], 0) + plan["loss"]
            outcome += f"; потеря влияния {lost}, улик +{plan['loss']}"
            if members and plan["injury"] and t.roll(100) < plan["injury"]:
                uid = members[t.roll(len(members))]
                t.underworld.disable(state, uid, now, "injured")
                outcome += f"; <@{uid}> восстанавливается 24 часа"
        if intercepted:
            t.earn(state, "police", 1 if success else 3, now)
            state["families"]["police"]["money"] += 10 if success else 30
        state["families"][op["family"]]["money"] += money
        op.update(
            status="resolved", stage="done", outcome=outcome, money=money, influence=influence
        )
        result = {
            "key": "night_resolved",
            "values": {
                "id": oid,
                "outcome": outcome,
                "money": money,
                "influence": influence,
                "personal": plan["personal"] if success else 0,
            },
        }
        result["news"] = {
            "key": "news_night_result",
            "values": {
                "family": self.family_name(op["family"]),
                "id": oid,
                "risk": RISKS[op["risk"]],
                "route": ROUTES[op["route"]],
                "outcome": outcome,
                "money": money,
                "influence": influence,
            },
        }
        return result

    def board(self, state, actor, now, operation):
        t = self.season
        require(
            operation in state["operations"] and is_night(state["operations"][operation]),
            "Ночная смена не найдена",
        )
        op = state["operations"][operation]
        p = t.player(state, actor)
        family = p["family"] == op["family"]
        police = p["family"] == "police"
        require(family or police, "Пульт доступен семье и полиции")
        details = [
            f"## 🌃 Ночная смена №{operation}",
            f"Семья: {self.family_name(op['family'])}",
            f"Сбор до <t:{int(op['until'])}:f> · Статус: {op['stage']}",
        ]
        controls = []
        if family:
            details += [
                f"Риск: {RISKS[op['risk']]} · Ваш маршрут: {ROUTES[op['route']]}",
                f"Участники: {len(op['members'])}/6 · Подготовлены: {len(self.ready_members(state, op, now))} (минимум 3)",
                f"Ваша задача: {TASKS.get(op['tasks'].get(actor), 'не выбрана')}",
            ]
            plan = PLANS[op["risk"]]
            details += [
                f"Успех: {plan['money']} в кассу, {plan['personal']} каждому, {plan['influence']} влияния.",
                "Бонус перехвата: +5 п.п. за вид подготовки, +5 за участника сверх третьего, +10 за подготовку за 40.",
                f"Конфискация: −{plan['loss']} влияния, +{plan['loss']} улик; риск ранения одного участника {plan['injury']}%.",
            ]
            if op["stage"] == "recruiting" and now < op["until"]:
                if actor not in op["members"]:
                    controls.append(("join", {"join": "🤝 Присоединиться"}))
                elif actor not in op["tasks"]:
                    controls.append(("task", TASKS))
            if op["stage"] == "intercept":
                details += [
                    f"Вы перехвачены. Решения до <t:{int(op['decision_until'])}:f>.",
                    "Сдача сохраняет людей, но теряет груз. Ложный конвой помогает против досмотра, уязвим для погони. Прорыв бесплатен, уязвим для блокады.",
                    f"Ваше решение: {DECISIONS.get(op['response'], op['response'] or 'не выбрано')}",
                ]
                if (
                    state["families"][op["family"]]["leader"] == actor
                    and op["response"] is None
                    and now < op["decision_until"]
                ):
                    controls.append(("family", DECISIONS))
        else:
            details += ["Маршрут семьи и груз засекречены."]
            raid = op["raid"]
            if raid and raid["officer"] == actor:
                details.append("Ваш заслон: " + ROUTES[raid["route"]])
                if op["stage"] == "intercept":
                    details += [
                        f"Перехват подтверждён. Решения до <t:{int(op['decision_until'])}:f>.",
                        "Погоня ловит ложный конвой; блокада мешает прорыву; досмотр — мягкая тактика по умолчанию.",
                        "Ваша тактика: " + TACTICS.get(op["tactic"], "не выбрана"),
                    ]
                    if op["tactic"] is None and now < op["decision_until"]:
                        controls.append(("tactic", TACTICS))
            elif not raid and op["status"] == "open" and now < op["until"]:
                details.append(
                    "Поставить заслон: 2 улики. Повторная облава на семью — раз в 7 суток."
                )
                controls.append(("raid", ROUTES))
            elif raid:
                details.append("Облава поручена другому сотруднику; место скрыто.")
        if op["status"] == "resolved":
            details.append("Итог: " + op["outcome"])
        buttons = []
        if op["status"] == "open":
            controls.append(("board", {"view": "🔄 Обновить"}))
            if family or (op["raid"] and op["raid"]["officer"] == actor):
                controls.append(("resolve", {"resolve": "📰 Подвести итог"}))
        for action, choices in controls:
            row = [
                {
                    "type": 2,
                    "style": 1 if action not in ("board", "resolve") else 2,
                    "label": label,
                    "custom_id": f"night:{actor}:{operation}:{action}:{choice}",
                }
                for choice, label in choices.items()
            ]
            buttons.append({"type": 1, "components": row})
        return {
            "night": True,
            "details": "\n".join(details),
            "components": buttons,
            "scenario_key": f"night_cargo_{op['risk']}_{op['cargo']}" if family else None,
        }
