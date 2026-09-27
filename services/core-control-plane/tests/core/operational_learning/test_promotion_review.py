from __future__ import annotations

from dataclasses import replace

import pytest
from fdai.core.control_loop._helpers import evaluate_unified
from fdai.core.measurement.operational_promotion import action_type_digest
from fdai.core.operational_learning.promotion_review import (
    ReviewedReplayAuthority,
    ReviewedReplayPromotionEvidence,
    ReviewedReplayReceiptVerifier,
)
from fdai.core.risk_gate.gate import (
    ActionPromotionRegistry,
    RiskDecisionOutcome,
    RiskGate,
)
from fdai.core.risk_gate.risk_table import load_risk_table
from fdai.shared.contracts.development_authority import evaluate_development_authority
from fdai.shared.contracts.models import (
    DevelopmentActionBinding,
    DevelopmentAuthorityEnvelope,
    Event,
    FullAuthorityDevelopmentProfile,
    Mode,
    RegisteredDevelopmentAction,
    RollbackKind,
    RollbackRef,
)
from tests.contracts.test_development_authority import (
    NOW,
    _binding,
    _binding_request,
    _BindingSource,
    _confirmation,
    _profile,
    _verification,
)
from tests.core.risk_gate.test_authority import TABLE_PATH
from tests.core.risk_gate.test_development_authority import _action
from tests.core.risk_gate.test_gate import (
    _action as _runtime_action,
)
from tests.core.risk_gate.test_gate import (
    _shipped_action_types,
    _shipped_rules_by_id,
)

REVISION = "a" * 40
DIGEST = "b" * 64


def _evidence(reviewer: str) -> ReviewedReplayPromotionEvidence:
    return ReviewedReplayPromotionEvidence(
        action_type="ops.restart-app",
        action_type_version="1.0.0",
        action_type_digest=DIGEST,
        fdai_revision=REVISION,
        scenario_set_version="v2026.08",
        candidate_digest=DIGEST,
        package_digest=DIGEST,
        replay_first_digest=DIGEST,
        replay_second_digest=DIGEST,
        promotion_evidence_digest=DIGEST,
        review_ref="governance-review:v2026.08",
        reviewer_principal=reviewer,
        approved=True,
    )


@pytest.mark.parametrize(
    "reviewer",
    ["Norns", "norns", "NORNS", " Mimir ", "mimir"],
)
def test_learning_agent_cannot_review_its_own_promotion(reviewer: str) -> None:
    with pytest.raises(ValueError, match="independent reviewer"):
        _evidence(reviewer)


@pytest.mark.parametrize("reviewer", ["", "   "])
def test_blank_reviewer_is_rejected(reviewer: str) -> None:
    with pytest.raises(ValueError, match="independent reviewer"):
        _evidence(reviewer)


def test_independent_reviewer_authorizes_the_exact_tuple() -> None:
    authority = ReviewedReplayAuthority((_evidence("independent-governance-reviewer"),))

    assert authority.accepts(
        action_type="ops.restart-app",
        action_type_version="1.0.0",
        action_type_digest=DIGEST,
        fdai_revision=REVISION,
        scenario_set_version="v2026.08",
        evidence_digest=DIGEST,
    )
    assert not authority.accepts(
        action_type="ops.restart-app",
        action_type_version="1.0.1",
        action_type_digest=DIGEST,
        fdai_revision=REVISION,
        scenario_set_version="v2026.08",
        evidence_digest=DIGEST,
    )


