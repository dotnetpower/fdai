from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from fdai.delivery.gitops_pr import (
    GovernedGovernancePrPublisher,
    StateStoreGovernancePrLifecycleStore,
)
from fdai.delivery.gitops_pr.governance_writers import (
    RetirementMode,
    render_exemption_grant,
    render_rule_retirement,
)
from fdai.shared.providers.direct_api import (
    DirectApiOutcome,
    DirectApiPreconditionError,
    DirectApiReceipt,
)
from fdai.shared.providers.remediation_pr import PublishReceipt, RemediationPr
from fdai.shared.providers.testing.state_store import InMemoryStateStore

NOW = datetime(2026, 8, 15, 12, tzinfo=UTC)
OID_A = "00000000-0000-0000-0000-000000000001"
OID_B = "00000000-0000-0000-0000-000000000002"


class _Publisher:
    async def publish(self, pr: RemediationPr) -> PublishReceipt:
        self.pr = pr
        return PublishReceipt(pr_ref="example/repo#1", url="https://example.com/pr/1")


class _ReconcilingPublisher(_Publisher):
    async def reconcile(self, pr_ref: str) -> str:
        assert pr_ref == "example/repo#1"
        return "merged"


class _PromotionExecutor:
    async def execute(self, request):  # type: ignore[no-untyped-def]
        return DirectApiReceipt(outcome=DirectApiOutcome.SUCCEEDED, receipt_ref="promotion:1")


def _document():
    return render_rule_retirement(
        rule_id="azure-builtin.storage.secure-transfer",
        mode=RetirementMode.SHADOW_ONLY,
        justification="The upstream control is superseded by a narrower authored rule.",
        requested_by=OID_A,
        approved_by=OID_B,
        decided_at=NOW,
    )


def _exemption_document():
    return render_exemption_grant(
        exemption_id="exemption-1",
        rule_id="azure-builtin.storage.secure-transfer",
        subscription_id="00000000-0000-0000-0000-000000000003",
        justification="The workload is covered by a compensating control.",
        requested_by=OID_A,
        approved_by=OID_B,
        created_at=NOW,
        expires_at=NOW + timedelta(days=1),
        resource_group="rg-workload",
    )


@pytest.mark.asyncio
async def test_governance_writer_is_bound_to_replayable_open_to_merge_receipt() -> None:
    publisher = _Publisher()
    store = InMemoryStateStore()
    service = GovernedGovernancePrPublisher(
        publisher=publisher,
        lifecycle_store=StateStoreGovernancePrLifecycleStore(store),
        clock=lambda: NOW,
    )

    first = await service.publish(_document(), correlation_id="governance-1")
    second = await service.publish(_document(), correlation_id="governance-1")

    assert first == second
    assert first.state == "open"
    assert first.merge_required is True
    assert first.applied is False
    assert publisher.pr.patch_path.endswith(".yaml")


@pytest.mark.asyncio
async def test_replay_reconciles_a_merged_pr_terminal_state() -> None:
    publisher = _ReconcilingPublisher()
    store = StateStoreGovernancePrLifecycleStore(InMemoryStateStore())
    service = GovernedGovernancePrPublisher(
        publisher=publisher,
        lifecycle_store=store,
        clock=lambda: NOW,
    )
    await service.publish(_document(), correlation_id="governance-merged")
    merged = await service.publish(_document(), correlation_id="governance-merged")

    assert merged.state == "merged"
    assert merged.applied is True
    assert merged.merge_required is False


@pytest.mark.asyncio
async def test_exemption_writer_uses_the_same_governed_pr_binding() -> None:
    publisher = _Publisher()
    service = GovernedGovernancePrPublisher(
        publisher=publisher,
        lifecycle_store=StateStoreGovernancePrLifecycleStore(InMemoryStateStore()),
        clock=lambda: NOW,
    )
    receipt = await service.publish(_exemption_document(), correlation_id="governance-2")
    assert receipt.action_type_name == "governance.grant-exemption"
    assert receipt.applied is False
    assert publisher.pr.patch_path.endswith(".json")
    assert publisher.pr.patch.startswith("{")


@pytest.mark.asyncio
async def test_governance_publisher_rejects_path_traversal_and_identifier_mismatch() -> None:
    from fdai.delivery.gitops_pr import GovernancePrError
    from fdai.delivery.gitops_pr.governance_writers import GovernanceDocument

    service = GovernedGovernancePrPublisher(
        publisher=_Publisher(),
        lifecycle_store=StateStoreGovernancePrLifecycleStore(InMemoryStateStore()),
        clock=lambda: NOW,
    )
    document = _document()
    for path in (
        "rule-catalog/other/azure-builtin.storage.secure-transfer.yaml",
        "rule-catalog/retirements/other.yaml",
        "rule-catalog/retirements/azure-builtin.storage.secure-transfer.json",
    ):
        with pytest.raises(GovernancePrError, match="path"):
            await service.publish(
                GovernanceDocument(path=path, document=document.document),
                correlation_id="governance-path",
            )


