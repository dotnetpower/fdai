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


class _ExistingPublisher(_Publisher):
    async def publish(self, pr: RemediationPr) -> PublishReceipt:
        self.pr = pr
        return PublishReceipt(
            pr_ref="example/repo#1",
            url="https://example.com/pr/1",
            already_existed=True,
        )


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

    first = await service.publish(
        _document(), correlation_id="governance-1", source_event_id="event-1"
    )
    second = await service.publish(
        _document(), correlation_id="governance-1", source_event_id="event-1"
    )

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
    await service.publish(
        _document(), correlation_id="governance-merged", source_event_id="event-merged"
    )
    merged = await service.publish(
        _document(), correlation_id="governance-merged", source_event_id="event-merged"
    )

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
    receipt = await service.publish(
        _exemption_document(), correlation_id="governance-2", source_event_id="event-2"
    )
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
                source_event_id="event-path",
            )


@pytest.mark.asyncio
async def test_distinct_source_events_in_one_correlation_do_not_collapse() -> None:
    """Two independent source events that happen to render the same
    document MUST get their own auditable receipt; the idempotency key
    binds to the source event, not the correlation group or content alone."""

    publisher = _Publisher()
    service = GovernedGovernancePrPublisher(
        publisher=publisher,
        lifecycle_store=StateStoreGovernancePrLifecycleStore(InMemoryStateStore()),
        clock=lambda: NOW,
    )

    first = await service.publish(
        _document(), correlation_id="governance-shared", source_event_id="event-a"
    )
    second = await service.publish(
        _document(), correlation_id="governance-shared", source_event_id="event-b"
    )

    assert first.document_digest == second.document_digest
    assert first.correlation_id == second.correlation_id == "governance-shared"
    assert first.idempotency_key != second.idempotency_key


@pytest.mark.asyncio
async def test_same_source_event_rejects_document_drift() -> None:
    from fdai.delivery.gitops_pr import GovernancePrError

    service = GovernedGovernancePrPublisher(
        publisher=_Publisher(),
        lifecycle_store=StateStoreGovernancePrLifecycleStore(InMemoryStateStore()),
        clock=lambda: NOW,
    )
    await service.publish(
        _document(),
        correlation_id="governance-drift",
        source_event_id="event-drift",
    )
    changed = render_rule_retirement(
        rule_id="azure-builtin.storage.secure-transfer",
        mode=RetirementMode.RETIRED,
        justification="The reviewed source event now contains different retirement content.",
        requested_by=OID_A,
        approved_by=OID_B,
        decided_at=NOW,
    )

    with pytest.raises(GovernancePrError, match="content drift"):
        await service.publish(
            changed,
            correlation_id="governance-drift",
            source_event_id="event-drift",
        )


