import asyncio
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from nullreference.application import Application
from nullreference.core.config import Config
from nullreference.core.flavour import FlavourCatalog
from nullreference.core.theme import RuleError
from nullreference.themes.mafia.commands import parse_options
from nullreference.themes.mafia.night_shift import ROUND, button_action
from nullreference.themes.mafia.policing import police_profile
from nullreference.themes.mafia.rules import DAY, MafiaSeason
from nullreference.themes.mafia.texts import DEFAULTS
from nullreference.visibility import deferred_response

NOW = 1793610000


def game():
    t = MafiaSeason(roll=lambda n: 0)
    s = t.initial_state()
    for uid, family in [
        ("1", "mafia"),
        ("2", "mafia"),
        ("3", "mafia"),
        ("4", "police"),
        ("5", "mafia"),
        ("6", "mafia"),
        ("7", "mafia"),
        ("8", "mafia"),
        ("9", "cartel"),
    ]:
        t.sync_members(s, {uid: family}, NOW)
        s["players"][uid]["money"] = 100
    s["families"]["mafia"].update(money=500, influence=10)
    return t, s


def act(t, s, action, actor="1", now=NOW, **args):
    candidate = deepcopy(s)
    result = t.apply(candidate, actor, action, now, **args)
    s.clear()
    s.update(candidate)
    return result


def ready(t, s, risk="normal", prepared=False, count=3):
    result = act(t, s, "operation_start", risk=risk, route="port", cargo=2, prepared=prepared)
    oid = result["news"]["values"]["id"]
    users = ["1", "2", "3", "5", "6", "7"][:count]
    for i, uid in enumerate(users):
        if uid != "1":
            act(t, s, "operation_join", actor=uid, operation=oid)
        act(
            t,
            s,
            "operation_task",
            actor=uid,
            operation=oid,
            task=("scout", "papers", "load")[i % 3],
        )
    return oid


def intercept(t, s, risk="normal", prepared=False):
    oid = ready(t, s, risk, prepared)
    act(t, s, "raid", actor="4", operation=oid, route="port")
    result = act(t, s, "operation_resolve", now=NOW + DAY, operation=oid)
    assert result["key"] == "night_intercept"
    return oid


@pytest.mark.parametrize(
    "risk,treasury,personal,influence",
    [
        ("low", 40, 15, 2),
        ("normal", 70, 25, 4),
        ("high", 110, 35, 6),
    ],
)
def test_free_route_ready_delivery_and_no_double_payout(risk, treasury, personal, influence):
    t, s = game()
    oid = ready(t, s, risk)
    # Different checkpoint: no outcome RNG or police rewards.
    act(t, s, "raid", actor="4", operation=oid, route="station")
    t.roll = lambda n: pytest.fail("Unintercepted delivery must not roll")
    result = act(t, s, "operation_resolve", now=NOW + DAY, operation=oid)
    assert result["key"] == "night_resolved"
    assert result["values"]["money"] == treasury
    assert s["families"]["mafia"]["money"] == 500 + treasury
    assert s["families"]["mafia"]["influence"] == 10 + influence
    assert all(s["players"][uid]["money"] == 100 + personal for uid in ("1", "2", "3"))
    assert s["families"]["police"]["money"] == s["families"]["police"]["influence"] == 0
    assert result["news"]["values"]["route"] == "⚓ Порт"
    before = deepcopy(s)
    with pytest.raises(RuleError):
        act(t, s, "operation_resolve", actor="2", now=NOW + DAY, operation=oid)
    assert s == before


def test_unprepared_members_do_not_count_and_mission_cancels_without_rewards():
    t, s = game()
    oid = ready(t, s, prepared=True, count=2)
    act(t, s, "operation_join", actor="3", operation=oid)
    result = act(t, s, "operation_resolve", now=NOW + DAY, operation=oid)
    assert "меньше трёх" in result["values"]["outcome"]
    assert s["families"]["mafia"]["money"] == 460
    assert all(s["players"][uid]["money"] == 100 for uid in ("1", "2", "3"))


