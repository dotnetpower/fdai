"""Risk admission for the full-authority development profile."""

from __future__ import annotations

from datetime import timedelta

import pytest
from fdai.core.measurement.operational_promotion import action_type_digest
from fdai.core.risk_gate import development_profile as _dev_profile
from fdai.core.risk_gate.approval_profile import OperatorPolicyOutcome
from fdai.core.risk_gate.authority import evaluate_execution_authority
from fdai.core.risk_gate.ceiling import AxisLevel
from fdai.core.risk_gate.gate import ActionModeRecord, PromotionMetrics
from fdai.core.risk_gate.operator_policy import (
    OperatorPolicyDecisionBinder,
    StateStoreOperatorPolicyRevisionReader,
    bounded_action_policy_input,
)
from fdai.core.risk_gate.risk_table import load_risk_table
from fdai.shared.contracts.development_authority import (
    development_promotion_target_digest,
    evaluate_development_authority,
)
from fdai.shared.contracts.models import (
    ActionBlastRadius,
    ActionInterface,
    BlastRadiusComputation,
    BlastRadiusScope,
    CeilingRole,
    DevelopmentAuthorityEnvelope,
    DevelopmentPromotionApproval,
    FullAuthorityDevelopmentProfile,
    Mode,
    OntologyActionType,
    Operation,
    PromotionGate,
    RegisteredDevelopmentAction,
    RollbackKind,
    RollbackRef,
    Tier,
)
from fdai.shared.providers.testing import InMemoryStateStore
from fdai_service_contracts.policy_administration import (
    AdmissionPolicyContent,
    PolicyKind,
    PolicyRevisionRecord,
    PolicyRevisionSignature,
    PolicyValidationResult,
    policy_content_digest,
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
from tests.core.risk_gate.test_gate import _action as _runtime_action


def _action(
    *,
    operation: Operation = Operation.RESTART,
    irreversible: bool = False,
    scope: BlastRadiusScope = BlastRadiusScope.RESOURCE,
    live_probe_ref: str | None = None,
    requires_inventory: bool = False,
    graph_derived: bool = False,
) -> OntologyActionType:
    return OntologyActionType(
        schema_version="1.0.0",
        name="ops.restart-service",
        version="1.0.0",
        operation=operation,
        interfaces=[
            ActionInterface.CONTROL_PLANE,
            *([ActionInterface.REQUIRES_INVENTORY_FRESH] if requires_inventory else []),
        ],
        rollback_contract=RollbackKind.SCRIPTED,
        irreversible=irreversible,
        promotion_gate=PromotionGate(
            min_shadow_days=1,
            min_samples=1,
            min_accuracy=0.9,
            max_policy_escapes=0,
        ),
        blast_radius=ActionBlastRadius(
            computation=(
                BlastRadiusComputation.GRAPH_DERIVED
                if graph_derived
                else BlastRadiusComputation.STATIC_ENUM
            ),
            static_bucket=None if graph_derived else scope,
            max_affected_resources=10 if graph_derived else None,
        ),
        live_probe_ref=live_probe_ref,
    )


def _evaluate(
    action: OntologyActionType,
    **overrides: object,
):  # type: ignore[no-untyped-def]
    digest = "sha256:" + action_type_digest(action)
    profile = _profile(resource_groups=(), action_type_digest=digest)
    binding = _binding(profile, action_type_digest=digest)
    confirmation = _confirmation(profile, binding)
    kwargs = {
        "tier": Tier.T0,
        "action_type": action,
        "table": load_risk_table(TABLE_PATH),
        "principal_role": CeilingRole.OWNER,
        "environment": "non-prod",
        "cost_impact_monthly": 10.0,
        "development_profile": profile,
        "development_confirmation": confirmation,
        "development_binding_source": _BindingSource(_verification(binding)),
        "development_binding_request": _binding_request(),
        "evaluated_at": NOW,
    }
    kwargs.update(overrides)
    return evaluate_execution_authority(**kwargs)  # type: ignore[arg-type]


def test_absent_profile_preserves_default_multi_operator_decision() -> None:
    action = _action(operation=Operation.DELETE, irreversible=True)
    baseline = evaluate_execution_authority(
        tier=Tier.T0,
        action_type=action,
        table=load_risk_table(TABLE_PATH),
        principal_role=CeilingRole.OWNER,
        environment="non-prod",
        cost_impact_monthly=10.0,
    )

    assert baseline.final_level is AxisLevel.ENFORCE_HIL
    assert baseline.quorum == 2
    assert baseline.original_quorum == 2
    assert baseline.development_authority is None


def test_exact_confirmation_routes_auto_and_category_only_deny_to_hil() -> None:
    ordinary = _evaluate(_action())
    subscription = _evaluate(_action(scope=BlastRadiusScope.SUBSCRIPTION))

    assert ordinary.original_level is AxisLevel.ENFORCE_AUTO
    assert ordinary.final_level is AxisLevel.ENFORCE_HIL
    assert subscription.original_level is AxisLevel.DENY
    assert subscription.table_verdict.rule_id == "deny-subscription-blast"
    assert subscription.final_level is AxisLevel.ENFORCE_HIL


def test_irreversible_risk_and_original_quorum_remain_audited() -> None:
    decision = _evaluate(_action(operation=Operation.DELETE, irreversible=True))
    audit = decision.as_audit_dict()

    assert decision.original_level is AxisLevel.ENFORCE_HIL
    assert decision.original_quorum == 2
    assert decision.quorum == 1
    assert audit["original_quorum"] == 2
    assert audit["effective_quorum"] == 1
    assert audit["development_authority"]["development_only"] is True


def test_policy_graph_kill_switch_and_degradation_stay_closed() -> None:
    assert _evaluate(_action(), policy_violation=True).is_denied
    assert _evaluate(_action(), graph_stale=True).is_denied
    assert _evaluate(_action(), kill_switch_engaged=True).is_denied
    assert _evaluate(_action(), system_degraded=True).is_denied


def test_stale_required_probe_and_changed_binding_stay_closed() -> None:
    assert _evaluate(_action(live_probe_ref="probe.current")).is_denied
    assert _evaluate(_action(requires_inventory=True), graph_stale=None).is_denied
    assert _evaluate(_action(graph_derived=True), graph_affected=None).is_denied
    assert _evaluate(
        _action(scope=BlastRadiusScope.SUBSCRIPTION),
        tier=Tier.T2,
    ).is_denied

    action = _action()
    digest = "sha256:" + action_type_digest(action)
    profile = _profile(resource_groups=(), action_type_digest=digest)
    original = _binding(profile, action_type_digest=digest)
    changed = _binding(profile, target="resource:changed", action_type_digest=digest)
    decision = evaluate_execution_authority(
        tier=Tier.T0,
        action_type=action,
        table=load_risk_table(TABLE_PATH),
        principal_role=CeilingRole.OWNER,
        environment="non-prod",
        cost_impact_monthly=10.0,
        development_profile=profile,
        development_confirmation=_confirmation(profile, original),
        development_binding_source=_BindingSource(_verification(changed)),
        development_binding_request=_binding_request(target="resource:changed"),
        evaluated_at=NOW,
    )

    assert decision.is_denied
    assert decision.development_authority is not None
    assert decision.development_authority.reason_code == "action_binding_mismatch"


def test_missing_source_and_stale_action_type_tuple_fail_closed() -> None:
    action = _action()
    current_digest = "sha256:" + action_type_digest(action)
    profile = _profile(resource_groups=(), action_type_digest=current_digest)
    current = _binding(profile, action_type_digest=current_digest)
    confirmation = _confirmation(profile, current)
    missing = evaluate_execution_authority(
        tier=Tier.T0,
        action_type=action,
        table=load_risk_table(TABLE_PATH),
        principal_role=CeilingRole.OWNER,
        environment="non-prod",
        development_profile=profile,
        development_confirmation=confirmation,
        development_binding_request=_binding_request(),
        evaluated_at=NOW,
    )
    stale_binding = _binding(profile, action_type_digest="sha256:" + "f" * 64)
    stale = evaluate_execution_authority(
        tier=Tier.T0,
        action_type=action,
        table=load_risk_table(TABLE_PATH),
        principal_role=CeilingRole.OWNER,
        environment="non-prod",
        development_profile=profile,
        development_confirmation=_confirmation(profile, stale_binding),
        development_binding_source=_BindingSource(_verification(stale_binding)),
        development_binding_request=_binding_request(),
        evaluated_at=NOW,
    )
    assert missing.is_denied
    assert missing.development_authority is not None
    assert missing.development_authority.reason_code == "binding_source_rejected"
    assert stale.is_denied
    assert stale.development_authority is not None
    assert stale.development_authority.reason_code == "current_action_type_mismatch"


def test_development_profile_promotion_demotion_and_mode_lifecycle() -> None:
    action = _action()
    action_digest = "sha256:" + action_type_digest(action)
    promo_digest = "sha256:" + "a" * 64
    base_profile = _profile(resource_groups=(), action_type_digest=action_digest)
    profile = FullAuthorityDevelopmentProfile.model_validate(
        {
            **base_profile.model_dump(mode="json"),
            "registered_actions": [
                RegisteredDevelopmentAction(
                    action_type="governance.promote-action-type",
                    version="1.0.0",
                    action_type_digest=promo_digest,
                ).model_dump(mode="json"),
                RegisteredDevelopmentAction(
                    action_type=action.name,
                    version=action.version,
                    action_type_digest=action_digest,
                ).model_dump(mode="json"),
            ],
        }
    )
    replay_digest = "sha256:" + "b" * 64
    evidence_digest = "sha256:" + "c" * 64
    source_rev = profile.source_revision
    scenario_ver = "v2026.09"
    target_digest = development_promotion_target_digest(
        action_type=action.name,
        action_type_version=action.version,
        action_type_digest=action_digest,
        reviewed_replay_digest=replay_digest,
        source_revision=source_rev,
        scenario_set_version=scenario_ver,
        promotion_evidence_digest=evidence_digest,
    )
    promo_params: dict[str, object] = {
        "action_type": action.name,
        "action_type_version": action.version,
        "action_type_digest": action_digest,
        "reviewed_replay_digest": replay_digest,
        "source_revision": source_rev,
        "scenario_set_version": scenario_ver,
        "promotion_evidence_digest": evidence_digest,
    }
    binding = _binding(
        profile,
        action_type="governance.promote-action-type",
        action_type_digest=promo_digest,
        params=promo_params,
    )
    verification = _verification(binding)
    source = _BindingSource(verification)
    request = _binding_request(
        action_type="governance.promote-action-type",
        params=promo_params,
    )
    confirmation = _confirmation(profile, binding)
    decision = evaluate_development_authority(
        profile, confirmation, verification, now=NOW, original_quorum=2
    )
    assert decision.grant is not None
    grant = decision.grant
    approval = DevelopmentPromotionApproval(
        profile_digest=grant.profile_digest,
        confirmation_digest=grant.confirmation_digest,
        binding_verification_digest=verification.digest,
        promotion_action_type="governance.promote-action-type",
        target_action_type=action.name,
        target_action_type_version=action.version,
        target_action_type_digest=action_digest,
        promotion_target_digest=target_digest,
        reviewed_replay_digest=replay_digest,
        promotion_evidence_digest=evidence_digest,
        fdai_revision=source_rev,
        scenario_set_version=scenario_ver,
        review_ref="review:dev-1",
        reviewer_principal=grant.owner_principal,
        approved_at=NOW,
        valid_until=grant.valid_until,
    )
    records: dict[tuple[str, str], ActionModeRecord] = {}
    assert (
        _dev_profile.mode_of(
            records,
            profile_digest=grant.profile_digest,
            action_type=action.name,
            clock=lambda: NOW,
        )
        is Mode.SHADOW
    )
    assert (
        _dev_profile.record_of(
            records, profile_digest=grant.profile_digest, action_type=action.name
        )
        is None
    )

    with pytest.raises(ValueError, match="binding changed"):
        _dev_profile.consider_promotion(
            records,
            record_factory=ActionModeRecord,
            clock=lambda: NOW,
            profile=profile,
            confirmation=confirmation,
            binding_source=source,
            binding_request=request,
            binding_verification=verification.model_copy(update={"source_revision": "other"}),
            grant=grant,
            action_type=action,
            approval=approval,
        )

    with pytest.raises(ValueError, match="authority is ineligible"):
        _dev_profile.consider_promotion(
            records,
            record_factory=ActionModeRecord,
            clock=lambda: NOW,
            profile=profile,
            confirmation=confirmation,
            binding_source=source,
            binding_request=request,
            binding_verification=verification,
            grant=grant.model_copy(update={"owner_principal": "human:other"}),
            action_type=action,
            approval=approval,
        )

    with pytest.raises(ValueError, match="approval does not match"):
        _dev_profile.consider_promotion(
            records,
            record_factory=ActionModeRecord,
            clock=lambda: NOW,
            profile=profile,
            confirmation=confirmation,
            binding_source=source,
            binding_request=request,
            binding_verification=verification,
            grant=grant,
            action_type=action.model_copy(update={"name": "ops.other"}),
            approval=approval,
        )

    bad_metrics = PromotionMetrics(
        action_type="ops.other", shadow_days=1, samples=1, accuracy=1.0, policy_escapes=0
    )
    with pytest.raises(ValueError, match="metrics action type does not match"):
        _dev_profile.consider_promotion(
            records,
            record_factory=ActionModeRecord,
            clock=lambda: NOW,
            profile=profile,
            confirmation=confirmation,
            binding_source=source,
            binding_request=request,
            binding_verification=verification,
            grant=grant,
            action_type=action,
            approval=approval,
            metrics=bad_metrics,
        )

    good_metrics = PromotionMetrics(
        action_type=action.name, shadow_days=1, samples=1, accuracy=1.0, policy_escapes=0
    )
    first = _dev_profile.consider_promotion(
        records,
        record_factory=ActionModeRecord,
        clock=lambda: NOW,
        profile=profile,
        confirmation=confirmation,
        binding_source=source,
        binding_request=request,
        binding_verification=verification,
        grant=grant,
        action_type=action,
        approval=approval,
        metrics=good_metrics,
    )
    later = NOW + timedelta(seconds=10)
    second = _dev_profile.consider_promotion(
        records,
        record_factory=ActionModeRecord,
        clock=lambda: later,
        profile=profile,
        confirmation=confirmation,
        binding_source=source,
        binding_request=request,
        binding_verification=verification,
        grant=grant,
        action_type=action,
        approval=approval,
    )
    assert second.promoted_at == first.promoted_at
    assert (
        _dev_profile.mode_of(
            records,
            profile_digest=grant.profile_digest,
            action_type=action.name,
            clock=lambda: NOW,
        )
        is Mode.ENFORCE
    )
    assert (
        _dev_profile.mode_of(
            records,
            profile_digest=grant.profile_digest,
            action_type=action.name,
            clock=lambda: grant.valid_until,
        )
        is Mode.SHADOW
    )
    assert (
        _dev_profile.record_of(
            records, profile_digest=grant.profile_digest, action_type=action.name
        )
        == second
    )

    with pytest.raises(ValueError, match="identity MUST be complete"):
        _dev_profile.demote(
            records,
            record_factory=ActionModeRecord,
            clock=lambda: later,
            profile_digest="",
            action_type_name=action.name,
        )
    demoted = _dev_profile.demote(
        records,
        record_factory=ActionModeRecord,
        clock=lambda: later,
        profile_digest=grant.profile_digest,
        action_type_name=action.name,
    )
    assert demoted.mode is Mode.SHADOW
    assert demoted.demoted_at == later
    demoted_again = _dev_profile.demote(
        records,
        record_factory=ActionModeRecord,
        clock=lambda: later,
        profile_digest=grant.profile_digest,
        action_type_name=action.name,
    )
    assert demoted_again.demoted_at is None


def test_current_profile_digest_revalidates_all_guards() -> None:
    action_type = _action()
    digest = "sha256:" + action_type_digest(action_type)
    profile = _profile(resource_groups=(), action_type_digest=digest)
    runtime_action = _runtime_action(action_type=action_type.name).model_copy(
        update={
            "target_resource_ref": "resource:one",
            "params": {"restart": True},
            "mode": Mode.ENFORCE,
            "rollback_ref": RollbackRef(kind=RollbackKind.SCRIPTED, reference="rb:1"),
            "idempotency_key": "stable-action-one",
        }
    )
    binding = _binding(
        profile,
        action_id=str(runtime_action.action_id),
        target=runtime_action.target_resource_ref,
        params=runtime_action.params,
        action_type_digest=digest,
        idempotency_key=runtime_action.idempotency_key,
        rollback_contract=runtime_action.rollback_ref.kind.value,
    )
    verification = _verification(binding)
    source = _BindingSource(verification)
    confirmation = _confirmation(profile, binding)
    decision = evaluate_development_authority(
        profile, confirmation, verification, now=NOW, original_quorum=1
    )
    assert decision.grant is not None
    envelope = DevelopmentAuthorityEnvelope(
        confirmation=confirmation,
        binding_verification=verification,
        grant=decision.grant,
    )

    assert (
        _dev_profile.current_profile_digest(
            envelope,
            action=runtime_action,
            action_type=action_type,
            profile=profile,
            binding_source=source,
            executor_principal=profile.executor_principal,
            clock=lambda: NOW,
        )
        == profile.digest
    )

    class _BadEnvelope:
        def model_dump(self, *, mode: str = "python") -> dict[str, object]:
            return {"invalid": mode}

    assert (
        _dev_profile.current_profile_digest(
            _BadEnvelope(),  # type: ignore[arg-type]
            action=runtime_action,
            action_type=action_type,
            profile=profile,
            binding_source=source,
            executor_principal=profile.executor_principal,
            clock=lambda: NOW,
        )
        is None
    )
    assert (
        _dev_profile.current_profile_digest(
            envelope,
            action=runtime_action,
            action_type=action_type,
            profile=None,
            binding_source=source,
            executor_principal=profile.executor_principal,
            clock=lambda: NOW,
        )
        is None
    )
    assert (
        _dev_profile.current_profile_digest(
            envelope,
            action=runtime_action,
            action_type=action_type,
            profile=profile,
            binding_source=source,
            executor_principal=profile.executor_principal,
            clock=lambda: NOW.replace(tzinfo=None),
        )
        is None
    )
    assert (
        _dev_profile.current_profile_digest(
            envelope,
            action=runtime_action.model_copy(update={"target_resource_ref": "resource:other"}),
            action_type=action_type,
            profile=profile,
            binding_source=source,
            executor_principal=profile.executor_principal,
            clock=lambda: NOW,
        )
        is None
    )
    assert (
        _dev_profile.current_profile_digest(
            envelope.model_copy(
                update={
                    "binding_verification": verification.model_copy(
                        update={"source_revision": "tampered"}
                    )
                }
            ),
            action=runtime_action,
            action_type=action_type,
            profile=profile,
            binding_source=source,
            executor_principal=profile.executor_principal,
            clock=lambda: NOW,
        )
        is None
    )
    assert (
        _dev_profile.current_profile_digest(
            envelope.model_copy(
                update={
                    "grant": decision.grant.model_copy(update={"owner_principal": "human:other"})
                }
            ),
            action=runtime_action,
            action_type=action_type,
            profile=profile,
            binding_source=source,
            executor_principal=profile.executor_principal,
            clock=lambda: NOW,
        )
        is None
    )
    assert (
        _dev_profile.current_profile_digest(
            envelope,
            action=runtime_action,
            action_type=action_type.model_copy(update={"version": "2.0.0"}),
            profile=profile,
            binding_source=source,
            executor_principal=profile.executor_principal,
            clock=lambda: NOW,
        )
        is None
    )


async def test_operator_policy_reader_binder_and_bounded_input() -> None:
    with pytest.raises(ValueError, match="timeout"):
        OperatorPolicyDecisionBinder(reader=None, evaluator=None, timeout_seconds=0)  # type: ignore[arg-type]
    assert (
        bounded_action_policy_input(
            action_type="remediate.x",
            resource_id="res-1",
            environment="prod",
            mode="enforce",
            policy_violation=False,
            irreversible=True,
            operation="delete",
        )["operation"]
        == "delete"
    )

    class _Verifier:
        async def verify_policy_revision_signature(self, record: PolicyRevisionRecord) -> bool:
            return (
                record.signature is not None
                and record.signature.signature_base64 == "signature-good"
            )

    store = InMemoryStateStore()
    reader = StateStoreOperatorPolicyRevisionReader(store, signature_verifier=_Verifier())
    assert await reader.active_revision_id(PolicyKind.ADMISSION) is None
    assert await reader.revision(policy_kind=PolicyKind.ADMISSION, revision_id="missing") is None

    adm_content = AdmissionPolicyContent(
        rego="package fdai.admission\ndefault allow := true\n",
    )
    adm_record = PolicyRevisionRecord(
        revision_id="admission:r1",
        policy_kind=PolicyKind.ADMISSION,
        content_digest=policy_content_digest(adm_content),
        content=adm_content,
        signature_ref="sig:adm",
        signature=PolicyRevisionSignature(
            key_id="https://fdai-example.vault.azure.net/keys/policy-signing/v1",
            algorithm="RS256",
            signature_base64="signature-good",
        ),
        author_principal="admin@example.com",
        reason="Admission policy test.",
        created_at=NOW,
        validation=PolicyValidationResult(
            rego_valid=True,
            release_maximums_valid=True,
            policy_tests_valid=True,
            validation_digest="sha256:" + "1" * 64,
        ),
        diff_digest="sha256:" + "2" * 64,
    )
    rev_key = "policy_revision:admission:admission:r1"
    await store.write_state(rev_key, adm_record.model_dump(mode="json"))
    assert (
        await StateStoreOperatorPolicyRevisionReader(store).revision(
            policy_kind=PolicyKind.ADMISSION, revision_id="admission:r1"
        )
        is None
    )

    class _Eval:
        def __init__(self, fail: bool = False) -> None:
            self.fail = fail

        async def evaluate(
            self, *, revision: object, action_input: object
        ) -> OperatorPolicyOutcome:
            if self.fail:
                raise RuntimeError("opa failed")
            return OperatorPolicyOutcome.ALLOW

    binder = OperatorPolicyDecisionBinder(reader=reader, evaluator=_Eval())
    assert await binder.bind(action_input={}) is None

    await store.write_state("policy_activation:admission", {"revision_id": "missing"})
    missing_bound = await binder.bind(action_input={})
    assert missing_bound is not None
    assert missing_bound.outcome is OperatorPolicyOutcome.REQUIRE_APPROVAL

    await store.write_state("policy_activation:admission", {"revision_id": "admission:r1"})
    ok_bound = await binder.bind(action_input={"action_type": "x"})
    assert ok_bound is not None and ok_bound.outcome is OperatorPolicyOutcome.ALLOW

    bad_sig = adm_record.model_dump(mode="json")
    bad_sig["signature"]["signature_base64"] = "bad"
    await store.write_state(rev_key, bad_sig)
    assert (
        await reader.revision(policy_kind=PolicyKind.ADMISSION, revision_id="admission:r1") is None
    )

    await store.write_state(rev_key, adm_record.model_dump(mode="json"))
    err_bound = await OperatorPolicyDecisionBinder(reader=reader, evaluator=_Eval(fail=True)).bind(
        action_input={}
    )
    assert err_bound is not None and err_bound.revision_id == "evaluation-error"
