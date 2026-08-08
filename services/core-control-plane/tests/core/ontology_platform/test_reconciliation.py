"""Focused authority and replay tests for effect reconciliation coordination."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.ontology_platform.action_plans import compile_action_mutation_plan
from fdai.core.ontology_platform.kinetics import (
    MutationEffect,
    MutationEffectKind,
    ReconciliationStatus,
)
from fdai.core.ontology_platform.planning import build_mutation_plan
from fdai.core.ontology_platform.reconciliation import (
    AuthenticatedObservationContext,
    EffectEvidenceAuthority,
    EffectObservationEnvelope,
    EffectReconciliationCoordinator,
    EffectReconciliationRequest,
    InMemoryReconciliationLedger,
    ObservationVerificationReceipt,
    ObservedEffectRecord,
    ReconciliationConflictError,
    ReconciliationNextStep,
    ReconciliationOutcome,
)
from fdai.shared.contracts.models import (
    ActionEffectSpec,
    ActionLockScope,
    ActionPostconditionKind,
    ActionPostconditionSpec,
    ActionSemanticContract,
    ActionSemanticEffectKind,
    ActionTargetCardinality,
    ActionTargetSelector,
    ActionTransactionMode,
    ActionTransactionPolicy,
    OntologyActionType,
    OntologyDeclarationKind,
    OntologyFunctionKind,
    OntologyFunctionType,
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


def _fixture():
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
    planner = OntologyFunctionType(
        name="plan.scale",
        version="1.0.0",
        kind=OntologyFunctionKind.PLAN,
        artifact_digest="sha256:" + "a" * 64,
        publisher="fdai",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
    )
    declarations = build_ontology_release(
        object_types=(object_type,), function_types=(planner,)
    ).declarations
    object_ref = next(
        item
        for item in declarations
        if item.kind is OntologyDeclarationKind.OBJECT and item.name == object_type.name
    )
    planner_ref = next(
        item
        for item in declarations
        if item.kind is OntologyDeclarationKind.FUNCTION and item.name == planner.name
    )
    semantic = ActionSemanticContract(
        target=ActionTargetSelector(
            type_ref=object_ref,
            cardinality=ActionTargetCardinality.ONE,
        ),
        planner_ref=planner_ref,
        effects=(
            ActionEffectSpec(
                effect_id="scale-command",
                kind=ActionSemanticEffectKind.PROVIDER_COMMAND,
                operation_ref="provider.scale",
                rollback_operation_ref="provider.scale.rollback",
            ),
        ),
        postconditions=(
            ActionPostconditionSpec(
                postcondition_id="replicas-converged",
                kind=ActionPostconditionKind.PROPERTY,
                observation_ref="property.replicas",
            ),
        ),
        transaction_policy=ActionTransactionPolicy(
            mode=ActionTransactionMode.SAGA,
            lock_scope=ActionLockScope.TARGET,
            max_affected_objects=1,
        ),
    )
    action_type = OntologyActionType(
        schema_version="2.0.0",
        name="ops.scale",
        version="2.0.0",
        operation=Operation.SCALE,
        rollback_contract=RollbackKind.STATE_FORWARD_ONLY,
        promotion_gate=PromotionGate(
            min_shadow_days=1,
            min_samples=1,
            min_accuracy=1.0,
            max_policy_escapes=0,
        ),
        semantic=semantic,
    )
    release = build_ontology_release(
        object_types=(object_type,),
        action_types=(action_type,),
        function_types=(planner,),
    )
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
    rollback = command.model_copy(update={"command_ref": "provider.scale.rollback"})
    expected_effects = (
        MutationEffect(
            effect_id="replicas-converged",
            kind=MutationEffectKind.EXPECTED_PROPERTY,
            target_id=target.id,
            property_name="replicas",
            value=3,
            observation_ref="property.replicas",
        ),
    )
    plan = compile_action_mutation_plan(
        action_type=action_type,
        release=release,
        function_types=(planner,),
        targets=(target,),
        effects=(command,),
        rollback_effects=(rollback,),
        expected_effects=expected_effects,
        created_at=CREATED_AT,
        arguments={},
    )
    return release, target, plan, action_type


def _request(
    *,
    release,
    target: OntologyObjectRecord,
    plan,
    action_type: OntologyActionType,
    replicas: object = 3,
    authority: EffectEvidenceAuthority = EffectEvidenceAuthority.PROVIDER,
    source_identity: str = "provider-readback",
    execution_identity: str = "thor-executor",
    evaluated_at: datetime = CREATED_AT + timedelta(minutes=2),
    observed_at: datetime = CREATED_AT + timedelta(minutes=1),
    correlation_id: str = "correlation-1",
):
    observed = OntologyObjectRecord(
        id=target.id,
        object_type=target.object_type,
        properties={"id": target.id, "replicas": replicas},
        revision=2,
        type_ref=target.type_ref,
    )
    recorded_at = observed_at
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
        action_type=action_type,
        evidence=evidence,
        deadline=DEADLINE,
        evaluated_at=evaluated_at,
    )


def _authenticated_context(
    request: EffectReconciliationRequest,
    *,
    source_authority: EffectEvidenceAuthority | None = None,
) -> AuthenticatedObservationContext:
    receipt = ObservationVerificationReceipt.create(
        observation_id=request.evidence.observation_id,
        observation_digest=request.evidence.content_digest(),
        verifier_identity="observation-authenticator",
        verifier_credential_lineage="credential:observation-authenticator:1",
        verified_at=request.evidence.recorded_at,
        signature_algorithm="ed25519",
        signature="base64:c2lnbmVkLW9ic2VydmF0aW9uLXJlY2VpcHQ",
    )
    return AuthenticatedObservationContext(
        source_authority=source_authority or request.evidence.source_authority,
        observer_identity=request.evidence.observer_identity,
        observer_credential_lineage="credential:heimdall-observer:1",
        executor_identity=request.evidence.execution_identity,
        executor_credential_lineage="credential:thor-executor:1",
        source_identity=request.evidence.source_identity,
        source_credential_lineage="credential:provider-readback:1",
        verification_receipt=receipt,
        signature_verified=True,
    )


async def _coordinate(
    coordinator: EffectReconciliationCoordinator,
    request: EffectReconciliationRequest,
    *,
    release,
) -> ReconciliationOutcome:
    return await coordinator.coordinate(
        request,
        observation_context=_authenticated_context(request),
        active_release=release,
    )


async def test_unscorable_attempt_does_not_poison_authenticated_terminal_retry() -> None:
    release, target, plan, action_type = _fixture()
    ledger = InMemoryReconciliationLedger()
    coordinator = EffectReconciliationCoordinator(ledger=ledger)
    first_request = _request(
        release=release,
        target=target,
        plan=plan,
        action_type=action_type,
    )
    invalid_context = _authenticated_context(first_request).model_copy(
        update={"observer_credential_lineage": "credential:thor-executor:1"}
    )

    first = await coordinator.coordinate(
        first_request,
        observation_context=invalid_context,
        active_release=release,
    )
    retry_request = _request(
        release=release,
        target=target,
        plan=plan,
        action_type=action_type,
        observed_at=CREATED_AT + timedelta(minutes=1, seconds=1),
        correlation_id=first_request.correlation_id,
    )
    retry = await coordinator.coordinate(
        retry_request,
        observation_context=_authenticated_context(retry_request),
        active_release=release,
    )

    assert first.receipt.status is ReconciliationStatus.UNSCORABLE
    assert retry.receipt.status is ReconciliationStatus.MATCHED
    assert first.observation_attempt_id != retry.observation_attempt_id
    assert first.reconciliation_id == retry.reconciliation_id
    assert len(ledger.attempts) == 2
    assert ledger.terminal_outcomes == (retry,)
    assert ledger.outbox == (retry.recommendation,)


async def test_same_observation_unscorable_attempt_does_not_block_later_timeout() -> None:
    release, target, plan, action_type = _fixture()
    ledger = InMemoryReconciliationLedger()
    coordinator = EffectReconciliationCoordinator(ledger=ledger)
    first_request = _request(
        release=release,
        target=target,
        plan=plan,
        action_type=action_type,
    )

    first = await coordinator.coordinate(
        first_request,
        observation_context=_authenticated_context(first_request).model_copy(
            update={"observer_credential_lineage": "credential:thor-executor:1"}
        ),
        active_release=release,
    )
    timeout_request = EffectReconciliationRequest.create(
        correlation_id=first_request.correlation_id,
        plan=plan,
        action_type=action_type,
        evidence=first_request.evidence,
        deadline=first_request.deadline,
        evaluated_at=DEADLINE + timedelta(seconds=1),
    )
    timed_out = await coordinator.coordinate(
        timeout_request,
        observation_context=_authenticated_context(timeout_request),
        active_release=release,
    )

    assert first.receipt.status is ReconciliationStatus.UNSCORABLE
    assert timed_out.receipt.status is ReconciliationStatus.TIMED_OUT
    assert first.observation_attempt_id != timed_out.observation_attempt_id
    assert len(ledger.attempts) == 2
    assert ledger.terminal_outcomes == (timed_out,)


@pytest.mark.parametrize(
    ("expected", "observed"),
    (
        (1, True),
        ({"enabled": 1, "nested": [0]}, {"enabled": True, "nested": [False]}),
    ),
)
async def test_expected_effect_comparison_is_json_type_strict(
    expected: object,
    observed: object,
) -> None:
    release, target, plan, action_type = _fixture()
    strict_plan = build_mutation_plan(
        action_type_ref=plan.action_type_ref,
        planner_ref=plan.planner_ref,
        targets=(target,),
        effects=plan.effects,
        rollback_effects=plan.rollback_effects,
        expected_effects=(plan.expected_effects[0].model_copy(update={"value": expected}),),
        created_at=plan.created_at,
        max_affected_objects=plan.max_affected_objects or 1,
        schema_version=plan.schema_version,
        arguments_digest=plan.arguments_digest,
        argument_bindings=plan.argument_bindings,
        read_set_receipt_digests=plan.read_set_receipt_digests,
        criterion_receipt_digests=plan.criterion_receipt_digests,
        transaction_mode=plan.transaction_mode,
        lock_scope=plan.lock_scope,
        lock_keys=plan.lock_keys,
        irreversible=plan.irreversible,
    )
    request = _request(
        release=release,
        target=target,
        plan=strict_plan,
        action_type=action_type,
        replicas=observed,
    )

    outcome = await _coordinate(
        EffectReconciliationCoordinator(ledger=InMemoryReconciliationLedger()),
        request,
        release=release,
    )

    assert outcome.receipt.status is ReconciliationStatus.MISMATCHED


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
    release, target, plan, action_type = _fixture()
    coordinator = EffectReconciliationCoordinator(ledger=InMemoryReconciliationLedger())

    outcome = await coordinator.coordinate(
        _request(
            release=release,
            target=target,
            plan=plan,
            action_type=action_type,
            replicas=replicas,
            evaluated_at=evaluated_at,
        ),
        observation_context=_authenticated_context(
            _request(
                release=release,
                target=target,
                plan=plan,
                action_type=action_type,
                replicas=replicas,
                evaluated_at=evaluated_at,
            )
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
    release, target, plan, action_type = _fixture()
    coordinator = EffectReconciliationCoordinator(ledger=InMemoryReconciliationLedger())

    request = _request(
        release=release,
        target=target,
        plan=plan,
        action_type=action_type,
        authority=authority,
        source_identity=source_identity,
        execution_identity=execution_identity,
    )
    outcome = await _coordinate(coordinator, request, release=release)

    assert outcome.receipt.status is ReconciliationStatus.UNSCORABLE
    assert outcome.recommendation.next_step is ReconciliationNextStep.HOLD_UNSCORABLE
    assert outcome.recommendation.reason_code == reason_code


async def test_coordinator_rejects_forged_plan_binding_and_stale_release() -> None:
    release, target, plan, action_type = _fixture()
    coordinator = EffectReconciliationCoordinator(ledger=InMemoryReconciliationLedger())
    forged = _request(
        release=release,
        target=target,
        plan=plan,
        action_type=action_type,
    )
    forged_evidence = EffectObservationEnvelope.create(
        **{
            **forged.evidence.model_dump(exclude={"observation_id", "plan_digest"}),
            "plan_digest": "sha256:" + "f" * 64,
        }
    )
    forged_request = EffectReconciliationRequest.create(
        correlation_id=forged.correlation_id,
        plan=plan,
        action_type=action_type,
        evidence=forged_evidence,
        deadline=forged.deadline,
        evaluated_at=forged.evaluated_at,
    )

    with pytest.raises(ValueError, match="plan digest"):
        await _coordinate(coordinator, forged_request, release=release)

    forged_action_evidence = EffectObservationEnvelope.create(
        **{
            **forged.evidence.model_dump(exclude={"observation_id", "action_type_ref"}),
            "action_type_ref": plan.action_type_ref.model_copy(update={"version": "9.0.0"}),
        }
    )
    forged_action_request = EffectReconciliationRequest.create(
        correlation_id=forged.correlation_id,
        plan=plan,
        action_type=action_type,
        evidence=forged_action_evidence,
        deadline=forged.deadline,
        evaluated_at=forged.evaluated_at,
    )
    with pytest.raises(ValueError, match="ActionType ref does not match"):
        await _coordinate(coordinator, forged_action_request, release=release)

    stale_object_type = OntologyObjectType(
        schema_version="1.0.0",
        name="Workload",
        version="2.0.0",
        key="id",
        properties={"id": PropertyDecl(type=PropertyType.STRING, required=True)},
    )
    stale_release = build_ontology_release(object_types=(stale_object_type,))
    with pytest.raises(ValueError, match="release is not active"):
        await _coordinate(coordinator, forged, release=stale_release)


def test_request_rejects_observation_before_plan() -> None:
    release, target, plan, action_type = _fixture()
    valid = _request(
        release=release,
        target=target,
        plan=plan,
        action_type=action_type,
    )
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
    with pytest.raises(ValidationError, match="MUST NOT precede plan creation"):
        EffectReconciliationRequest.create(
            correlation_id=valid.correlation_id,
            plan=plan,
            action_type=action_type,
            evidence=stale_evidence,
            deadline=valid.deadline,
            evaluated_at=valid.evaluated_at,
        )


async def test_coordinator_detects_inconsistent_duplicate() -> None:
    release, target, plan, action_type = _fixture()
    ledger = InMemoryReconciliationLedger()
    coordinator = EffectReconciliationCoordinator(ledger=ledger)
    matched = _request(
        release=release,
        target=target,
        plan=plan,
        action_type=action_type,
        replicas=3,
    )
    mismatched = _request(
        release=release,
        target=target,
        plan=plan,
        action_type=action_type,
        replicas=4,
    )

    first = await _coordinate(coordinator, matched, release=release)
    replay = await _coordinate(coordinator, matched, release=release)
    assert replay == first

    with pytest.raises(ReconciliationConflictError, match="different request content"):
        await _coordinate(coordinator, mismatched, release=release)


def test_request_rejects_invalid_deadline() -> None:
    release, target, plan, action_type = _fixture()
    valid = _request(
        release=release,
        target=target,
        plan=plan,
        action_type=action_type,
    )

    with pytest.raises(ValidationError, match="deadline MUST follow"):
        EffectReconciliationRequest.create(
            correlation_id=valid.correlation_id,
            plan=plan,
            action_type=action_type,
            evidence=valid.evidence,
            deadline=CREATED_AT,
            evaluated_at=valid.evaluated_at,
        )


async def test_coordinator_holds_plan_without_scorable_postconditions() -> None:
    release, target, semantic_plan, action_type = _fixture()
    plan = build_mutation_plan(
        action_type_ref=semantic_plan.action_type_ref,
        planner_ref="legacy-planner",
        targets=(target,),
        effects=semantic_plan.effects,
        rollback_effects=semantic_plan.rollback_effects,
        expected_effects=semantic_plan.expected_effects,
        created_at=CREATED_AT,
        max_affected_objects=1,
    )
    coordinator = EffectReconciliationCoordinator(ledger=InMemoryReconciliationLedger())

    request = _request(
        release=release,
        target=target,
        plan=plan,
        action_type=action_type,
    )
    outcome = await _coordinate(coordinator, request, release=release)

    assert outcome.receipt.status is ReconciliationStatus.UNSCORABLE
    assert outcome.recommendation.next_step is ReconciliationNextStep.HOLD_UNSCORABLE
    assert outcome.recommendation.reason_code == "semantic_effect_coverage_unproven"
