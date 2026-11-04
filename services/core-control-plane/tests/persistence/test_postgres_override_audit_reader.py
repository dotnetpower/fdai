"""PostgreSQL integration tests for StateStoreOverrideAuditReader."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fdai.core.operational_learning import OverrideSignalThresholds
from fdai.delivery.override_discovery import (
    StateStoreOverrideAuditReader,
    bind_override_discovery_source,
)
from fdai.delivery.persistence import PostgresStateStore, PostgresStateStoreConfig


def _config() -> PostgresStateStoreConfig:
    value = os.environ.get("FDAI_DATABASE_URL")
    if not value:
        pytest.skip("FDAI_DATABASE_URL is unset")
    return PostgresStateStoreConfig(dsn=value.replace("postgresql+psycopg://", "postgresql://", 1))


async def test_postgres_override_audit_reader_filters_exact_window_and_admits_mimir_only() -> None:
    store = PostgresStateStore(config=_config())
    suffix = uuid4().hex[:12]
    rule_id = f"rule.override.pg.{suffix}"
    # Use a distinct historical window so concurrent tests do not collide
    base = datetime(2024, 3, 1, 0, 0, tzinfo=UTC)
    window_start = base + timedelta(days=1)
    window_end = base + timedelta(days=16)

    # Pre-window record (must be excluded by SQL timestamptz filter)
    await store.append_audit_entry(
        {
            "action_kind": "governance.override_resolved",
            "actor": "fdai.core.control_loop",
            "producer_principal": "Mimir",
            "event_id": f"evt-pre-{suffix}",
            "idempotency_key": f"idem-pre-{suffix}",
            "rule_id": rule_id,
            "override_id": f"ovr-pre-{suffix}",
            "override_scope": "scope://org/sub/rg-0",
            "override_mode": "disabled",
            "recorded_at": (window_start - timedelta(minutes=5)).isoformat(),
        }
    )
    # 5 in-window records across 3 scopes and 14 days
    for idx, day_offset in enumerate((0, 3, 7, 11, 14)):
        await store.append_audit_entry(
            {
                "action_kind": "governance.override_resolved",
                "actor": "fdai.core.control_loop",
                "producer_principal": "Mimir",
                "event_id": f"evt-{idx}-{suffix}",
                "idempotency_key": f"idem-{idx}-{suffix}",
                "rule_id": rule_id,
                "override_id": f"ovr-{idx % 3}-{suffix}",
                "override_scope": f"scope://org/sub/rg-{idx % 3}-{suffix}",
                "override_mode": "parameter-relaxation" if idx % 2 == 0 else "disabled",
                "recorded_at": (window_start + timedelta(days=day_offset, hours=1)).isoformat(),
            }
        )
    # Post-window record (must be excluded by SQL timestamptz filter)
    await store.append_audit_entry(
        {
            "action_kind": "governance.override_resolved",
            "actor": "fdai.core.control_loop",
            "producer_principal": "Mimir",
            "event_id": f"evt-post-{suffix}",
            "idempotency_key": f"idem-post-{suffix}",
            "rule_id": rule_id,
            "override_id": f"ovr-post-{suffix}",
            "override_scope": "scope://org/sub/rg-0",
            "override_mode": "disabled",
            "recorded_at": (window_end + timedelta(minutes=5)).isoformat(),
        }
    )

    reader = StateStoreOverrideAuditReader(store)
    page = await reader.list_override_resolutions(
        window_start=window_start,
        window_end=window_end,
        limit=20,
    )
    matching = [row for row in page.records if row.get("rule_id") == rule_id]
    assert len(matching) == 5
    assert page.complete is True

    source = bind_override_discovery_source(
        store,
        thresholds=OverrideSignalThresholds(
            min_distinct_scopes=3,
            min_dwell_days=14,
            min_shadow_hits=5,
        ),
    )
    batch = await source.observe(
        window_start=window_start,
        window_end=window_end,
        limit=20,
    )
    rule_signals = [sig for sig in batch.signals if sig.facts.get("rule_id") == rule_id]
    assert len(rule_signals) == 1
    assert rule_signals[0].facts["distinct_scope_count"] == 3
    assert rule_signals[0].facts["dwell_days"] == 14
    assert rule_signals[0].facts["shadow_hit_count"] == 5
