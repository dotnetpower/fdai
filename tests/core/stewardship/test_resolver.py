"""Resolver fail-fast + env-override + placeholder-gate tests."""

from __future__ import annotations

import pytest

from fdai.core.stewardship import (
    Responsibility,
    StewardKind,
    StewardshipValidationError,
    load_stewardship_from_mapping,
)


def test_valid_config_loads(valid_raw: dict) -> None:
    mp = load_stewardship_from_mapping(valid_raw)
    assert len(mp.agents) == 15
    assert len(mp.maintainers) == 2
    assert mp.agents["Loki"].is_autonomous
    assert mp.agents["Thor"].accountable[0].responsibility is Responsibility.ACCOUNTABLE


def test_zero_maintainers_fails(valid_raw: dict) -> None:
    valid_raw["stewardship"]["maintainers"] = []
    with pytest.raises(StewardshipValidationError, match="at least 1 maintainer"):
        load_stewardship_from_mapping(valid_raw)


def test_unsupported_version_fails(valid_raw: dict) -> None:
    valid_raw["stewardship"]["version"] = 2
    with pytest.raises(StewardshipValidationError, match="'version' MUST be 1"):
        load_stewardship_from_mapping(valid_raw)


def test_forbidden_role_field_fails(valid_raw: dict) -> None:
    valid_raw["stewardship"]["executor"] = "Thor"
    with pytest.raises(StewardshipValidationError, match="role fields are forbidden"):
        load_stewardship_from_mapping(valid_raw)


def test_missing_agent_fails(valid_raw: dict) -> None:
    del valid_raw["stewardship"]["agents"]["Thor"]
    with pytest.raises(StewardshipValidationError, match="missing pantheon members"):
        load_stewardship_from_mapping(valid_raw)


def test_unknown_agent_fails(valid_raw: dict) -> None:
    valid_raw["stewardship"]["agents"]["Zeus"] = {"stewards": []}
    with pytest.raises(StewardshipValidationError, match="unknown agents"):
        load_stewardship_from_mapping(valid_raw)


def test_agent_without_accountable_or_autonomous_fails(valid_raw: dict, oid) -> None:
    valid_raw["stewardship"]["agents"]["Thor"] = {
        "stewards": [{"kind": "user", "id": oid(200), "responsibility": "informed"}]
    }
    with pytest.raises(StewardshipValidationError, match="no accountable steward"):
        load_stewardship_from_mapping(valid_raw)


def test_accept_autonomous_without_reason_fails(valid_raw: dict) -> None:
    valid_raw["stewardship"]["agents"]["Thor"] = {
        "accept_autonomous": {"reason": ""},
        "stewards": [],
    }
    with pytest.raises(StewardshipValidationError, match="non-empty 'reason'"):
        load_stewardship_from_mapping(valid_raw)


def test_bad_kind_fails(valid_raw: dict, oid) -> None:
    valid_raw["stewardship"]["agents"]["Thor"]["stewards"][0]["kind"] = "robot"
    with pytest.raises(StewardshipValidationError, match="'kind' MUST be"):
        load_stewardship_from_mapping(valid_raw)


def test_bad_responsibility_fails(valid_raw: dict) -> None:
    valid_raw["stewardship"]["agents"]["Thor"]["stewards"][0]["responsibility"] = "boss"
    with pytest.raises(StewardshipValidationError, match="'responsibility' MUST be"):
        load_stewardship_from_mapping(valid_raw)


def test_non_uuid_id_fails(valid_raw: dict) -> None:
    valid_raw["stewardship"]["agents"]["Thor"]["stewards"][0]["id"] = "not-a-uuid"
    with pytest.raises(StewardshipValidationError, match="valid Entra object id"):
        load_stewardship_from_mapping(valid_raw)


def test_deployment_binding_gate_rejects_placeholder(valid_raw: dict) -> None:
    with pytest.raises(StewardshipValidationError, match="all-zero placeholder"):
        load_stewardship_from_mapping(
            valid_raw,
            environ={"FDAI_STEWARDSHIP_REQUIRE_BINDINGS": "1"},
        )


def test_reference_profile_allows_placeholder(valid_raw: dict) -> None:
    mp = load_stewardship_from_mapping(valid_raw, environ={})
    assert len(mp.agents) == 15


def test_env_override_maintainers(valid_raw: dict, oid) -> None:
    mp = load_stewardship_from_mapping(
        valid_raw, environ={"FDAI_MAINTAINERS": f"{oid(9)},{oid(10)},{oid(11)}"}
    )
    assert mp.maintainer_oids == (oid(9), oid(10), oid(11))


def test_duplicate_real_maintainers_fail(valid_raw: dict) -> None:
    real_oid = "10000000" + "-0000-0000-0000-000000000009"
    valid_raw["stewardship"]["maintainers"] = [{"oid": real_oid}, {"oid": real_oid}]
    with pytest.raises(StewardshipValidationError, match="distinct Entra object ids"):
        load_stewardship_from_mapping(valid_raw)


def test_env_override_steward(valid_raw: dict, oid) -> None:
    mp = load_stewardship_from_mapping(
        valid_raw,
        environ={"FDAI_STEWARD_THOR": f"user:{oid(50)}:accountable,group:{oid(51)}:informed"},
    )
    thor = mp.agents["Thor"]
    assert thor.accountable[0].id == oid(50)
    assert thor.informed[0].kind is StewardKind.GROUP


def test_env_steward_defaults_to_accountable(valid_raw: dict, oid) -> None:
    mp = load_stewardship_from_mapping(valid_raw, environ={"FDAI_STEWARD_THOR": f"user:{oid(60)}"})
    assert mp.agents["Thor"].accountable[0].id == oid(60)


def test_duplicate_steward_fails(valid_raw: dict, oid) -> None:
    entry = {"kind": "user", "id": oid(60), "responsibility": "accountable"}
    valid_raw["stewardship"]["agents"]["Thor"]["stewards"] = [entry, dict(entry)]
    with pytest.raises(StewardshipValidationError, match="duplicate steward"):
        load_stewardship_from_mapping(valid_raw)


def test_env_steward_rejects_extra_token_parts(valid_raw: dict, oid) -> None:
    with pytest.raises(StewardshipValidationError, match="MUST be 'user:<oid>'"):
        load_stewardship_from_mapping(
            valid_raw,
            environ={"FDAI_STEWARD_THOR": f"user:{oid(60)}:accountable:extra"},
        )


def test_channels_binding_parsed(valid_raw: dict, oid) -> None:
    valid_raw["stewardship"]["channels"] = {oid(1): "teams-hil-prd"}
    mp = load_stewardship_from_mapping(valid_raw)
    assert mp.channels[oid(1)] == "teams-hil-prd"


def test_channel_binding_requires_uuid_key(valid_raw: dict) -> None:
    valid_raw["stewardship"]["channels"] = {"not-an-oid": "teams-hil-prd"}
    with pytest.raises(StewardshipValidationError, match="valid Entra object id"):
        load_stewardship_from_mapping(valid_raw)
