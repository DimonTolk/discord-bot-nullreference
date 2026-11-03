from copy import deepcopy

import pytest

from nullreference.core.theme import RuleError
from nullreference.themes.mafia.commands import BY_NAME
from nullreference.themes.mafia.rules import DAY, MafiaSeason
from nullreference.visibility import deferred_response

NOW = 1793610000


def game(roll=lambda n: 99):
    t = MafiaSeason(roll=roll)
    s = t.initial_state()
    for uid, family in [
        ("1", "mafia"),
        ("2", "mafia"),
        ("3", "police"),
        ("4", "cartel"),
        ("5", "cartel"),
        ("6", "mafia"),
    ]:
        t.sync_members(s, {uid: family}, NOW)
        s["players"][uid]["money"] = 101
    s["families"]["mafia"].update(money=500, influence=20)
    s["families"]["cartel"].update(money=500, influence=20)
    return t, s


def act(t, s, actor, action, now=NOW, **args):
    candidate = deepcopy(s)
    result = t.apply(candidate, actor, action, now, **args)
    s.clear()
    s.update(candidate)
    return result


def plot(t, s):
    return act(t, s, "1", "plot_start", target="4")["values"]["id"]


def test_plot_privacy_permissions_and_recruit_validation():
    t, s = game()
    pid = plot(t, s)
    assert s["families"]["mafia"]["money"] == 460
    for name in ("plot_start", "plot_join", "plot_status", "plot_resolve", "cooperate", "evidence"):
        assert deferred_response({"type": 2, "data": {"name": name}})["data"]["flags"] == 64
    for uid in ("2", "3", "4"):
        with pytest.raises(RuleError):
            act(t, s, uid, "plot_status", plot=pid)
    for uid in ("3", "4"):
        with pytest.raises(RuleError):
            act(t, s, uid, "plot_join", plot=pid)
    result = act(t, s, "2", "plot_join", plot=pid)
    assert result == {"key": "plot_joined", "values": {}}
    assert act(t, s, "1", "plot_status", plot=pid)["values"]["chance"] == 40
    before = deepcopy(s)
    with pytest.raises(RuleError):
        act(t, s, "2", "plot_join", plot=pid)
    assert before == s
    with pytest.raises(RuleError):
        act(t, s, "1", "plot_start", target="5")
    with pytest.raises(RuleError):
        act(t, s, "2", "plot_resolve", now=NOW + DAY, plot=pid)
    with pytest.raises(RuleError):
        act(t, s, "1", "plot_resolve", plot=pid)


@pytest.mark.parametrize(
    "leak,name,news,clues",
    [
        (42, 0, None, 0),
        (41, 50, "news_plot_leak", 0),
        (41, 49, "news_plot_named", 3),
    ],
)
def test_leak_and_conditional_identity_boundaries(leak, name, news, clues):
    draws = iter([leak, name])
    t, s = game(roll=lambda n: next(draws))
    pid = plot(t, s)
    result = act(t, s, "2", "plot_join", plot=pid)
    assert result.get("news", {}).get("key") == news
    assert s["clues"].get("mafia", 0) == clues
    if news:
        values = result["news"]["values"]
        assert values["target"] == "<@4>"
        assert ("organizer" in values) == (news == "news_plot_named")


def test_each_named_recruit_leak_adds_clues_once():
    t, s = game(roll=lambda n: 0)
    pid = plot(t, s)
    act(t, s, "2", "plot_join", plot=pid)
    act(t, s, "6", "plot_join", plot=pid)
    assert s["clues"]["mafia"] == 6
    assert s["plots"][pid]["leaks"] == 2


def test_plot_week_limit_and_changed_or_incapacitated_targets():
    t, s = game()
    pid = plot(t, s)
    act(t, s, "2", "plot_join", plot=pid)
    # A target moving into the attacking family must not be attacked.
    t.sync_members(s, {"4": "mafia"}, NOW + DAY)
    result = act(t, s, "1", "plot_resolve", now=NOW + DAY, plot=pid)
    assert result["values"]["outcome"] == "цель недоступна"
    with pytest.raises(RuleError, match="неделю"):
        act(t, s, "1", "plot_start", now=NOW + DAY, target="5")
    assert act(t, s, "1", "plot_start", now=NOW + 7 * DAY, target="5")["key"] == "plot_started"


