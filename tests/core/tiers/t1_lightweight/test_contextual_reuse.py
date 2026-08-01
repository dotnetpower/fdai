from __future__ import annotations

from datetime import UTC, datetime

import pytest

from fdai.core.tiers.t1_lightweight import (
    CurrentReuseVerification,
    LearnedAction,
    OperationalCaseContext,
    T1Outcome,
    T1Tier,
)
from fdai.core.tiers.t1_lightweight.testing import (
    DeterministicEmbeddingModel,
    InMemoryPatternLibrary,
)
from fdai.shared.contracts.models import Event


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
        return CurrentReuseVerification(**values)  # type: ignore[arg-type]


async def _tier(verifier: object | None) -> tuple[T1Tier, Event]:
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
        ),
        event,
    )


async def test_operational_case_reuse_abstains_without_current_verifier() -> None:
    tier, event = await _tier(None)
    decision = await tier.evaluate(event=event)

    assert decision.outcome is T1Outcome.ABSTAIN
    assert decision.reason == "current_reuse_verifier_unavailable"


async def test_operational_case_reuse_requires_all_current_checks() -> None:
    tier, event = await _tier(_Verifier())

    decision = await tier.evaluate(event=event)

    assert decision.outcome is T1Outcome.REUSED
    assert decision.requires_reverification is True
    assert decision.current_reuse_verification is not None
    assert decision.current_reuse_verification.case_ref == _context().case_ref
    assert decision.current_reuse_verification.evidence_refs == ("d" * 64,)


async def test_recent_cached_evidence_may_precede_event_ingestion() -> None:
    tier, event = await _tier(
        _Verifier(observed_at=datetime(2026, 8, 1, 0, 0, 0, 500_000, tzinfo=UTC))
    )

    decision = await tier.evaluate(event=event)

    assert decision.outcome is T1Outcome.REUSED


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
