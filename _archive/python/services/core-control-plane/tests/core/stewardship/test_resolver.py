"""Resolver fail-fast + env-override + placeholder-gate tests."""

from __future__ import annotations

import pytest
from fdai.core.stewardship import (
    Duty,
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
    assert mp.agents["Thor"].primary[0].duty is Duty.PRIMARY


def test_zero_maintainers_fails(valid_raw: dict) -> None:
    valid_raw["stewardship"]["maintainers"] = []
    with pytest.raises(StewardshipValidationError, match="at least 1 maintainer"):
        load_stewardship_from_mapping(valid_raw)


def test_unsupported_version_fails(valid_raw: dict) -> None:
    valid_raw["stewardship"]["version"] = 3
    with pytest.raises(StewardshipValidationError, match="'version' MUST be 1 or 2"):
        load_stewardship_from_mapping(valid_raw)


def test_version_two_requires_explicit_duty(valid_raw: dict) -> None:
    valid_raw["stewardship"]["version"] = 2
    with pytest.raises(StewardshipValidationError, match="MUST declare 'duty'"):
        load_stewardship_from_mapping(valid_raw)


def test_version_two_requires_backup_or_escalation(valid_raw: dict) -> None:
    valid_raw["stewardship"]["version"] = 2
    for agent in valid_raw["stewardship"]["agents"].values():
        for steward in agent.get("stewards", []):
            steward["duty"] = "primary"
    with pytest.raises(StewardshipValidationError, match="requires a distinct backup"):
        load_stewardship_from_mapping(valid_raw)


def test_version_two_loads_primary_and_backup(valid_raw: dict, oid) -> None:
    valid_raw["stewardship"]["version"] = 2
    for index, agent in enumerate(valid_raw["stewardship"]["agents"].values()):
        stewards = agent.get("stewards", [])
        if not stewards:
            continue
        stewards[0]["duty"] = "primary"
        stewards.append(
            {
                "kind": "user",
                "id": oid(800 + index),
                "responsibility": "accountable",
                "duty": "backup",
            }
        )

    mp = load_stewardship_from_mapping(valid_raw)

    assert mp.version == 2
    assert mp.agents["Thor"].primary[0].duty is Duty.PRIMARY
    assert mp.agents["Thor"].backup[0].duty is Duty.BACKUP


def test_informed_subject_rejects_duty(valid_raw: dict, oid) -> None:
    valid_raw["stewardship"]["agents"]["Thor"]["stewards"].append(
        {
            "kind": "user",
            "id": oid(999),
            "responsibility": "informed",
            "duty": "backup",
        }
    )
    with pytest.raises(StewardshipValidationError, match="MUST NOT declare 'duty'"):
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


def test_accept_autonomous_with_accountable_steward_fails(valid_raw: dict) -> None:
    valid_raw["stewardship"]["agents"]["Thor"]["accept_autonomous"] = {
        "reason": "Ownership is intentionally absent."
    }
    with pytest.raises(StewardshipValidationError, match="MUST NOT declare 'accept_autonomous'"):
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
            environ={"FDAI_STEWARD_THOR": f"user:{oid(60)}:accountable:primary:extra"},
        )


def test_channels_binding_parsed(valid_raw: dict, oid) -> None:
    valid_raw["stewardship"]["channels"] = {oid(1): "teams-hil-prd"}
    mp = load_stewardship_from_mapping(valid_raw)
    assert mp.channels[oid(1)] == "teams-hil-prd"


def test_channel_binding_requires_uuid_key(valid_raw: dict) -> None:
    valid_raw["stewardship"]["channels"] = {"not-an-oid": "teams-hil-prd"}
    with pytest.raises(StewardshipValidationError, match="valid Entra object id"):
        load_stewardship_from_mapping(valid_raw)


