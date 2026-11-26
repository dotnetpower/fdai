from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.tiers.t1_lightweight import (
    CurrentReuseVerification,
    LearnedAction,
    OperationalCaseContext,
    T1Outcome,
    T1Tier,
)
from fdai.core.tiers.t1_lightweight.contextual_reuse import (
    CURRENT_REUSE_EVIDENCE_PURPOSE,
    contextual_reuse_reasons,
    current_reuse_evidence_digest,
    current_reuse_scope_digest,
)
from fdai.core.tiers.t1_lightweight.testing import (
    DeterministicEmbeddingModel,
    InMemoryPatternLibrary,
)
from fdai.shared.contracts.models import Event
from fdai.shared.providers.decision_evidence_verifier import DecisionEvidenceAdmission


def _event() -> Event:
    return Event.model_validate(
        {
            "schema_version": "1.0.0",
            "event_id": "00000000-0000-0000-0000-000000000001",
            "idempotency_key": "event-1",
            "source": "example",
            "event_type": "change_detected",
            "detected_at": "2026-08-01T00:00:00Z",
            "ingested_at": "2026-08-01T00:00:01Z",
            "mode": "shadow",
            "payload": {"resource": {"type": "kubernetes.service", "props": {}}},
        }
    )


def _context() -> OperationalCaseContext:
    return OperationalCaseContext(
        case_ref=f"case-history:case-success:1:{'a' * 64}",
        failure_fingerprint="f" * 64,
        resource_type="kubernetes.service",
        action_type="ops.scale-out",
        required_topology_role="serves",
        graph_digest="b" * 64,
        owner_digest="c" * 64,
        evidence_cutoff=datetime(2026, 8, 1, tzinfo=UTC),
        access_scope_digest="a" * 64,
        purpose="operational-learning",
    )


def _action() -> LearnedAction:
    return LearnedAction(
        signature="sig-operational",
        rule_id="learned.operational.example",
        action_type="ops.scale-out",
        params={},
        incident_id="case-success",
        success_rate=0.99,
        operational_case=_context(),
    )


class _Verifier:
    def __init__(self, **changes: object) -> None:
        self._changes = changes

    async def verify(self, *, event, action, context):  # type: ignore[no-untyped-def]
        values = {
            "case_ref": context.case_ref,
            "observed_at": datetime(2026, 8, 1, 0, 0, 2, tzinfo=UTC),
            "evidence_refs": ("d" * 64,),
            "failure_fingerprint": context.failure_fingerprint,
            "resource_type": context.resource_type,
            "topology_role": context.required_topology_role,
            "graph_digest": context.graph_digest,
            "owner_digest": context.owner_digest,
            "preconditions_passed": True,
            "target_identity_verified": True,
            "blast_radius_within_limit": True,
            "policy_allowed": True,
            "dry_run_passed": True,
            "idempotency_available": True,
            "rollback_resolved": True,
        }
        values.update(self._changes)
        verification = CurrentReuseVerification(**values)  # type: ignore[arg-type]
        if "decision_evidence" in self._changes:
            return verification
        return replace(
            verification,
            decision_evidence=DecisionEvidenceAdmission(
                receipt_digest="sha256:" + "e" * 64,
                verification_bundle_digest="sha256:" + "9" * 64,
                evidence_digest=current_reuse_evidence_digest(verification),
                scope_digest=current_reuse_scope_digest(
                    event=event,
                    action=action,
                    context=context,
                ),
                purpose_id=CURRENT_REUSE_EVIDENCE_PURPOSE,
                source_revision=context.graph_digest,
                verified_at=verification.observed_at,
                valid_until=verification.observed_at + timedelta(days=1),
            ),
        )


async def _tier(verifier: object | None) -> tuple[T1Tier, Event]:
    class _CurrentCases:
        async def current_revision_available(self, **_values):
            return True

    event = _event()
    embed = DeterministicEmbeddingModel()
    library = InMemoryPatternLibrary()
    from fdai.core.tiers.t1_lightweight.tier import _event_text  # type: ignore

    library.add(vector=await embed.embed(_event_text(event)), action=_action())
    return (
        T1Tier(
            embedding_model=embed,
            pattern_library=library,
            current_reuse_verifier=verifier,  # type: ignore[arg-type]
            clock=lambda: datetime(2026, 8, 1, 0, 0, 3, tzinfo=UTC),
            case_history=_CurrentCases(),
        ),
        event,
    )


