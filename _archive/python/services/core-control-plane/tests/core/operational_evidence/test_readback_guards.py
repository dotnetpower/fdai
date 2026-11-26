"""One negative test per verifier guard: each asserts its exact rejection class and reason."""

from __future__ import annotations

import dataclasses
from dataclasses import asdict
from datetime import UTC, timedelta
from typing import Any

import pytest
from fdai.core.operational_context.test_context import TestContextClaim as ContextClaim
from fdai.core.operational_context.test_context_commands import (
    TestContextCommandHandler as ContextCommandHandler,
)
from fdai.core.operational_context.test_context_commands import (
    transition_claim,
)
from fdai.core.operational_context.test_context_lifecycle import (
    GovernedTestContextStore,
    context_history_key,
    context_transition_digest,
)
from fdai.core.operational_evidence.readback.test_context_sources import AuditRow
from fdai.core.operational_evidence.revision_history import RegistryHistory
from fdai.shared.providers.decision_evidence_verifier import DecisionEvidenceAdmission
from fdai_service_contracts.ontology_query import content_digest
from fdai_service_contracts.operational_evidence import (
    OperationalEvidenceIssuanceStatus,
    OperationalEvidenceRejectionClass,
)
from tests.core.operational_evidence.harness import VerifierVenue
from tests.core.operational_evidence.support import (
    NOW,
    POLICY,
    REQUESTER,
    REQUESTER_GROUP,
    REVIEWER,
    REVIEWER_GROUP,
    SCOPE,
    TARGET,
    command_from_row,
    grant_document,
    history,
)

_R = OperationalEvidenceRejectionClass


class _SubstitutingAdmission:
    """A store-side admission stub that cites one fixed, real receipt for every transition."""

    def __init__(self, receipt_digest: str) -> None:
        self._receipt = receipt_digest

    async def admit(self, **values: str) -> DecisionEvidenceAdmission:
        return DecisionEvidenceAdmission(
            **values,
            receipt_digest=self._receipt,
            verification_bundle_digest="sha256:" + "c" * 64,
            verified_at=NOW,
            valid_until=NOW + timedelta(hours=1),
        )


async def _review_citing(venue: VerifierVenue, receipt_digest: str) -> ContextClaim:
    stub = _SubstitutingAdmission(receipt_digest)
    handler = ContextCommandHandler(
        contexts=GovernedTestContextStore(store=venue.state, admission=stub, clock=lambda: NOW),
        admission=stub,
        clock=lambda: NOW,
    )
    await handler.transition(venue.review(), reviewed_by_var=True)
    return (await venue.context_history())["context-test"][-1]


def _transition_receipts(venue: VerifierVenue) -> list[str]:
    return [
        issued.receipt.receipt_digest
        for issued, _record in venue.proofs.admissions
        if issued.purpose_id == "test-context-transition"
    ]


def _assert_rejected(result: Any, rejection_class: Any, reason: str) -> None:
    response, rejection = result
    assert response.status is OperationalEvidenceIssuanceStatus.REJECTED
    assert rejection is not None
    assert rejection.rejection_class is rejection_class
    assert reason in rejection.reason_codes


async def test_current_context_rejects_lineage_cited_from_another_transition() -> None:
    venue = VerifierVenue()
    await venue.handler.transition(venue.propose(), reviewed_by_var=False)
    (proposal_receipt,) = _transition_receipts(venue)
    reviewed = await _review_citing(venue, proposal_receipt)
    assert reviewed.state == "reviewed"
    _assert_rejected(
        await venue.issue_current(reviewed), _R.REPLAY_SUBSTITUTED, "lineage_lookup_mismatch"
    )
    assert (
        await venue.provider.admit(
            evidence_digest=reviewed.digest,
            scope_digest="sha256:" + SCOPE,
            purpose_id="operational-test-context",
            source_revision=POLICY,
        )
        is None
    )


async def test_current_context_rejects_a_lineage_reference_to_no_admission() -> None:
    venue = VerifierVenue()
    await venue.handler.transition(venue.propose(), reviewed_by_var=False)
    reviewed = await _review_citing(venue, "sha256:" + "d" * 64)
    _assert_rejected(await venue.issue_current(reviewed), _R.PARTIAL, "lineage_missing")


async def test_current_context_rejects_lineage_whose_matched_grant_was_revoked_since() -> None:
    venue = VerifierVenue()
    reviewed = await venue.reviewed_chain()
    revoked = grant_document()
    revoked["revision"] = 2
    revoked["principal_grants"][1]["revoked"] = True
    restored = grant_document()
    restored["revision"] = 3
    venue.history = RegistryHistory(
        (venue.history.current, history(revoked).current, history(restored).current)
    )
    _assert_rejected(await venue.issue_current(reviewed), _R.REVOKED, "lineage_revoked")


async def test_current_context_with_its_own_transition_lineage_is_issued() -> None:
    venue = VerifierVenue()
    reviewed = await venue.reviewed_chain()
    response, rejection = await venue.issue_current(reviewed)
    assert rejection is None and response.status is OperationalEvidenceIssuanceStatus.ISSUED