def _development_evidence() -> tuple[
    object,
    _BindingSource,
    object,
    DevelopmentActionBinding,
    object,
    object,
    ReviewedReplayPromotionEvidence,
    object,
]:
    promotion_action = _shipped_action_types()["governance.promote-action-type"]
    promotion_action_digest = "sha256:" + action_type_digest(promotion_action)
    profile = _profile(
        resource_groups=(),
        action_type="governance.promote-action-type",
        action_type_digest=promotion_action_digest,
    )
    base = replace(
        _evidence(profile.owner_principal),
        action_type=_action().name,
        action_type_digest=action_type_digest(_action()),
    )
    profile = FullAuthorityDevelopmentProfile.model_validate(
        {
            **profile.model_dump(mode="json"),
            "registered_actions": [
                RegisteredDevelopmentAction(
                    action_type=promotion_action.name,
                    version=promotion_action.version,
                    action_type_digest=promotion_action_digest,
                ).model_dump(mode="json"),
                RegisteredDevelopmentAction(
                    action_type=base.action_type,
                    version=base.action_type_version,
                    action_type_digest="sha256:" + base.action_type_digest,
                ).model_dump(mode="json"),
            ],
        }
    )
    promotion_params = {
        "action_type": base.action_type,
        "action_type_version": base.action_type_version,
        "action_type_digest": "sha256:" + base.action_type_digest,
        "reviewed_replay_digest": base.reviewed_replay_digest,
        "source_revision": base.fdai_revision,
        "scenario_set_version": base.scenario_set_version,
        "promotion_evidence_digest": "sha256:" + base.promotion_evidence_digest,
    }
    binding = _binding(
        profile,
        action_type="governance.promote-action-type",
        action_type_digest=promotion_action_digest,
        action_id="promotion:one",
        target="registry:development:ops.restart-service",
        params=promotion_params,
        idempotency_key="promotion-one",
    )
    verification = _verification(binding)
    source = _BindingSource(verification)
    request = _binding_request(
        action_type="governance.promote-action-type",
        action_id="promotion:one",
        target="registry:development:ops.restart-service",
        params=promotion_params,
        idempotency_key="promotion-one",
    )
    confirmation = _confirmation(profile, binding)
    decision = evaluate_development_authority(
        profile,
        confirmation,
        verification,
        now=NOW,
        original_quorum=2,
    )
    assert decision.grant is not None
    evidence = replace(
        base,
        reviewer_role="owner",
        development_confirmation=confirmation,
        development_binding_verification=verification,
        development_grant=decision.grant,
        development_binding_request=request,
    )
    return (
        profile,
        source,
        request,
        binding,
        confirmation,
        decision.grant,
        evidence,
        promotion_action,
    )


def test_sole_owner_review_is_development_only_and_exactly_attributed() -> None:
    (
        profile,
        source,
        _request,
        _binding_value,
        _confirmation_value,
        _grant,
        evidence,
        promotion_action,
    ) = _development_evidence()
    authority = ReviewedReplayAuthority(
        (evidence,),
        development_profile=profile,
        development_binding_source=source,
        development_action_types={promotion_action.name: promotion_action},
        clock=lambda: NOW,
    )

    assert not authority.accepts(
        action_type=evidence.action_type,
        action_type_version=evidence.action_type_version,
        action_type_digest=evidence.action_type_digest,
        fdai_revision=evidence.fdai_revision,
        scenario_set_version=evidence.scenario_set_version,
        evidence_digest=evidence.promotion_evidence_digest,
    )
    assert authority.accepts_development(
        profile_digest=profile.digest,
        action_type=evidence.action_type,
        action_type_version=evidence.action_type_version,
        action_type_digest=evidence.action_type_digest,
        fdai_revision=evidence.fdai_revision,
        scenario_set_version=evidence.scenario_set_version,
        evidence_digest=evidence.promotion_evidence_digest,
    )
    attribution = authority.review_attribution(
        profile_digest=profile.digest,
        action_type=evidence.action_type,
        action_type_version=evidence.action_type_version,
        action_type_digest=evidence.action_type_digest,
        fdai_revision=evidence.fdai_revision,
        scenario_set_version=evidence.scenario_set_version,
        evidence_digest=evidence.promotion_evidence_digest,
    )
    assert attribution is not None
    assert attribution["development_only"] is True
    assert attribution["production_ready"] is False
    assert attribution["reviewer_principal"] == profile.owner_principal


