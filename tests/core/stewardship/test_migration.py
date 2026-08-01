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
