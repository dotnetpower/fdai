"""DeploymentHistoryMemberSource - antecedent changes for T1 causal-chain RCA.

Verifies the bridge that turns a DeploymentHistoryProvider's change
records into ``is_change=True`` CorrelatedEvents an incident's causal
chain roots on: resource derivation from correlation_keys, dedup, the
best-effort (never-raise) contract, and the abstain-friendly empties.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from fdai.core.rca import DeploymentHistoryMemberSource
from fdai.shared.contracts.models import (
    Incident,
    IncidentSeverity,
    IncidentState,
)
from fdai.shared.providers.observation import DeploymentHistoryError, DeploymentRecord
from fdai.shared.providers.testing.observation import InMemoryDeploymentHistoryProvider

_INCIDENT_ID = "00000000-0000-0000-0000-000000000001"


def _incident(*, correlation_keys: tuple[str, ...]) -> Incident:
    return Incident(
        schema_version="1.0.0",
        incident_id=UUID(_INCIDENT_ID),
        state=IncidentState.OPEN,
        severity=IncidentSeverity.SEV3,
        opened_at=datetime(2026, 7, 7, 12, 0, 0, tzinfo=UTC),
        correlation_keys=correlation_keys,
        member_event_ids=(UUID("00000000-0000-0000-0000-000000000002"),),
    )


def _record(
    *,
    deployment_ref: str = "corr-1",
    timestamp: str = "2026-07-07T11:58:00Z",
    resource_refs: tuple[str, ...] = ("app",),
    status: str = "Update",
) -> DeploymentRecord:
    return DeploymentRecord(
        deployment_ref=deployment_ref,
        timestamp=timestamp,
        author="ci@example.com",
        resource_refs=resource_refs,
        status=status,
    )


def _source(
    incident: Incident | None,
    provider: InMemoryDeploymentHistoryProvider,
    **kw: object,
) -> DeploymentHistoryMemberSource:
    return DeploymentHistoryMemberSource(
        lookup=lambda _iid: incident,
        deployment_history=provider,
        **kw,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_maps_deployments_to_change_events() -> None:
    provider = InMemoryDeploymentHistoryProvider()
    provider.seed(_record(deployment_ref="corr-1"))
    provider.seed(_record(deployment_ref="corr-2", timestamp="2026-07-07T11:59:00Z"))
    source = _source(_incident(correlation_keys=("res:app", "window:5")), provider)

    members = await source.members(incident_id=_INCIDENT_ID)

    assert len(members) == 2
    for m in members:
        assert m.is_change is True
        assert m.change_kind == "deploy"
        assert m.resource_ref == "app"
    assert {m.event_id for m in members} == {"corr-1", "corr-2"}
    # The provider was queried with the configured lookback window.
    assert provider.calls[0] == ("P1D", "app")


@pytest.mark.asyncio
async def test_custom_lookback_is_used() -> None:
    provider = InMemoryDeploymentHistoryProvider()
    provider.seed(_record())
    source = _source(_incident(correlation_keys=("res:app",)), provider, lookback="P7D")
    await source.members(incident_id=_INCIDENT_ID)
    assert provider.calls[0] == ("P7D", "app")


@pytest.mark.asyncio
async def test_multiple_resources_are_all_queried() -> None:
    provider = InMemoryDeploymentHistoryProvider()
    provider.seed(_record(deployment_ref="d-app", resource_refs=("app",)))
    provider.seed(_record(deployment_ref="d-db", resource_refs=("db",)))
    source = _source(_incident(correlation_keys=("res:app", "res:db")), provider)
    members = await source.members(incident_id=_INCIDENT_ID)
    assert {m.event_id for m in members} == {"d-app", "d-db"}


@pytest.mark.asyncio
async def test_deduplicates_by_deployment_ref() -> None:
    # The same deployment touches two correlated resources -> one event.
    provider = InMemoryDeploymentHistoryProvider()
    provider.seed(_record(deployment_ref="shared", resource_refs=("app", "db")))
    source = _source(_incident(correlation_keys=("res:app", "res:db")), provider)
    members = await source.members(incident_id=_INCIDENT_ID)
    assert len(members) == 1
    assert members[0].event_id == "shared"


# ---------------------------------------------------------------------------
# Empty / abstain-friendly paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_incident_returns_empty() -> None:
    provider = InMemoryDeploymentHistoryProvider()
    provider.seed(_record())
    source = _source(None, provider)
    assert await source.members(incident_id=_INCIDENT_ID) == ()


@pytest.mark.asyncio
async def test_incident_without_resource_keys_returns_empty() -> None:
    provider = InMemoryDeploymentHistoryProvider()
    provider.seed(_record())
    source = _source(_incident(correlation_keys=("corr:abc", "window:5")), provider)
    assert await source.members(incident_id=_INCIDENT_ID) == ()


@pytest.mark.asyncio
async def test_empty_res_key_is_ignored() -> None:
    provider = InMemoryDeploymentHistoryProvider()
    provider.seed(_record())
    source = _source(_incident(correlation_keys=("res:",)), provider)
    assert await source.members(incident_id=_INCIDENT_ID) == ()


# ---------------------------------------------------------------------------
# Best-effort (never-raise) contract
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_provider_error_is_swallowed() -> None:
    provider = InMemoryDeploymentHistoryProvider()
    provider.next_error(DeploymentHistoryError("boom"))
    source = _source(_incident(correlation_keys=("res:app",)), provider)
    # A failing deployment query yields no changes but never raises.
    assert await source.members(incident_id=_INCIDENT_ID) == ()


@pytest.mark.asyncio
async def test_partial_error_across_resources_keeps_the_good_leg() -> None:
    # First resource errors (one-shot), second succeeds.
    provider = InMemoryDeploymentHistoryProvider()
    provider.seed(_record(deployment_ref="d-db", resource_refs=("db",)))
    provider.next_error(DeploymentHistoryError("app leg down"))
    source = _source(_incident(correlation_keys=("res:app", "res:db")), provider)
    members = await source.members(incident_id=_INCIDENT_ID)
    assert {m.event_id for m in members} == {"d-db"}


@pytest.mark.asyncio
async def test_unparseable_timestamp_drops_that_record() -> None:
    provider = InMemoryDeploymentHistoryProvider()
    provider.seed(_record(deployment_ref="good", timestamp="2026-07-07T11:58:00Z"))
    provider.seed(_record(deployment_ref="bad", timestamp="not-a-timestamp"))
    provider.seed(_record(deployment_ref="empty", timestamp=""))
    source = _source(_incident(correlation_keys=("res:app",)), provider)
    members = await source.members(incident_id=_INCIDENT_ID)
    assert {m.event_id for m in members} == {"good"}


# ---------------------------------------------------------------------------
# Config validation
# ---------------------------------------------------------------------------


def test_blank_lookback_is_rejected() -> None:
    provider = InMemoryDeploymentHistoryProvider()
    with pytest.raises(ValueError, match="lookback"):
        _source(_incident(correlation_keys=("res:app",)), provider, lookback="   ")


@pytest.mark.asyncio
async def test_naive_timestamp_is_coerced_to_aware_utc() -> None:
    # A tz-less deployment timestamp must not yield a naive datetime, or the
    # causal-chain engine would raise TypeError comparing it to the aware
    # failure time and silently sink the whole chain.
    provider = InMemoryDeploymentHistoryProvider()
    provider.seed(_record(deployment_ref="naive", timestamp="2026-07-07T11:58:00"))
    source = _source(_incident(correlation_keys=("res:app",)), provider)
    members = await source.members(incident_id=_INCIDENT_ID)
    assert len(members) == 1
    assert members[0].at.tzinfo is not None


@pytest.mark.asyncio
async def test_lookup_exception_is_swallowed() -> None:
    # A fork lookup that raises (e.g. UUID(malformed)) must not break the
    # never-raise contract - it degrades to an empty member set.
    provider = InMemoryDeploymentHistoryProvider()
    provider.seed(_record())

    def _raising_lookup(_iid: str) -> Incident | None:
        raise ValueError("badly formed incident id")

    source = DeploymentHistoryMemberSource(lookup=_raising_lookup, deployment_history=provider)
    assert await source.members(incident_id="not-a-uuid") == ()


@pytest.mark.asyncio
async def test_shared_deployment_dedup_is_order_independent() -> None:
    # The same deployment id surfaces as two separate records from two
    # resource queries; dedup must resolve to the same representative
    # record regardless of correlation-key order (deterministic).
    def _provider() -> InMemoryDeploymentHistoryProvider:
        p = InMemoryDeploymentHistoryProvider()
        p.seed(_record(deployment_ref="shared", resource_refs=("app",)))
        p.seed(_record(deployment_ref="shared", resource_refs=("db",)))
        return p

    forward = await _source(_incident(correlation_keys=("res:app", "res:db")), _provider()).members(
        incident_id=_INCIDENT_ID
    )
    backward = await _source(
        _incident(correlation_keys=("res:db", "res:app")), _provider()
    ).members(incident_id=_INCIDENT_ID)
    assert len(forward) == 1
    assert forward[0].event_id == backward[0].event_id == "shared"
    assert forward[0].resource_ref == backward[0].resource_ref