@pytest.mark.asyncio
async def test_promotion_dispatch_requires_approved_distinct_approver_transition() -> None:
    from fdai.core.rbac.roles import Role
    from fdai.delivery.promotion import (
        GovernancePromotionAttestation,
        GovernancePromotionDispatcher,
        promotion_request_fingerprint,
    )
    from fdai.rule_catalog.schema.governance_review_authority import (
        GovernanceApproval,
        GovernanceChangeClass,
        GovernancePrincipal,
        GovernanceReviewRequest,
    )
    from fdai.shared.contracts.models import Mode
    from fdai.shared.providers.direct_api import DirectApiRequest

    request = DirectApiRequest(
        action_id=UUID("00000000-0000-0000-0000-000000000010"),
        idempotency_key="promotion-1",
        action_type_name="governance.promote-action-type",
        rule_ids=("operator.promotion",),
        resource_ref="action-type:remediate.tag-add",
        arguments={
            "action_type_id": "remediate.tag-add",
            "target_mode": "enforce",
            "fdai_revision": "a" * 40,
            "scenario_set_version": "scenario-v1",
            "evidence_digest": "b" * 64,
            "justification": "Measured evidence passed every promotion guard.",
        },
        labels=("enforce",),
        mode=Mode.ENFORCE,
    )
    dispatcher = GovernancePromotionDispatcher(_PromotionExecutor())  # type: ignore[arg-type]
    with pytest.raises(DirectApiPreconditionError, match="distinct-approver"):
        await dispatcher.dispatch(request)

    review = GovernanceReviewRequest(
        change_class=GovernanceChangeClass.ENFORCE_PROMOTION,
        author=GovernancePrincipal(oid=OID_A, roles=frozenset({Role.APPROVER})),
        head_revision="a" * 40,
        head_committed_at=NOW,
        approvals=(
            GovernanceApproval(
                approver=GovernancePrincipal(oid=OID_B, roles=frozenset({Role.APPROVER})),
                reviewed_revision="a" * 40,
                approved_at=NOW,
                phishing_resistant=True,
            ),
            GovernanceApproval(
                approver=GovernancePrincipal(
                    oid="00000000-0000-0000-0000-000000000004",
                    roles=frozenset({Role.APPROVER}),
                ),
                reviewed_revision="a" * 40,
                approved_at=NOW,
                phishing_resistant=True,
            ),
        ),
    )
    attestation = GovernancePromotionAttestation(
        review=review,
        action_type_id="remediate.tag-add",
        fdai_revision="a" * 40,
        scenario_set_version="scenario-v1",
        evidence_digest="b" * 64,
        idempotency_key="promotion-1",
        nonce="nonce-1",
        request_fingerprint=promotion_request_fingerprint(request),
    )
    result = await dispatcher.dispatch(request, attestation=attestation)
    assert result.receipt_ref == "promotion:1"

    from fdai.delivery.promotion import StateStorePromotionAttestationStore

    store = StateStorePromotionAttestationStore(InMemoryStateStore())
    await store.save(attestation)
    routed = GovernancePromotionDispatcher(
        _PromotionExecutor(),
        attestation_store=store,
    )
    assert (await routed.execute(request)).receipt_ref == "promotion:1"
    with pytest.raises(DirectApiPreconditionError, match="unused"):
        await routed.execute(request)


