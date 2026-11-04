import asyncio
from copy import deepcopy
from itertools import product
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from nullreference.application import Application
from nullreference.core.config import Config
from nullreference.core.theme import RuleError
from nullreference.themes.mafia.casino import component_action, render, total
from nullreference.themes.mafia.commands import parse_options
from nullreference.themes.mafia.rules import MafiaSeason
from nullreference.visibility import deferred_response

NOW = 1793610000  # Monday 2026-11-02.


def game(draws=()):
    sequence = iter(draws)
    theme = MafiaSeason(roll=lambda n: next(sequence))
    state = theme.initial_state()
    theme.sync_members(state, {"1": "mafia", "2": "police"}, NOW)
    state["players"]["1"]["money"] = 1000
    return theme, state


def act(theme, state, action, now=NOW, **args):
    candidate = deepcopy(state)
    result = theme.apply(candidate, "1", action, now, **args)
    state.clear()
    state.update(candidate)
    return result


def test_slots_exact_odds_and_wallet_conservation():
    wins, payouts = 0, 0
    for reels in product(range(4), repeat=3):
        theme, state = game(reels)
        result = act(theme, state, "slots", amount=10)
        assert result["reels"] == list(reels)
        wins += result["payout"] > 0
        payouts += result["payout"]
        assert state["players"]["1"]["money"] == 990 + result["payout"]
        assert state["families"]["mafia"]["money"] == 0
        assert "│" in render(result)["content"]
    assert wins == 13 and payouts == 300  # 300 / 640 = 46.875% RTP.


@pytest.mark.parametrize(
    "action,amount",
    [
        ("slots", -5),
        ("slots", 0),
        ("slots", 4),
        ("slots", 21),
        ("slots", True),
        ("blackjack", -10),
        ("blackjack", 9),
        ("blackjack", 1001),
        ("blackjack", 10.5),
    ],
)
def test_bad_bets_do_not_touch_wallet_quota_or_family(action, amount):
    theme, state = game()
    before = deepcopy(state)
    with pytest.raises(RuleError):
        act(theme, state, action, amount=amount)
    assert state == before


