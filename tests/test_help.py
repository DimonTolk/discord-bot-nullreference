import asyncio
import re
from pathlib import Path
from types import SimpleNamespace

from nullreference.application import Application
from nullreference.core.config import Config
from nullreference.themes.mafia.commands import manifest, parse_options
from nullreference.themes.mafia.help import PAGES, TOPICS, render_help


def test_help_fits_discord_and_covers_every_registered_command():
    text = "\n".join(PAGES.values())
    documented = set(re.findall(r"/([a-z_]+)", text))
    registered = {command["name"] for command in manifest()}
    assert registered <= documented
    assert TOPICS.keys() == PAGES.keys()
    for topic in TOPICS:
        page = render_help(topic)
        assert len(page.encode("utf-16-le")) // 2 <= 2000, (topic, len(page))
        assert page.count("```") % 2 == 0
        assert page.startswith("## ")


def test_help_topic_defaults_choices_and_actual_output_are_not_truncated():
    assert parse_options({}, "help") == {"topic": "overview"}
    command = next(c for c in manifest() if c["name"] == "help")
    assert {choice["value"] for choice in command["options"][0]["choices"]} == TOPICS.keys()

    async def scenario():
        app = Application(
            Config("test", "00" * 32, "1", "2", "unused"), SimpleNamespace(), SimpleNamespace()
        )
        for topic in TOPICS:
            payload = {
                "type": 2,
                "member": {"user": {"id": "3"}},
                "data": {"name": "help", "options": [{"name": "topic", "value": topic}]},
            }
            assert (await app.dispatch(payload))["content"] == render_help(topic)

    asyncio.run(scenario())


def test_readme_is_completely_english():
    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text("utf-8")
    assert not re.search(r"[\u0400-\u04ff]", readme)