def test_invalid_plot_start_is_free_and_organizer_role_change_cancels():
    t, s = game()
    for actor, target in (("2", "4"), ("3", "4"), ("1", "1"), ("1", "2")):
        before = deepcopy(s)
        with pytest.raises(RuleError):
            act(t, s, actor, "plot_start", target=target)
        assert s == before
    pid = plot(t, s)
    t.sync_members(s, {"1": "cartel"}, NOW)
    assert s["plots"][pid]["status"] == "cancelled"
    assert s["families"]["mafia"]["money"] == 460


def test_public_status_omits_private_plots_and_join_reply_omits_news_payload():
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from nullreference.application import Application
    from nullreference.core.config import Config
    from nullreference.core.flavour import FlavourCatalog

    async def scenario():
        t, s = game(roll=lambda n: 0)
        pid = plot(t, s)
        joined = act(t, s, "2", "plot_join", plot=pid)
        # Even a join that leaked externally has a generic private acknowledgement.
        app = Application(
            Config("test", "00" * 32, "1", "2", "unused"), SimpleNamespace(), SimpleNamespace()
        )
        app.state = AsyncMock(return_value=s)
        app.act = AsyncMock(return_value=joined)
        app.flavour = FlavourCatalog(
            SimpleNamespace(query=AsyncMock(return_value=[])), "2", "season"
        )
        payload = {
            "type": 2,
            "member": {"user": {"id": "2"}},
            "data": {"name": "plot_join", "options": [{"name": "plot", "value": pid}]},
        }
        response = await app.dispatch(payload)
        assert "<@4>" not in str(response) and "<@1>" not in str(response)
        payload["data"] = {"name": "status"}
        status = await app.dispatch(payload)
        assert "<@4>" not in str(status) and "покушение" not in status["content"].lower()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "count,roll,success",
    [(1, 0, False), (2, 39, True), (2, 40, False), (6, 79, True), (12, 80, False)],
)
def test_success_probability_and_half_wallet(count, roll, success):
    t, s = game()
    pid = plot(t, s)
    for i in range(count - 1):
        uid = str(100 + i)
        t.sync_members(s, {uid: "mafia"}, NOW)
        act(t, s, uid, "plot_join", plot=pid)
    t.roll = lambda n: roll
    result = act(t, s, "1", "plot_resolve", now=NOW + DAY, plot=pid)
    assert (result["values"]["outcome"] == "успех") == success
    assert "news" not in result
    assert s["players"]["4"]["money"] == (51 if success else 101)
    assert s["families"]["cartel"]["money"] == 500
    before = deepcopy(s)
    with pytest.raises(RuleError):
        act(t, s, "1", "plot_resolve", now=NOW + DAY, plot=pid)
    assert s == before


def test_incapacitation_cancels_plots_removes_members_and_settles_escrow():
    draws = iter([9, 7, 0, 5])
    t, s = game(roll=lambda n: next(draws))
    act(t, s, "4", "blackjack", amount=10)  # 18 vs soft17: win20 when forced to stand.
    oid = act(t, s, "4", "operation_start")["values"]["id"]
    ownplot = act(t, s, "4", "plot_start", target="1")["values"]["id"]
    pid = plot(t, s)
    t.roll = lambda n: 99
    act(t, s, "2", "plot_join", plot=pid)
    t.roll = lambda n: 0
    act(t, s, "1", "plot_resolve", now=NOW + DAY, plot=pid)
    assert s["players"]["4"]["blackjack"]["status"] == "done"
    assert s["players"]["4"]["money"] == 56  # 101-10+20=111; lose55.
    assert "4" not in s["operations"][oid]["members"]
    assert s["plots"][ownplot]["status"] == "cancelled"


