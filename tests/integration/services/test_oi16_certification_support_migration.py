"""OI-16 certification-support migration contract tests."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
MIGRATION = (
    REPO_ROOT
    / "service-migrations/branches/core-control-plane/versions"
    / "20260907_core_oi16_certification_support.py"
)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("oi16_certification_support_migration", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_is_linear_and_core_owned() -> None:
    module = _load()

    assert module.down_revision == "core_t2_cache_lookup_repair_20260906"
    assert module.migration_owner == "core-control-plane"
    assert "operational_retention_policy" in module.owned_tables
    assert "inventory_observation_partition" in module.owned_tables
    assert "operational_archive_manifest" in module.owned_tables
    assert "operational_history_recovery_rehearsal" in module.owned_tables


def test_upgrade_authorizes_only_the_oi16_synthetic_fact_family(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load()
    statements: list[str] = []
    monkeypatch.setattr(module.op, "execute", statements.append)

    module.upgrade()

    sql = "\n".join(statements)
    assert "'oi16_synthetic_full_observation'" in sql
    assert "'oi16-dev-synthetic-certification'" in sql
    assert "'partition_purge'" in sql
    assert "'scope_prefix', 'synthetic/oi16-certification/'" in sql
    assert "'deletion_authority', TRUE" in sql
    assert "manifest.record->'source_partitions'" in sql
    assert "checkpoint.valid" in sql
    assert "'^synthetic/oi16-certification/[0-9a-f]{48}$'" in sql
    assert "CREATE TABLE operational_history_recovery_rehearsal" in sql
    assert "BEFORE UPDATE ON operational_history_recovery_rehearsal" in sql
    assert "BEFORE DELETE ON operational_history_recovery_rehearsal" in sql


def test_downgrade_removes_only_the_exact_synthetic_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load()
    statements: list[str] = []
    monkeypatch.setattr(module.op, "execute", statements.append)

    module.downgrade()

    sql = "\n".join(statements)
    assert "WHERE policy_digest =" in sql
    assert "fact_family = 'oi16_synthetic_full_observation'" in sql
    assert "purpose = 'oi16-dev-synthetic-certification'" in sql
    assert "NOT EXISTS" in sql
    assert "partition.retention_policy_digest = policy.policy_digest" in sql
    assert "set_config('fdai.archive_purge', 'authorized', true)" in sql
    assert "set_config('fdai.archive_purge', '', true)" in sql
    assert sql.index("DROP TABLE operational_history_recovery_rehearsal") < sql.index(
        "DELETE FROM operational_retention_policy"
    )
