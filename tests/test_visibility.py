from nullreference.visibility import PUBLIC_COMMANDS, deferred_response


def test_shared_game_results_are_public_at_the_initial_acknowledgement():
    for name in PUBLIC_COMMANDS:
        assert deferred_response({"type": 2, "data": {"name": name}})["data"]["flags"] == 0


def test_private_information_and_modal_submissions_never_become_public():
    for name in (
        "profile",
        "inbox",
        "work",
        "donate",
        "bribe_offer",
        "bribe_decide",
        "investigate",
        "raid_response",
        "family_role",
        "reward",
        "flavour_export",
        "unknown",
    ):
        assert deferred_response({"type": 2, "data": {"name": name}})["data"]["flags"] == 64
    assert deferred_response({"type": 5, "data": {"name": "start"}})["data"]["flags"] == 64
