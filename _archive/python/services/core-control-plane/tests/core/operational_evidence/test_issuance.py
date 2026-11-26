"""Verifier-issued admissions: exact-source readback, owners, and every rejection class."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from fdai.core.operational_context.test_context import evaluate_test_context
from fdai.core.operational_context.test_context_commands import (
    TestContextCommandHandler as ContextCommandHandler,
)
from fdai.core.operational_context.test_context_lifecycle import (
    GovernedTestContextStore,
    context_history_key,
    parse_test_context_history,
)
from fdai.core.operational_evidence.owner_outcome import (
    OperationalEvidenceRejectedError,
    OperationalEvidenceRequester,
    request_operational_evidence,
)
from fdai.delivery.operational_evidence_admission import OperationalEvidenceAdmissionProvider
from fdai.delivery.operational_evidence_transport import (
    BoundedOperationalEvidenceIssuer,
)
from fdai.delivery.persistence.state_store_decision_evidence import parse_decision_evidence_record
from fdai_service_contracts.ontology_query import content_digest
from fdai_service_contracts.operational_evidence import (
    OperationalEvidenceIssuanceRequest,
    OperationalEvidenceIssuanceStatus,
    OperationalEvidenceLocator,
    OperationalEvidenceLookup,
    OperationalEvidenceRejectionClass,
)
from fdai_service_contracts.operator_authentication import OperatorAuthenticationEvidenceClass
from tests.core.operational_evidence.harness import VerifierVenue
from tests.core.operational_evidence.support import (
    NOW,
    POLICY,
    SCOPE,
    TARGET,
    anchors,
    grant_document,
    history,
)

_R = OperationalEvidenceRejectionClass


def _request(command: dict[str, Any], **lookup: str) -> OperationalEvidenceIssuanceRequest:
    values = {
        "evidence_digest": content_digest(command),
        "scope_digest": "sha256:" + SCOPE,
        "purpose_id": "operator-test-context-command",
        "source_revision": POLICY,
    }
    values.update(lookup)
    return OperationalEvidenceIssuanceRequest(
        attempt_id="f" * 32,
        lookup=OperationalEvidenceLookup(**values),
        locator=OperationalEvidenceLocator(
            purpose_id=values["purpose_id"],
            coordinates={"idempotency_key": command["idempotency_key"]},
        ),
        producer_id="core-control-plane",
        producer_version="1.0.0",
        requested_at=NOW,
    )


async def test_full_test_context_chain_is_admitted_only_after_verifier_readback() -> None:
    venue = VerifierVenue()
    proposal = venue.propose()
    assert (await venue.handler.validate(proposal)).idempotency_key == proposal["idempotency_key"]
    await venue.handler.transition(proposal, reviewed_by_var=False)
    await venue.handler.transition(venue.review(), reviewed_by_var=True)
    _, histories = parse_test_context_history(
        await venue.state.read_state(context_history_key(SCOPE, TARGET))
    )
    claim = histories["context-test"][-1]
    assert claim.state == "reviewed"
    purposes = [issued.purpose_id for issued, _record in venue.proofs.admissions]
    assert purposes == [
        "operator-test-context-command",
        "operator-test-context-command",
        "test-context-transition",
        "operator-test-context-command",
        "test-context-transition",
    ]
    for issued, record in venue.proofs.admissions:
        retained = parse_decision_evidence_record(record)
        assert retained.receipt.synthetic is False
        assert retained.receipt.completeness_basis_points == 10_000
        assert retained.admission.execution_authority is False
        assert retained.verification_bundle.verifier_id == "operational-evidence-verifier"
        assert issued.binding.matched_grants
    audit = [item["entry"] for item in venue.state.audit_entries]
    transition_receipts = {
        issued.receipt.receipt_digest
        for issued, _record in venue.proofs.admissions
        if issued.purpose_id == "test-context-transition"
    }
    assert {entry["admission_ref"] for entry in audit} == transition_receipts

    attempt = await request_operational_evidence(
        venue.requester,
        evidence_digest=claim.digest,
        scope_digest="sha256:" + SCOPE,
        purpose_id="operational-test-context",
        source_revision=POLICY,
        locator={"context_id": "context-test", "target_ref": TARGET, "signal_code": "cpu_percent"},
        clock=lambda: NOW,
    )
    assert attempt.status is OperationalEvidenceIssuanceStatus.ISSUED
    admission = await venue.provider.admit(
        evidence_digest=claim.digest,
        scope_digest="sha256:" + SCOPE,
        purpose_id="operational-test-context",
        source_revision=POLICY,
    )
    assert admission is not None
    decision = evaluate_test_context(
        claim,
        target_ref=TARGET,
        access_scope_digest=SCOPE,
        signal_code="cpu_percent",
        observed_value=70.0,
        observed_at=NOW,
        evaluated_at=NOW,
        service_impact="none",
        protected_signal=False,
        admission=admission,
    )
    assert decision.reason == "observation_admission_required"


async def test_no_admission_exists_without_verifier_readback() -> None:
    venue = VerifierVenue()
    proposal = venue.propose()
    unissued = ContextCommandHandler(
        contexts=GovernedTestContextStore(store=venue.state, admission=venue.provider),
        admission=venue.provider,
        clock=lambda: NOW,
    )
    with pytest.raises(PermissionError) as refused:
        await unissued.validate(proposal)
    assert not isinstance(refused.value, OperationalEvidenceRejectedError)
    assert venue.proofs.admissions == []


def _deny_group(document: dict[str, Any]) -> dict[str, Any]:
    document["principal_grants"] = document["principal_grants"][1:]
    return document


def _revoke(document: dict[str, Any]) -> dict[str, Any]:
    document["principal_grants"][0]["revoked"] = True
    return document


def _supersede(document: dict[str, Any]) -> dict[str, Any]:
    document["case_scopes"][0]["policy_revision"] = "policy:test-context:2"
    return document


@pytest.mark.parametrize(
    ("case", "expected", "reason"),
    [
        ("stale", _R.STALE, "evidence_not_fresh"),
        ("revoked", _R.REVOKED, "grant_revoked"),
        ("competing", _R.CONFLICTING, "competing_command_record"),
        ("superseded", _R.CONFLICTING, "policy_revision_superseded"),
        ("partial", _R.PARTIAL, "authentication_receipt_missing"),
        ("synthetic", _R.SYNTHETIC_LIVE, "local_loopback_receipt"),
        ("cross_scope", _R.CROSS_SCOPE, "grant_missing"),
        ("groups", _R.CROSS_SCOPE, "principal_groups_mismatch"),
        ("replay", _R.REPLAY_SUBSTITUTED, "evidence_mismatch"),
    ],
)
async def test_each_rejection_class_reaches_the_owner_explicitly(
    case: str, expected: OperationalEvidenceRejectionClass, reason: str
) -> None:
    grants = grant_document()
    mutate = {"revoked": _revoke, "superseded": _supersede, "cross_scope": _deny_group}
    if case in mutate:
        grants = mutate[case](grants)
    deployed = case == "synthetic"
    bound = anchors(venue="deployed", evidence_class="live") if deployed else None
    venue = VerifierVenue(registry=history(grants), bound=bound)
    overrides: dict[str, Any] = {}
    if case == "stale":
        overrides["accepted_at"] = NOW - timedelta(minutes=11)
    if case == "partial":
        overrides["with_receipt"] = False
    if case == "groups":
        overrides["receipt_group"] = "00000000-0000-0000-0000-000000000099"
    if case == "competing":
        overrides["key"] = "context-shared-key"
        venue.propose(key="context-shared-key", accepted_at=NOW - timedelta(minutes=2))
    command = venue.propose(**overrides)
    if case == "replay":
        command = {**command, "idempotency_key": command["idempotency_key"]}
        command["request"] = {**command["request"], "source_ref": "operator-turn:substituted"}
    if case == "synthetic":
        assert venue.outbox.rows[-1].authentication_receipt is not None
    with pytest.raises(OperationalEvidenceRejectedError) as refused:
        await venue.handler.validate(command)
    rejection = refused.value.attempt.rejection
    assert rejection is not None
    assert rejection.rejection_class is expected
    assert reason in rejection.reason_codes
    assert f"operational_evidence_{expected.value}" in str(refused.value)
    assert refused.value.attempt.rejection_digest == venue.proofs.rejections[-1].record_digest
    assert rejection.valid_until - rejection.recorded_at == timedelta(seconds=60)
    assert venue.proofs.admissions == []
    if expected is _R.CONFLICTING:
        assert rejection.conflict_evidence_digests


async def test_self_verified_writes_no_record_and_keeps_the_generic_hold() -> None:
    venue = VerifierVenue(
        bound=anchors(overrides={"anchor:operational-evidence-verifier": "fdai_core"})
    )
    with pytest.raises(PermissionError) as refused:
        await venue.handler.validate(venue.propose())
    assert not isinstance(refused.value, OperationalEvidenceRejectedError)
    assert str(refused.value) == "test context command identity or scope admission failed"
    assert venue.proofs.admissions == [] and venue.proofs.rejections == []


async def test_stopped_verifier_yields_only_unavailable() -> None:
    venue = VerifierVenue()

    class _Stopped:
        async def send(self, request: OperationalEvidenceIssuanceRequest) -> Any:
            raise ConnectionRefusedError("verifier stopped")

    venue.requester = OperationalEvidenceRequester(
        issuer=BoundedOperationalEvidenceIssuer(_Stopped()),
        outcomes=venue.provider,
        producer_id="core-control-plane",
        producer_version="1.0.0",
    )
    handler = ContextCommandHandler(
        contexts=GovernedTestContextStore(store=venue.state, admission=venue.provider),
        admission=venue.provider,
        evidence=venue.requester,
        clock=lambda: NOW,
    )
    with pytest.raises(PermissionError) as refused:
        await handler.validate(venue.propose(accepted_at=NOW - timedelta(minutes=11)))
    assert not isinstance(refused.value, OperationalEvidenceRejectedError)
    assert venue.proofs.rejections == []


async def test_unregistered_producer_or_foreign_caller_is_replay_substituted() -> None:
    venue = VerifierVenue()
    command = venue.propose()
    forged = _request(command).model_copy(update={"producer_id": "core-control-plane.forged"})
    response = await venue.engine.issue(forged, caller_principal="fdai_core")
    assert response.status is OperationalEvidenceIssuanceStatus.REJECTED
    assert "producer_not_registered" in venue.proofs.rejections[-1].reason_codes
    foreign = await venue.engine.issue(
        _request(command).model_copy(update={"attempt_id": "e" * 32}),
        caller_principal="fdai_operator",
    )
    assert foreign.status is OperationalEvidenceIssuanceStatus.REJECTED
    assert "producer_anchor_mismatch" in venue.proofs.rejections[-1].reason_codes
    assert venue.proofs.admissions == []


async def test_foreign_admission_never_admits_another_input() -> None:
    venue = VerifierVenue()
    command = venue.propose()
    issued = await venue.engine.issue(_request(command), caller_principal="fdai_core")
    assert issued.status is OperationalEvidenceIssuanceStatus.ISSUED
    other = venue.propose(key="context-other-key")
    assert (
        await venue.provider.admit(
            evidence_digest=content_digest(other),
            scope_digest="sha256:" + SCOPE,
            purpose_id="operator-test-context-command",
            source_revision=POLICY,
        )
        is None
    )
    assert (
        await venue.provider.admit(
            evidence_digest=content_digest(command),
            scope_digest="sha256:" + SCOPE,
            purpose_id="deployment-apply",
            source_revision=POLICY,
        )
        is None
    )


async def test_consumer_rebinding_rejects_a_revoked_verifier_binding() -> None:
    venue = VerifierVenue()
    command = venue.propose()
    assert (
        await venue.engine.issue(_request(command), caller_principal="fdai_core")
    ).status is OperationalEvidenceIssuanceStatus.ISSUED
    lookup = {
        "evidence_digest": content_digest(command),
        "scope_digest": "sha256:" + SCOPE,
        "purpose_id": "operator-test-context-command",
        "source_revision": POLICY,
    }
    assert await venue.provider.admit(**lookup) is not None
    rebound = OperationalEvidenceAdmissionProvider(
        reader=venue.proofs,
        history=lambda: venue.history,
        anchors=anchors(overrides={"anchor:operational-evidence-verifier": "fdai_core"}),
        verifier_id="operational-evidence-verifier",
        clock=lambda: NOW,
    )
    assert await rebound.admit(**lookup) is None


async def test_no_token_or_secret_reaches_any_record() -> None:
    venue = VerifierVenue()
    await venue.handler.transition(venue.propose(), reviewed_by_var=False)
    with pytest.raises(OperationalEvidenceRejectedError):
        await venue.handler.validate(venue.propose(key="k2", with_receipt=False))
    serialized = repr(
        [record for _issued, record in venue.proofs.admissions]
        + [item.readback for item, _record in venue.proofs.admissions]
        + [item.authentication_receipts for item, _record in venue.proofs.admissions]
        + [record.model_dump(mode="json") for record in venue.proofs.rejections]
    )
    for marker in ("Bearer", "eyJ", "token-id-", "session_token", "password"):
        assert marker not in serialized
    receipts = [
        r for item, _record in venue.proofs.admissions for r in item.authentication_receipts
    ]
    assert receipts and all(r["token_retained"] is False for r in receipts)
    assert all(
        r["evidence_class"] == OperatorAuthenticationEvidenceClass.LOCAL_LOOPBACK.value
        for r in receipts
    )