async def test_operational_case_reuse_abstains_without_current_verifier() -> None:
    tier, event = await _tier(None)
    decision = await tier.evaluate(event=event)

    assert decision.outcome is T1Outcome.ABSTAIN
    assert decision.reason == "current_reuse_verifier_unavailable"


@pytest.mark.parametrize("missing", [True, False])
async def test_corrected_or_missing_current_case_cannot_enter_t1_reuse(missing: bool) -> None:
    class _Corrected:
        async def current_revision_available(self, **_values):
            return False

    tier, event = await _tier(_Verifier())
    tier._case_history = None if missing else _Corrected()
    result = await tier.evaluate(event=event)
    assert result.outcome is T1Outcome.ABSTAIN
    assert result.reason == "current_case_revision_unavailable"


async def test_case_revision_changed_during_verification_is_held() -> None:
    class _ChangingCases:
        calls = 0

        async def current_revision_available(self, **_values):
            self.calls += 1
            return self.calls == 1

    tier, event = await _tier(_Verifier())
    tier._case_history = _ChangingCases()
    result = await tier.evaluate(event=event)
    assert result.outcome is T1Outcome.ABSTAIN
    assert result.reason == "current_case_revision_changed"


@pytest.mark.parametrize("failure_call", [1, 2])
@pytest.mark.parametrize("failure", [PermissionError, LookupError, OSError])
async def test_current_case_provider_failure_is_auditable_abstention(failure_call, failure):
    class _FailingCases:
        calls = 0

        async def current_revision_available(self, **_values):
            self.calls += 1
            if self.calls == failure_call:
                raise failure("source unavailable")
            return True

    tier, event = await _tier(_Verifier())
    tier._case_history = _FailingCases()
    result = await tier.evaluate(event=event)
    assert result.outcome is T1Outcome.ABSTAIN
    assert result.reason == (
        "current_case_revision_unavailable"
        if failure_call == 1
        else "current_case_revision_changed"
    )


async def test_verification_expiry_during_final_source_read_is_held() -> None:
    instant = datetime(2026, 8, 1, 0, 0, 3, tzinfo=UTC)

    class _SlowCases:
        calls = 0

        async def current_revision_available(self, **_values):
            nonlocal instant
            self.calls += 1
            if self.calls == 2:
                instant += timedelta(days=1)
            return True

    tier, event = await _tier(_Verifier())
    tier._case_history = _SlowCases()
    tier._clock = lambda: instant
    result = await tier.evaluate(event=event)
    assert result.outcome is T1Outcome.ABSTAIN
    assert any("expired" in reason or "stale" in reason for reason in result.reasons)


async def test_operational_case_reuse_requires_all_current_checks() -> None:
    tier, event = await _tier(_Verifier())

    decision = await tier.evaluate(event=event)

    assert decision.outcome is T1Outcome.REUSED
    assert decision.requires_reverification is True
    assert decision.current_reuse_verification is not None
    assert decision.current_reuse_verification.case_ref == _context().case_ref
    assert decision.current_reuse_verification.evidence_refs == ("d" * 64,)


async def test_operational_case_reuse_rejects_missing_decision_evidence() -> None:
    tier, event = await _tier(_Verifier(decision_evidence=None))

    decision = await tier.evaluate(event=event)

    assert decision.outcome is T1Outcome.ABSTAIN
    assert "decision_evidence_admission_missing" in decision.reasons


async def test_recent_cached_evidence_may_precede_event_ingestion() -> None:
    tier, event = await _tier(
        _Verifier(observed_at=datetime(2026, 8, 1, 0, 0, 0, 500_000, tzinfo=UTC))
    )

    decision = await tier.evaluate(event=event)

    assert decision.outcome is T1Outcome.REUSED


