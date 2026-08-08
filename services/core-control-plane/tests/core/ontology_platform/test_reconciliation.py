"""Focused authority and replay tests for effect reconciliation coordination."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.ontology_platform.kinetics import (
    MutationEffect,
    MutationEffectKind,
    ReconciliationStatus,
)
from fdai.core.ontology_platform.planning import build_mutation_plan
from fdai.core.ontology_platform.reconciliation import (
    EffectEvidenceAuthority,
    EffectObservationEnvelope,
    EffectReconciliationCoordinator,
    EffectReconciliationRequest,
    InMemoryReconciliationLedger,
    ObservedEffectRecord,
    ReconciliationConflictError,
    ReconciliationNextStep,
    ReconciliationOutcome,
)
from fdai.shared.contracts.models import (
    OntologyActionType,
    OntologyDeclarationKind,
    OntologyObjectType,
    Operation,
    PromotionGate,
    PropertyDecl,
    PropertyType,
    RollbackKind,
)
from fdai.shared.ontology.release import build_ontology_release
from fdai.shared.providers.ontology_instance import OntologyObjectRecord
from pydantic import ValidationError

CREATED_AT = datetime(2026, 8, 8, 10, 0, tzinfo=UTC)
DEADLINE = CREATED_AT + timedelta(minutes=5)


def _fixture(*, expected: bool = True):
    object_type = OntologyObjectType(
        schema_version="1.0.0",
        name="Workload",
        version="1.0.0",
        key="id",
        properties={
            "id": PropertyDecl(type=PropertyType.STRING, required=True),
            "replicas": PropertyDecl(type=PropertyType.INTEGER, required=True),
        },
    )
    action_type = OntologyActionType(
        schema_version="1.0.0",
        name="ops.scale",
        version="1.0.0",
        operation=Operation.SCALE,
        rollback_contract=RollbackKind.STATE_FORWARD_ONLY,
        promotion_gate=PromotionGate(
            min_shadow_days=1,
            min_samples=1,
            min_accuracy=1.0,
            max_policy_escapes=0,
        ),
    )
    release = build_ontology_release(object_types=(object_type,), action_types=(action_type,))
    target = OntologyObjectRecord(
        id="workload-a",
        object_type="Workload",
        properties={"id": "workload-a", "replicas": 2},
        revision=1,
        type_ref=release.type_ref(OntologyDeclarationKind.OBJECT, "Workload"),
    )
    command = MutationEffect(
        effect_id="scale-command",
        kind=MutationEffectKind.PROVIDER_COMMAND,
        target_id=target.id,
        command_ref="provider.scale",
    )
    expected_effects = (
        (
            MutationEffect(
                effect_id="replicas-converged",
                kind=MutationEffectKind.EXPECTED_PROPERTY,
                target_id=target.id,
                property_name="replicas",
                value=3,
            ),
        )
        if expected
        else ()
    )
    plan = build_mutation_plan(
        action_type_ref=release.type_ref(OntologyDeclarationKind.ACTION, "ops.scale"),
        planner_ref="plan.scale@1.0.0",
        targets=(target,),
        effects=(command,),
        rollback_effects=(command,),
        expected_effects=expected_effects,
        created_at=CREATED_AT,
        max_affected_objects=1,
    )
    return release, target, plan


def _request(
    *,
    release,
    target: OntologyObjectRecord,
    plan,
    replicas: int = 3,
    authority: EffectEvidenceAuthority = EffectEvidenceAuthority.PROVIDER,
    source_identity: str = "provider-readback",
    execution_identity: str = "thor-executor",
    evaluated_at: datetime = CREATED_AT + timedelta(minutes=2),
    correlation_id: str = "correlation-1",
):
    observed = OntologyObjectRecord(
        id=target.id,
        object_type=target.object_type,
        properties={"id": target.id, "replicas": replicas},
        revision=2,
        type_ref=target.type_ref,
    )
    recorded_at = CREATED_AT + timedelta(minutes=1)
    evidence = EffectObservationEnvelope.create(
        correlation_id=correlation_id,
        plan_digest=plan.digest,
        ontology_release_ref=release.ref(),
        action_type_ref=plan.action_type_ref,
        observer_identity="heimdall-observer",
        execution_identity=execution_identity,
        source_identity=source_identity,
        source_authority=authority,
        observed_at=recorded_at,
        observation_cutoff=recorded_at,
        recorded_at=recorded_at,
        fresh_until=CREATED_AT + timedelta(minutes=10),
        complete=True,
        synthetic=False,
        evidence_refs=("evidence:provider-readback:1",),
        records=(ObservedEffectRecord.from_record(observed),),
    )
    return EffectReconciliationRequest.create(
        correlation_id=correlation_id,
        plan=plan,
        evidence=evidence,
        deadline=DEADLINE,
        evaluated_at=evaluated_at,
    )


@pytest.mark.parametrize(
    ("replicas", "evaluated_at", "status", "next_step", "target_agent"),
    (
        (
            3,
            CREATED_AT + timedelta(minutes=2),
            ReconciliationStatus.MATCHED,
            ReconciliationNextStep.CLOSE_MATCHED,
            None,
        ),
        (
            4,
            CREATED_AT + timedelta(minutes=2),
            ReconciliationStatus.MISMATCHED,
            ReconciliationNextStep.REQUEST_VIDAR_RECOVERY,
            "vidar",
        ),
        (
            3,
            CREATED_AT + timedelta(minutes=6),
            ReconciliationStatus.TIMED_OUT,
            ReconciliationNextStep.REQUEST_VIDAR_RECOVERY,
            "vidar",
        ),
    ),
)
async def test_coordinator_maps_terminal_status_to_typed_next_step(
    replicas,
    evaluated_at,
    status,
    next_step,
    target_agent,
) -> None:
    release, target, plan = _fixture()
    coordinator = EffectReconciliationCoordinator(ledger=InMemoryReconciliationLedger())

    outcome = await coordinator.coordinate(
        _request(
            release=release,
            target=target,
            plan=plan,
            replicas=replicas,
            evaluated_at=evaluated_at,
        ),
        active_release=release,
    )

    assert outcome.receipt.status is status
    assert outcome.recommendation.next_step is next_step
    assert outcome.recommendation.target_agent == target_agent
    assert ReconciliationOutcome.model_validate_json(outcome.model_dump_json()) == outcome
    with pytest.raises(ValidationError):
        outcome.correlation_id = "changed"


@pytest.mark.parametrize(
    ("authority", "source_identity", "execution_identity", "reason_code"),
    (
        (
            EffectEvidenceAuthority.API_RECEIPT,
            "provider-api-receipt",
            "thor-executor",
            "source_not_authoritative",
        ),
        (
            EffectEvidenceAuthority.UNKNOWN,
            "unknown-source",
            "thor-executor",
            "source_not_authoritative",
        ),
        (
            EffectEvidenceAuthority.PROVIDER,
            "thor-executor",
            "thor-executor",
            "observation_not_independent",
        ),
    ),
)
async def test_coordinator_holds_unscorable_or_self_observed_evidence(
    authority,
    source_identity,
    execution_identity,
    reason_code,
) -> None:
    release, target, plan = _fixture()
    coordinator = EffectReconciliationCoordinator(ledger=InMemoryReconciliationLedger())

    outcome = await coordinator.coordinate(
        _request(
            release=release,
            target=target,
            plan=plan,
            authority=authority,
            source_identity=source_identity,
            execution_identity=execution_identity,
        ),
        active_release=release,
    )

    assert outcome.receipt.status is ReconciliationStatus.UNSCORABLE
    assert outcome.recommendation.next_step is ReconciliationNextStep.HOLD_UNSCORABLE
    assert outcome.recommendation.reason_code == reason_code


async def test_coordinator_rejects_forged_plan_binding_and_stale_release() -> None:
    release, target, plan = _fixture()
    coordinator = EffectReconciliationCoordinator(ledger=InMemoryReconciliationLedger())
    forged = _request(release=release, target=target, plan=plan)
    forged_evidence = EffectObservationEnvelope.create(
        **{
            **forged.evidence.model_dump(exclude={"observation_id", "plan_digest"}),
            "plan_digest": "sha256:" + "f" * 64,
        }
    )
    forged_request = EffectReconciliationRequest.create(
        correlation_id=forged.correlation_id,
        plan=plan,
        evidence=forged_evidence,
        deadline=forged.deadline,
        evaluated_at=forged.evaluated_at,
    )

    with pytest.raises(ValueError, match="plan digest"):
        await coordinator.coordinate(forged_request, active_release=release)

    forged_action_evidence = EffectObservationEnvelope.create(
        **{
            **forged.evidence.model_dump(exclude={"observation_id", "action_type_ref"}),
            "action_type_ref": plan.action_type_ref.model_copy(update={"version": "9.0.0"}),
        }
    )
    forged_action_request = EffectReconciliationRequest.create(
        correlation_id=forged.correlation_id,
        plan=plan,
        evidence=forged_action_evidence,
        deadline=forged.deadline,
        evaluated_at=forged.evaluated_at,
    )
    with pytest.raises(ValueError, match="ActionType ref does not match"):
        await coordinator.coordinate(forged_action_request, active_release=release)

    stale_object_type = OntologyObjectType(
        schema_version="1.0.0",
        name="Workload",
        version="2.0.0",
        key="id",
        properties={"id": PropertyDecl(type=PropertyType.STRING, required=True)},
    )
    stale_release = build_ontology_release(object_types=(stale_object_type,))
    with pytest.raises(ValueError, match="release is not active"):
        await coordinator.coordinate(forged, active_release=stale_release)


async def test_coordinator_holds_observation_cutoff_before_plan() -> None:
    release, target, plan = _fixture()
    valid = _request(release=release, target=target, plan=plan)
    stale_evidence = EffectObservationEnvelope.create(
        **{
            **valid.evidence.model_dump(
                exclude={
                    "observation_id",
                    "observed_at",
                    "observation_cutoff",
                    "recorded_at",
                }
            ),
            "observed_at": CREATED_AT - timedelta(minutes=2),
            "observation_cutoff": CREATED_AT - timedelta(minutes=1),
            "recorded_at": CREATED_AT + timedelta(minutes=1),
        }
    )
    request = EffectReconciliationRequest.create(
        correlation_id=valid.correlation_id,
        plan=plan,
        evidence=stale_evidence,
        deadline=valid.deadline,
        evaluated_at=valid.evaluated_at,
    )

    outcome = await EffectReconciliationCoordinator(
        ledger=InMemoryReconciliationLedger()
    ).coordinate(request, active_release=release)

    assert outcome.receipt.status is ReconciliationStatus.UNSCORABLE
    assert outcome.recommendation.reason_code == "observation_before_plan"


async def test_coordinator_detects_inconsistent_duplicate() -> None:
    release, target, plan = _fixture()
    ledger = InMemoryReconciliationLedger()
    coordinator = EffectReconciliationCoordinator(ledger=ledger)
    matched = _request(release=release, target=target, plan=plan, replicas=3)
    mismatched = _request(release=release, target=target, plan=plan, replicas=4)

    first = await coordinator.coordinate(matched, active_release=release)
    replay = await coordinator.coordinate(matched, active_release=release)
    assert replay == first

    with pytest.raises(ReconciliationConflictError, match="different request content"):
        await coordinator.coordinate(mismatched, active_release=release)


def test_request_rejects_invalid_deadline() -> None:
    release, target, plan = _fixture()
    valid = _request(release=release, target=target, plan=plan)

    with pytest.raises(ValidationError, match="deadline MUST follow"):
        EffectReconciliationRequest.create(
            correlation_id=valid.correlation_id,
            plan=plan,
            evidence=valid.evidence,
            deadline=CREATED_AT,
            evaluated_at=valid.evaluated_at,
        )


async def test_coordinator_holds_plan_without_scorable_postconditions() -> None:
    release, target, plan = _fixture(expected=False)
    coordinator = EffectReconciliationCoordinator(ledger=InMemoryReconciliationLedger())

    outcome = await coordinator.coordinate(
        _request(release=release, target=target, plan=plan),
        active_release=release,
    )

    assert outcome.receipt.status is ReconciliationStatus.UNSCORABLE
    assert outcome.recommendation.next_step is ReconciliationNextStep.HOLD_UNSCORABLE
