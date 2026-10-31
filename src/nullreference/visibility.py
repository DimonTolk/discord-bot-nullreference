"""Choose visibility before acknowledging an interaction; unknown commands stay private."""

PUBLIC_COMMANDS = frozenset(
    {
        "start",
        "help",
        "leaderboard",
        "status",
        "operation_start",
        "operation_join",
        "operation_resolve",
        "raid",
        "district_bid",
        "district_resolve",
        "district_income",
    }
)


def deferred_response(payload):
    public = payload.get("type") == 2 and payload.get("data", {}).get("name") in PUBLIC_COMMANDS
    return {"type": 5, "data": {"flags": 0 if public else 64}}
