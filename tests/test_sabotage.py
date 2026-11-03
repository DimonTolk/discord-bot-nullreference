import asyncio
from copy import deepcopy
from string import Template
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from nullreference.application import Application
from nullreference.core.config import Config
from nullreference.core.flavour import FlavourCatalog
from nullreference.core.theme import RuleError
from nullreference.themes.mafia.policing import police_profile
from nullreference.themes.mafia.rules import DAY, FAMILIES, MafiaSeason
from nullreference.themes.mafia.sabotage import success_chance
from nullreference.themes.mafia.texts import DEFAULTS
from nullreference.visibility import deferred_response

NOW = 1793610000


def game():
    t = MafiaSeason(roll=lambda n: 0)
    s = t.initial_state()
    t.sync_members(
        s, {"1": "mafia", "2": "mafia", "3": "police", "4": "cartel", "5": "yakuza"}, NOW
    )
    s["families"]["mafia"]["money"] = 200
    s["families"]["cartel"].update(influence=10, earned=25)
    return t, s


def act(t, s, action, actor="1", now=NOW, **args):
    candidate = deepcopy(s)
    result = t.apply(candidate, actor, action, now, **args)
    s.clear()
    s.update(candidate)
    return result


def start(t, s, **args):
    return act(t, s, "sabotage_start", family="cartel", **args)["values"]["id"]


def test_private_launch_join_and_no_randomness_or_news_before_deadline():
    t, s = game()
    t.roll = lambda n: pytest.fail("Recruitment must not roll or leak")
    oid = start(t, s, beneficiary="yakuza")
    assert s["families"]["mafia"]["money"] == 160
    joined = act(t, s, "sabotage_join", actor="2", operation=oid)
    assert joined == {"key": "sabotage_joined", "values": {}}
    assert act(t, s, "sabotage_status", operation=oid)["values"]["chance"] == 40
    for name in ("sabotage_start", "sabotage_join", "sabotage_status", "sabotage_resolve"):
        assert deferred_response({"type": 2, "data": {"name": name}})["data"]["flags"] == 64
    for action, actor in (
        ("sabotage_status", "2"),
        ("sabotage_join", "4"),
        ("sabotage_resolve", "2"),
    ):
        with pytest.raises(RuleError):
            act(t, s, action, actor=actor, operation=oid)
    before = deepcopy(s)
    with pytest.raises(RuleError, match="засекречена"):
        act(t, s, "sabotage_resolve", now=NOW + DAY - 1, operation=oid)
    assert s == before
    with pytest.raises(RuleError):
        act(t, s, "sabotage_join", actor="2", operation=oid)


@pytest.mark.parametrize(
    "members,influence,expected",
    [
        (1, 1, 0),
        (2, 10, 40),
        (4, 10, 64),
        (12, 1, 90),
        (2, 6, 48),
        (3, 6, 60),
        (4, 6, 72),
        (5, 6, 84),
        (6, 6, 90),
        (2, 100, 10),
    ],
)
def test_documented_probability(members, influence, expected):
    assert (
        success_chance({"members": list(range(members)), "target_influence": influence}) == expected
    )


def test_outside_actions_and_delay_cannot_change_committed_probability():
    t, s = game()
    oid = start(t, s)
    act(t, s, "sabotage_join", actor="2", operation=oid)
    assert success_chance(s["sabotages"][oid]) == 40
    s["families"]["cartel"]["influence"] = 100
    t.underworld.disable(s, "2", NOW + 1, "jail")
    t.sync_members(s, {"2": "police"}, NOW + 2)
    t.underworld.disable(s, "1", NOW + 3, "injured")
    assert s["sabotages"][oid]["members"] == ["1", "2"]
    assert success_chance(s["sabotages"][oid]) == 40
    with pytest.raises(RuleError, match="Восстановление"):
        act(t, s, "sabotage_resolve", now=NOW + DAY, operation=oid)
    assert act(t, s, "sabotage_status", operation=oid)["values"]["chance"] == 40
    result = act(t, s, "sabotage_resolve", now=NOW + 3 * DAY, operation=oid)
    assert result["values"]["outcome"] == "успех"
    assert result["values"]["amount"] == 4


