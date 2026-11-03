from copy import deepcopy

import pytest

from nullreference.core.theme import RuleError
from nullreference.themes.mafia.commands import parse_options
from nullreference.themes.mafia.rules import DAY, MafiaSeason
from nullreference.visibility import deferred_response

MONDAY = 1793577600


def game():
    theme = MafiaSeason(roll=lambda n: 0)
    state = theme.initial_state()
    theme.sync_members(state, {"1": "police", "2": "police", "3": "cartel"}, MONDAY)
    return theme, state


def patrol(theme, state, actor="1", now=MONDAY, family="cartel"):
    candidate = deepcopy(state)
    result = theme.apply(candidate, actor, "patrol", now, family=family)
    state.clear()
    state.update(candidate)
    return result


def test_patrol_generates_clue_without_operation_and_does_not_award_money():
    t, s = game()
    s["clues"]["cartel"] = 4
    result = patrol(t, s)
    assert result["values"] == {"family": "Картель", "clues": 5, "remaining": 2}
    assert not s["operations"] and not s["police_actions"]
    assert s["players"]["1"]["money"] == s["families"]["police"]["money"] == 0
    assert "news" not in result
    assert deferred_response({"type": 2, "data": {"name": "patrol"}})["data"]["flags"] == 64


def test_personal_daily_and_weekly_limits_exact_reset_and_role_changes():
    t, s = game()
    patrol(t, s)
    before = deepcopy(s)
    with pytest.raises(RuleError, match="сутки"):
        patrol(t, s, now=MONDAY + DAY - 1, family="mafia")
    assert s == before
    patrol(t, s, actor="2")  # Another officer has an independent allowance.
    patrol(t, s, now=MONDAY + DAY)
    patrol(t, s, now=MONDAY + 2 * DAY)
    with pytest.raises(RuleError, match="три патруля"):
        patrol(t, s, now=MONDAY + 3 * DAY)
    t.sync_members(s, {"1": "mafia"}, MONDAY)
    t.sync_members(s, {"1": "police"}, MONDAY)
    with pytest.raises(RuleError, match="три патруля"):
        patrol(t, s, now=MONDAY + 7 * DAY - 1)
    patrol(t, s, now=MONDAY + 7 * DAY)
    assert s["clues"]["cartel"] == 5


@pytest.mark.parametrize(
    "actor,family,field",
    [
        ("3", "cartel", None),
        ("1", "police", None),
        ("1", "unknown", None),
        ("1", "cartel", "suspended"),
        ("1", "cartel", "injured_until"),
        ("1", "cartel", "jail_until"),
    ],
)
def test_unauthorized_or_unavailable_patrol_does_not_change_state(actor, family, field):
    t, s = game()
    if field:
        s["players"][actor][field] = MONDAY + DAY
    before = deepcopy(s)
    with pytest.raises(RuleError):
        patrol(t, s, actor=actor, family=family)
    assert s == before


def test_patrol_independent_of_work_and_investigations_and_validates_choice():
    t, s = game()
    t.apply(s, "1", "work", MONDAY)
    s["police_actions"]["2026-45"] = 3
    patrol(t, s)
    assert s["players"]["1"]["money"] == 20
    assert s["police_actions"]["2026-45"] == 3
    for family in ("police", "unknown"):
        with pytest.raises(RuleError):
            parse_options({"data": {"options": [{"name": "family", "value": family}]}}, "patrol")


@pytest.mark.parametrize("action", ["patrol", "investigate"])
def test_exact_sixty_percent_odds_and_failed_attempt_consumes_budget(action):
    successes = 0
    for draw in range(100):
        t, s = game()
        s["operations"]["test"] = {"family": "cartel", "status": "open", "raid": None}
        s["clues"]["cartel"] = 5
        t.roll = lambda n, value=draw: value
        result = t.apply(s, "1", action, MONDAY, family="cartel")
        found = s["clues"]["cartel"] == 6
        successes += found
        assert found == (draw < 60)
        assert result["key"] == (
            ("patrolled" if action == "patrol" else "investigated")
            if found
            else ("patrol_empty" if action == "patrol" else "investigation_empty")
        )
        if action == "patrol":
            assert s["players"]["1"]["last_patrol"] == "2026-11-02"
            with pytest.raises(RuleError, match="сутки"):
                patrol(t, s)
        else:
            assert s["police_actions"]["2026-45"] == 1
            t.apply(s, "1", action, MONDAY, family="cartel")
            t.apply(s, "2", action, MONDAY, family="cartel")
            with pytest.raises(RuleError, match="три действия"):
                t.apply(s, "1", action, MONDAY, family="cartel")
    assert successes == 60
