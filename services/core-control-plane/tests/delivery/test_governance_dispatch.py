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


@pytest.mark.asyncio
async def test_promotion_dispatch_requires_approved_distinct_approver_transition() -> None:
    from fdai.delivery.promotion import GovernancePromotionDispatcher
    from fdai.rule_catalog.schema.governance_review_authority import (
        GovernanceChangeClass,
        ReviewAuthorityDecision,
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

    decision = ReviewAuthorityDecision(
        change_class=GovernanceChangeClass.ENFORCE_PROMOTION,
        allowed=True,
        required_quorum=2,
        satisfied_quorum=2,
        counted_approver_oids=(OID_A, OID_B),
    )
    result = await dispatcher.dispatch(request, review=decision)
    assert result.receipt_ref == "promotion:1"


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
