from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from fdai.core.incident.intervention import (
    IncidentExceptionDuration,
    IncidentIntakeExceptionRegistry,
    IncidentInterventionService,
    StateStoreIncidentIntakeExceptionRegistry,
)
from fdai.core.incident.lifecycle import IncidentWorkflowForbiddenError
from fdai.core.incident.registry import IncidentRegistry
from fdai.shared.contracts.models import IncidentSeverity, IncidentState
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts.incident_intervention import (
    IncidentInterventionProposalBody,
    IncidentInterventionRequest,
    build_incident_intervention_request,
    incident_target_ref,
)
from fdai_service_contracts.operator import OperatorRole


@dataclass(frozen=True)
class _Principal:
    id: str
    role: str


NOW = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)
EXCEPTION_ID = UUID("00000000-0000-0000-0000-000000000123")


def test_bounded_exception_matches_only_exact_target_until_expiry() -> None:
    registry = IncidentIntakeExceptionRegistry()
    created = registry.create(
        target_ref="service:checkout-api",
        justification="Expected behavior during active development.",
        duration=IncidentExceptionDuration.ONE_WEEK,
        principal=_Principal("approver-1", "Approver"),
        now=NOW,
        exception_id=EXCEPTION_ID,
    )

    assert created.expires_at == NOW + timedelta(days=7)
    assert registry.active_for("service:checkout-api", now=NOW) == created
    assert registry.active_for("service:checkout-worker", now=NOW) is None
    assert registry.active_for("service:checkout-api", now=created.expires_at) is None


def test_until_revoked_requires_owner_and_records_review_boundary() -> None:
    registry = IncidentIntakeExceptionRegistry()
    with pytest.raises(IncidentWorkflowForbiddenError):
        registry.create(
            target_ref="service:checkout-api",
            justification="Development remains active.",
            duration=IncidentExceptionDuration.UNTIL_REVOKED,
            principal=_Principal("approver-1", "Approver"),
            now=NOW,
        )

    created = registry.create(
        target_ref="service:checkout-api",
        justification="Development remains active.",
        duration=IncidentExceptionDuration.UNTIL_REVOKED,
        principal=_Principal("owner-1", "Owner"),
        now=NOW,
        exception_id=EXCEPTION_ID,
    )

    assert created.expires_at is None
    assert created.review_at == NOW + timedelta(days=30)
    assert registry.active_for(created.target_ref, now=NOW + timedelta(days=365)) == created


def test_revoke_is_idempotent_and_restores_intake_without_deleting_history() -> None:
    registry = IncidentIntakeExceptionRegistry()
    created = registry.create(
        target_ref="service:checkout-api",
        justification="Development remains active.",
        duration=IncidentExceptionDuration.ONE_MONTH,
        principal=_Principal("owner-1", "Owner"),
        now=NOW,
        exception_id=EXCEPTION_ID,
    )

    revoked = registry.revoke(
        created.exception_id,
        principal=_Principal("approver-2", "Approver"),
        now=NOW + timedelta(hours=1),
    )

    assert (
        registry.revoke(
            created.exception_id,
            principal=_Principal("owner-1", "Owner"),
            now=NOW + timedelta(hours=2),
        )
        == revoked
    )
    assert registry.active_for(created.target_ref, now=NOW + timedelta(hours=1)) is None
    assert registry.snapshot()[created.exception_id].revoked_by == "approver-2"


def test_exception_rejects_blank_or_oversized_justification() -> None:
    registry = IncidentIntakeExceptionRegistry()
    for justification in ("", "x" * 501):
        with pytest.raises(ValueError):
            registry.create(
                target_ref="service:checkout-api",
                justification=justification,
                duration=IncidentExceptionDuration.ONE_DAY,
                principal=_Principal("owner-1", "Owner"),
                now=NOW,
            )


async def test_state_store_registry_persists_exception_and_audits_suppression_once() -> None:
    state_store = InMemoryStateStore()
    registry = StateStoreIncidentIntakeExceptionRegistry(state_store)
    created = await registry.create(
        target_ref="service:checkout-api",
        justification="Expected during development.",
        duration=IncidentExceptionDuration.ONE_DAY,
        principal=_Principal("owner-1", "Owner"),
        now=NOW,
        exception_id=EXCEPTION_ID,
    )

    reloaded = StateStoreIncidentIntakeExceptionRegistry(state_store)
    assert await reloaded.active_for(created.target_ref, now=NOW) == created
    first = await reloaded.record_suppression(
        exception=created,
        correlation_id="episode-1",
        evidence_keys=("evidence-2", "evidence-1"),
        event_type="availability.probe_failed",
        occurred_at=NOW,
    )
    replay = await reloaded.record_suppression(
        exception=created,
        correlation_id="episode-1",
        evidence_keys=("evidence-1", "evidence-2"),
        event_type="availability.probe_failed",
        occurred_at=NOW,
    )

    assert first is True
    assert replay is False
    assert any(
        row.get("entry", {}).get("kind") == "finding.incident-intake-suppressed"
        for row in state_store.audit_entries
    )


