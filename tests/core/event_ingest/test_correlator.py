"""EventCorrelator - deterministic key + window incident grouping.

Asserts the observability-and-detection.md section 1 contract: a burst
sharing a key in one window collapses to one incident, a new window
opens a fresh incident, an uncorrelatable event passes through, and the
correlation keys feed IncidentRegistry.open to accumulate membership.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from fdai.core.event_ingest import EventCorrelator
from fdai.shared.contracts.models import Event, IncidentCorrelation, Mode

_T0 = datetime(2026, 7, 8, 9, 0, 0, tzinfo=UTC)


def _event(
    *,
    event_id: str = "00000000-0000-0000-0000-000000000001",
    correlation_id: str | None = None,
    resource_ref: str | None = None,
    resource_id: str | None = None,
    detected_at: datetime = _T0,
    idem: str = "k",
    incident_correlation: IncidentCorrelation = IncidentCorrelation.CORRELATE,
) -> Event:
    payload: dict[str, object] = {}
    if resource_id is not None:
        payload["resource"] = {"resource_id": resource_id}
    return Event(
        schema_version="1.0.0",
        event_id=UUID(event_id),
        idempotency_key=idem,
        source="src",
        event_type="config_changed",
        detected_at=detected_at,
        ingested_at=detected_at,
        mode=Mode.SHADOW,
        correlation_id=correlation_id,
        resource_ref=resource_ref,
        payload=payload,
        incident_correlation=incident_correlation,
    )


def test_same_resource_same_window_group_to_one_incident() -> None:
    correlator = EventCorrelator(window_seconds=60)
    r1 = correlator.correlate(
        _event(
            event_id="00000000-0000-0000-0000-000000000001", resource_ref="rg/a", detected_at=_T0
        )
    )
    r2 = correlator.correlate(
        _event(
            event_id="00000000-0000-0000-0000-000000000002",
            resource_ref="rg/a",
            detected_at=_T0 + timedelta(seconds=30),
        )
    )
    assert r1.correlated and r2.correlated
    assert r1.incident_id == r2.incident_id


def test_new_window_opens_new_incident() -> None:
    correlator = EventCorrelator(window_seconds=60)
    r1 = correlator.correlate(_event(resource_ref="rg/a", detected_at=_T0))
    r2 = correlator.correlate(_event(resource_ref="rg/a", detected_at=_T0 + timedelta(seconds=90)))
    assert r1.incident_id != r2.incident_id


def test_correlation_id_is_the_anchor() -> None:
    r = EventCorrelator().correlate(_event(correlation_id="corr-1", detected_at=_T0))
    assert r.correlated
    assert any(k == "corr:corr-1" for k in r.correlation_keys)


def test_resource_ref_from_payload() -> None:
    r = EventCorrelator().correlate(_event(resource_id="vm-a", detected_at=_T0))
    assert r.correlated
    assert any(k == "res:vm-a" for k in r.correlation_keys)


def test_uncorrelatable_event_passes_through() -> None:
    r = EventCorrelator().correlate(_event(detected_at=_T0))
    assert r.correlated is False
    assert r.incident_id is None
    assert r.reason == "no_correlation_anchor"


def test_operational_event_keeps_trace_without_incident() -> None:
    r = EventCorrelator().correlate(
        _event(
            correlation_id="inventory:resource-1",
            resource_ref="resource-1",
            incident_correlation=IncidentCorrelation.NONE,
        )
    )
    assert r.correlated is False
    assert r.incident_id is None
    assert r.correlation_keys == ()
    assert r.reason == "incident_correlation_disabled"


def test_burst_collapses_to_one_incident() -> None:
    correlator = EventCorrelator(window_seconds=60)
    ids = {
        correlator.correlate(
            _event(
                event_id=f"00000000-0000-0000-0000-0000000000{i:02d}",
                resource_ref="rg/a",
                detected_at=_T0 + timedelta(seconds=i),
            )
        ).incident_id
        for i in range(1, 11)
    }
    assert len(ids) == 1  # a 10-event burst in one 60s window -> one incident


def test_deterministic_across_correlators() -> None:
    event = _event(resource_ref="rg/a", detected_at=_T0)
    a = EventCorrelator().correlate(event)
    b = EventCorrelator().correlate(event)
    assert a.incident_id == b.incident_id


def test_window_seconds_validation() -> None:
    with pytest.raises(ValueError, match="window_seconds"):
        EventCorrelator(window_seconds=0)


def test_result_is_immutable() -> None:
    r = EventCorrelator().correlate(_event(resource_ref="rg/a"))
    with pytest.raises((AttributeError, TypeError)):
        r.incident_id = "x"  # type: ignore[misc]


@pytest.mark.asyncio
async def test_correlation_keys_feed_registry_membership() -> None:
    from fdai.core.incident.registry import IncidentRegistry
    from fdai.shared.contracts.models import IncidentSeverity
    from fdai.shared.providers.testing import InMemoryStateStore

    correlator = EventCorrelator(window_seconds=60)
    registry = IncidentRegistry(state_store=InMemoryStateStore())
    e1 = _event(
        event_id="00000000-0000-0000-0000-000000000001", resource_ref="rg/a", detected_at=_T0
    )
    e2 = _event(
        event_id="00000000-0000-0000-0000-000000000002",
        resource_ref="rg/a",
        detected_at=_T0 + timedelta(seconds=10),
    )
    r1 = correlator.correlate(e1)
    r2 = correlator.correlate(e2)

    inc1 = await registry.open(
        correlation_keys=r1.correlation_keys,
        severity=IncidentSeverity.SEV3,
        member_event_ids=[e1.event_id],
        actor_oid="system",
    )
    inc2 = await registry.open(
        correlation_keys=r2.correlation_keys,
        severity=IncidentSeverity.SEV3,
        member_event_ids=[e2.event_id],
        actor_oid="system",
    )
    # Same window -> same incident, both events accumulated as members.
    assert str(inc1.incident_id) == r1.incident_id
    assert inc1.incident_id == inc2.incident_id
    assert e1.event_id in inc2.member_event_ids
    assert e2.event_id in inc2.member_event_ids