def test_capacity_task_commit_and_deadlines():
    t, s = game()
    oid = ready(t, s, count=6)
    for action, kwargs in (
        ("operation_join", {"actor": "8"}),
        ("operation_task", {"actor": "1", "task": "papers"}),
    ):
        before = deepcopy(s)
        with pytest.raises(RuleError):
            act(t, s, action, operation=oid, **kwargs)
        assert s == before
    assert act(t, s, "operation_task", operation=oid, task="scout")["night"]
    with pytest.raises(RuleError):
        act(t, s, "operation_task", actor="2", now=NOW + DAY, operation=oid, task="papers")
    with pytest.raises(RuleError):
        act(t, s, "operation_resolve", now=NOW + DAY - 1, operation=oid)


def test_both_decisions_can_resolve_early_and_decoy_is_paid_only_once():
    t, s = game()
    oid = intercept(t, s)
    assert s["clues"]["mafia"] == 0
    assert s["families"]["police"]["influence"] == 0
    with pytest.raises(RuleError, match="Ожидаются"):
        act(t, s, "operation_resolve", now=NOW + DAY + 1, operation=oid)
    act(t, s, "raid_response", now=NOW + DAY + 1, operation=oid, decision="reroute")
    act(t, s, "raid_response", now=NOW + DAY + 2, operation=oid, decision="reroute")
    assert s["families"]["mafia"]["money"] == 480
    with pytest.raises(RuleError):
        act(t, s, "raid_response", now=NOW + DAY + 2, operation=oid, decision="continue")
    act(t, s, "raid_tactic", actor="4", now=NOW + DAY + 3, operation=oid, tactic="inspect")
    # Normal60 + three distinct tasks15 + decoy vs inspection20 ->95%.
    t.roll = lambda n: 94
    result = act(t, s, "operation_resolve", actor="4", now=NOW + DAY + 4, operation=oid)
    assert "шанс 95%" in result["values"]["outcome"]
    assert s["families"]["mafia"]["money"] == 550
    assert s["families"]["police"]["money"] == 10
    assert s["families"]["police"]["influence"] == 1


@pytest.mark.parametrize(
    "decision,tactic,expected",
    [
        ("reroute", "inspect", 95),
        ("reroute", "pursue", 60),
        ("reroute", "block", 80),
        ("continue", "inspect", 85),
        ("continue", "pursue", 70),
        ("continue", "block", 55),
    ],
)
def test_opposed_choices_have_distinct_documented_effects(decision, tactic, expected):
    t, s = game()
    oid = ready(t, s)
    op = s["operations"][oid]
    op.update(response=decision, tactic=tactic)
    assert t.night.chance(op, ["1", "2", "3"]) == expected
    op["tasks"] = {uid: "scout" for uid in ("1", "2", "3")}
    assert t.night.chance(op, ["1", "2", "3"]) == expected - 10


@pytest.mark.parametrize(
    "kwargs",
    [
        {"risk": "unknown", "route": "port"},
        {"risk": "high", "route": "unknown"},
        {"risk": "low", "route": "port", "cargo": 7},
    ],
)
def test_invalid_plan_does_not_spend_money_or_create_clues(kwargs):
    t, s = game()
    before = deepcopy(s)
    with pytest.raises(RuleError):
        act(t, s, "operation_start", **kwargs)
    assert s == before


def test_timeout_defaults_and_surrender_without_waiting():
    t, s = game()
    oid = intercept(t, s, prepared=True)
    act(t, s, "raid_response", now=NOW + DAY + 1, operation=oid, decision="cancel")
    result = act(t, s, "operation_resolve", now=NOW + DAY + 2, operation=oid)
    assert "без сопротивления" in result["values"]["outcome"]
    assert s["families"]["mafia"]["money"] == 480
    assert s["families"]["police"]["influence"] == 3
    assert s["players"]["1"].get("injured_until", 0) == 0
    t, s = game()
    oid = intercept(t, s)
    result = act(t, s, "operation_resolve", now=NOW + DAY + ROUND, operation=oid)
    assert "Прорыв" in result["values"]["outcome"] and "Досмотр" in result["values"]["outcome"]


