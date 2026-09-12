"""Tests for fail-closed A3-E effect shadow-reversion planning."""

from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fdai.core.ontology_platform.kinetics import ReconciliationStatus
from fdai.core.ontology_platform.reconciliation import (
    EffectReconciliationCoordinator,
    EffectReconciliationRequest,
    InMemoryReconciliationLedger,
)
from fdai.core.ontology_platform.reconciliation_contracts import (
    AuthenticatedObservationContext,
    EffectEvidenceAuthority,
    EffectObservationEnvelope,
    ObservationVerificationReceipt,
    ObservedEffectRecord,
)
from fdai.core.standing_authority.effect_shadow_reversion import (
    EffectEvidenceDisposition,
    EffectVerificationFinding,
    ShadowReversionTransition,
    build_effect_verification_finding,
    plan_effect_shadow_reversion,
)
from fdai.shared.providers.ontology_instance import OntologyObjectRecord
from tests.delivery.azure.vm_power_state_fixtures import (
    CREATED_AT,
    vm_start_fixture,
)

NOW = datetime(2026, 9, 12, 4, 10, tzinfo=UTC)
DEADLINE = NOW + timedelta(minutes=5)
SOURCE_ROOT = Path(__file__).resolve().parents[3] / "src" / "fdai"


def _finding(
    *,
    status: ReconciliationStatus | None,
    reason_code: str,
    evaluated_at: datetime = NOW,
) -> EffectVerificationFinding:
    outcome_ids = (
        {
            "observation_id": None,
            "reconciliation_id": None,
            "receipt_digest": None,
        }
        if status is None
        else {
            "observation_id": "effect-observation:" + "a" * 64,
            "reconciliation_id": "reconciliation:" + "b" * 64,
            "receipt_digest": "sha256:" + "c" * 64,
        }
    )
    return EffectVerificationFinding(
        action_type_name="ops.start-vm",
        action_type_version="1.0.0",
        action_type_digest="d" * 64,
        target_digest="sha256:" + "e" * 64,
        source_revision_id="f" * 40,
        candidate_id="sha256:" + "1" * 64,
        fencing_generation=3,
        correlation_id="correlation:vm-start",
        plan_digest="sha256:" + "2" * 64,
        deadline=DEADLINE,
        evaluated_at=evaluated_at,
        reconciliation_status=status,
        reason_code=reason_code,
        **outcome_ids,
    )


@pytest.mark.parametrize(
    ("status", "reason", "disposition", "transition"),
    [
        (
            ReconciliationStatus.MATCHED,
            "effects_matched",
            EffectEvidenceDisposition.MATCHED,
            ShadowReversionTransition.NONE,
        ),
        (
            ReconciliationStatus.MISMATCHED,
            "effects_mismatched",
            EffectEvidenceDisposition.FAILED,
            ShadowReversionTransition.RETURN_TO_SHADOW,
        ),
        (
            ReconciliationStatus.TIMED_OUT,
            "timed_out_evaluation_late",
            EffectEvidenceDisposition.TIMED_OUT,
            ShadowReversionTransition.RETURN_TO_SHADOW,
        ),
        (
            ReconciliationStatus.UNSCORABLE,
            "observation_stale",
            EffectEvidenceDisposition.STALE,
            ShadowReversionTransition.RETURN_TO_SHADOW,
        ),
        (
            ReconciliationStatus.UNSCORABLE,
            "observation_conflicted",
            EffectEvidenceDisposition.CONFLICTING,
            ShadowReversionTransition.RETURN_TO_SHADOW,
        ),
        (
            ReconciliationStatus.UNSCORABLE,
            "observation_censored",
            EffectEvidenceDisposition.CENSORED,
            ShadowReversionTransition.RETURN_TO_SHADOW,
        ),
        (
            ReconciliationStatus.UNSCORABLE,
            "future_unscorable_reason",
            EffectEvidenceDisposition.UNSCORABLE,
            ShadowReversionTransition.RETURN_TO_SHADOW,
        ),
    ],
)
def test_reconciliation_outcomes_map_fail_closed(
    status: ReconciliationStatus,
    reason: str,
    disposition: EffectEvidenceDisposition,
    transition: ShadowReversionTransition,
) -> None:
    plan = plan_effect_shadow_reversion(_finding(status=status, reason_code=reason))

    assert plan.disposition is disposition
    assert plan.required_transition is transition
    assert plan.proposal_only is True
    assert plan.grants_authority is False
    assert plan.registry_mutated is False
    assert plan.recovery_authority is False


def test_missing_observation_waits_until_deadline_then_requires_reversion() -> None:
    pending = plan_effect_shadow_reversion(
        _finding(
            status=None,
            reason_code="observation_pending",
            evaluated_at=DEADLINE - timedelta(microseconds=1),
        )
    )
    missing = plan_effect_shadow_reversion(
        _finding(
            status=None,
            reason_code="observation_missing",
            evaluated_at=DEADLINE,
        )
    )

    assert pending.disposition is EffectEvidenceDisposition.PENDING
    assert pending.required_transition is ShadowReversionTransition.NONE
    assert missing.disposition is EffectEvidenceDisposition.MISSING
    assert missing.required_transition is ShadowReversionTransition.RETURN_TO_SHADOW


