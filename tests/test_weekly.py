import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from nullreference.core.theme import RuleError
from nullreference.themes.mafia.commands import authorize, parse_options
from nullreference.themes.mafia.weekly import MafiaWeeklyTasks


def test_weekly_management_is_admin_only_and_limits_time_values():
    with pytest.raises(RuleError):
        authorize({"member": {"permissions": "0"}}, "weekly_tasks")
    authorize({"member": {"permissions": "32"}}, "weekly_tasks")
    assert parse_options({}, "weekly_tasks") == {
        "action": "status",
        "day": None,
        "hour": None,
        "minute": None,
    }
    for key, value in (("day", 0), ("day", 8), ("hour", 24), ("minute", 60)):
        with pytest.raises(RuleError):
            parse_options({"data": {"options": [{"name": key, "value": value}]}}, "weekly_tasks")


def test_weekly_configuration_requires_news_channel_and_schedule_parameters():
    async def scenario():
        tasks = MafiaWeeklyTasks(SimpleNamespace(query=AsyncMock(return_value=[])), "1", "test")
        with pytest.raises(RuleError, match="news_channel"):
            await tasks.settings()
        tasks.settings = AsyncMock(return_value={})
        with pytest.raises(RuleError, match="day"):
            await tasks.configure("schedule")

    asyncio.run(scenario())