@pytest.mark.asyncio
async def test_legacy_lifecycle_key_blocks_duplicate_publication() -> None:
    import hashlib
    import json

    from fdai.delivery.gitops_pr import GovernancePrError

    document = _document()
    digest = hashlib.sha256(
        json.dumps(
            document.document,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).hexdigest()
    state = InMemoryStateStore()
    legacy_key = f"governance.retire-rule:{digest}"
    await state.write_state(
        f"governance-pr-lifecycle:{legacy_key}:open",
        {
            "schema_version": "1.0.0",
            "idempotency_key": legacy_key,
        },
    )
    service = GovernedGovernancePrPublisher(
        publisher=_Publisher(),
        lifecycle_store=StateStoreGovernancePrLifecycleStore(state),
        clock=lambda: NOW,
    )

    with pytest.raises(GovernancePrError, match="unsupported"):
        await service.publish(
            document,
            correlation_id="governance-legacy",
            source_event_id="event-legacy",
        )


@pytest.mark.asyncio
async def test_existing_pr_without_lifecycle_receipt_fails_closed() -> None:
    from fdai.delivery.gitops_pr import GovernancePrError

    service = GovernedGovernancePrPublisher(
        publisher=_ExistingPublisher(),
        lifecycle_store=StateStoreGovernancePrLifecycleStore(InMemoryStateStore()),
        clock=lambda: NOW,
    )

    with pytest.raises(GovernancePrError, match="lifecycle evidence"):
        await service.publish(
            _document(),
            correlation_id="governance-existing",
            source_event_id="event-existing",
        )


@pytest.mark.asyncio
async def test_mutating_the_source_document_after_publish_starts_does_not_change_the_patch() -> (
    None
):
    """The digest and the rendered PR patch MUST come from the same
    snapshot. A store whose `load` mutates the caller's still-referenced
    document mapping (simulating a concurrent actor racing the awaited
    lookup) must not be able to change what gets rendered or recorded."""
    import hashlib
    import json

    from fdai.delivery.gitops_pr.governance import GovernancePrLifecycleReceipt

    document = _document()
    mutable_view = document.document  # a plain, still-mutable caller-owned dict

    class _MutatingStore:
        async def load(self, idempotency_key: str) -> GovernancePrLifecycleReceipt | None:
            # Simulate another actor mutating the shared mapping while this
            # lookup is awaited, before the patch is rendered.
            mutable_view["justification"] = "TAMPERED after the digest was computed."
            return None

        async def save(self, receipt: GovernancePrLifecycleReceipt) -> None:
            self.saved = receipt

    publisher = _Publisher()
    store = _MutatingStore()
    service = GovernedGovernancePrPublisher(
        publisher=publisher, lifecycle_store=store, clock=lambda: NOW
    )

    receipt = await service.publish(
        document, correlation_id="governance-race", source_event_id="event-race"
    )

    original_payload = json.dumps(
        {
            "schema_version": "1.0.0",
            "rule_id": "azure-builtin.storage.secure-transfer",
            "mode": "shadow_only",
            "justification": "The upstream control is superseded by a narrower authored rule.",
            "requested_by": OID_A,
            "approved_by": OID_B,
            "decided_at": "2026-08-15T12:00:00Z",
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    assert receipt.document_digest == hashlib.sha256(original_payload).hexdigest()
    assert "TAMPERED" not in publisher.pr.patch
    assert "superseded by a narrower authored rule" in publisher.pr.patch

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
    assert (await routed.execute(request)).receipt_ref == "promotion:1"

    class _MustNotExecute:
        async def execute(self, request):  # type: ignore[no-untyped-def]
            raise AssertionError(f"replay reached executor: {request.idempotency_key}")

    restarted = GovernancePromotionDispatcher(
        _MustNotExecute(),  # type: ignore[arg-type]
        attestation_store=store,
    )
    assert (await restarted.execute(request)).receipt_ref == "promotion:1"


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
    # Exact retries replay the confirmed receipt without calling the executor.
    replay = await routed.execute(request)
    assert replay == result
    assert executor.calls == 2


@pytest.mark.asyncio
async def test_promotion_attestation_recovers_when_restore_itself_fails() -> None:
    """A restore write can fail for the exact same reason the apply did -
    both hit the same durable store. The reservation MUST still recover
    once its bounded lease expires, not remain permanently spent."""
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

    class _AlwaysFailingExecutor:
        async def execute(self, request):  # type: ignore[no-untyped-def]
            raise RuntimeError("simulated durable write failure")

    class _NthCasFailsStore(InMemoryStateStore):
        """Fail exactly the ``fail_on_call``-th compare-and-set - the
        restore attempt right after the first failed apply - as if the
        same durable-store outage that broke the apply also broke the
        compensating restore write."""

        def __init__(self, *, fail_on_call: int) -> None:
            super().__init__()
            self._fail_on_call = fail_on_call
            self.cas_calls = 0

        async def compare_and_set_state_with_audit(  # type: ignore[no-untyped-def]
            self, key, value, *, expected_revision, audit_entry
        ):
            self.cas_calls += 1
            if self.cas_calls == self._fail_on_call:
                raise RuntimeError("simulated store outage")
            return await super().compare_and_set_state_with_audit(
                key, value, expected_revision=expected_revision, audit_entry=audit_entry
            )

    request = DirectApiRequest(
        action_id=UUID("00000000-0000-0000-0000-000000000014"),
        idempotency_key="promotion-5",
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
        idempotency_key="promotion-5",
        nonce="nonce-5",
        request_fingerprint=promotion_request_fingerprint(request),
    )

    clock_now = NOW

    def _clock() -> datetime:
        return clock_now

    # The 2nd compare-and-set across this test is the `restore` write that
    # follows the first failed apply (the 1st is `consume`'s own reserve).
    outage_store = _NthCasFailsStore(fail_on_call=2)
    store = StateStorePromotionAttestationStore(
        outage_store,
        reservation_lease_seconds=60,
        clock=_clock,
    )
    await store.save(attestation)
    routed = GovernancePromotionDispatcher(
        _AlwaysFailingExecutor(),  # type: ignore[arg-type]
        attestation_store=store,
    )

    with pytest.raises(RuntimeError, match="simulated durable write failure"):
        await routed.execute(request)

    # The compensating `restore` write itself failed (same outage), so the
    # nonce is still `reserved`, not `pending` - an immediate retry MUST NOT
    # silently mint a second concurrent claim on the same approval.
    with pytest.raises(DirectApiPreconditionError, match="unused"):
        await routed.execute(request)

    # Once the bounded reservation lease elapses, the same governance
    # approval recovers on its own - no successful `restore` write required.
    clock_now = NOW + timedelta(seconds=61)
    with pytest.raises(RuntimeError, match="simulated durable write failure"):
        await routed.execute(request)

    # The approval was never permanently lost: a working executor retry
    # (again after the lease elapses) can still apply it.
    clock_now = NOW + timedelta(seconds=122)
    working = GovernancePromotionDispatcher(_PromotionExecutor(), attestation_store=store)
    result = await working.execute(request)
    assert result.receipt_ref == "promotion:1"

    # Only now, after a confirmed durable success, is it truly spent. Exact
    # retries replay the confirmed receipt without reapplying the promotion.
    assert (await working.execute(request)) == result


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


@pytest.mark.asyncio
async def test_stale_fencing_token_cannot_touch_a_reclaimed_reservation() -> None:
    """A holder whose lease already expired MUST NOT restore or finalize
    the *reclaimer's* still-active reservation.

    `consume` claims the nonce before the guarded apply is known to
    succeed, bounded by a lease. If that lease expires, a fresh `consume`
    call reclaims the same nonce and bumps its revision. The original
    (now stale) holder may still be mid-flight - for example a slow
    network call that outlived its own lease - and eventually call
    `restore` or `finalize` with the token it captured back when it first
    reserved. Both MUST be safe no-ops against the reclaimer's revision,
    not just against `consumed`/`pending` states.
    """
    from fdai.core.rbac.roles import Role
    from fdai.delivery.promotion import (
        GovernancePromotionAttestation,
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

    request = DirectApiRequest(
        action_id=UUID("00000000-0000-0000-0000-000000000016"),
        idempotency_key="promotion-7",
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
        idempotency_key="promotion-7",
        nonce="nonce-7",
        request_fingerprint=promotion_request_fingerprint(request),
    )

    clock_now = NOW

    def _clock() -> datetime:
        return clock_now

    store = StateStorePromotionAttestationStore(
        InMemoryStateStore(),
        reservation_lease_seconds=60,
        clock=_clock,
    )
    await store.save(attestation)

    stale = await store.consume("promotion-7", attestation.request_fingerprint)
    assert stale is not None

    # The stale holder's lease elapses without it ever calling restore or
    # finalize (for example it is still blocked on a slow network call).
    clock_now = NOW + timedelta(seconds=61)
    fresh = await store.consume("promotion-7", attestation.request_fingerprint)
    assert fresh is not None
    assert fresh.fencing_token != stale.fencing_token

    # The stale holder now wakes up and tries to unwind what it believes
    # is still its own reservation. Both calls MUST be no-ops: the fresh
    # holder's active claim is untouched.
    await store.restore("promotion-7", stale.attestation, stale.fencing_token)
    replay_receipt = DirectApiReceipt(
        outcome=DirectApiOutcome.SUCCEEDED,
        receipt_ref="promotion:1",
    )
    await store.finalize(
        "promotion-7",
        stale.attestation,
        stale.fencing_token,
        replay_receipt,
    )

    key = "governance-promotion-attestation:promotion-7"
    raw = await store._store.read_state(key)  # noqa: SLF001 - assert internal durable state
    assert raw is not None
    assert raw["state"] == "reserved"
    assert raw["revision"] == fresh.fencing_token

    # The fresh holder's own token, however, still works.
    await store.finalize(
        "promotion-7",
        fresh.attestation,
        fresh.fencing_token,
        replay_receipt,
    )
    raw = await store._store.read_state(key)  # noqa: SLF001 - assert internal durable state
    assert raw is not None
    assert raw["state"] == "consumed"


@pytest.mark.asyncio
async def test_finalize_failure_after_durable_apply_is_a_recoverable_success() -> None:
    """A `finalize` bookkeeping failure MUST NOT mask an already-durable apply.

    By the time `finalize` runs, the wrapped executor already durably
    applied the promotion - `finalize` only spends the reservation
    bookkeeping. If that write itself fails (the same class of
    durable-store outage that can afflict `restore`), the caller MUST
    still see the confirmed success receipt, not an exception that could
    make it believe the action never happened and reapply it. The
    dangling `reserved` record instead self-heals via the bounded
    reservation lease, exactly like an unrestored failure does."""
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

    class _CountingExecutor:
        def __init__(self) -> None:
            self.calls = 0

        async def execute(self, request):  # type: ignore[no-untyped-def]
            self.calls += 1
            return DirectApiReceipt(outcome=DirectApiOutcome.SUCCEEDED, receipt_ref="promotion:1")

    class _NthCasFailsStore(InMemoryStateStore):
        """Fail exactly the ``fail_on_call``-th compare-and-set - the
        `finalize` write that follows a successful apply - as if the
        durable store became unreachable right after the guarded apply
        already durably persisted."""

        def __init__(self, *, fail_on_call: int) -> None:
            super().__init__()
            self._fail_on_call = fail_on_call
            self.cas_calls = 0

        async def compare_and_set_state_with_audit(  # type: ignore[no-untyped-def]
            self, key, value, *, expected_revision, audit_entry
        ):
            self.cas_calls += 1
            if self.cas_calls == self._fail_on_call:
                raise RuntimeError("simulated store outage")
            return await super().compare_and_set_state_with_audit(
                key, value, expected_revision=expected_revision, audit_entry=audit_entry
            )

    request = DirectApiRequest(
        action_id=UUID("00000000-0000-0000-0000-000000000017"),
        idempotency_key="promotion-8",
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
        idempotency_key="promotion-8",
        nonce="nonce-8",
        request_fingerprint=promotion_request_fingerprint(request),
    )

    # The 1st compare-and-set is `consume`'s own reserve; the 2nd is the
    # `finalize` write that follows the (successful) apply.
    outage_store = _NthCasFailsStore(fail_on_call=2)
    store = StateStorePromotionAttestationStore(outage_store, reservation_lease_seconds=60)
    await store.save(attestation)
    executor = _CountingExecutor()
    routed = GovernancePromotionDispatcher(executor, attestation_store=store)  # type: ignore[arg-type]

    result = await routed.execute(request)
    assert result.receipt_ref == "promotion:1"
    assert executor.calls == 1

    # The bookkeeping `finalize` write failed, but this process retains the
    # exact confirmed receipt. A retry returns that receipt and MUST NOT
    # reapply the already-durable promotion.
    replay = await routed.execute(request)
    assert replay == result
    assert executor.calls == 1