async def test_distinct_suppression_occurrences_remain_auditable() -> None:
    state_store = InMemoryStateStore()
    registry = StateStoreIncidentIntakeExceptionRegistry(state_store)
    principal = _Principal("owner-one", "owner")
    created = await registry.create(
        target_ref="sha256:" + "a" * 64,
        justification="Expected activity during active development.",
        duration=IncidentExceptionDuration.UNTIL_REVOKED,
        principal=principal,
        now=NOW,
        exception_id=UUID("00000000-0000-0000-0000-000000000011"),
    )
    first_at = NOW + timedelta(days=31)
    second_at = first_at + timedelta(hours=1)

    assert await registry.record_suppression(
        exception=created,
        correlation_id="episode-1",
        evidence_keys=("evidence-1",),
        event_type="availability.probe_failed",
        occurred_at=first_at,
    )
    assert not await registry.record_suppression(
        exception=created,
        correlation_id="episode-1",
        evidence_keys=("evidence-1",),
        event_type="availability.probe_failed",
        occurred_at=first_at.astimezone(timezone(timedelta(hours=2))),
    )
    assert await registry.record_suppression(
        exception=created,
        correlation_id="episode-1",
        evidence_keys=("evidence-1",),
        event_type="availability.probe_failed",
        occurred_at=second_at,
    )

    suppressions = [
        row["entry"]
        for row in state_store.audit_entries
        if row["entry"].get("kind") == "finding.incident-intake-suppressed"
    ]
    assert [row["at"] for row in suppressions] == [first_at.isoformat(), second_at.isoformat()]
    assert all(row["exception_review_overdue"] is True for row in suppressions)


async def _service_fixture() -> tuple[
    IncidentInterventionService,
    IncidentRegistry,
    InMemoryStateStore,
    UUID,
]:
    store = InMemoryStateStore()
    registry = IncidentRegistry(state_store=store)
    incident = await registry.open(
        correlation_keys=("resource:service:checkout-api", "signal:availability"),
        severity=IncidentSeverity.SEV2,
        member_event_ids=(uuid4(),),
        actor_oid="Heimdall",
        opened_at=NOW,
    )
    return (
        IncidentInterventionService(
            registry=registry,
            exceptions=StateStoreIncidentIntakeExceptionRegistry(store),
            state_store=store,
        ),
        registry,
        store,
        incident.incident_id,
    )


def _request(
    incident_id: UUID,
    *,
    action: str = "operator_guidance",
    expected_state: str = "open",
    target_ref: str | None = None,
    request_id: str = "request-one",
    role: OperatorRole = OperatorRole.CONTRIBUTOR,
) -> IncidentInterventionRequest:
    body_values: dict[str, object] = {
        "action": action,
        "incident_id": str(incident_id),
        "correlation_id": "correlation-one",
        "expected_state": expected_state,
        "comment": "Expected behavior during active development.",
    }
    if action == "create_development_exception":
        body_values["duration"] = "one_week"
    body = IncidentInterventionProposalBody.model_validate(body_values)
    return build_incident_intervention_request(
        request_id=request_id,
        principal_id="operator-one",
        principal_roles=(role,),
        idempotency_key="idempotency-one",
        target_ref=target_ref or incident_target_ref("service:checkout-api"),
        body=body,
        requested_at=NOW + timedelta(minutes=1),
    )


async def test_guidance_is_exact_target_and_replay_safe() -> None:
    service, _registry, store, incident_id = await _service_fixture()
    request = _request(incident_id)

    await service.apply(request)
    await service.apply(request)

    interventions = [
        row["entry"]
        for row in store.audit_entries
        if row["entry"].get("kind") == "incident.intervention-applied"
    ]
    assert len(interventions) == 1
    assert interventions[0]["comment"] == request.comment
    with pytest.raises(ValueError, match="target"):
        await service.apply(
            _request(
                incident_id,
                target_ref=incident_target_ref("service:checkout-worker"),
                request_id="request-two",
            )
        )


async def test_development_close_uses_only_legal_lifecycle_edges() -> None:
    service, registry, store, incident_id = await _service_fixture()

    await service.apply(_request(incident_id, action="close_as_development"))

    assert registry.get(incident_id).state is IncidentState.CLOSED  # type: ignore[union-attr]
    edges = [
        (row["entry"].get("from_state"), row["entry"].get("to_state"))
        for row in store.audit_entries
        if row["entry"].get("kind") == "incident.transition"
    ]
    assert edges == [("open", "triaging"), ("triaging", "resolved"), ("resolved", "closed")]


async def test_development_close_resumes_only_request_owned_partial_progress() -> None:
    service, registry, _store, incident_id = await _service_fixture()
    request = _request(incident_id, action="close_as_development")
    reason = f"development closure [{request.request_id}]: {request.comment}"
    await registry.transition(
        incident_id=incident_id,
        to_state=IncidentState.TRIAGING,
        actor_oid=request.principal_id,
        reason=reason,
        at=request.requested_at,
    )

    await service.apply(request)

    assert registry.get(incident_id).state is IncidentState.CLOSED  # type: ignore[union-attr]


async def test_development_close_rejects_foreign_partial_progress() -> None:
    service, registry, _store, incident_id = await _service_fixture()
    request = _request(incident_id, action="close_as_development")
    await registry.transition(
        incident_id=incident_id,
        to_state=IncidentState.TRIAGING,
        actor_oid="another-operator",
        reason="another decision",
        at=request.requested_at,
    )

    with pytest.raises(ValueError, match="not request-owned"):
        await service.apply(request)


async def test_exception_create_uses_request_derived_identity_and_role_floor() -> None:
    service, _registry, store, incident_id = await _service_fixture()
    request = _request(
        incident_id,
        action="create_development_exception",
        role=OperatorRole.APPROVER,
    )

    await service.apply(request)
    await service.apply(request)

    created = [
        row["entry"]
        for row in store.audit_entries
        if row["entry"].get("kind") == "incident.intake-exception-created"
    ]
    assert len(created) == 1