@pytest.mark.parametrize("remaining,expected", [(10, 4), (2, 2), (0, 0), (100, 4)])
def test_transfer_is_bounded_conserves_available_influence_and_can_benefit_ally(
    remaining, expected
):
    t, s = game()
    oid = start(t, s, beneficiary="yakuza")
    act(t, s, "sabotage_join", actor="2", operation=oid)
    s["families"]["cartel"]["influence"] = remaining
    result = act(t, s, "sabotage_resolve", now=NOW + DAY, operation=oid)
    assert s["families"]["cartel"]["influence"] == remaining - expected
    assert s["families"]["yakuza"]["influence"] == expected
    assert s["families"]["yakuza"]["earned"] == expected
    assert s["families"]["cartel"]["earned"] == 25
    assert result["news"]["values"] == {"beneficiary": "Якудза", "amount": expected}
    assert "<@1>" not in str(result["news"])
    before = deepcopy(s)
    with pytest.raises(RuleError):
        act(t, s, "sabotage_resolve", now=NOW + DAY, operation=oid)
    assert s == before


@pytest.mark.parametrize("reveal,exposed", [(20, True), (21, False)])
def test_failed_campaign_only_reveals_family_conditionally_after_deadline(reveal, exposed):
    t, s = game()
    oid = start(t, s)
    act(t, s, "sabotage_join", actor="2", operation=oid)
    draws = iter([40, reveal, 9])  # At 40%, draw40 fails; last draw selects tenth story.
    t.roll = lambda n: next(draws)
    result = act(t, s, "sabotage_resolve", now=NOW + DAY, operation=oid)
    assert result["values"]["outcome"] == "неудача"
    assert s["sabotages"][oid]["exposed"] == exposed
    assert result["news"]["key"] == "news_sabotage_cartel_failure_10"
    assert ("Мафия" in result["news"]["values"]["exposure"]) == exposed
    assert "<@" not in str(result["news"])
    assert s["families"]["cartel"]["influence"] == 10
    assert s["families"]["mafia"]["influence"] == 0
    assert s["clues"] == {}


def test_single_member_fails_and_late_join_denied_and_weekly_start_limit():
    t, s = game()
    oid = start(t, s)
    with pytest.raises(RuleError, match="закрыт"):
        act(t, s, "sabotage_join", actor="2", now=NOW + DAY, operation=oid)
    assert (
        act(t, s, "sabotage_resolve", now=NOW + DAY, operation=oid)["values"]["outcome"]
        == "неудача"
    )
    with pytest.raises(RuleError, match="неделю"):
        act(t, s, "sabotage_start", now=NOW + DAY, family="cartel")
    assert (
        act(t, s, "sabotage_start", now=NOW + 7 * DAY, family="cartel")["key"] == "sabotage_started"
    )


@pytest.mark.parametrize(
    "actor,target,beneficiary",
    [
        ("2", "cartel", None),
        ("3", "cartel", None),
        ("1", "mafia", None),
        ("1", "police", None),
        ("1", "unknown", None),
        ("1", "cartel", "cartel"),
        ("1", "cartel", "police"),
        ("1", "cartel", "unknown"),
        ("1", "triad", None),
    ],
)
def test_invalid_start_does_not_charge_or_create_operation(actor, target, beneficiary):
    t, s = game()
    before = deepcopy(s)
    with pytest.raises(RuleError):
        act(t, s, "sabotage_start", actor=actor, family=target, beneficiary=beneficiary)
    assert s == before


def test_catalog_has_ten_distinct_success_and_failure_stories_per_family():
    news = {key: value for key, value in DEFAULTS.items() if key.startswith("news_sabotage_")}
    assert len(news) == 100 and len(set(news.values())) == 100
    for family in set(FAMILIES) - {"police"}:
        for outcome in ("success", "failure"):
            for index in range(1, 11):
                key = f"news_sabotage_{family}_{outcome}_{index:02d}"
                values = (
                    {"amount": 4, "beneficiary": "Мафия"}
                    if outcome == "success"
                    else {"exposure": "Организаторы остались неизвестны."}
                )
                assert len(Template(news[key]).substitute(**values).encode("utf-16-le")) // 2 < 2000
                FlavourCatalog(None, "guild", "season").validate(key, news[key])


def test_public_status_police_dashboard_and_join_ack_do_not_disclose_campaign():
    async def scenario():
        t, s = game()
        oid = start(t, s)
        joined = act(t, s, "sabotage_join", actor="2", operation=oid)
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
            "data": {"name": "sabotage_join", "options": [{"name": "operation", "value": oid}]},
        }
        response = await app.dispatch(payload)
        assert "Картель" not in str(response) and "<@1>" not in str(response)
        payload["data"] = {"name": "status"}
        assert "sabotage" not in str(await app.dispatch(payload))
        assert "sabotage" not in str(police_profile(s, "3", NOW))
        payload["data"] = {"name": "profile"}
        assert "Ваши незавершённые подрывы влияния: нет" in (await app.dispatch(payload))["content"]
        payload["member"]["user"]["id"] = "1"
        assert (
            f"Ваши незавершённые подрывы влияния: {oid}" in (await app.dispatch(payload))["content"]
        )

    asyncio.run(scenario())
