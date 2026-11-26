"""Unit tests for StateStoreOverrideAuditReader and CompositeDiscoverySignalSource."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.operational_learning import (
    DiscoveryObservationBatch,
    DiscoverySignal,
    DiscoverySignalKind,
    OverrideSignalThresholds,
)
from fdai.delivery.override_discovery import (
    CompositeDiscoverySignalSource,
    StateStoreOverrideAuditReader,
    bind_override_discovery_source,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_START = datetime(2026, 10, 1, 0, 0, tzinfo=UTC)


def _override_entry(
    index: int,
    *,
    recorded_at: datetime,
    actor: str = "fdai.core.control_loop",
    producer_principal: str = "Mimir",
    scope: str | None = None,
) -> dict[str, object]:
    return {
        "action_kind": "governance.override_resolved",
        "actor": actor,
        "producer_principal": producer_principal,
        "event_id": f"evt-override-{index}",
        "idempotency_key": f"idem-override-{index}",
        "rule_id": "postgresql-server.point-in-time-restore",
        "resource_id": f"postgresql.server/rg-{index % 3}/db-{index}",
        "override_id": f"override.pitr.rg-{index % 3}",
        "override_scope": scope or f"scope://org/account-000/rg-{index % 3}",
        "override_mode": "parameter-relaxation" if index % 2 == 0 else "disabled",
        "recorded_at": recorded_at.isoformat(),
    }


@dataclass(frozen=True, slots=True)
class _StaticUpstreamSource:
    signal: DiscoverySignal

    async def observe(
        self,
        *,
        window_start: datetime,
        window_end: datetime,
        limit: int,
    ) -> DiscoveryObservationBatch:
        del limit
        return DiscoveryObservationBatch(
            window_start=window_start,
            window_end=window_end,
            signals=(self.signal,),
            complete=True,
        )


async def test_state_store_override_reader_enforces_exact_window_and_source_admission() -> None:
    store = InMemoryStateStore()
    # Before window: excluded
    await store.append_audit_entry(_override_entry(0, recorded_at=_START - timedelta(seconds=1)))
    # Unrelated audit entry in window: ignored
    await store.append_audit_entry(
        {
            "action_kind": "control_loop.abstain",
            "actor": "fdai.core.control_loop",
            "producer_principal": "Forseti",
            "recorded_at": (_START + timedelta(hours=1)).isoformat(),
        }
    )
    # 5 valid records inside [window_start, window_end] across 3 scopes and 14 days
    offsets = (
        timedelta(days=0),
        timedelta(days=3),
        timedelta(days=7),
        timedelta(days=11),
        timedelta(days=14, hours=2),
    )
    for idx, offset in enumerate(offsets, start=1):
        await store.append_audit_entry(_override_entry(idx, recorded_at=_START + offset))
    # After window: excluded
    await store.append_audit_entry(
        _override_entry(99, recorded_at=_START + timedelta(days=15, seconds=1))
    )

    source = bind_override_discovery_source(
        store,
        thresholds=OverrideSignalThresholds(
            min_distinct_scopes=3,
            min_dwell_days=14,
            min_shadow_hits=5,
        ),
    )
    batch = await source.observe(
        window_start=_START,
        window_end=_START + timedelta(days=15),
        limit=10,
    )

    assert batch.complete is True
    assert len(batch.signals) == 1
    signal = batch.signals[0]
    assert signal.kind is DiscoverySignalKind.OVERRIDE
    assert signal.facts["rule_id"] == "postgresql-server.point-in-time-restore"
    assert signal.facts["distinct_scope_count"] == 3
    assert signal.facts["dwell_days"] == 14
    assert signal.facts["shadow_hit_count"] == 5


async def test_state_store_override_reader_rejects_self_produced_or_untrusted_records() -> None:
    with pytest.raises(ValueError, match="Norns MUST NOT be admitted"):
        StateStoreOverrideAuditReader(
            InMemoryStateStore(),
            allowed_producer_principals=("Norns",),
        )

    store = InMemoryStateStore()
    await store.append_audit_entry(
        _override_entry(
            1,
            recorded_at=_START + timedelta(hours=1),
            producer_principal="Norns",
        )
    )
    reader = StateStoreOverrideAuditReader(store)
    with pytest.raises(ValueError, match="independent producer admission"):
        await reader.list_override_resolutions(
            window_start=_START,
            window_end=_START + timedelta(days=1),
            limit=10,
        )

    store_bad_actor = InMemoryStateStore()
    await store_bad_actor.append_audit_entry(
        _override_entry(
            2,
            recorded_at=_START + timedelta(hours=1),
            actor="operator.manual",
        )
    )
    reader_bad_actor = StateStoreOverrideAuditReader(store_bad_actor)
    with pytest.raises(ValueError, match="independent actor admission"):
        await reader_bad_actor.list_override_resolutions(
            window_start=_START,
            window_end=_START + timedelta(days=1),
            limit=10,
        )


async def test_state_store_override_reader_marks_incomplete_when_window_exceeds_limit() -> None:
    store = InMemoryStateStore()
    for idx in range(4):
        await store.append_audit_entry(
            _override_entry(idx, recorded_at=_START + timedelta(hours=idx))
        )
    reader = StateStoreOverrideAuditReader(store)
    page = await reader.list_override_resolutions(
        window_start=_START,
        window_end=_START + timedelta(days=1),
        limit=3,
    )

    assert len(page.records) == 3
    assert page.complete is False


async def test_composite_discovery_signal_source_combines_override_and_upstream_signals() -> None:
    store = InMemoryStateStore()
    for idx in range(5):
        await store.append_audit_entry(
            _override_entry(idx, recorded_at=_START + timedelta(days=idx * 4))
        )
    upstream_signal = DiscoverySignal(
        signal_id="upstream-cis-aks-1",
        kind=DiscoverySignalKind.UPSTREAM,
        observed_at=_START + timedelta(days=2),
        evidence_refs=("https://learn.microsoft.com/azure/aks/security#00000000",),
        facts={"control_id": "AKS-SEC-01"},
    )
    composite = bind_override_discovery_source(
        store,
        thresholds=OverrideSignalThresholds(
            min_distinct_scopes=3,
            min_dwell_days=14,
            min_shadow_hits=5,
        ),
        additional_sources=(_StaticUpstreamSource(upstream_signal),),
    )
    assert isinstance(composite, CompositeDiscoverySignalSource)

    batch = await composite.observe(
        window_start=_START,
        window_end=_START + timedelta(days=20),
        limit=10,
    )

    assert batch.complete is True
    assert {item.kind for item in batch.signals} == {
        DiscoverySignalKind.OVERRIDE,
        DiscoverySignalKind.UPSTREAM,
    }