@pytest.mark.asyncio
async def test_promotion_attestation_survives_a_failed_durable_apply() -> None:
    """A transient executor failure MUST NOT permanently spend the approval."""
    from fdai.core.rbac.roles import Role
    from fdai.delivery.promotion import (
        GovernancePromotionAttestation,
        GovernancePromotionDispatcher,
        StateStorePromotionAttestationStore,
        promotion_request_fingerprint,
    )
    from fdai.rule_catalog.schema.governance_review_authority import (
        GovernanceApproval,
        GovernanceChangeClass,
        GovernancePrincipal,
        GovernanceReviewRequest,
    )
    from fdai.shared.contracts.models import Mode
    from fdai.shared.providers.direct_api import DirectApiRequest

    class _FlakyExecutor:
        def __init__(self) -> None:
            self.calls = 0

        async def execute(self, request):  # type: ignore[no-untyped-def]
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("simulated durable write failure")
            return DirectApiReceipt(outcome=DirectApiOutcome.SUCCEEDED, receipt_ref="promotion:1")

    request = DirectApiRequest(
        action_id=UUID("00000000-0000-0000-0000-000000000013"),
        idempotency_key="promotion-4",
        action_type_name="governance.promote-action-type",
        rule_ids=("operator.promotion",),
        resource_ref="action-type:remediate.tag-add",
        arguments={
            "action_type_id": "remediate.tag-add",
            "target_mode": "enforce",
            "fdai_revision": "a" * 40,
            "scenario_set_version": "scenario-v1",
            "evidence_digest": "b" * 64,
            "justification": "Measured evidence passed every promotion guard.",
        },
        labels=("enforce",),
        mode=Mode.ENFORCE,
    )
    review = GovernanceReviewRequest(
        change_class=GovernanceChangeClass.ENFORCE_PROMOTION,
        author=GovernancePrincipal(oid=OID_A, roles=frozenset({Role.APPROVER})),
        head_revision="a" * 40,
        head_committed_at=NOW,
        approvals=(
            GovernanceApproval(
                approver=GovernancePrincipal(oid=OID_B, roles=frozenset({Role.APPROVER})),
                reviewed_revision="a" * 40,
                approved_at=NOW,
                phishing_resistant=True,
            ),
            GovernanceApproval(
                approver=GovernancePrincipal(
                    oid="00000000-0000-0000-0000-000000000004",
                    roles=frozenset({Role.APPROVER}),
                ),
                reviewed_revision="a" * 40,
                approved_at=NOW,
                phishing_resistant=True,
            ),
        ),
    )
    attestation = GovernancePromotionAttestation(
        review=review,
        action_type_id="remediate.tag-add",
        fdai_revision="a" * 40,
        scenario_set_version="scenario-v1",
        evidence_digest="b" * 64,
        idempotency_key="promotion-4",
        nonce="nonce-4",
        request_fingerprint=promotion_request_fingerprint(request),
    )
    store = StateStorePromotionAttestationStore(InMemoryStateStore())
    await store.save(attestation)
    executor = _FlakyExecutor()
    routed = GovernancePromotionDispatcher(executor, attestation_store=store)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="simulated durable write failure"):
        await routed.execute(request)
    assert executor.calls == 1

    # The same governance approval - not a fresh one - backs the retry.
    result = await routed.execute(request)
    assert result.receipt_ref == "promotion:1"
    assert executor.calls == 2

    # Only now that the apply durably succeeded is the approval truly spent.
    with pytest.raises(DirectApiPreconditionError, match="unused"):
        await routed.execute(request)


@pytest.mark.asyncio
async def test_promotion_rejects_forged_bare_decision_and_mismatched_attestation() -> None:
    from fdai.core.rbac.roles import Role
    from fdai.delivery.promotion import (
        GovernancePromotionAttestation,
        GovernancePromotionDispatcher,
        promotion_request_fingerprint,
    )
    from fdai.rule_catalog.schema.governance_review_authority import (
        GovernanceChangeClass,
        GovernancePrincipal,
        GovernanceReviewRequest,
        ReviewAuthorityDecision,
    )
    from fdai.shared.contracts.models import Mode
    from fdai.shared.providers.direct_api import DirectApiRequest

    request = DirectApiRequest(
        action_id=UUID("00000000-0000-0000-0000-000000000012"),
        idempotency_key="promotion-3",
        action_type_name="governance.promote-action-type",
        rule_ids=("operator.promotion",),
        resource_ref="action-type:remediate.tag-add",
        arguments={
            "action_type_id": "remediate.tag-add",
            "target_mode": "enforce",
            "fdai_revision": "a" * 40,
            "scenario_set_version": "scenario-v1",
            "evidence_digest": "b" * 64,
        },
        labels=("enforce",),
        mode=Mode.ENFORCE,
    )
    dispatcher = GovernancePromotionDispatcher(_PromotionExecutor())  # type: ignore[arg-type]
    forged = ReviewAuthorityDecision(
        change_class=GovernanceChangeClass.ENFORCE_PROMOTION,
        allowed=True,
        required_quorum=0,
        satisfied_quorum=0,
    )
    with pytest.raises(DirectApiPreconditionError):
        await dispatcher.dispatch(request, attestation=forged)  # type: ignore[arg-type]

    with pytest.raises(DirectApiPreconditionError, match="exact request"):
        await dispatcher.dispatch(
            request,
            attestation=GovernancePromotionAttestation(
                review=GovernanceReviewRequest(
                    change_class=GovernanceChangeClass.ENFORCE_PROMOTION,
                    author=GovernancePrincipal(oid=OID_A, roles=frozenset({Role.APPROVER})),
                    head_revision="a" * 40,
                    head_committed_at=NOW,
                    approvals=(),
                ),
                action_type_id="remediate.other",
                fdai_revision="a" * 40,
                scenario_set_version="scenario-v1",
                evidence_digest="b" * 64,
                idempotency_key="promotion-3",
                nonce="nonce-3",
                request_fingerprint=promotion_request_fingerprint(request),
            ),
        )


@pytest.mark.asyncio
async def test_promotion_direct_route_is_inert_without_review() -> None:
    from fdai.delivery.promotion import GovernancePromotionDispatcher
    from fdai.shared.providers.direct_api import DirectApiRequest

    request = DirectApiRequest(
        action_id=UUID("00000000-0000-0000-0000-000000000011"),
        idempotency_key="promotion-2",
        action_type_name="governance.promote-action-type",
        rule_ids=("operator.promotion",),
        resource_ref="action-type:remediate.tag-add",
    )
    with pytest.raises(DirectApiPreconditionError, match="inert"):
        await GovernancePromotionDispatcher(_PromotionExecutor()).execute(request)  # type: ignore[arg-type]
