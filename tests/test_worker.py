import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from nullreference.application import Application
from nullreference.core.config import Config
from nullreference.core.flavour import FlavourCatalog
from nullreference.core.http import DiscordHTTP, NeonHTTP, ServiceError
from nullreference.core.theme import RuleError
from nullreference.security import modal, signature_parts
from nullreference.themes.mafia.commands import ADMIN_COMMANDS, authorize, manifest, parse_options
from nullreference.themes.mafia.membership import MafiaMembership


def payload(name="work", options=None, permissions="0"):
    return {
        "id": "123",
        "application_id": "111",
        "guild_id": "222",
        "type": 2,
        "token": "test-only",
        "member": {"user": {"id": "1"}, "roles": ["10"], "permissions": permissions},
        "data": {"name": name, "options": options or []},
    }


def test_manifest_and_server_side_admin_checks():
    commands = manifest()
    assert len(commands) == 36
    assert "join" not in {c["name"] for c in commands}
    assert all(not any(k.startswith("_") for k in c) for c in commands)
    for name in ADMIN_COMMANDS:
        with pytest.raises(RuleError):
            authorize(payload(), name)
        authorize(payload(permissions="32"), name)
        authorize(payload(permissions="8"), name)
    assert parse_options(payload(), "operation_start") == {"prepared": False}
    for value in (-1, 0, 10001, "20", True):
        with pytest.raises(RuleError):
            parse_options(payload(options=[{"name": "amount", "value": value}]), "donate")


def test_signature_exact_bytes_and_replay_window():
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    body = '{"message":"Сицилия"}'.encode()
    timestamp = "1000"
    signature = private.sign(timestamp.encode() + body)
    key, sig, signed = signature_parts(public.hex(), timestamp, signature.hex(), body, now=1001)
    private.public_key().verify(sig, signed)
    assert key == public
    with pytest.raises(ValueError):
        signature_parts(public.hex(), timestamp, signature.hex(), body, now=1400)


def test_flavour_modal_is_owner_and_admin_only():
    p = payload(permissions="32")
    p["data"] = {"custom_id": "flavour:open:work:1"}
    p["message"] = {"embeds": [{"title": "work", "description": "$amount $balance"}]}
    assert modal(p, {"work": "value"})["type"] == 9
    p["member"]["user"]["id"] = "2"
    with pytest.raises(RuleError):
        modal(p, {"work": "value"})


def test_flavour_variable_validation_and_live_override():
    async def scenario():
        sql = SimpleNamespace(
            query=AsyncMock(return_value=[{"value": "Доход $amount, остаток $balance"}])
        )
        catalog = FlavourCatalog(sql, "1", "test")
        assert await catalog.render("work", amount=2, balance=3) == "Доход 2, остаток 3"
        for value in ("$amount", "$amount $balance $token", "$amount $balance $"):
            with pytest.raises(ValueError):
                catalog.validate("work", value)

    asyncio.run(scenario())


def test_role_membership_uses_ids_and_rejects_conflicts():
    bindings = {"cartel": 10, "police": 20}
    assert MafiaMembership.resolve(["10"], bindings) == "cartel"
    for roles in ([], ["10", "20"]):
        with pytest.raises(RuleError):
            MafiaMembership.resolve(roles, bindings)


def test_neon_protocol_typed_rows_and_sanitized_errors():
    async def scenario():
        result = {
            "fields": [
                {"name": "version", "dataTypeID": 20},
                {"name": "state", "dataTypeID": 3802},
            ],
            "rows": [["2", '{"money": 50}']],
        }
        fetch = AsyncMock(
            return_value=SimpleNamespace(status=200, json=AsyncMock(return_value=result))
        )
        sql = NeonHTTP("postgresql://test:secret@ep-test.eu-central-1.aws.neon.tech/test", fetch)
        assert await sql.query("SELECT $1", [1]) == [{"version": 2, "state": {"money": 50}}]
        assert fetch.call_args.args[0] == "https://api.eu-central-1.aws.neon.tech/sql"
        fetch.return_value = SimpleNamespace(
            status=500, json=AsyncMock(return_value={"code": "23505", "detail": "secret"})
        )
        with pytest.raises(ServiceError) as exc:
            await sql.query("SELECT $1", [1])
        assert "secret" not in str(exc.value)

    asyncio.run(scenario())


def test_discord_attachment_export_is_private_and_disables_mentions():
    async def scenario():
        fetch = AsyncMock(return_value=SimpleNamespace(status=200))
        client = DiscordHTTP("test", fetch)
        await client.respond("1", "test", {"content": "export", "_file": '{"work":"text"}'})
        body = fetch.call_args.kwargs["body"].decode()
        assert 'filename="flavour.json"' in body
        assert '"allowed_mentions": {"parse": []}' in body
        assert "Authorization" not in fetch.call_args.kwargs["headers"]

    asyncio.run(scenario())


def test_offline_roles_are_checked_before_operation_payout():
    async def scenario():
        config = Config("test", "00" * 32, "111", "222", "unused", "test")
        app = Application(
            config,
            SimpleNamespace(),
            SimpleNamespace(member=AsyncMock(side_effect=[{"roles": ["10"]}, {"roles": ["20"]}])),
        )
        app.membership.bindings = AsyncMock(return_value={"mafia": 10, "cartel": 20})
        app.state = AsyncMock(
            return_value={"operations": {"7": {"members": ["1", "2"], "raid": None}}, "bribes": {}}
        )
        assert await app.identities(payload(), "operation_resolve", {"operation": "7"}) == {
            "1": "mafia",
            "2": "cartel",
        }

    asyncio.run(scenario())


def test_role_switch_preserves_wallet_and_cooldowns():
    from nullreference.themes.mafia.rules import MafiaSeason

    theme = MafiaSeason(roll=lambda n: 0)
    state = theme.initial_state()
    theme.sync_members(state, {"1": "mafia"}, 1000)
    theme.apply(state, "1", "work", 1000)
    theme.sync_members(state, {"1": "cartel"}, 1001)
    assert state["players"]["1"]["money"] == 20
    assert state["families"]["mafia"]["leader"] is None
    with pytest.raises(RuleError):
        theme.apply(state, "1", "work", 1001)


def test_admin_command_cannot_be_dispatched_without_permission():
    async def scenario():
        config = Config("test", "00" * 32, "111", "222", "unused", "test")
        app = Application(config, SimpleNamespace(), SimpleNamespace())
        with pytest.raises(RuleError):
            await app.dispatch(payload("reward"))

    asyncio.run(scenario())