def test_stewardship_hardening_rounds_h001_to_h016(
    valid_raw: dict[str, object], oid: object
) -> None:
    from fdai.core.stewardship.coverage import (
        Finding,
        Severity,
        audit_stale_oids,
        build_coverage_report,
    )
    from fdai.core.stewardship.directory import StaticGroupMembershipProvider
    from fdai.core.stewardship.escalation import (
        affected_agents_from_stewardship_change,
        affected_agents_from_workflow,
        resolve_person_channel,
        stakeholders_for_change,
    )
    from fdai.core.stewardship.governance import StewardshipGovernanceResult
    from fdai.core.stewardship.migration import migrate_stewardship_mapping_to_v2
    from fdai.core.stewardship.model import (
        AgentStewardship,
        Maintainer,
        StewardshipMap,
        StewardSubject,
    )
    from fdai.core.stewardship.notify import StewardshipChangeEvent

    # H001-H003: model validation
    with pytest.raises(StewardshipValidationError, match="Maintainer oid"):
        Maintainer("   ")
    with pytest.raises(StewardshipValidationError, match="informed steward subject"):
        StewardSubject(StewardKind.USER, oid(1), Responsibility.INFORMED, Duty.BACKUP)
    with pytest.raises(StewardshipValidationError, match="agent_name MUST be non-empty"):
        AgentStewardship(agent_name=" ")
    with pytest.raises(StewardshipValidationError, match="accept_autonomous_reason"):
        AgentStewardship(agent_name="Loki", accept_autonomous_reason="   ")

    # H004: bool rejection in hop_timeout_seconds and over_assigned_max
    bad_timeout = dict(valid_raw)
    bad_timeout["stewardship"] = {
        **valid_raw["stewardship"],
        "escalation": {"hop_timeout_seconds": True},
    }
    with pytest.raises(StewardshipValidationError, match="positive integer"):
        load_stewardship_from_mapping(bad_timeout)

    bad_threshold = dict(valid_raw)
    bad_threshold["stewardship"] = {
        **valid_raw["stewardship"],
        "thresholds": {"over_assigned_max": True},
    }
    with pytest.raises(StewardshipValidationError, match="positive integer"):
        load_stewardship_from_mapping(bad_threshold)

    # H005: case-insensitive duplicate real maintainers
    real_a = "10000000" + "-0000-0000-0000-00000000000a"
    dup_maint = dict(valid_raw)
    dup_maint["stewardship"] = {
        **valid_raw["stewardship"],
        "maintainers": [{"oid": real_a}, {"oid": f" {real_a.upper()} "}],
    }
    with pytest.raises(StewardshipValidationError, match="distinct Entra object ids"):
        load_stewardship_from_mapping(dup_maint)

    # H006: duplicate case-folded channel OIDs
    dup_chan = dict(valid_raw)
    chan_oid = "00000000-0000-0000-0000-0000000000aa"
    dup_chan["stewardship"] = {
        **valid_raw["stewardship"],
        "channels": {chan_oid: "ch-1", chan_oid.upper(): "ch-2"},
    }
    with pytest.raises(StewardshipValidationError, match="duplicate Entra object id"):
        load_stewardship_from_mapping(dup_chan)

    # H007: duplicate steward in env tokens
    env_tokens = f"user:{chan_oid}:accountable,user:{chan_oid.upper()}:informed"
    with pytest.raises(StewardshipValidationError, match="duplicate steward"):
        load_stewardship_from_mapping(
            valid_raw,
            environ={"FDAI_STEWARD_THOR": env_tokens},
        )

    # H008: Finding agent validation
    with pytest.raises(ValueError, match="pantheon agent"):
        Finding(code="c", severity=Severity.WARN, message="m", agent="UnknownAgent")

    # H010: StaticGroupMembershipProvider strips whitespace
    provider = StaticGroupMembershipProvider({" grp-1 ": (" u-1 ", "")})
    import asyncio

    assert asyncio.run(provider.members_of("grp-1")) == ("u-1",)

    # H011-H013: resolve_person_channel, workflow set/frozenset, version change
    valid_raw["stewardship"]["channels"] = {chan_oid: "teams-custom"}
    mp = load_stewardship_from_mapping(valid_raw)
    assert resolve_person_channel(mp, f" {chan_oid.upper()} ", "fallback") == "teams-custom"
    assert affected_agents_from_workflow({"owners": frozenset({"Thor", "Odin"})}) == frozenset(
        {"Thor", "Odin"}
    )
    mp_v2 = StewardshipMap(
        version=2,
        maintainers=mp.maintainers,
        agents=mp.agents,
        channels=mp.channels,
        hop_timeout_seconds=mp.hop_timeout_seconds,
        over_assigned_max=mp.over_assigned_max,
    )
    assert len(affected_agents_from_stewardship_change(mp, mp_v2)) == 15
    assert len(stakeholders_for_change(mp, ("Thor",))) >= 2

    # H014: migration preserves explicit escalation duty on secondary steward
    v1_for_mig = load_stewardship_from_mapping(valid_raw)
    assert build_coverage_report(v1_for_mig).total_agents == 15
    calls: list[str] = []

    class _CountingDir:
        async def is_active(self, check_oid: str) -> bool:
            calls.append(check_oid)
            return True

    # H009: deduplicated is_active calls per distinct user OID
    asyncio.run(audit_stale_oids(mp, _CountingDir()))
    assert len(calls) == len({s.casefold() for s in calls})

    for idx, agent in enumerate(valid_raw["stewardship"]["agents"].values()):
        stewards = agent.get("stewards", [])
        if stewards:
            stewards.append(
                {
                    "kind": "user",
                    "id": f" {oid(700 + idx)} ",
                    "responsibility": "accountable",
                }
            )
    migrated = migrate_stewardship_mapping_to_v2(valid_raw)
    assert migrated["stewardship"]["agents"]["Thor"]["stewards"][1]["duty"] == "backup"
    assert migrated["stewardship"]["agents"]["Thor"]["stewards"][1]["id"] == oid(701)

    # H015-H016: StewardshipChangeEvent & StewardshipGovernanceResult invariants
    with pytest.raises(ValueError, match="valid pantheon agents"):
        StewardshipChangeEvent(
            actor_oid=oid(1),
            artifact="config/agent-stewardship.yaml",
            affected_agents=("NotAnAgent",),
            summary="bad",
            correlation_id="corr-1",
        )
    with pytest.raises(ValueError, match="published=True requires a receipt"):
        StewardshipGovernanceResult(published=True, receipt=None, idempotency_key="k1")
