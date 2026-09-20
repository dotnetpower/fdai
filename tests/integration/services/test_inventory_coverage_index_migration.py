"""Retry-safety contract for non-transactional inventory coverage indexes."""

from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_MIGRATION = (
    _ROOT / "service-migrations/branches/core-control-plane/versions/"
    "20260919_core_inventory_coverage_indexes.py"
)


def test_inventory_coverage_indexes_are_safe_after_partial_migration_failure() -> None:
    source = _MIGRATION.read_text(encoding="utf-8")

    assert source.count("CREATE INDEX CONCURRENTLY IF NOT EXISTS") == 2
    assert source.count("DROP INDEX CONCURRENTLY IF EXISTS") == 2
