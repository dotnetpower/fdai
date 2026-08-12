"""Adversarial authentication, bounds, and concurrency tests for reconciliation."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta

import pytest
from fdai.core.ontology_platform.kinetics import (
    ReconciliationReceipt,
    ReconciliationStatus,
)
from fdai.core.ontology_platform.planning import build_mutation_plan
from fdai.core.ontology_platform.reconciliation import (
    EffectEvidenceAuthority,
    EffectObservationEnvelope,
    EffectReconciliationCoordinator,
    EffectReconciliationRequest,
    InMemoryReconciliationLedger,
    ObservationVerificationReceipt,
    ObservedEffectRecord,
    ReconciliationNextStep,
)
from pydantic import ValidationError
from tests.core.ontology_platform.test_reconciliation import (
    CREATED_AT,
    DEADLINE,
    _authenticated_context,
    _coordinate,
    _fixture,
    _request,
)


async def test_authenticated_authority_is_separate_from_untrusted_envelope_claim() -> None:
    release, target, plan, action_type = _fixture()
    claimed_unknown = _request(
        release=release,
        target=target,
        plan=plan,
        action_type=action_type,
        authority=EffectEvidenceAuthority.UNKNOWN,
    )
    trusted = await EffectReconciliationCoordinator(
        ledger=InMemoryReconciliationLedger()
    ).coordinate(
        claimed_unknown,
        observation_context=_authenticated_context(
            claimed_unknown,
            source_authority=EffectEvidenceAuthority.PROVIDER,
        ),
        active_release=release,
    )
    claimed_provider = _request(
        release=release,
        target=target,
        plan=plan,
        action_type=action_type,
        authority=EffectEvidenceAuthority.PROVIDER,
        correlation_id="correlation-2",
    )
    untrusted = await EffectReconciliationCoordinator(
        ledger=InMemoryReconciliationLedger()
    ).coordinate(
        claimed_provider,
        observation_context=_authenticated_context(
            claimed_provider,
            source_authority=EffectEvidenceAuthority.UNKNOWN,
        ),
        active_release=release,
    )

    assert trusted.receipt.status is ReconciliationStatus.MATCHED
    assert untrusted.receipt.status is ReconciliationStatus.UNSCORABLE
    assert untrusted.recommendation.reason_code == "source_not_authoritative"


async def test_verification_receipt_is_signed_content_addressed_and_observation_bound() -> None:
    release, target, plan, action_type = _fixture()
    request = _request(
        release=release,
        target=target,
        plan=plan,
        action_type=action_type,
    )
    context = _authenticated_context(request)
    tampered = context.verification_receipt.model_dump(mode="json")
    tampered["signature"] = "base64:c2lnbmVkLWJ1dC10YW1wZXJlZA"
    with pytest.raises(ValidationError, match="digest does not match"):
        ObservationVerificationReceipt.model_validate(tampered)

    wrong_observation = ObservationVerificationReceipt.create(
        **context.verification_receipt.model_dump(exclude={"receipt_digest", "observation_digest"}),
        observation_digest="sha256:" + "f" * 64,
    )
    wrong_context = context.model_copy(update={"verification_receipt": wrong_observation})
    with pytest.raises(ValueError, match="content digest does not match"):
        await EffectReconciliationCoordinator(ledger=InMemoryReconciliationLedger()).coordinate(
            request,
            observation_context=wrong_context,
            active_release=release,
        )


@pytest.mark.parametrize(
    ("authority", "execution_identity", "reason_code"),
    (
        (
            EffectEvidenceAuthority.UNKNOWN,
            "thor-executor",
            "source_not_authoritative",
        ),
        (
            EffectEvidenceAuthority.PROVIDER,
            "heimdall-observer",
            "observation_not_independent",
        ),
    ),
)
async def test_untrusted_observation_cannot_become_terminal_after_deadline(
    authority: EffectEvidenceAuthority,
    execution_identity: str,
    reason_code: str,
) -> None:
    release, target, plan, action_type = _fixture()
    request = _request(
        release=release,
        target=target,
        plan=plan,
        action_type=action_type,
        authority=authority,
        execution_identity=execution_identity,
        evaluated_at=DEADLINE + timedelta(seconds=1),
    )
    incomplete_evidence = EffectObservationEnvelope.create(
        **request.evidence.model_dump(exclude={"observation_id", "complete"}),
        complete=False,
    )
    timed_request = EffectReconciliationRequest.create(
        correlation_id=request.correlation_id,
        plan=plan,
        action_type=action_type,
        evidence=incomplete_evidence,
        deadline=DEADLINE,
        evaluated_at=request.evaluated_at,
    )
    outcome = await EffectReconciliationCoordinator(
        ledger=InMemoryReconciliationLedger()
    ).coordinate(
        timed_request,
        observation_context=_authenticated_context(
            timed_request,
            source_authority=authority,
        ),
        active_release=release,
    )

    assert outcome.receipt.status is ReconciliationStatus.UNSCORABLE
    assert outcome.recommendation.next_step is ReconciliationNextStep.HOLD_UNSCORABLE
    assert outcome.recommendation.reason_code == reason_code


async def test_independent_incomplete_observation_can_close_as_timed_out() -> None:
    release, target, plan, action_type = _fixture()
    request = _request(
        release=release,
        target=target,
        plan=plan,
        action_type=action_type,
        evaluated_at=DEADLINE + timedelta(seconds=1),
    )
    incomplete_evidence = EffectObservationEnvelope.create(
        **request.evidence.model_dump(exclude={"observation_id", "complete"}),
        complete=False,
    )
    timed_request = EffectReconciliationRequest.create(
        correlation_id=request.correlation_id,
        plan=plan,
        action_type=action_type,
        evidence=incomplete_evidence,
        deadline=DEADLINE,
        evaluated_at=request.evaluated_at,
    )

    outcome = await EffectReconciliationCoordinator(
        ledger=InMemoryReconciliationLedger()
    ).coordinate(
        timed_request,
        observation_context=_authenticated_context(timed_request),
        active_release=release,
    )

    assert outcome.receipt.status is ReconciliationStatus.TIMED_OUT
    assert outcome.recommendation.next_step is ReconciliationNextStep.REQUEST_VIDAR_RECOVERY
    assert outcome.recommendation.proposal_only is True
    assert outcome.recommendation.grants_authority is False


async def test_v2_semantic_effect_coverage_is_revalidated_before_matching() -> None:
    release, target, semantic_plan, action_type = _fixture()
    drifted_expected = semantic_plan.expected_effects[0].model_copy(
        update={"property_name": "unreviewed", "observation_ref": "property.unreviewed"}
    )
    drifted_plan = build_mutation_plan(
        action_type_ref=semantic_plan.action_type_ref,
        planner_ref=semantic_plan.planner_ref,
        targets=(target,),
        effects=semantic_plan.effects,
        rollback_effects=semantic_plan.rollback_effects,
        expected_effects=(drifted_expected,),
        created_at=semantic_plan.created_at,
        max_affected_objects=semantic_plan.max_affected_objects or 1,
        schema_version="2.0.0",
        arguments_digest=semantic_plan.arguments_digest,
        argument_bindings=semantic_plan.argument_bindings,
        transaction_mode=semantic_plan.transaction_mode,
        lock_scope=semantic_plan.lock_scope,
        lock_keys=semantic_plan.lock_keys,
        irreversible=semantic_plan.irreversible,
    )
    request = _request(
        release=release,
        target=target,
        plan=drifted_plan,
        action_type=action_type,
    )
    outcome = await _coordinate(
        EffectReconciliationCoordinator(ledger=InMemoryReconciliationLedger()),
        request,
        release=release,
    )

    assert outcome.receipt.status is ReconciliationStatus.UNSCORABLE
    assert outcome.recommendation.reason_code == "semantic_effect_coverage_unproven"


def test_reconciliation_receipt_and_status_next_step_invariants() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        ReconciliationReceipt(
            plan_digest="sha256:" + "a" * 64,
            status=ReconciliationStatus.MATCHED,
            observed_at=datetime(2026, 8, 8),
            evidence_refs=("evidence:1",),
        )
    with pytest.raises(ValidationError, match="requires mismatches"):
        ReconciliationReceipt(
            plan_digest="sha256:" + "a" * 64,
            status=ReconciliationStatus.MISMATCHED,
            observed_at=CREATED_AT,
            evidence_refs=("evidence:1",),
        )


async def test_recommendation_binds_exact_refs_and_concurrent_replay_is_singleton() -> None:
    release, target, plan, action_type = _fixture()
    request = _request(
        release=release,
        target=target,
        plan=plan,
        action_type=action_type,
    )
    ledger = InMemoryReconciliationLedger()
    coordinator = EffectReconciliationCoordinator(ledger=ledger)

    outcomes = await asyncio.gather(
        *(_coordinate(coordinator, request, release=release) for _ in range(32))
    )
    recommendation = outcomes[0].recommendation

    assert all(outcome == outcomes[0] for outcome in outcomes)
    assert recommendation.ontology_release_ref == release.ref()
    assert recommendation.action_type_ref == plan.action_type_ref
    assert recommendation.plan_digest == plan.digest
    assert recommendation.observation_id == request.evidence.observation_id
    assert recommendation.request_digest == request.request_digest
    assert outcomes[0].observation_context_digest == recommendation.observation_context_digest
    assert (
        outcomes[0].verification_receipt_digest
        == recommendation.verification_receipt_digest
        == _authenticated_context(request).verification_receipt.receipt_digest
    )
    assert recommendation.proposal_only is True
    assert recommendation.grants_authority is False
    assert len(ledger.attempts) == 1
    assert len(ledger.terminal_outcomes) == 1
    assert ledger.outbox[0].recommendation == recommendation


@pytest.mark.parametrize(
    "field",
    (
        "plan_digest",
        "observation_id",
        "ontology_release_ref",
        "action_type_ref",
        "idempotency_key",
        "next_step",
        "observation_context_digest",
        "verification_receipt_digest",
    ),
)
async def test_outcome_wire_validation_rejects_forged_recommendation_binding(
    field: str,
) -> None:
    release, target, plan, action_type = _fixture()
    request = _request(
        release=release,
        target=target,
        plan=plan,
        action_type=action_type,
    )
    outcome = await _coordinate(
        EffectReconciliationCoordinator(ledger=InMemoryReconciliationLedger()),
        request,
        release=release,
    )
    forged_values: dict[str, object] = {
        "plan_digest": "sha256:" + "f" * 64,
        "observation_id": "effect-observation:" + "f" * 64,
        "ontology_release_ref": outcome.recommendation.ontology_release_ref.model_copy(
            update={"digest": "sha256:" + "f" * 64}
        ),
        "action_type_ref": outcome.recommendation.action_type_ref.model_copy(
            update={"version": "9.0.0"}
        ),
        "idempotency_key": "reconciliation-next-step:" + "f" * 64,
        "next_step": ReconciliationNextStep.HOLD_UNSCORABLE,
        "observation_context_digest": "sha256:" + "f" * 64,
        "verification_receipt_digest": "sha256:" + "f" * 64,
    }
    payload = outcome.model_dump(mode="json")
    payload["recommendation"][field] = forged_values[field]

    with pytest.raises(ValidationError):
        type(outcome).model_validate(payload)


async def test_outcome_wire_validation_rejects_forged_context_digest() -> None:
    release, target, plan, action_type = _fixture()
    request = _request(
        release=release,
        target=target,
        plan=plan,
        action_type=action_type,
    )
    outcome = await _coordinate(
        EffectReconciliationCoordinator(ledger=InMemoryReconciliationLedger()),
        request,
        release=release,
    )
    payload = outcome.model_dump(mode="json")
    payload["observation_context_digest"] = "sha256:" + "f" * 64

    with pytest.raises(ValidationError, match="context digest does not match content"):
        type(outcome).model_validate(payload)


def test_effect_observation_enforces_item_and_canonical_byte_bounds() -> None:
    release, target, plan, action_type = _fixture()
    request = _request(
        release=release,
        target=target,
        plan=plan,
        action_type=action_type,
    )
    base = request.evidence.model_dump(
        exclude={"observation_id", "conflicts", "evidence_refs", "records"}
    )
    with pytest.raises(ValidationError):
        EffectObservationEnvelope.create(
            **base,
            conflicts=tuple(f"conflict-{index}" for index in range(65)),
            evidence_refs=request.evidence.evidence_refs,
            records=request.evidence.records,
        )
    with pytest.raises(ValidationError):
        EffectObservationEnvelope.create(
            **base,
            conflicts=(),
            evidence_refs=tuple(f"evidence:{index}" for index in range(129)),
            records=request.evidence.records,
        )
    with pytest.raises(ValidationError):
        EffectObservationEnvelope.create(
            **base,
            conflicts=(),
            evidence_refs=request.evidence.evidence_refs,
            records=tuple(
                request.evidence.records[0].model_copy(update={"object_id": f"object-{index}"})
                for index in range(1001)
            ),
        )

    large_properties = json.dumps(
        {"payload": "x" * 60_000},
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    with pytest.raises(ValidationError, match="canonical byte limit"):
        EffectObservationEnvelope.create(
            **base,
            conflicts=(),
            evidence_refs=request.evidence.evidence_refs,
            records=tuple(
                ObservedEffectRecord(
                    object_id=f"object-{index}",
                    type_ref=target.type_ref,
                    revision=2,
                    properties_json=large_properties,
                )
                for index in range(20)
            ),
        )