def test_shared_quota_daily_reset_and_role_change():
    theme, state = game([0] * 45)
    for _ in range(4):
        act(theme, state, "slots", amount=5)
    for _ in range(5):
        act(theme, state, "roulette", amount=5, bet="number", number=0)
    act(theme, state, "blackjack", amount=10)  # Four aces: active hand.
    with pytest.raises(RuleError, match="активная"):
        act(theme, state, "blackjack", amount=10)
    act(theme, state, "blackjack_table")
    with pytest.raises(RuleError, match="10 игр"):
        act(theme, state, "slots", amount=5)
    theme.sync_members(state, {"1": "cartel"}, NOW)
    with pytest.raises(RuleError, match="10 игр"):
        act(theme, state, "slots", amount=5)
    act(theme, state, "slots", now=(NOW // 86400 + 1) * 86400, amount=5)
    assert state["players"]["1"]["casino_usage"]["count"] == 1


@pytest.mark.parametrize(
    "bet,number,wins",
    [
        ("red", None, 18),
        ("black", None, 18),
        ("even", None, 18),
        ("odd", None, 18),
        ("number", 0, 1),
    ],
)
def test_roulette_payouts_across_the_wheel(bet, number, wins):
    payouts = []
    for drawn in range(37):
        theme, state = game([drawn])
        result = act(theme, state, "roulette", amount=5, bet=bet, number=number)
        payouts.append(result["payout"])
        if drawn == 0:
            assert result["payout"] == (180 if bet == "number" else 0)
    assert sum(payout > 0 for payout in payouts) == wins
    assert sum(payouts) == 180


def test_blackjack_hidden_card_buttons_and_repeated_clicks():
    theme, state = game([9, 5, 8, 6, 1, 1])  # 16 vs 16; hit ->18, stand ->18.
    first = act(theme, state, "blackjack", amount=10)
    assert first["dealer"] == [8] and "dealer" not in first["hand"]
    assert state["players"]["1"]["money"] == 990
    assert "🂠" in render(first)["content"]
    assert len(render(first)["components"][0]["components"]) == 2
    hand = first["hand"]["id"]
    second = act(theme, state, "blackjack_move", hand=hand, revision=0, decision="hit")
    assert total(second["hand"]["player"]) == 18
    stale = act(theme, state, "blackjack_move", hand=hand, revision=0, decision="hit")
    assert second == stale
    done = act(theme, state, "blackjack_move", hand=hand, revision=1, decision="stand")
    assert done["hand"]["payout"] == 10 and done["money"] == 1000
    assert not render(done)["components"] and "🂠" not in render(done)["content"]
    assert act(theme, state, "blackjack_move", hand=hand, revision=1, decision="stand") == done
    assert state["players"]["1"]["casino_usage"]["count"] == 1


def test_daily_quota_boundary_and_legacy_weekly_state():
    midnight = (NOW // 86400 + 1) * 86400
    theme, state = game([0] * 36)
    player = state["players"]["1"]
    player["casino_usage"] = {"week": "2026-45", "count": 5}
    # Switching to daily quotas starts a fresh daily counter once.
    for _ in range(10):
        act(theme, state, "slots", now=midnight - 1, amount=5)
    with pytest.raises(RuleError, match="10 игр в день"):
        act(theme, state, "slots", now=midnight - 1, amount=5)
    act(theme, state, "slots", now=midnight, amount=5)
    usage = state["players"]["1"]["casino_usage"]
    assert usage["count"] == 1 and "day" in usage and "week" not in usage
    act(theme, state, "slots", now=midnight + 1, amount=5)
    assert state["players"]["1"]["casino_usage"]["count"] == 2


@pytest.mark.parametrize(
    "draws,payout",
    [
        ([0, 9, 8, 7], 27),  # Natural 3:2, odd stake 11 -> profit16.
        ([0, 9, 13, 22], 11),  # Both naturals.
        ([8, 7, 0, 9], 0),  # Dealer natural.
    ],
)
def test_naturals(draws, payout):
    theme, state = game(draws)
    result = act(theme, state, "blackjack", amount=11)
    assert result["hand"]["status"] == "done"
    assert result["hand"]["payout"] == payout
    assert result["money"] == 989 + payout


def test_aces_soft17_bust_and_expiry():
    assert total([0, 13, 9]) == 12
    theme, state = game([9, 7, 0, 5])  # Player18 vs dealer soft17; no draw.
    first = act(theme, state, "blackjack", amount=10)
    done = act(
        theme, state, "blackjack_move", hand=first["hand"]["id"], revision=0, decision="stand"
    )
    assert done["hand"]["payout"] == 20
    theme, state = game([9, 7, 0, 5, 9])
    first = act(theme, state, "blackjack", amount=10)
    done = act(theme, state, "blackjack_move", hand=first["hand"]["id"], revision=0, decision="hit")
    assert done["hand"]["payout"] == 0
    theme, state = game([9, 7, 0, 5])
    act(theme, state, "blackjack", amount=10)
    act(theme, state, "tick", now=NOW + 86400)
    assert state["players"]["1"]["money"] == 1010
    act(theme, state, "tick", now=NOW + 86401)
    assert state["players"]["1"]["money"] == 1010


def test_button_owner_validation_and_deferred_update():
    payload = {
        "type": 3,
        "member": {"user": {"id": "1"}},
        "data": {"custom_id": "blackjack:1:42:3:hit"},
    }
    assert component_action(payload) == {"hand": "42", "revision": 3, "decision": "hit"}
    assert deferred_response(payload) == {"type": 6}
    payload["member"]["user"]["id"] = "2"
    with pytest.raises(RuleError, match="чужая"):
        component_action(payload)
    assert (
        parse_options({"data": {"options": [{"name": "amount", "value": 2**53 - 1}]}}, "blackjack")[
            "amount"
        ]
        == 2**53 - 1
    )


def test_application_channel_guard_and_component_routing():
    async def scenario():
        sql = SimpleNamespace(query=AsyncMock(return_value=[{"casino_channel_id": "99"}]))
        app = Application(Config("test", "00" * 32, "1", "2", "unused"), sql, SimpleNamespace())
        theme, state = game([9, 7, 0, 5])
        result = act(theme, state, "blackjack", amount=10)
        app.act = AsyncMock(return_value=result)
        payload = {
            "type": 2,
            "channel_id": "98",
            "member": {"user": {"id": "1"}},
            "data": {"name": "blackjack", "options": [{"name": "amount", "value": 10}]},
        }
        with pytest.raises(RuleError, match="канале казино"):
            await app.dispatch(payload)
        app.act.assert_not_called()
        payload.update(type=3, channel_id="99", data={"custom_id": "blackjack:1:42:0:hit"})
        response = await app.dispatch(payload)
        assert response["components"] and response["allowed_mentions"] == {"parse": []}
        assert app.act.call_args.args[1] == "blackjack_move"

    asyncio.run(scenario())