async def test_tampered_audit_row_is_replay_substituted() -> None:
    venue = VerifierVenue()
    reviewed = await venue.reviewed_chain()

    def tamper(row: AuditRow) -> AuditRow:
        return dataclasses.replace(row, entry={**row.entry, "timestamp": "1970-01-01T00:00:00Z"})

    venue.sources.audit_tamper = tamper
    _assert_rejected(
        await venue.issue_current(reviewed), _R.REPLAY_SUBSTITUTED, "audit_hash_mismatch"
    )


async def test_store_revision_change_between_reads_is_conflicting() -> None:
    venue = VerifierVenue()
    reviewed = await venue.reviewed_chain()
    venue.sources.change_revision_after(1)
    _assert_rejected(await venue.issue_current(reviewed), _R.CONFLICTING, "store_revision_changed")


async def _inject_competing_reviewed_context(venue: VerifierVenue, context_id: str) -> None:
    """Write a second overlapping reviewed context the way a tampered store would."""

    proposal = command_from_row(
        venue.outbox.add(
            "propose",
            principal=REQUESTER,
            group=REQUESTER_GROUP,
            roles=("Contributor",),
            accepted_at=NOW - timedelta(minutes=2),
            expected_revision=0,
            key="propose-competing",
            context_id=context_id,
        )
    )
    review = command_from_row(
        venue.outbox.add(
            "review",
            principal=REVIEWER,
            group=REVIEWER_GROUP,
            roles=("Approver",),
            accepted_at=NOW - timedelta(minutes=1),
            expected_revision=1,
            key="review-competing",
            context_id=context_id,
        )
    )
    first = transition_claim(proposal, None)
    second = transition_claim(review, first)
    key = context_history_key(SCOPE, TARGET)
    value = dict(await venue.state.read_state(key) or {})
    histories = dict(value["histories"])
    histories[context_id] = [_mapping(first), _mapping(second)]
    await venue.state.write_state(
        key, {"revision": int(value["revision"]) + 1, "histories": histories}
    )
    for claim, prior in ((first, None), (second, first)):
        await venue.state.append_audit_entry(
            {
                "action_kind": "test_context.transition",
                "owner_agent": "Mimir",
                "context_digest": claim.digest,
                "previous_digest": prior.digest if prior else None,
                "admission_ref": "sha256:" + "e" * 64,
                "state": claim.state,
                "scope_digest": SCOPE,
                "timestamp": NOW.isoformat(),
                "execution_authority": False,
                "promotion_authority": False,
            }
        )


def _mapping(claim: ContextClaim) -> dict[str, Any]:
    value = asdict(claim)
    for name in ("effective_from", "effective_to", "recorded_at"):
        value[name] = getattr(claim, name).astimezone(UTC).isoformat()
    return value


async def test_second_active_reviewed_context_is_conflicting() -> None:
    venue = VerifierVenue()
    reviewed = await venue.reviewed_chain()
    await _inject_competing_reviewed_context(venue, "context-competing")
    _assert_rejected(
        await venue.issue_current(reviewed), _R.CONFLICTING, "competing_active_context"
    )


async def test_review_overlapping_another_reviewed_context_is_conflicting() -> None:
    venue = VerifierVenue()
    await venue.reviewed_chain()
    other = venue.propose(key="propose-other", context_id="context-other")
    await venue.handler.transition(other, reviewed_by_var=False)
    row = venue.outbox.add(
        "review",
        principal=REVIEWER,
        group=REVIEWER_GROUP,
        roles=("Approver",),
        accepted_at=NOW - timedelta(seconds=10),
        expected_revision=1,
        key="review-other",
        context_id="context-other",
    )
    prior = (await venue.context_history())["context-other"][-1]
    claim = transition_claim(command_from_row(row), prior)
    _assert_rejected(
        await venue.issue(
            "test-context-transition",
            context_transition_digest(claim, prior),
            idempotency_key="review-other",
            context_id="context-other",
            target_ref=TARGET,
        ),
        _R.CONFLICTING,
        "overlapping_reviewed_claim",
    )


async def _command_rejection(venue: VerifierVenue, command: dict[str, Any]) -> Any:
    return await venue.issue(
        "operator-test-context-command",
        content_digest(command),
        idempotency_key=command["idempotency_key"],
    )


@pytest.mark.parametrize(
    ("overrides", "expected", "reason"),
    [
        ({"receipt_roles": ("Approver",)}, _R.CROSS_SCOPE, "principal_roles_mismatch"),
        (
            {"receipt_issued_at": NOW + timedelta(hours=2)},
            _R.STALE,
            "authentication_receipt_not_current",
        ),
        ({"dispatch_status": "rejected"}, _R.PARTIAL, "delivery_rejected"),
    ],
)
async def test_command_source_guards_reject_with_their_class(
    overrides: dict[str, Any], expected: Any, reason: str
) -> None:
    venue = VerifierVenue()
    command = venue.propose(**overrides)
    _assert_rejected(await _command_rejection(venue, command), expected, reason)


async def test_forged_request_digest_is_replay_substituted() -> None:
    venue = VerifierVenue()
    command = venue.propose()
    venue.outbox.rows[-1].record["request_digest"] = "0" * 64
    _assert_rejected(
        await _command_rejection(venue, command), _R.REPLAY_SUBSTITUTED, "request_digest_mismatch"
    )
