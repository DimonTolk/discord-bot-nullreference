import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from nullreference.application import Application
from nullreference.core.config import Config
from nullreference.themes.mafia.policing import police_profile
from nullreference.themes.mafia.rules import MafiaSeason
from nullreference.visibility import deferred_response

NOW = 1793610000


def game():
    theme = MafiaSeason()
    state = theme.initial_state()
    theme.sync_members(state, {"1": "police", "2": "mafia", "3": "mafia", "4": "cartel"}, NOW)
    state["clues"] = {"mafia": 5, "cartel": 1}
    state["operations"]["7"] = {
        "family": "mafia",
        "status": "open",
        "until": NOW + 100,
        "raid": None,
    }
    state["plots"] = {"SECRET": {"target": "PRIVATE_TARGET", "organizer": "PRIVATE_OWNER", "status": "resolved"}}
    return theme, state


def mafia_field(response):
    return response["embeds"][0]["fields"][0]["value"]


def test_clues_ready_raids_and_candidates_are_private_and_never_show_plots():
    _, s = game()
    response = police_profile(s, "1", NOW)
    fields = response["embeds"][0]["fields"]
    assert len(fields) == 5
    assert fields[0]["name"] == "Мафия · 🔎 5 улик"
    assert "/raid operation:7" in fields[0]["value"]
    assert "<@2>" in fields[0]["value"] and "<@3>" in fields[0]["value"]
    assert "ещё 3 улик" in fields[2]["value"]  # Cartel: one of four clues.
    assert "SECRET" not in str(response) and "PRIVATE" not in str(response)
    assert response["allowed_mentions"] == {"parse": []}
    assert deferred_response({"type": 2, "data": {"name": "profile"}})["data"]["flags"] == 64


@pytest.mark.parametrize(
    "cause,expected",
    [
        ("clues", "ещё 1 улик"),
        ("deadline", "сбор завершён"),
        ("cooldown", "защита от облавы"),
        ("raid", "облава уже назначена"),
    ],
)
def test_raid_denial_reasons(cause, expected):
    _, s = game()
    if cause == "clues":
        s["clues"]["mafia"] = 2
    elif cause == "deadline":
        s["operations"]["7"]["until"] = NOW
    elif cause == "cooldown":
        s["raid_cooldowns"]["mafia"] = NOW + 100
    else:
        s["operations"]["7"]["raid"] = {"officer": "1"}
    value = mafia_field(police_profile(s, "1", NOW))
    assert expected in value and "/raid operation:7" not in value


def test_arrest_slots_remain_attributed_to_original_family_and_injuries_filter_candidates():
    _, s = game()
    s["players"]["2"].update(jail_family="mafia", jail_until=NOW + 100, family="cartel")
    value = mafia_field(police_profile(s, "1", NOW))
    assert "уже под стражей" in value and "Кандидаты на арест" not in value
    s["players"]["2"]["jail_until"] = NOW
    s["players"]["3"]["injured_until"] = NOW + 100
    value = mafia_field(police_profile(s, "1", NOW))
    assert "доступных участников" in value and "<@3>" not in value
    s["players"]["3"]["injured_until"] = NOW
    assert "<@3>" in mafia_field(police_profile(s, "1", NOW))


@pytest.mark.parametrize("field", ["suspended", "injured_until", "jail_until"])
def test_officer_restrictions_suppress_actionable_hints(field):
    _, s = game()
    s["players"]["1"][field] = NOW + 100
    response = police_profile(s, "1", NOW)
    assert "недоступны" in response["content"]
    assert "/raid operation:7" not in mafia_field(response)
    assert "После снятия" in mafia_field(response)


def test_large_rosters_and_many_operations_fit_discord_embed_limits():
    t, s = game()
    for i in range(200):
        t.sync_members(s, {str(900000000000000000 + i): "mafia"}, NOW)
        s["operations"][str(800000000000000000 + i)] = dict(s["operations"]["7"])
    response = police_profile(s, "1", NOW)
    embed = response["embeds"][0]
    assert all(len(field["value"].encode("utf-16-le")) // 2 <= 1024 for field in embed["fields"])
    assert len(str(embed).encode("utf-16-le")) // 2 < 6000
    assert "Ещё кандидатов: 194" in mafia_field(response)
    assert "Других активных дел: 198" in mafia_field(response)


def test_application_uses_police_dashboard_only_for_police():
    async def scenario():
        _, s = game()
        app = Application(
            Config("test", "00" * 32, "1", "2", "unused"), SimpleNamespace(), SimpleNamespace()
        )
        app.act = AsyncMock(return_value={"ok": True})
        app.state = AsyncMock(return_value=s)
        payload = {"type": 2, "member": {"user": {"id": "1"}}, "data": {"name": "profile"}}
        response = await app.dispatch(payload)
        assert response["embeds"][0]["title"] == "Оперативная сводка по семьям"
        app.act.assert_awaited_with(payload, "sync", {})
        s["plots"] = {}
        payload["member"]["user"]["id"] = "2"
        assert "embeds" not in await app.dispatch(payload)

    asyncio.run(scenario())