def test_owner_review_changes_only_profile_scoped_registry() -> None:
    (
        profile,
        source,
        request,
        binding,
        confirmation,
        grant,
        evidence,
        promotion_action,
    ) = _development_evidence()
    action = _action()
    clock = [NOW]
    authority = ReviewedReplayAuthority(
        (evidence,),
        development_profile=profile,
        development_binding_source=source,
        development_action_types={promotion_action.name: promotion_action},
        clock=lambda: NOW,
    )
    registry = ActionPromotionRegistry(
        receipt_verifier=ReviewedReplayReceiptVerifier(authority),
        clock=lambda: clock[0],
    )
    approval = authority.authorize_development(
        profile_digest=profile.digest,
        action_type=action,
        fdai_revision=evidence.fdai_revision,
        scenario_set_version=evidence.scenario_set_version,
        evidence_digest=evidence.promotion_evidence_digest,
        approved_at=NOW,
    )
    assert approval is not None

    record = registry.consider_development_promotion(
        profile=profile,
        confirmation=confirmation,
        binding_source=source,
        binding_request=request,
        binding_verification=evidence.development_binding_verification,
        grant=grant,
        action_type=action,
        approval=approval,
    )
    with pytest.raises(ValueError, match="approval does not match"):
        registry.consider_development_promotion(
            profile=profile,
            confirmation=confirmation,
            binding_source=source,
            binding_request=request,
            binding_verification=evidence.development_binding_verification,
            grant=grant,
            action_type=action.model_copy(update={"name": "ops.retargeted-action"}),
            approval=approval,
        )

    assert record.mode is Mode.ENFORCE
    assert record.development_only is True
    assert record.production_ready is False
    assert registry.development_mode_of(profile.digest, action.name) is Mode.ENFORCE
    assert registry.mode_of(action.name) is Mode.SHADOW
    runtime_action = _runtime_action(action_type=action.name).model_copy(
        update={
            "rollback_ref": RollbackRef(
                kind=RollbackKind.SCRIPTED,
                reference="rollback:scripted",
            )
        }
    )
    rule = _shipped_rules_by_id()["object-storage.owner-tag.required"]
    execution_binding = _binding(
        profile,
        action_type=action.name,
        action_type_digest="sha256:" + action_type_digest(action),
        action_id=str(runtime_action.action_id),
        target=runtime_action.target_resource_ref,
        params=runtime_action.params,
        idempotency_key=runtime_action.idempotency_key,
        rollback_contract=runtime_action.rollback_ref.kind.value,
    )
    execution_verification = _verification(execution_binding)
    execution_source = _BindingSource(execution_verification)
    gate = RiskGate(
        registry=registry,
        clock=lambda: clock[0],
        development_profile=profile,
        development_binding_source=execution_source,
        development_executor_principal=profile.executor_principal,
    )
    execution_confirmation = _confirmation(profile, execution_binding)
    execution_decision = evaluate_development_authority(
        profile,
        execution_confirmation,
        execution_verification,
        now=NOW,
        original_quorum=1,
    )
    assert execution_decision.grant is not None
    envelope = DevelopmentAuthorityEnvelope(
        confirmation=execution_confirmation,
        binding_verification=execution_verification,
        grant=execution_decision.grant,
    )
    scoped = gate.evaluate(
        action=runtime_action,
        rule=rule,
        action_type=action,
        development_authority=envelope,
    )
    cross_confirmation = execution_confirmation.model_copy(
        update={"profile_digest": "sha256:" + "f" * 64}
    )
    cross_profile_envelope = DevelopmentAuthorityEnvelope(
        confirmation=cross_confirmation,
        binding_verification=execution_verification,
        grant=execution_decision.grant.model_copy(
            update={
                "profile_digest": "sha256:" + "f" * 64,
                "confirmation_digest": cross_confirmation.digest,
            }
        ),
    )
    cross_profile = gate.evaluate(
        action=runtime_action,
        rule=rule,
        action_type=action,
        development_authority=cross_profile_envelope,
    )
    false_envelope = envelope.model_copy(
        update={
            "grant": envelope.grant.model_copy(
                update={"action_binding_digest": "sha256:" + "f" * 64}
            )
        }
    )
    unverified = gate.evaluate(
        action=runtime_action,
        rule=rule,
        action_type=action,
        development_authority=false_envelope,
    )
    absent_source = RiskGate(
        registry=registry,
        clock=lambda: clock[0],
        development_profile=profile,
        development_executor_principal=profile.executor_principal,
    ).evaluate(
        action=runtime_action,
        rule=rule,
        action_type=action,
        development_authority=envelope,
    )
    stale_source = RiskGate(
        registry=registry,
        clock=lambda: clock[0],
        development_profile=profile,
        development_binding_source=_BindingSource(
            execution_verification.model_copy(update={"expires_at": NOW})
        ),
        development_executor_principal=profile.executor_principal,
    ).evaluate(
        action=runtime_action,
        rule=rule,
        action_type=action,
        development_authority=envelope,
    )
    stale_profile = RiskGate(
        registry=registry,
        clock=lambda: clock[0],
        development_profile=profile.model_copy(update={"valid_until": NOW}),
        development_binding_source=execution_source,
        development_executor_principal=profile.executor_principal,
    ).evaluate(
        action=runtime_action,
        rule=rule,
        action_type=action,
        development_authority=envelope,
    )
    other_action = action.model_copy(update={"name": "ops.other-action"})
    cross_action = gate.evaluate(
        action=runtime_action,
        rule=rule,
        action_type=other_action,
        development_authority=envelope,
    )
    default = gate.evaluate(
        action=runtime_action,
        rule=rule,
        action_type=action,
    )
    assert scoped.outcome is RiskDecisionOutcome.AUTO
    assert scoped.effective_mode is Mode.ENFORCE
    assert cross_profile.effective_mode is Mode.SHADOW
    assert unverified.effective_mode is Mode.SHADOW
    assert "development_authority_unverified" in unverified.reasons
    assert absent_source.effective_mode is Mode.SHADOW
    assert "development_authority_unverified" in absent_source.reasons
    assert stale_source.effective_mode is Mode.SHADOW
    assert stale_profile.effective_mode is Mode.SHADOW
    assert cross_action.effective_mode is Mode.SHADOW
    assert default.effective_mode is Mode.SHADOW
    unified = evaluate_unified(
        event=Event(
            schema_version="1.0.0",
            event_id=runtime_action.event_id,
            idempotency_key=runtime_action.idempotency_key,
            correlation_id="development-risk",
            source="test",
            event_type="operator.requested",
            resource_ref=runtime_action.target_resource_ref,
            payload={"resource": {"props": {"environment": "dev"}}},
            detected_at=NOW,
            ingested_at=NOW,
            mode=Mode.SHADOW,
        ),
        action=runtime_action,
        rule=rule,
        action_type=action,
        table=load_risk_table(TABLE_PATH),
        risk_gate=gate,
        development_profile=profile,
        development_confirmation=execution_confirmation,
        development_binding_source=execution_source,
        development_binding_request=_binding_request(
            action_type=action.name,
            action_id=str(runtime_action.action_id),
            target=runtime_action.target_resource_ref,
            params=runtime_action.params,
            idempotency_key=runtime_action.idempotency_key,
            rollback_contract=runtime_action.rollback_ref.kind.value,
        ),
        development_evaluated_at=NOW,
    )
    assert unified.gate.effective_mode is Mode.ENFORCE
    assert unified.authority is not None
    assert unified.authority.development_authority is not None
    assert unified.authority.development_authority.eligible
    clock[0] = grant.valid_until
    expired = gate.evaluate(
        action=runtime_action,
        rule=rule,
        action_type=action,
        development_authority=envelope,
    )
    assert expired.effective_mode is Mode.SHADOW
    assert registry.development_mode_of(profile.digest, action.name) is Mode.SHADOW
    registry.demote_development(profile.digest, action.name)
    assert registry.development_mode_of(profile.digest, action.name) is Mode.SHADOW