@pytest.mark.parametrize(
    "instant",
    [datetime(2026, 8, 2, tzinfo=UTC), datetime(2026, 8, 1, 0, 0, 4, tzinfo=UTC)],
)
async def test_reuse_rejects_future_or_expired_evidence_at_actual_decision(
    instant: datetime,
) -> None:
    event, action, context = _event(), _action(), _context()
    verification = await _Verifier().verify(event=event, action=action, context=context)
    verification = replace(
        verification,
        decision_evidence=replace(verification.decision_evidence, valid_until=instant),
    )
    tier, event = await _tier(_Verifier(decision_evidence=verification.decision_evidence))
    tier._clock = lambda: instant
    decision = await tier.evaluate(event=event)
    assert decision.outcome is T1Outcome.ABSTAIN
    assert any("expired" in reason for reason in decision.reasons)


async def test_future_current_observation_cannot_authorize_reuse() -> None:
    tier, event = await _tier(_Verifier(observed_at=datetime(2026, 8, 2, tzinfo=UTC)))
    assert "current_evidence_future" in (await tier.evaluate(event=event)).reasons


@pytest.mark.parametrize("mutation", ["target", "scope", "params", "rule", "signature"])
async def test_reuse_admission_binds_exact_event_and_action(mutation: str) -> None:
    event, action, context = _event(), _action(), _context()
    verification = await _Verifier().verify(event=event, action=action, context=context)
    if mutation == "target":
        event = event.model_copy(
            update={
                "payload": {"resource": {"type": context.resource_type, "id": "other-resource"}}
            }
        )
    elif mutation == "scope":
        event = event.model_copy(
            update={"payload": {**event.payload, "access_scope_digest": "9" * 64}}
        )
    elif mutation == "params":
        action = replace(action, params={"replicas": 20})
    elif mutation == "rule":
        action = replace(action, rule_id="learned.other-rule")
    else:
        action = replace(action, signature="other-signature")
    reasons = contextual_reuse_reasons(
        event=event,
        action=action,
        context=context,
        verification=verification,
        evaluated_at=datetime(2026, 8, 1, 0, 0, 3, tzinfo=UTC),
    )
    assert any("scope" in reason for reason in reasons)


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"observed_at": datetime(2026, 7, 31, tzinfo=UTC)}, "current_evidence_stale"),
        ({"resource_type": "kubernetes.deployment"}, "current_resource_type_changed"),
        ({"failure_fingerprint": "7" * 64}, "current_failure_fingerprint_changed"),
        ({"topology_role": "depends-on"}, "current_topology_role_changed"),
        ({"graph_digest": "9" * 64}, "current_graph_changed"),
        ({"owner_digest": "8" * 64}, "current_owner_changed"),
        ({"preconditions_passed": False}, "current_precondition_failed"),
        ({"target_identity_verified": False}, "current_target_identity_unverified"),
        ({"blast_radius_within_limit": False}, "current_blast_radius_exceeded"),
        ({"policy_allowed": False}, "current_policy_denied"),
        ({"dry_run_passed": False}, "current_dry_run_failed"),
        ({"idempotency_available": False}, "current_idempotency_conflict"),
        ({"rollback_resolved": False}, "historical_rollback_unresolved"),
    ],
)
async def test_current_context_or_safety_change_abstains(
    changes: dict[str, object],
    reason: str,
) -> None:
    tier, event = await _tier(_Verifier(**changes))

    decision = await tier.evaluate(event=event)

    assert decision.outcome is T1Outcome.ABSTAIN
    assert reason in decision.reasons


async def test_current_verifier_error_abstains() -> None:
    class _RaisingVerifier:
        async def verify(self, *, event, action, context):  # type: ignore[no-untyped-def]
            raise RuntimeError("current evidence unavailable")

    tier, event = await _tier(_RaisingVerifier())

    decision = await tier.evaluate(event=event)

    assert decision.outcome is T1Outcome.ABSTAIN
    assert decision.reason == "current_reuse_verification_error:RuntimeError"


async def test_stalled_current_verifier_has_a_total_deadline() -> None:
    closed = asyncio.Event()

    class _BlockedVerifier:
        async def verify(self, **_values):
            try:
                await asyncio.Event().wait()
            finally:
                closed.set()

    tier, event = await _tier(_BlockedVerifier())
    tier._config = replace(tier._config, timeout_seconds=0.01)
    decision = await tier.evaluate(event=event)
    assert closed.is_set()
    assert decision.outcome is T1Outcome.ABSTAIN
    assert decision.reason == "t1_deadline_exceeded"


