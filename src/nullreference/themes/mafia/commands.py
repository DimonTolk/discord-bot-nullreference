"""One registry drives Discord registration, validation and admin authorization."""

from nullreference.core.theme import RuleError
from .rules import FAMILIES, DISTRICTS
from .help import TOPICS


def option(name, description, kind=3, required=True, choices=None, default=None, **limits):
    result = {
        "name": name,
        "description": description,
        "type": kind,
        "required": required,
        **limits,
    }
    if choices:
        result["choices"] = [{"name": label, "value": value} for value, label in choices.items()]
    return result, default


FAMILY = option("family", "Сторона", choices=FAMILIES)
DISTRICT = option("district", "Район", choices=DISTRICTS)
OPERATION = option("operation", "Номер дела", max_length=20)
KEY = option("key", "Ключ тематического текста", max_length=64)


def command(name, description, *options, admin=False):
    return {
        "name": name,
        "description": description,
        "type": 1,
        "dm_permission": False,
        "options": [o[0] for o in options],
        **({"default_member_permissions": "32"} if admin else {}),
        "_defaults": {o[0]["name"]: o[1] for o in options if not o[0]["required"]},
    }


COMMANDS = [
    command("start", "Знакомство с городом"),
    command(
        "help",
        "Подробная справка, права, лимиты и примеры",
        option("topic", "Раздел справки", required=False, choices=TOPICS, default="overview"),
    ),
    command("profile", "Личный кошелёк, влияние и касса семьи"),
    command("leaderboard", "Рейтинг сторон по заработанному влиянию"),
    command("status", "Карта районов и открытые операции"),
    command("inbox", "Личные конверты и предложения передачи районов"),
    command("work", "Подработка: 20–30 денег, три раза в неделю"),
    command(
        "donate",
        "Внести личные деньги в кассу",
        option("amount", "Сумма", 4, min_value=1, max_value=10000),
    ),
    command(
        "operation_start",
        "Открыть дело на 24 часа (глава семьи)",
        option("prepared", "Подготовка за 40 из кассы", 5, False, default=False),
    ),
    command("operation_join", "Присоединиться к делу своей семьи", OPERATION),
    command("operation_resolve", "Подвести итог дела после срока", OPERATION),
    command("investigate", "Проверить семью (полиция)", FAMILY),
    command("raid", "Назначить облаву за три улики", OPERATION),
    command(
        "raid_response",
        "Ответить на облаву (глава)",
        OPERATION,
        option(
            "decision",
            "Решение",
            choices={
                "cancel": "Отменить",
                "reroute": "Сменить маршрут: 40",
                "continue": "Продолжить",
            },
        ),
    ),
    command(
        "bribe_offer",
        "Предложить личные деньги за отмену облавы",
        OPERATION,
        option("amount", "Сумма", 4, min_value=20, max_value=200),
    ),
    command(
        "bribe_decide",
        "Ответить на адресованный вам конверт",
        option("bribe", "Номер конверта", max_length=20),
        option(
            "decision",
            "Решение",
            choices={
                "accept": "Принять",
                "reject": "Отказать",
                "evidence": "Оформить доказательство",
            },
        ),
    ),
    command("district_open", "Открыть розыгрыш района на 48 часов", DISTRICT, admin=True),
    command(
        "district_bid",
        "Подать заявку на район (глава)",
        DISTRICT,
        option("support", "Поддержка за 2 влияния", 5, False, default=False),
        option("supply", "Снабжение за 60 денег", 5, False, default=False),
    ),
    command("district_resolve", "Подвести итог розыгрыша района", DISTRICT),
    command("district_transfer", "Предложить передачу района (глава)", DISTRICT, FAMILY),
    command(
        "district_accept",
        "Принять район за 3 влияния (глава)",
        option("transfer", "Номер передачи", max_length=20),
    ),
    command("district_income", "Собрать недельный доход районов в кассу"),
    command(
        "reward",
        "Оплатить выполненное задание",
        FAMILY,
        option("reference", "Уникальный ключ задания", min_length=3, max_length=80),
        option("influence", "Влияние", 4, False, default=3, min_value=0, max_value=10),
        option("money", "Деньги в кассу", 4, False, default=0, min_value=0, max_value=200),
        admin=True,
    ),
    command(
        "leader_set",
        "Назначить главу по роли участника",
        option("member", "Участник", 6),
        admin=True,
    ),
    command(
        "family_role",
        "Привязать роль; без role — снять привязку",
        FAMILY,
        option("role", "Роль стороны", 8, False),
        admin=True,
    ),
    command("family_roles", "Посмотреть привязки игровых ролей", admin=True),
    command(
        "news_channel",
        "Выбрать канал городской газеты",
        option("channel", "Текстовый канал", 7, channel_types=[0]),
        admin=True,
    ),
    command("flavour_edit", "Изменить тематический текст без деплоя", KEY, admin=True),
    command("flavour_reset", "Восстановить стандартный текст", KEY, admin=True),
    command("flavour_export", "Выгрузить тексты приватными сообщениями", admin=True),
    command("setup", "Проверить миграции и зарегистрировать команды", admin=True),
    command(
        "weekly_tasks",
        "Расписание, пресеты и публикация задания недели",
        option(
            "action",
            "Действие",
            required=False,
            default="status",
            choices={
                "status": "Расписание",
                "enable": "Включить",
                "disable": "Выключить",
                "schedule": "Изменить время",
                "presets": "Список пресетов",
                "publish": "Опубликовать сейчас",
            },
        ),
        option("day", "День: 1 — понедельник, 7 — воскресенье", 4, False, min_value=1, max_value=7),
        option("hour", "Час по Минску", 4, False, min_value=0, max_value=23),
        option("minute", "Минута", 4, False, min_value=0, max_value=59),
        admin=True,
    ),
]
BY_NAME = {c["name"]: c for c in COMMANDS}
ADMIN_COMMANDS = {c["name"] for c in COMMANDS if "default_member_permissions" in c}


