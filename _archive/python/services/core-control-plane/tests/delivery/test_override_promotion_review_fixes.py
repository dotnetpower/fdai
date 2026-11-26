import sys
from datetime import timedelta
from pathlib import Path

import pytest
from fdai_service_contracts.approval_profile import (
    ApprovalProfileKind,
    ApprovalProfileRevision,
    approval_profile_policy_digest,
)

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_promotion_executor as base
from fdai.core.rbac.roles import Role
from fdai.delivery.persistence import (
    StateStoreActionPromotionRegistry,
    StateStoreOperatorOverrideAuthorityVerifier,
)
from fdai.delivery.promotion import (
    GovernancePromotionDispatcher,
    OperationalPromotionDirectApiExecutor,
    OperatorOverridePromotionDirectApiExecutor,
    StateStorePromotionAttestationStore,
)
from fdai.delivery.promotion_attestation import promotion_attestation_digest
from fdai.rule_catalog.schema.governance_review_authority import (
    GovernanceApproval,
    GovernanceChangeClass,
    GovernancePrincipal,
    GovernanceReviewRequest,
)
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.direct_api import (
    DirectApiOutcome,
    DirectApiPreconditionError,
    DirectApiRetryableError,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore


class _FailingFinalizeStore(StateStorePromotionAttestationStore):
    async def finalize(self, *args: object, **kwargs: object) -> None:
        del args, kwargs
        raise RuntimeError("simulated finalize failure")


class _FailAfterReserveStateStore(InMemoryStateStore):
    def __init__(self) -> None:
        super().__init__()
        self.fail_after_reserved_write = False
        self.fail_reads = False

    async def read_state(self, key: str):  # type: ignore[no-untyped-def]
        if self.fail_reads:
            raise RuntimeError("simulated store outage")
        return await super().read_state(key)

    async def compare_and_set_state_with_audit(self, key, value, *, expected_revision, audit_entry):  # type: ignore[no-untyped-def]
        applied = await super().compare_and_set_state_with_audit(
            key,
            value,
            expected_revision=expected_revision,
            audit_entry=audit_entry,
        )
        if applied and self.fail_after_reserved_write and value.get("state") == "reserved":
            self.fail_reads = True
        return applied


def _single_operator_profile(revision_id: str) -> ApprovalProfileRevision:
    payload = {
        "revision_id": revision_id,
        "approval_profile": ApprovalProfileKind.SINGLE_OPERATOR_PRODUCTION.value,
        "executor_principal": "thor-executor@example.com",
        "effective_from": base._NOW.isoformat(),
        "operator_principal": base._OPERATOR_A,
    }
    return ApprovalProfileRevision(
        revision_id=revision_id,
        approval_profile=ApprovalProfileKind.SINGLE_OPERATOR_PRODUCTION,
        executor_principal="thor-executor@example.com",
        effective_from=base._NOW,
        operator_principal=base._OPERATOR_A,
        policy_digest=approval_profile_policy_digest(payload),
    )


async def _apply_override(
    *,
    store: InMemoryStateStore,
    profile: ApprovalProfileRevision | None,
) -> str:
    action_types = base._action_types()
    target = action_types["remediate.tag-add"]
    registry = StateStoreActionPromotionRegistry(
        store=store,
        override_authority_verifier=StateStoreOperatorOverrideAuthorityVerifier(store),
    )
    executor = OperatorOverridePromotionDirectApiExecutor(
        action_types=action_types,
        registry=registry,
        clock=lambda: base._NOW,
    )
    attestations = StateStorePromotionAttestationStore(store)
    dispatcher = GovernancePromotionDispatcher(
        executor,
        attestation_store=attestations,
        active_approval_profile=profile,
    )
    if profile is None:
        draft = base._override_request(target.name)
        attestation = base._override_attestation(draft)
    else:
        approval = GovernanceApproval(
            approver=GovernancePrincipal(
                oid=base._OPERATOR_A,
                roles=frozenset({Role.APPROVER}),
            ),
            reviewed_revision=base._REVISION,
            approved_at=base._NOW,
            phishing_resistant=True,
        )
        draft = base._override_request(target.name, operator_principal=base._OPERATOR_A)
        attestation = base._override_attestation(
            draft,
            approvals=(approval,),
            approval_profile=profile,
            author_oid=base._OPERATOR_A,
        )
    digest = promotion_attestation_digest(attestation)
    request = base._override_request(
        target.name,
        operator_principal=base._OPERATOR_A if profile is not None else base._OPERATOR_B,
        approval_receipt_digest=digest,
    )
    await attestations.save(attestation)
    await dispatcher.execute(request)
    return target.name


async def test_retry_after_finalize_failure_and_profile_change_consumes_attestation() -> None:
    store = InMemoryStateStore()
    action_types = base._action_types()
    target = action_types["remediate.tag-add"]
    first_profile = _single_operator_profile("single-profile-v1")
    next_profile = _single_operator_profile("single-profile-v2")
    registry = StateStoreActionPromotionRegistry(
        store=store,
        override_authority_verifier=StateStoreOperatorOverrideAuthorityVerifier(store),
    )
    first_executor = OperatorOverridePromotionDirectApiExecutor(
        action_types=action_types,
        registry=registry,
        clock=lambda: base._NOW,
    )
    first_store = _FailingFinalizeStore(store, clock=lambda: base._NOW)
    first_dispatcher = GovernancePromotionDispatcher(
        first_executor,
        attestation_store=first_store,
        active_approval_profile=first_profile,
    )
    approval = GovernanceApproval(
        approver=GovernancePrincipal(oid=base._OPERATOR_A, roles=frozenset({Role.APPROVER})),
        reviewed_revision=base._REVISION,
        approved_at=base._NOW,
        phishing_resistant=True,
    )
    draft = base._override_request(target.name, operator_principal=base._OPERATOR_A)
    attestation = base._override_attestation(
        draft,
        approvals=(approval,),
        approval_profile=first_profile,
        author_oid=base._OPERATOR_A,
    )
    digest = promotion_attestation_digest(attestation)
    request = base._override_request(
        target.name,
        operator_principal=base._OPERATOR_A,
        approval_receipt_digest=digest,
    )
    await first_store.save(attestation)

    first = await first_dispatcher.execute(request)
    assert first.outcome is DirectApiOutcome.SUCCEEDED
    reserved = await store.read_state(f"governance-promotion-attestation:{request.idempotency_key}")
    assert reserved is not None
    assert reserved["state"] == "reserved"

    later = base._NOW + timedelta(seconds=301)
    retry_registry = StateStoreActionPromotionRegistry(
        store=store,
        override_authority_verifier=StateStoreOperatorOverrideAuthorityVerifier(store),
    )
    retry_executor = OperatorOverridePromotionDirectApiExecutor(
        action_types=action_types,
        registry=retry_registry,
        clock=lambda: later,
    )
    retry_store = StateStorePromotionAttestationStore(store, clock=lambda: later)
    retry_dispatcher = GovernancePromotionDispatcher(
        retry_executor,
        attestation_store=retry_store,
        active_approval_profile=next_profile,
    )

    replay = await retry_dispatcher.execute(request)

    assert replay.detail == "verified operator override promotion already applied"
    consumed = await store.read_state(f"governance-promotion-attestation:{request.idempotency_key}")
    assert consumed is not None
    assert consumed["state"] == "consumed"
    assert retry_registry.mode_of(target.name) is Mode.ENFORCE
    await retry_registry.refresh_for_update(target.name)
    retry_registry.demote(target.name)
    await retry_registry.persist(target.name)
    assert retry_registry.mode_of(target.name) is Mode.SHADOW


async def test_retry_store_outage_keeps_retryable_restore_path() -> None:
    store = _FailAfterReserveStateStore()
    action_types = base._action_types()
    target = action_types["remediate.tag-add"]
    first_profile = _single_operator_profile("single-profile-v1")
    next_profile = _single_operator_profile("single-profile-v2")
    registry = StateStoreActionPromotionRegistry(
        store=store,
        override_authority_verifier=StateStoreOperatorOverrideAuthorityVerifier(store),
    )
    first_store = _FailingFinalizeStore(store, clock=lambda: base._NOW)
    first_dispatcher = GovernancePromotionDispatcher(
        OperatorOverridePromotionDirectApiExecutor(
            action_types=action_types,
            registry=registry,
            clock=lambda: base._NOW,
        ),
        attestation_store=first_store,
        active_approval_profile=first_profile,
    )
    approval = GovernanceApproval(
        approver=GovernancePrincipal(oid=base._OPERATOR_A, roles=frozenset({Role.APPROVER})),
        reviewed_revision=base._REVISION,
        approved_at=base._NOW,
        phishing_resistant=True,
    )
    draft = base._override_request(target.name, operator_principal=base._OPERATOR_A)
    attestation = base._override_attestation(
        draft,
        approvals=(approval,),
        approval_profile=first_profile,
        author_oid=base._OPERATOR_A,
    )
    digest = promotion_attestation_digest(attestation)
    request = base._override_request(
        target.name,
        operator_principal=base._OPERATOR_A,
        approval_receipt_digest=digest,
    )
    await first_store.save(attestation)
    await first_dispatcher.execute(request)

    later = base._NOW + timedelta(seconds=301)
    retry_dispatcher = GovernancePromotionDispatcher(
        OperatorOverridePromotionDirectApiExecutor(
            action_types=action_types,
            registry=StateStoreActionPromotionRegistry(
                store=store,
                override_authority_verifier=StateStoreOperatorOverrideAuthorityVerifier(store),
            ),
            clock=lambda: later,
        ),
        attestation_store=StateStorePromotionAttestationStore(store, clock=lambda: later),
        active_approval_profile=next_profile,
    )
    store.fail_after_reserved_write = True

    with pytest.raises(DirectApiRetryableError, match="active profile"):
        await retry_dispatcher.execute(request)


async def test_override_promotion_execute_uses_reserved_attestation_digest() -> None:
    action_types = base._action_types()
    target = action_types["remediate.tag-add"]
    store = InMemoryStateStore()
    registry = StateStoreActionPromotionRegistry(
        store=store,
        override_authority_verifier=StateStoreOperatorOverrideAuthorityVerifier(store),
    )
    executor = OperatorOverridePromotionDirectApiExecutor(
        action_types=action_types,
        registry=registry,
        clock=lambda: base._NOW,
    )
    attestations = StateStorePromotionAttestationStore(store)
    dispatcher = GovernancePromotionDispatcher(executor, attestation_store=attestations)
    draft = base._override_request(target.name)
    attestation = base._override_attestation(draft)
    digest = promotion_attestation_digest(attestation)
    request = base._override_request(target.name, approval_receipt_digest=digest)

    await attestations.save(attestation)
    result = await dispatcher.execute(request)

    assert result.outcome is DirectApiOutcome.SUCCEEDED
    stored = await store.read_state(f"governance-promotion-attestation:{request.idempotency_key}")
    assert stored is not None
    assert stored["state"] == "consumed"
    assert stored["approval_receipt_digest"] == digest
    assert registry.mode_of(target.name) is Mode.ENFORCE


@pytest.mark.parametrize("profile", [None, _single_operator_profile("single-profile-v1")])
async def test_applied_override_survives_later_profile_change(
    profile: ApprovalProfileRevision | None,
) -> None:
    store = InMemoryStateStore()
    target_name = await _apply_override(store=store, profile=profile)

    refreshed = StateStoreActionPromotionRegistry(
        store=store,
        override_authority_verifier=StateStoreOperatorOverrideAuthorityVerifier(store),
    )
    await refreshed.refresh(target_name)
    await refreshed.refresh_for_update(target_name)

    assert refreshed.mode_of(target_name) is Mode.ENFORCE
    assert refreshed.read_model(target_name)["promotion_kind"] == "operator_override"

    recalled = StateStoreActionPromotionRegistry(
        store=store,
        override_authority_verifier=StateStoreOperatorOverrideAuthorityVerifier(store),
    )
    await recalled.recall_capability(
        target_name,
        reason="vendor capability recall",
        recalled_at=base._NOW,
    )
    assert recalled.mode_of(target_name) is Mode.SHADOW

    demoted = StateStoreActionPromotionRegistry(
        store=store,
        override_authority_verifier=StateStoreOperatorOverrideAuthorityVerifier(store),
    )
    await demoted.refresh_for_update(target_name)
    demoted.demote(target_name)
    await demoted.persist(target_name)
    assert demoted.mode_of(target_name) is Mode.SHADOW

    fresh = StateStoreActionPromotionRegistry(
        store=store,
        override_authority_verifier=StateStoreOperatorOverrideAuthorityVerifier(store),
    )
    await fresh.refresh(target_name)
    assert fresh.mode_of(target_name) is Mode.SHADOW


async def test_forged_override_record_without_attestation_still_clamps_to_shadow() -> None:
    action_types = base._action_types()
    target = action_types["remediate.tag-add"]
    store = InMemoryStateStore()
    assert target.provenance is not None
    await store.write_state(
        f"action_promotion:{target.name}",
        {
            "schema_version": "1.0.0",
            "action_type": target.name,
            "mode": "enforce",
            "promotion_kind": "operator_override",
            "promoted_at": base._NOW.isoformat(),
            "demoted_at": None,
            "promotion_evidence_digest": "e" * 64,
            "action_type_version": target.version,
            "action_type_digest": target.provenance.content_hash.removeprefix("sha256:"),
            "gate_status": "failed",
            "gate_evidence_digest": "e" * 64,
            "approval_receipt_digest": base._APPROVAL,
            "operator_principal": "operator@example.com",
            "override_reason": "Operator accepted bounded risk.",
            "override_recorded_at": base._NOW.isoformat(),
            "metrics": None,
        },
    )
    registry = StateStoreActionPromotionRegistry(
        store=store,
        override_authority_verifier=StateStoreOperatorOverrideAuthorityVerifier(store),
    )

    await registry.refresh(target.name)

    assert registry.mode_of(target.name) is Mode.SHADOW


async def test_shortcut_refuses_invalid_attestation_reusing_applied_digest() -> None:
    store = InMemoryStateStore()
    first_profile = _single_operator_profile("single-profile-v1")
    target_name = await _apply_override(store=store, profile=first_profile)
    action_types = base._action_types()
    target = action_types[target_name]
    invalid_profile = _single_operator_profile("forged-profile")
    invalid_request = base._override_request(target.name, operator_principal=base._OPERATOR_A)
    invalid_attestation = base._override_attestation(
        invalid_request,
        approvals=(
            GovernanceApproval(
                approver=GovernancePrincipal(
                    oid=base._OPERATOR_A,
                    roles=frozenset({Role.APPROVER}),
                ),
                reviewed_revision=base._REVISION,
                approved_at=base._NOW,
                phishing_resistant=True,
            ),
        ),
        approval_profile=invalid_profile,
        author_oid=base._OPERATOR_A,
    )
    applied = await store.read_state(f"action_promotion:{target.name}")
    assert applied is not None
    digest = applied["approval_receipt_digest"]
    invalid_request = base._override_request(
        target.name,
        operator_principal=base._OPERATOR_A,
        approval_receipt_digest=str(digest),
    )

    with pytest.raises(DirectApiPreconditionError, match="active profile"):
        await GovernancePromotionDispatcher(
            OperatorOverridePromotionDirectApiExecutor(
                action_types=action_types,
                registry=StateStoreActionPromotionRegistry(
                    store=store,
                    override_authority_verifier=StateStoreOperatorOverrideAuthorityVerifier(store),
                ),
                clock=lambda: base._NOW,
            ),
            active_approval_profile=None,
        ).dispatch(invalid_request, attestation=invalid_attestation)


async def test_shortcut_refuses_wrong_change_class_reusing_applied_digest() -> None:
    store = InMemoryStateStore()
    target_name = await _apply_override(store=store, profile=None)
    action_types = base._action_types()
    target = action_types[target_name]
    applied = await store.read_state(f"action_promotion:{target.name}")
    assert applied is not None
    digest = str(applied["approval_receipt_digest"])
    request = base._override_request(target.name, approval_receipt_digest=digest)
    forged_profile = _single_operator_profile("wrong-class-profile")
    attestation = base.GovernancePromotionAttestation(
        review=GovernanceReviewRequest(
            change_class=GovernanceChangeClass.OVERRIDE,
            author=GovernancePrincipal(
                oid=base._OPERATOR_A,
                roles=frozenset({Role.APPROVER}),
            ),
            head_revision=base._REVISION,
            head_committed_at=base._NOW,
            approvals=(
                GovernanceApproval(
                    approver=GovernancePrincipal(
                        oid=base._OPERATOR_B,
                        roles=frozenset({Role.APPROVER}),
                    ),
                    reviewed_revision=base._REVISION,
                    approved_at=base._NOW,
                    phishing_resistant=True,
                ),
                GovernanceApproval(
                    approver=GovernancePrincipal(
                        oid=base._OPERATOR_C,
                        roles=frozenset({Role.APPROVER}),
                    ),
                    reviewed_revision=base._REVISION,
                    approved_at=base._NOW,
                    phishing_resistant=True,
                ),
            ),
            approval_profile=forged_profile,
        ),
        action_type_id=target.name,
        fdai_revision=base._REVISION,
        scenario_set_version=base._SCENARIO,
        evidence_digest=base._EVIDENCE,
        idempotency_key=request.idempotency_key,
        nonce="wrong-class",
        request_fingerprint=base.promotion_request_fingerprint(request),
    )

    with pytest.raises(DirectApiPreconditionError, match="active profile"):
        await GovernancePromotionDispatcher(
            OperatorOverridePromotionDirectApiExecutor(
                action_types=action_types,
                registry=StateStoreActionPromotionRegistry(
                    store=store,
                    override_authority_verifier=StateStoreOperatorOverrideAuthorityVerifier(store),
                ),
                clock=lambda: base._NOW,
            ),
        ).dispatch(request, attestation=attestation)


def test_override_target_eligibility_accepts_real_catalog_safeguard_declarations() -> None:
    from fdai.delivery.promotion_override import _validate_target_override_eligible
    from fdai.shared.providers.direct_api import DirectApiPreconditionError

    refused: dict[str, str] = {}
    for action_type in base._action_types().values():
        try:
            _validate_target_override_eligible(action_type)
        except DirectApiPreconditionError as exc:
            refused[action_type.name] = str(exc)

    assert refused == {
        "remediate.azure-policy-managed": (
            "override promotion target ActionType release maximum is shadow_only"
        )
    }


def test_release_maximum_uses_runtime_defaults_for_undeclared_tiers() -> None:
    from fdai.delivery.promotion_override import _validate_target_override_eligible

    action_type = base._action_types()["remediate.azure-policy-managed"]
    assert action_type.ceiling_by_tier is not None
    partial = action_type.model_copy(
        update={
            "ceiling_by_tier": action_type.ceiling_by_tier.model_copy(
                update={"t0": None, "t1": None}
            )
        }
    )

    _validate_target_override_eligible(partial)


async def test_override_promotion_refuses_attested_profile_when_runtime_profile_differs() -> None:
    action_types = base._action_types()
    target = action_types["remediate.tag-add"]
    registry = StateStoreActionPromotionRegistry(
        store=InMemoryStateStore(),
        override_authority_verifier=base._OverrideAuthorityVerifier(),
    )
    executor = OperatorOverridePromotionDirectApiExecutor(
        action_types=action_types,
        registry=registry,
        clock=lambda: base._NOW,
    )
    profile = ApprovalProfileRevision(
        revision_id="self-made",
        approval_profile=ApprovalProfileKind.SINGLE_OPERATOR_PRODUCTION,
        executor_principal="thor-executor@example.com",
        effective_from=base._NOW,
        operator_principal=base._OPERATOR_A,
        policy_digest=approval_profile_policy_digest(
            {
                "revision_id": "self-made",
                "approval_profile": ApprovalProfileKind.SINGLE_OPERATOR_PRODUCTION.value,
                "executor_principal": "thor-executor@example.com",
                "effective_from": base._NOW.isoformat(),
                "operator_principal": base._OPERATOR_A,
            }
        ),
    )
    request = base._override_request(target.name, operator_principal=base._OPERATOR_A)
    approval = GovernanceApproval(
        approver=GovernancePrincipal(
            oid=base._OPERATOR_A,
            roles=frozenset({Role.APPROVER}),
        ),
        reviewed_revision=base._REVISION,
        approved_at=base._NOW,
        phishing_resistant=True,
    )
    attestation = base._override_attestation(
        request,
        approvals=(approval,),
        approval_profile=profile,
        author_oid=base._OPERATOR_A,
    )
    digest = promotion_attestation_digest(attestation)
    request = base._override_request(
        target.name,
        operator_principal=base._OPERATOR_A,
        approval_receipt_digest=digest,
    )
    attestation = base._override_attestation(
        request,
        approvals=(approval,),
        approval_profile=profile,
        author_oid=base._OPERATOR_A,
    )

    with pytest.raises(DirectApiPreconditionError, match="active profile"):
        await GovernancePromotionDispatcher(executor).dispatch(request, attestation=attestation)


async def test_gate_promotion_refuses_existing_operator_override_record() -> None:
    action_types = base._action_types()
    target = action_types["remediate.tag-add"]
    store = InMemoryStateStore()
    verifier = base._OverrideAuthorityVerifier()
    verifier.receipts.add(base._APPROVAL)
    registry = StateStoreActionPromotionRegistry(
        store=store,
        receipt_verifier=base._ReceiptVerifier(),
        persisted_authority_verifier=base._PersistedAuthorityVerifier(),
        override_authority_verifier=verifier,
    )
    override = OperatorOverridePromotionDirectApiExecutor(
        action_types=action_types,
        registry=registry,
        clock=lambda: base._NOW,
    )
    await override.execute(
        base._override_request(target.name, approval_receipt_digest=base._APPROVAL)
    )
    gate = OperationalPromotionDirectApiExecutor(
        action_types=action_types,
        receipts=base._ReceiptReader(base._receipt(target)),
        registry=registry,
    )

    with pytest.raises(DirectApiPreconditionError, match="attribution differs"):
        await gate.execute(base._request(target.name, mode=Mode.ENFORCE))

    assert registry.read_model(target.name)["promotion_kind"] == "operator_override"


async def test_override_promotion_refuses_existing_gate_evidence_record() -> None:
    action_types = base._action_types()
    target = action_types["remediate.tag-add"]
    verifier = base._OverrideAuthorityVerifier()
    verifier.receipts.add(base._APPROVAL)
    registry = StateStoreActionPromotionRegistry(
        store=InMemoryStateStore(),
        receipt_verifier=base._ReceiptVerifier(),
        persisted_authority_verifier=base._PersistedAuthorityVerifier(),
        override_authority_verifier=verifier,
    )
    gate = OperationalPromotionDirectApiExecutor(
        action_types=action_types,
        receipts=base._ReceiptReader(base._receipt(target)),
        registry=registry,
    )
    await gate.execute(base._request(target.name, mode=Mode.ENFORCE))
    override = OperatorOverridePromotionDirectApiExecutor(
        action_types=action_types,
        registry=registry,
        clock=lambda: base._NOW,
    )

    with pytest.raises(DirectApiPreconditionError, match="attribution differs"):
        await override.execute(
            base._override_request(target.name, approval_receipt_digest=base._APPROVAL)
        )

    assert registry.read_model(target.name)["promotion_kind"] == "gate_evidence"
