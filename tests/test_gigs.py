import pytest

from nullreference.core.theme import RuleError
from nullreference.themes.mafia.rules import DAY, MafiaSeason


NOW = 1793610000


def test_resale_charges_once_and_failed_sale_returns_only_ten():
    theme = MafiaSeason(roll=lambda _: 65)
    state = theme.initial_state()
    theme.sync_members(state, {"1": "mafia"}, NOW)
    player = state["players"]["1"]
    player["money"] = 20
    theme.apply(state, "1", "resell", NOW, market="black")
    assert player["money"] == 0
    with pytest.raises(RuleError):
        theme.apply(state, "1", "resell_collect", NOW + 21599)
    with pytest.raises(RuleError):
        theme.apply(state, "1", "courier", NOW, mode="regular")
    theme.apply(state, "1", "resell_collect", NOW + 21600)
    with pytest.raises(RuleError):
        theme.apply(state, "1", "resell_collect", NOW + DAY)
    assert player["money"] == 10


def test_fixer_requires_invited_partner_and_consumes_both_quotas():
    theme = MafiaSeason()
    state = theme.initial_state()
    theme.sync_members(state, {"1": "mafia", "2": "cartel", "3": "police"}, NOW)
    offer = theme.apply(state, "1", "fixer", NOW, member="2", mode="safe")
    args = {"deal": offer["values"]["deal"], "organizer": "1"}
    with pytest.raises(RuleError):
        theme.apply(state, "3", "fixer_accept", NOW, **args)
    theme.apply(state, "2", "fixer_accept", NOW, **args)
    with pytest.raises(RuleError):
        theme.apply(state, "2", "fixer_accept", NOW, **args)
    for member in ("1", "2"):
        assert state["players"][member]["money"] == 18
        with pytest.raises(RuleError):
            theme.apply(state, member, "courier", NOW, mode="regular")