@pytest.mark.parametrize(
    "risk,loss,injured", [("low", 0, False), ("normal", 1, True), ("high", 2, True)]
)
def test_confiscation_penalties_and_injury(risk, loss, injured):
    t, s = game()
    oid = intercept(t, s, risk)
    act(t, s, "raid_response", now=NOW + DAY + 1, operation=oid, decision="continue")
    act(t, s, "raid_tactic", actor="4", now=NOW + DAY + 1, operation=oid, tactic="block")
    draws = iter([99, 0, 0])
    t.roll = lambda n: next(draws)
    result = act(t, s, "operation_resolve", actor="4", now=NOW + DAY + 2, operation=oid)
    assert "конфискован" in result["values"]["outcome"]
    assert result["values"]["personal"] == result["values"]["money"] == 0
    assert s["families"]["mafia"]["influence"] == 10 - loss
    assert s["clues"]["mafia"] == loss
    assert (s["players"]["1"].get("injured_until", 0) > NOW + DAY) == injured
    assert s["families"]["police"]["money"] == 30


def test_hidden_routes_and_decisions_in_both_boards_and_public_news():
    t, s = game()
    oid = ready(t, s, "high")
    act(t, s, "raid", actor="4", operation=oid, route="station")
    police = act(t, s, "operation_board", actor="4", operation=oid)
    family = act(t, s, "operation_board", operation=oid)
    assert "Порт" not in police["details"] and "Горячий" not in police["details"]
    assert police["scenario_key"] is None
    assert "Вокзал" not in family["details"]
    with pytest.raises(RuleError):
        act(t, s, "operation_board", actor="9", operation=oid)
    summary = police_profile(s, "4", NOW)
    assert "Порт" not in str(summary) and "Вокзал" not in str(summary)
    for name in ("operation_start", "raid", "operation_board", "operation_task", "raid_tactic"):
        assert deferred_response({"type": 2, "data": {"name": name}})["data"]["flags"] == 64


def test_bribe_cancels_interception_with_existing_corruption_rules():
    t, s = game()
    oid = intercept(t, s)
    bid = act(t, s, "bribe_offer", now=NOW + DAY + 1, operation=oid, amount=20)["values"]["id"]
    act(t, s, "bribe_decide", actor="4", now=NOW + DAY + 2, bribe=bid, decision="accept")
    result = act(t, s, "operation_resolve", now=NOW + DAY + 3, operation=oid)
    assert "конверт" in result["values"]["outcome"]
    assert s["players"]["4"]["money"] == 120
    assert s["players"]["4"]["suspicion"] == 1
    assert s["families"]["police"]["money"] == 0


def test_button_owner_guard_and_application_panel_rendering():
    async def scenario():
        t, s = game()
        oid = ready(t, s)
        payload = {
            "type": 3,
            "member": {"user": {"id": "1"}},
            "data": {"custom_id": f"night:1:{oid}:board:view"},
        }
        assert button_action(payload) == ("operation_board", {"operation": oid})
        assert deferred_response(payload) == {"type": 6}
        payload["member"]["user"]["id"] = "2"
        with pytest.raises(RuleError):
            button_action(payload)
        payload["member"]["user"]["id"] = "1"
        app = Application(
            Config("test", "00" * 32, "1", "2", "unused"), SimpleNamespace(), SimpleNamespace()
        )
        app.act = AsyncMock(return_value=t.night.board(s, "1", NOW, oid))
        app.flavour = FlavourCatalog(
            SimpleNamespace(query=AsyncMock(return_value=[])), "2", "season"
        )
        response = await app.dispatch(payload)
        assert "Порт" in response["content"] and response["components"]
        assert response["allowed_mentions"] == {"parse": []}
        assert len(response["content"].encode("utf-16-le")) // 2 <= 2000
        for row in response["components"]:
            for button in row["components"]:
                assert len(button["custom_id"]) <= 100
        assert len([key for key in DEFAULTS if key.startswith("night_cargo_")]) == 18
        options = parse_options(
            {
                "data": {
                    "options": [
                        {"name": "risk", "value": "high"},
                        {"name": "route", "value": "highway"},
                    ]
                }
            },
            "operation_start",
        )
        assert options["risk"] == "high"
        for risk in ("low", "normal", "high"):
            catalog = await app.dispatch(
                {
                    "type": 2,
                    "member": {"user": {"id": "1"}},
                    "data": {
                        "name": "operation_catalog",
                        "options": [{"name": "risk", "value": risk}],
                    },
                }
            )
            assert len(catalog["content"].encode("utf-16-le")) // 2 <= 2000
            assert "**6.**" in catalog["content"]

    asyncio.run(scenario())