async def test_external_reuse_cancellation_is_not_a_completed_decision() -> None:
    entered = asyncio.Event()

    class _BlockedVerifier:
        async def verify(self, **_values):
            entered.set()
            await asyncio.Event().wait()

    tier, event = await _tier(_BlockedVerifier())
    task = asyncio.create_task(tier.evaluate(event=event))
    await asyncio.wait_for(entered.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.parametrize(
    "payload",
    [
        {"resource": {"resource_type": "kubernetes.service", "props": {}}},
        {"resource_type": "kubernetes.service", "resource": {"props": {}}},
    ],
)
async def test_reuse_accepts_every_canonical_resource_type_shape(
    payload: dict[str, object],
) -> None:
    event = Event.model_validate(
        {
            "schema_version": "1.0.0",
            "event_id": "00000000-0000-0000-0000-000000000001",
            "idempotency_key": "event-1",
            "source": "example",
            "event_type": "change_detected",
            "detected_at": "2026-08-01T00:00:00Z",
            "ingested_at": "2026-08-01T00:00:01Z",
            "mode": "shadow",
            "payload": payload,
        }
    )

    reasons = contextual_reuse_reasons(
        event=event,
        action=_action(),
        context=_context(),
        verification=await _Verifier().verify(
            event=event,
            action=_action(),
            context=_context(),
        ),
        evaluated_at=datetime(2026, 8, 1, 0, 0, 3, tzinfo=UTC),
    )

    assert "current_resource_type_changed" not in reasons


def test_operational_context_round_trip_preserves_exact_fields() -> None:
    context = _context()
    assert OperationalCaseContext.from_mapping(context.to_mapping()) == context


@pytest.mark.parametrize(
    "changes",
    [
        {"case_ref": "current"},
        {"graph_digest": "bad"},
        {"action_type": "Bad Action"},
        {"evidence_cutoff": datetime(2026, 8, 1)},
    ],
)
def test_invalid_operational_case_contract_is_rejected(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        replace(_context(), **changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"authority": True},
        {"evidence_cutoff": 1},
        {"case_ref": ""},
        {"evidence_cutoff": "not-a-timestamp"},
    ],
)
def test_invalid_context_wire_record_is_rejected(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        OperationalCaseContext.from_mapping({**_context().to_mapping(), **changes})


@pytest.mark.parametrize(
    "changes",
    [
        {"observed_at": datetime(2026, 8, 1)},
        {"evidence_refs": ()},
        {"evidence_refs": ("d" * 64, "d" * 64)},
        {"resource_type": "Bad Type"},
        {"owner_digest": "bad"},
        {"policy_allowed": "true"},
    ],
)
async def test_invalid_current_verification_contract_is_rejected(
    changes: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        await _Verifier(**changes).verify(event=_event(), action=_action(), context=_context())


@pytest.mark.parametrize("mutation", ["naive-clock", "action-type", "case-ref", "missing-type"])
async def test_contextual_reuse_reports_identity_and_clock_gaps(mutation: str) -> None:
    event, action, context = _event(), _action(), _context()
    verification = await _Verifier().verify(event=event, action=action, context=context)
    evaluated_at = datetime(2026, 8, 1, 0, 0, 3, tzinfo=UTC)
    if mutation == "naive-clock":
        evaluated_at = evaluated_at.replace(tzinfo=None)
        expected = "current_evaluation_time_invalid"
    elif mutation == "action-type":
        action = replace(action, action_type="ops.restart-service")
        expected = "operational_case_action_type_changed"
    elif mutation == "case-ref":
        verification = replace(verification, case_ref="case-history:other-case:1:" + "e" * 64)
        expected = "current_case_ref_conflict"
    else:
        event = event.model_copy(update={"payload": {"resource": {}}})
        expected = "current_resource_type_changed"
    assert expected in contextual_reuse_reasons(
        event=event,
        action=action,
        context=context,
        verification=verification,
        evaluated_at=evaluated_at,
    )
