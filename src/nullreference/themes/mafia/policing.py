"""Private operational dashboard derived only from public operations and player status."""

from .rules import FAMILIES
from .underworld import available, restriction


def police_profile(state, actor, now):
    officer = state["players"][actor]
    department = state["families"]["police"]
    suspended = officer.get("suspended", 0) > now
    ready = available(officer, now) and not suspended
    content = (
        "## 🚔 Досье полицейского\n"
        f"Личные деньги: {officer['money']} · Касса отдела: {department['money']}\n"
        f"Влияние: {department['influence']} · Всего: {department['earned']}\n"
        f"Глава отдела: <@{department['leader']}>\n"
        f"Подозрение: {officer.get('suspicion', 0)}\n"
        + restriction(officer, now)
        + (f"\nОтстранение до <t:{int(officer['suspended'])}:f>" if suspended else "")
        + (
            "\n✅ Вы можете проводить облавы и аресты."
            if ready
            else "\n⛔ Пока вы ограничены или отстранены, облавы и аресты недоступны."
        )
    )
    fields = []
    for family, label in FAMILIES.items():
        if family == "police":
            continue
        clues = state["clues"].get(family, 0)
        operations = [
            (oid, op)
            for oid, op in state["operations"].items()
            if op["family"] == family and op["status"] == "open"
        ]
        lines = []
        if not operations:
            lines.append("📦 Активных дел нет — облава недоступна.")
        for oid, op in operations[:3]:
            if op.get("raid"):
                status = "облава уже назначена"
            elif now >= op["until"]:
                status = "сбор завершён, для облавы поздно"
            elif state["raid_cooldowns"].get(family, 0) > now:
                status = f"защита от облавы до <t:{int(state['raid_cooldowns'][family])}:f>"
            elif clues < 3:
                status = f"для облавы нужно ещё {3 - clues} улик"
            elif not ready:
                status = "условия для облавы выполнены; вы пока не можете действовать"
            else:
                status = f"✅ `/raid operation:{oid}` до <t:{int(op['until'])}:f>"
            lines.append(f"📦 Дело №{oid}: {status}.")
        if len(operations) > 3:
            lines.append(f"Других активных дел: {len(operations) - 3}; см. /status.")
        prisoner = next(
            (
                (uid, p)
                for uid, p in state["players"].items()
                if p.get("jail_family") == family and p.get("jail_until", 0) > now
            ),
            None,
        )
        if prisoner:
            uid, p = prisoner
            lines.append(
                f"🔒 Арест недоступен: <@{uid}> уже под стражей до <t:{int(p['jail_until'])}:f>."
            )
        elif clues < 4:
            lines.append(f"🔒 Для ареста нужно ещё {4 - clues} улик.")
        else:
            candidates = [
                uid
                for uid, p in state["players"].items()
                if p["family"] == family and available(p, now)
            ]
            if candidates:
                heading = "Кандидаты на арест" if ready else "После снятия ваших ограничений"
                lines.append(
                    "🔒 " + heading + ": " + ", ".join(f"<@{uid}>" for uid in candidates[:8]) + "."
                )
                if len(candidates) > 8:
                    lines.append(f"Ещё кандидатов: {len(candidates) - 8}.")
            else:
                lines.append(
                    "🔒 Улик достаточно, но доступных участников среди известных профилей нет."
                )
        fields.append({"name": f"{label} · 🔎 {clues} улик", "value": "\n".join(lines)})
    return {
        "content": content,
        "allowed_mentions": {"parse": []},
        "embeds": [
            {
                "title": "Оперативная сводка по семьям",
                "color": 3447003,
                "fields": fields,
                "description": "Облава: **3 улики**, арест: **4 улики**.\n"
                "Арестовать выбранного участника: `/arrest member:@Игрок`.",
                "footer": {
                    "text": "По известным игровым профилям. Актуальные роли, улики и сроки повторно проверяются при действии."
                },
            }
        ],
    }