def test_all_game_mutations_blocked_but_views_available_and_roles_do_not_clear():
    t, s = game()
    s["players"]["1"]["injured_until"] = NOW + DAY
    read_or_admin = {
        "sync",
        "tick",
        "blackjack_table",
        "plot_status",
        "evidence",
        "leader_set",
        "reward",
        "district_open",
    }
    handlers = {name[3:] for name in dir(t) if name.startswith("do_")}
    for action in handlers - read_or_admin:
        with pytest.raises(RuleError, match="Восстановление"):
            act(t, s, "1", action)  # Central guard precedes argument-specific validation.
    act(t, s, "1", "sync")
    t.sync_members(s, {"1": "cartel"}, NOW)
    with pytest.raises(RuleError, match="Восстановление"):
        act(t, s, "1", "work", now=NOW + DAY - 1)
    assert act(t, s, "1", "work", now=NOW + DAY)["key"] == "work"
    assert "blackjack_move" in handlers and "blackjack_move" not in BY_NAME


def test_arrest_consumes_four_preserves_excess_and_one_family_slot():
    t, s = game()
    s["clues"]["cartel"] = 9
    result = act(t, s, "3", "arrest", member="4")
    assert result["news"]["key"] == "news_arrest"
    assert s["clues"]["cartel"] == 5
    assert s["players"]["4"]["money"] == 101
    with pytest.raises(RuleError, match="заключённый"):
        act(t, s, "3", "arrest", member="5")
    t.sync_members(s, {"4": "mafia"}, NOW)
    with pytest.raises(RuleError, match="заключённый"):
        act(t, s, "3", "arrest", member="5")
    with pytest.raises(RuleError, match="Под арестом"):
        act(t, s, "4", "slots", amount=5)
    act(t, s, "3", "arrest", now=NOW + DAY, member="5")
    assert s["clues"]["cartel"] == 1
    with pytest.raises(RuleError, match="4 улики"):
        act(t, s, "3", "arrest", now=NOW + 2 * DAY, member="5")


@pytest.mark.parametrize("roll,released", [(49, True), (50, False)])
def test_bail_cost_chance_and_single_attempt(roll, released):
    t, s = game(roll=lambda n: roll)
    s["clues"]["cartel"] = 4
    act(t, s, "3", "arrest", member="5")
    with pytest.raises(RuleError):
        act(t, s, "1", "bail", member="5")
    act(t, s, "4", "bail", member="5")
    assert s["families"]["cartel"]["money"] == 440
    assert (s["players"]["5"]["jail_until"] == NOW) == released
    with pytest.raises(RuleError):
        act(t, s, "4", "bail", member="5")
    assert s["families"]["cartel"]["money"] == 440


def test_cooperation_requires_actual_custody_and_influence_and_eligible_leader():
    t, s = game()
    with pytest.raises(RuleError):
        act(t, s, "4", "cooperate", family="mafia")
    s["clues"]["cartel"] = 4
    act(t, s, "3", "arrest", member="5")
    for _ in range(4):
        act(t, s, "4", "cooperate", family="mafia")
    assert s["clues"]["mafia"] == 4
    assert s["families"]["cartel"]["influence"] == 12
    for target in ("cartel", "police"):
        with pytest.raises(RuleError):
            act(t, s, "4", "cooperate", family=target)
    with pytest.raises(RuleError):
        act(t, s, "4", "cooperate", now=NOW + DAY, family="mafia")
    s["families"]["cartel"]["influence"] = 1
    with pytest.raises(RuleError):
        act(t, s, "4", "cooperate", family="mafia")
    assert s["clues"]["mafia"] == 4


def test_raid_preserves_surplus_and_investigation_can_exceed_three():
    t, s = game(roll=lambda n: 0)
    oid = act(t, s, "1", "operation_start")["values"]["id"]
    s["clues"]["mafia"] = 4
    act(t, s, "3", "investigate", family="mafia")
    assert s["clues"]["mafia"] == 5
    act(t, s, "3", "raid", operation=oid)
    assert s["clues"]["mafia"] == 2
    assert "Мафия: 2" in act(t, s, "3", "evidence")["values"]["clues"]
