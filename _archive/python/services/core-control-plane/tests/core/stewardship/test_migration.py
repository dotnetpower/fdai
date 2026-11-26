"""Stewardship v1 to v2 candidate migration tests."""

from __future__ import annotations

import copy

import pytest
from fdai.core.stewardship import (
    Duty,
    StewardshipMigrationError,
    load_stewardship_from_mapping,
    migrate_stewardship_mapping_to_v2,
)


def test_migration_refuses_to_invent_backup(valid_raw: dict) -> None:
    with pytest.raises(StewardshipMigrationError, match="requires a second accountable subject"):
        migrate_stewardship_mapping_to_v2(valid_raw)


def test_migration_is_deterministic_and_round_trips(valid_raw: dict, oid) -> None:
    for index, agent in enumerate(valid_raw["stewardship"]["agents"].values()):
        if not agent.get("stewards"):
            continue
        agent["stewards"].append(
            {
                "kind": "user",
                "id": oid(900 + index),
                "responsibility": "accountable",
            }
        )
    original = copy.deepcopy(valid_raw)

    first = migrate_stewardship_mapping_to_v2(valid_raw)
    second = migrate_stewardship_mapping_to_v2(valid_raw)
    migrated = load_stewardship_from_mapping(first, environ={})

    assert first == second
    assert valid_raw == original
    assert migrated.version == 2
    assert migrated.agent("Thor").primary[0].duty is Duty.PRIMARY
    assert migrated.agent("Thor").backup[0].duty is Duty.BACKUP


def test_migration_is_idempotent_for_valid_v2(valid_raw: dict, oid) -> None:
    for index, agent in enumerate(valid_raw["stewardship"]["agents"].values()):
        if not agent.get("stewards"):
            continue
        agent["stewards"][0]["duty"] = "primary"
        agent["stewards"].append(
            {
                "kind": "user",
                "id": oid(950 + index),
                "responsibility": "accountable",
                "duty": "backup",
            }
        )
    valid_raw["stewardship"]["version"] = 2

    assert migrate_stewardship_mapping_to_v2(valid_raw) == valid_raw


def test_migration_and_directory_edge_branches(
    valid_raw: dict, oid, monkeypatch: pytest.MonkeyPatch
) -> None:
    import fdai.core.stewardship.migration as mig_mod
    from fdai.core.stewardship.directory import (
        StaticGroupMembershipProvider,
        StaticIdentityDirectory,
    )

    with pytest.raises(ValueError, match="assume_active MUST be a boolean"):
        StaticIdentityDirectory(assume_active=1)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="members MUST be a mapping"):
        StaticGroupMembershipProvider(members="invalid")  # type: ignore[arg-type]

    # Autonomous agent and informed steward in v1->v2 migration
    for index, (name, agent) in enumerate(valid_raw["stewardship"]["agents"].items()):
        if name == "Odin":
            agent.pop("stewards", None)
            agent["accept_autonomous"] = {"reason": "  autonomous root agent  "}
            continue
        if not agent.get("stewards"):
            continue
        agent["stewards"].append(
            {
                "kind": "user",
                "id": oid(900 + index),
                "responsibility": "accountable",
            }
        )
        if name == "Thor":
            agent["stewards"].append(
                {
                    "kind": "user",
                    "id": oid(980),
                    "responsibility": "informed",
                }
            )

    migrated_raw = migrate_stewardship_mapping_to_v2(valid_raw)
    assert (
        migrated_raw["stewardship"]["agents"]["Odin"]["accept_autonomous"]["reason"]
        == "autonomous root agent"
    )
    thor_stewards = migrated_raw["stewardship"]["agents"]["Thor"]["stewards"]
    assert thor_stewards[1]["duty"] == "backup"
    assert "duty" not in thor_stewards[2]

    # Defensive shape checks and pre-existing escalation/informed duty cleanup
    v1_map = load_stewardship_from_mapping(valid_raw, environ={})
    orig_load = mig_mod.load_stewardship_from_mapping
    with_esc = copy.deepcopy(valid_raw)
    with_esc["stewardship"]["agents"]["Thor"]["stewards"][1]["duty"] = "escalation"
    with_esc["stewardship"]["agents"]["Thor"]["stewards"][2]["duty"] = "backup"
    calls = 0

    def first_v1(*args, **kwargs):
        nonlocal calls
        calls += 1
        return v1_map if calls == 1 else orig_load(*args, **kwargs)

    monkeypatch.setattr(mig_mod, "load_stewardship_from_mapping", first_v1)
    esc_migrated = migrate_stewardship_mapping_to_v2(with_esc)
    assert esc_migrated["stewardship"]["agents"]["Thor"]["stewards"][1]["duty"] == "escalation"
    assert "duty" not in esc_migrated["stewardship"]["agents"]["Thor"]["stewards"][2]

    monkeypatch.setattr(mig_mod, "load_stewardship_from_mapping", lambda *_a, **_kw: v1_map)
    for bad_input, match in [
        ({"stewardship": "not-dict"}, "mutable root mapping"),
        ({"stewardship": {"agents": "not-dict"}}, "mutable agents mapping"),
        ({"stewardship": {"agents": {"Thor": "not-dict"}}}, "must be a mutable mapping"),
        (
            {"stewardship": {"agents": {"Thor": {"stewards": "not-list"}}}},
            "must be a mutable list",
        ),
    ]:
        with pytest.raises(StewardshipMigrationError, match=match):
            migrate_stewardship_mapping_to_v2(bad_input)
    monkeypatch.setattr(mig_mod, "load_stewardship_from_mapping", orig_load)
