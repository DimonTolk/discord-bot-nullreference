"""One registry drives Discord registration, validation and admin authorization."""

from nullreference.core.theme import RuleError
from .rules import FAMILIES, DISTRICTS
from .help import TOPICS
from .night_shift import ROUTES, RISKS, TASKS, TACTICS


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
    command(
        "plot_start",
        "Секретно организовать покушение: 40 из кассы (глава)",
        option("target", "Цель — участник другой стороны", 6),
    ),
    command(
        "plot_join",
        "Секретно присоединиться по номеру покушения",
        option("plot", "Номер от организатора", max_length=20),
    ),
    command(
        "plot_status",
        "Секретный статус покушения (только организатор)",
        option("plot", "Номер покушения", max_length=20),
    ),
    command(
        "plot_resolve",
        "Подвести итог покушения после 24 часов (организатор)",
        option("plot", "Номер покушения", max_length=20),
    ),
    command(
        "arrest",
        "Арестовать члена семьи за 4 улики на 24 часа (полиция)",
        option("member", "Кого арестовать", 6),
    ),
    command(
        "bail",
        "Залог 60 из кассы: шанс освобождения 50% (глава)",
        option("member", "Заключённый вашей семьи", 6),
    ),
    command("cooperate", "За 2 влияния создать улику, пока член семьи под арестом", FAMILY),
    command("evidence", "Посмотреть количество улик по семьям (полиция)"),
    command(
        "sabotage_start",
        "Тайно перехватить влияние: 40 из кассы (глава)",
        option("family", "Цель", choices={k: v for k, v in FAMILIES.items() if k != "police"}),
        option(
            "beneficiary",
            "Получатель, по умолчанию ваша семья",
            required=False,
            choices={k: v for k, v in FAMILIES.items() if k != "police"},
        ),
    ),
    command("sabotage_join", "Тайно присоединиться к подрыву влияния", OPERATION),
    command("sabotage_status", "Секретный статус подрыва влияния (организатор)", OPERATION),
    command(
        "sabotage_resolve", "Подвести итог подрыва влияния после срока (организатор)", OPERATION
    ),
    command("inbox", "Личные конверты и предложения передачи районов"),
    command(
        "slots",
        "Слоты: личная ставка 5–20, общий лимит казино 5 игр в день",
        option("amount", "Личная ставка", 4, min_value=5, max_value=20),
    ),
    command(
        "blackjack",
        "Начать блэкджек: личная ставка от 10",
        option("amount", "Личная ставка", 4, min_value=10, max_value=2**53 - 1),
    ),
    command("blackjack_table", "Показать свою раздачу и кнопки, без новой ставки"),
    command(
        "casino_channel",
        "Настроить канал казино",
        option("channel", "Канал казино", 7, channel_types=[0]),
        admin=True,
    ),
    command("work", "Подработка: 20–30 денег, три раза в неделю"),
    command(
        "donate",
        "Внести личные деньги в кассу",
        option("amount", "Сумма", 4, min_value=1, max_value=10000),
    ),
    command(
        "operation_start",
        "Ночная смена: выбрать риск и скрытый маршрут (глава)",
        option("risk", "Уровень риска", choices=RISKS),
        option("route", "Скрытый маршрут", choices=ROUTES),
        option(
            "cargo", "Груз 1–6 из /operation_catalog", 4, False, default=1, min_value=1, max_value=6
        ),
        option("prepared", "Подготовка за 40 из кассы", 5, False, default=False),
    ),
    command(
        "operation_catalog",
        "Шесть грузов для выбранного риска",
        option("risk", "Уровень риска", choices=RISKS),
    ),
    command("operation_board", "Личный пульт дела с кнопками и скрытой информацией", OPERATION),
    command(
        "operation_task",
        "Выбрать задачу подготовки один раз",
        OPERATION,
        option("task", "Подготовка", choices=TASKS),
    ),
    command(
        "raid_tactic",
        "Выбрать тактику при перехвате (назначенный полицейский)",
        OPERATION,
        option("tactic", "Тактика", choices=TACTICS),
    ),
    command("operation_join", "Присоединиться к делу своей семьи", OPERATION),
    command("operation_resolve", "Подвести итог дела после срока", OPERATION),
    command(
        "patrol",
        "Патруль: шанс 60% на улику, раз в сутки, 3 раза в неделю на полицейского",
        option(
            "family",
            "Против какой семьи собирать улики",
            choices={k: v for k, v in FAMILIES.items() if k != "police"},
        ),
    ),
    command("investigate", "Проверить семью: шанс 60% на улику (полиция)", FAMILY),
    command(
        "raid",
        "Тайно поставить заслон: 2 улики для Ночной смены, 3 для старых дел",
        OPERATION,
        option("route", "Скрытое место заслона (Ночная смена)", required=False, choices=ROUTES),
    ),
    command(
        "raid_response",
        "Ответить на облаву (глава)",
        OPERATION,
        option(
            "decision",
            "Решение",
            choices={
                "cancel": "Сдать груз (старое дело: отменить)",
                "reroute": "Ложный конвой: 20 (старое дело: смена маршрута за 40)",
                "continue": "Прорыв (старое дело: продолжить)",
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