def manifest():
    return [{key: value for key, value in c.items() if not key.startswith("_")} for c in COMMANDS]


def is_admin(payload):
    permissions = int(payload.get("member", {}).get("permissions", "0"))
    return bool(permissions & (32 | 8))


def authorize(payload, name):
    if name not in BY_NAME:
        raise RuleError("Неизвестная команда")
    if name in ADMIN_COMMANDS and not is_admin(payload):
        raise RuleError("Нужно разрешение «Управлять сервером»")


def parse_options(payload, name):
    specs = {o["name"]: o for o in BY_NAME[name]["options"]}
    values = dict(BY_NAME[name]["_defaults"])
    for item in payload.get("data", {}).get("options", []):
        key, value = item["name"], item.get("value")
        if key not in specs:
            raise RuleError("Неизвестный параметр")
        spec = specs[key]
        kind = spec["type"]
        if (
            (kind == 4 and type(value) is not int)
            or (kind == 5 and type(value) is not bool)
            or (kind in (3, 6, 7, 8) and not isinstance(value, str))
        ):
            raise RuleError("Неверный тип параметра")
        if kind == 3 and not spec.get("min_length", 1) <= len(value) <= spec.get("max_length", 100):
            raise RuleError("Неверная длина параметра")
        if kind in (6, 7, 8) and not value.isdecimal():
            raise RuleError("Неверный идентификатор")
        if kind == 4 and not spec.get("min_value", -(10**9)) <= value <= spec.get(
            "max_value", 10**9
        ):
            raise RuleError("Сумма вне разрешённых границ")
        if spec.get("choices") and value not in {c["value"] for c in spec["choices"]}:
            raise RuleError("Неверный вариант")
        values[key] = value
    if any(s["required"] and key not in values for key, s in specs.items()):
        raise RuleError("Не хватает параметров")
    return values
