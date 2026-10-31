from copy import deepcopy

import pytest

from nullreference.core.theme import RuleError
from nullreference.themes.mafia.rules import DAY, MafiaSeason, week

NOW = 1793448000.0


@pytest.fixture
def game():
    theme = MafiaSeason(roll=lambda n: 0)
    s = theme.initial_state()
    for uid, family in [("1", "mafia"), ("2", "mafia"), ("3", "police"), ("4", "cartel")]:
        theme.sync_members(s, {uid: family}, NOW)
    return theme, s


def transact(theme, s, actor, action, now=NOW, **args):
    """Mirror DB rollback on domain errors."""
    candidate = deepcopy(s)
    result = theme.apply(candidate, actor, action, now, **args)
    s.clear()
    s.update(candidate)
    return result


def prepare_raid(theme, s, now=NOW):
    oid = transact(theme, s, "1", "operation_start", now)["values"]["id"]
    transact(theme, s, "2", "operation_join", now, operation=oid)
    transact(theme, s, "3", "investigate", now, family="mafia")
    transact(theme, s, "3", "raid", now, operation=oid)
    return oid


def test_work_limits_and_no_negative_donation(game):
    t, s = game
    transact(t, s, "1", "work")
    assert s["players"]["1"]["money"] == 20
    for amount in (-1, 21):
        with pytest.raises(RuleError):
            transact(t, s, "1", "donate", amount=amount)
    with pytest.raises(RuleError):
        transact(t, s, "1", "work")
    assert s["families"]["mafia"]["money"] == 0


def test_weekly_work_limit(game):
    t, s = game
    # Start at Monday UTC and choose four successive days within that week.
    monday = 1793577600.0
    assert week(monday) == week(monday + 3 * DAY)
    for i in range(3):
        transact(t, s, "1", "work", monday + i * DAY)
    with pytest.raises(RuleError):
        transact(t, s, "1", "work", monday + 3 * DAY)


def test_operation_requires_two_and_pays_once(game):
    t, s = game
    oid = transact(t, s, "1", "operation_start")["values"]["id"]
    transact(t, s, "2", "operation_join", operation=oid)
    with pytest.raises(RuleError):
        transact(t, s, "1", "operation_resolve", operation=oid)
    transact(t, s, "1", "operation_resolve", NOW + DAY, operation=oid)
    assert s["families"]["mafia"]["influence"] == 4
    assert s["players"]["2"]["money"] == 25
    with pytest.raises(RuleError):
        transact(t, s, "2", "operation_resolve", NOW + DAY, operation=oid)


def test_bribe_accept_atomic_and_target_authorized(game):
    t, s = game
    oid = prepare_raid(t, s)
    s["players"]["1"]["money"] = 100
    bid = transact(t, s, "1", "bribe_offer", operation=oid, amount=60)["values"]["id"]
    assert s["players"]["1"]["money"] == 40
    with pytest.raises(RuleError):
        transact(t, s, "4", "bribe_decide", bribe=bid, decision="accept")
    transact(t, s, "3", "bribe_decide", bribe=bid, decision="accept")
    assert s["players"]["3"]["money"] == 60
    assert s["operations"][oid]["response"] == "bribed"
    with pytest.raises(RuleError):
        transact(t, s, "3", "bribe_decide", bribe=bid, decision="accept")
    transact(t, s, "1", "operation_resolve", NOW + DAY, operation=oid)
    assert s["families"]["police"]["earned"] == 2
    assert s["families"]["mafia"]["money"] == 40


@pytest.mark.parametrize("decision", ["reject", "evidence"])
def test_bribe_refund(game, decision):
    t, s = game
    oid = prepare_raid(t, s)
    s["players"]["1"]["money"] = 100
    bid = transact(t, s, "1", "bribe_offer", operation=oid, amount=60)["values"]["id"]
    transact(t, s, "3", "bribe_decide", bribe=bid, decision=decision)
    assert s["players"]["1"]["money"] == 100
    assert s["players"]["3"]["money"] == 0