def test_plans_are_content_addressed_and_replay_stable() -> None:
    finding = _finding(
        status=ReconciliationStatus.MISMATCHED,
        reason_code="effects_mismatched",
    )

    first = plan_effect_shadow_reversion(finding)
    second = plan_effect_shadow_reversion(finding)

    assert first == second
    assert first.finding_id == finding.finding_id
    assert first.plan_id.startswith("sha256:")


def test_finding_factory_requires_explicit_missing_observation_time() -> None:
    artifacts, _action = vm_start_fixture()

    with pytest.raises(Exception, match="missing observation finding requires"):
        build_effect_verification_finding(
            action_type=artifacts.action_type,
            plan=artifacts.plan,
            source_revision_id="a" * 40,
            candidate_id="sha256:" + "b" * 64,
            fencing_generation=1,
        )


async def test_finding_factory_binds_exact_reconciliation_outcome() -> None:
    artifacts, outcome = await _matched_outcome()

    finding = build_effect_verification_finding(
        action_type=artifacts.action_type,
        plan=artifacts.plan,
        source_revision_id="a" * 40,
        candidate_id="sha256:" + "b" * 64,
        fencing_generation=4,
        outcome=outcome,
    )

    assert finding.reconciliation_status is ReconciliationStatus.MATCHED
    assert finding.reconciliation_id == outcome.reconciliation_id
    assert finding.receipt_digest == outcome.receipt_digest
    assert finding.observation_id == outcome.request.evidence.observation_id
    assert (
        plan_effect_shadow_reversion(finding).required_transition is ShadowReversionTransition.NONE
    )

    substituted_plan = artifacts.plan.model_copy(update={"planner_ref": "substituted-planner"})
    with pytest.raises(Exception, match="does not match"):
        build_effect_verification_finding(
            action_type=artifacts.action_type,
            plan=substituted_plan,
            source_revision_id="a" * 40,
            candidate_id="sha256:" + "b" * 64,
            fencing_generation=4,
            outcome=outcome,
        )


def test_reversion_module_has_no_authority_or_side_effect_imports() -> None:
    module_path = SOURCE_ROOT / "core" / "standing_authority" / "effect_shadow_reversion.py"
    forbidden = (
        "fdai.core.risk_gate",
        "fdai.core.executor",
        "fdai.core.workflow",
        "fdai.delivery",
        "fdai.runtime",
        "fdai.shared.providers.event_bus",
        "fdai.shared.providers.state_store",
    )
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.append(node.module)

    assert not any(module.startswith(prefix) for module in imported for prefix in forbidden)


async def _matched_outcome():
    artifacts, action = vm_start_fixture()
    target = artifacts.plan.targets[0]
    observed_at = CREATED_AT + timedelta(seconds=30)
    observed = OntologyObjectRecord(
        id=target.object_id,
        object_type=target.type_ref.name,
        properties={"power_state": "running"},
        revision=target.revision,
        type_ref=target.type_ref,
    )
    evidence = EffectObservationEnvelope.create(
        correlation_id="correlation:vm-start",
        plan_digest=artifacts.plan.digest,
        ontology_release_ref=artifacts.active_release.ref(),
        action_type_ref=artifacts.plan.action_type_ref,
        observer_identity="observer:heimdall:vm-power",
        execution_identity=action.executor_identity_ref,
        source_identity="source:azure-arm:vm-power",
        source_authority=EffectEvidenceAuthority.PROVIDER,
        observed_at=observed_at,
        observation_cutoff=observed_at,
        recorded_at=observed_at,
        fresh_until=observed_at + timedelta(minutes=1),
        complete=True,
        synthetic=False,
        conflicts=(),
        censoring_refs=(),
        evidence_refs=("sha256:" + "c" * 64,),
        records=(ObservedEffectRecord.from_record(observed),),
    )
    verification = ObservationVerificationReceipt.create(
        observation_id=evidence.observation_id,
        observation_digest=evidence.content_digest(),
        verifier_identity="observer-verifier",
        verifier_credential_lineage="credential:observer-verifier:1",
        verified_at=observed_at,
        signature_algorithm="ed25519",
        signature="base64:c3ludGhldGljLXNpZ25hdHVyZQ",
    )
    context = AuthenticatedObservationContext(
        source_authority=evidence.source_authority,
        observer_identity=evidence.observer_identity,
        observer_credential_lineage="credential:heimdall:1",
        executor_identity=evidence.execution_identity,
        executor_credential_lineage="credential:thor:1",
        source_identity=evidence.source_identity,
        source_credential_lineage="credential:azure-reader:1",
        verification_receipt=verification,
        signature_verified=True,
    )
    request = EffectReconciliationRequest.create(
        correlation_id=evidence.correlation_id,
        plan=artifacts.plan,
        action_type=artifacts.action_type,
        evidence=evidence,
        deadline=CREATED_AT + timedelta(minutes=5),
        evaluated_at=CREATED_AT + timedelta(minutes=1),
    )
    outcome = await EffectReconciliationCoordinator(
        ledger=InMemoryReconciliationLedger()
    ).coordinate(
        request,
        observation_context=context,
        active_release=artifacts.active_release,
    )
    return artifacts, outcome
