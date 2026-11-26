"""Round 6: every current plan, principal, quorum and time commitment is independently binding."""

from datetime import datetime, timedelta

import pytest
from fdai.core.detection.alert_noise.admission import admission_reasons
from fdai.core.detection.alert_noise.planning import plan_alert_change
from fdai_service_contracts.alert_noise import AlertEvidence, NoisePolicy, digest_record
from fdai_service_contracts.alert_noise_plan import (
    AlertApproval,
    AlertChangePlan,
    AlertDispatchEvidence,
)

from .test_planning_hardening import routing


def context(
    evidence: AlertEvidence, now: datetime
) -> tuple[AlertChangePlan, AlertDispatchEvidence, tuple[AlertApproval, ...]]:
    plan = plan_alert_change(
        evidence, routing(), policy=NoisePolicy(), requester_ref="principal:requester", now=now
    )
    proof = AlertDispatchEvidence(
        plan_digest=digest_record(plan),
        evidence_digest=plan.evidence_digest,
        policy_digest=plan.policy_digest,
        target_revision=plan.target_revision,
        evaluated_at=now,
        valid_until=now + timedelta(minutes=5),
        authorization_until=now + timedelta(hours=3),
        executor_ref="principal:executor",
        dry_run_digest="sha256:" + "e" * 64,
        promotion_digest="sha256:" + "f" * 64,
        writer_fence_ref="fence:one",
        audit_intent_ref="audit:one",
        recovery_admission_ref="recovery:one",
        dependencies_current=True,
        actors_current=True,
        observer_ready=True,
        recovery_ready=True,
        kill_switch=False,
        mode="enforce",
    )
    approvals = tuple(
        AlertApproval(
            plan_digest=digest_record(plan),
            principal_ref=f"principal:{lane}",
            tenant_ref=plan.tenant_ref,
            scope_ref=plan.scope_ref,
            decision="approved",
            lane=lane,
            service_refs=plan.service_refs if lane == "service_owner" else (),
            decided_at=now,
            expires_at=now + timedelta(hours=3),
            receipt_ref=f"receipt:{lane}",
            authority_revision="sha256:" + "a" * 64,
        )
        for lane in ("service_owner", "change_owner")
    )
    return plan, proof, approvals


def test_exact_quorum_allows_only_eligibility(evidence: AlertEvidence, now: datetime) -> None:
    plan, proof, approvals = context(evidence, now)
    assert admission_reasons(plan, approvals=approvals, evidence=proof, now=now) == ()
    assert plan.execution_authority is False


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"principal_ref": "principal:requester"}, "self_approval"),
        ({"principal_ref": "principal:executor"}, "self_approval"),
        ({"scope_ref": "scope:other"}, "approval_binding_mismatch"),
        ({"plan_digest": "sha256:" + "0" * 64}, "approval_binding_mismatch"),
        ({"decision": "rejected"}, "approval_rejected"),
        ({"service_refs": ()}, "service_approval_missing"),
    ],
)
def test_current_human_approval_is_exact(
    evidence: AlertEvidence, now: datetime, change: dict, reason: str
) -> None:
    plan, proof, approvals = context(evidence, now)
    decisions = (approvals[0].model_copy(update=change), approvals[1])
    assert reason in admission_reasons(plan, approvals=decisions, evidence=proof, now=now)


def test_duplicate_approval_and_missing_lane_never_make_quorum(
    evidence: AlertEvidence, now: datetime
) -> None:
    plan, proof, approvals = context(evidence, now)
    for values in ((approvals[0],), (approvals[0], approvals[0])):
        assert "independent_quorum_missing" in admission_reasons(
            plan, approvals=values, evidence=proof, now=now
        )


def test_plan_approval_and_evidence_expiry_are_independent(
    evidence: AlertEvidence, now: datetime
) -> None:
    plan, proof, approvals = context(evidence, now)
    for at, reason in (
        (now.replace(tzinfo=None), "clock_invalid"),
        (now + timedelta(minutes=6), "admission_expired"),
        (now + timedelta(days=1), "plan_expired"),
    ):
        assert reason in admission_reasons(plan, approvals=approvals, evidence=proof, now=at)
    early = tuple(
        row.model_copy(update={"expires_at": now + timedelta(minutes=1)}) for row in approvals
    )
    assert "approval_expired" in admission_reasons(plan, approvals=early, evidence=proof, now=now)


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"synthetic": True}, "synthetic_evidence"),
        ({"mode": "shadow"}, "shadow_only"),
        ({"kill_switch": True}, "kill_switch_active"),
        ({"writer_fence_ref": None}, "writer_fence_missing"),
        ({"audit_intent_ref": None}, "audit_intent_missing"),
        ({"promotion_digest": None}, "promotion_missing"),
        ({"recovery_admission_ref": None}, "recovery_admission_missing"),
        ({"authorization_until": None}, "deadline_does_not_fit"),
        ({"dependencies_current": False}, "dependencies_current"),
        ({"actors_current": False}, "actors_current"),
        ({"observer_ready": False}, "observer_ready"),
        ({"recovery_ready": False}, "recovery_ready"),
        ({"evidence_digest": "sha256:" + "0" * 64}, "admission_binding_mismatch"),
    ],
)
def test_each_trusted_dispatch_proof_is_required(
    evidence: AlertEvidence, now: datetime, change: dict, reason: str
) -> None:
    plan, proof, approvals = context(evidence, now)
    assert reason in admission_reasons(
        plan, approvals=approvals, evidence=proof.model_copy(update=change), now=now
    )