def test_bribe_expiry_refunds_once(game):
    t, s = game
    oid = prepare_raid(t, s)
    s["players"]["1"]["money"] = 100
    transact(t, s, "1", "bribe_offer", operation=oid, amount=60)
    for _ in range(2):
        transact(t, s, "0", "tick", NOW + DAY + 1)
    assert s["players"]["1"]["money"] == 100


def test_corruption_suspension(game):
    t, s = game
    oid = prepare_raid(t, s)
    s["players"]["1"]["money"] = 100
    s["players"]["3"].update(suspicion=2, dirty=100, money=100)
    bid = transact(t, s, "1", "bribe_offer", operation=oid, amount=60)["values"]["id"]
    result = transact(t, s, "3", "bribe_decide", bribe=bid, decision="accept")
    assert result["news"]["key"] == "news_corruption"
    assert s["players"]["3"]["money"] == 80
    with pytest.raises(RuleError):
        transact(t, s, "3", "investigate", family="cartel")


def test_raid_continue_confiscates_and_rewards_police(game):
    t, s = game
    oid = prepare_raid(t, s)
    transact(t, s, "1", "raid_response", operation=oid, decision="continue")
    transact(t, s, "1", "operation_resolve", NOW + DAY, operation=oid)
    assert s["families"]["mafia"]["money"] == 20
    assert s["families"]["police"]["earned"] == 3


def test_reward_deduplication(game):
    t, s = game
    args = dict(family="mafia", influence=3, money=20, reference="week1:quiz:mafia")
    transact(t, s, "0", "reward", **args)
    with pytest.raises(RuleError):
        transact(t, s, "0", "reward", **args)
    assert s["families"]["mafia"]["earned"] == 3


def test_bid_failure_rolls_back_influence(game):
    t, s = game
    s["families"]["mafia"]["influence"] = 10
    transact(t, s, "0", "district_open", district="bank")
    with pytest.raises(RuleError):
        transact(t, s, "1", "district_bid", district="bank", supply=True)
    assert s["families"]["mafia"]["influence"] == 10
    assert not s["districts"]["bank"]["contest"]["bids"]


def test_district_transfer_preserves_deadline_and_income(game):
    t, s = game
    for family in ("mafia", "cartel"):
        t.earn(s, family, 20, NOW)
    transact(t, s, "0", "district_open", district="bank")
    transact(t, s, "1", "district_bid", district="bank")
    end = NOW + 2 * DAY
    transact(t, s, "1", "district_resolve", end, district="bank")
    until = s["districts"]["bank"]["until"]
    transact(t, s, "1", "district_income", end)
    tid = transact(t, s, "1", "district_transfer", end, district="bank", family="cartel")["values"][
        "id"
    ]
    transact(t, s, "4", "district_accept", end, transfer=tid)
    assert s["districts"]["bank"]["until"] == until
    assert s["districts"]["bank"]["owner"] == "cartel"
    result = transact(t, s, "4", "district_income", end)
    assert result["values"]["amount"] == 0
    with pytest.raises(RuleError):
        transact(t, s, "4", "district_transfer", end, district="bank", family="mafia")
    transact(t, s, "0", "tick", until)
    assert s["districts"]["bank"]["owner"] is None


def test_cross_family_operations_rejected(game):
    t, s = game
    oid = transact(t, s, "1", "operation_start")["values"]["id"]
    with pytest.raises(RuleError):
        transact(t, s, "4", "operation_join", operation=oid)
    with pytest.raises(RuleError):
        transact(t, s, "1", "investigate", family="cartel")


def test_only_leader_controls_family_resources_and_can_be_reassigned(game):
    t, s = game
    assert s["families"]["mafia"]["leader"] == "1"
    with pytest.raises(RuleError):
        transact(t, s, "2", "operation_start")
    transact(t, s, "0", "leader_set", member="2")
    transact(t, s, "2", "operation_start")
    with pytest.raises(RuleError):
        transact(t, s, "1", "district_transfer", district="bank", family="cartel")
