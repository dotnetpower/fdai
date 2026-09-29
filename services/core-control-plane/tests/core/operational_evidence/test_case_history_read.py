"""Case-history readback binds semantic authentication receipts to grants."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from fdai.core.operational_evidence.issuance import (
    OperationalEvidenceVerifierEngine,
    VerifierIdentity,
)
from fdai.core.operational_evidence.readback.case_history_read import (
    CaseHistoryReadback,
    SemanticAuthenticationReceiptRow,
)
from fdai_service_contracts.ontology_query import content_digest
from fdai_service_contracts.operational_evidence import (
    OperationalEvidenceIssuanceRequest,
    OperationalEvidenceIssuanceStatus,
    OperationalEvidenceLocator,
    OperationalEvidenceLookup,
    OperationalEvidenceRejectionClass,
)
from fdai_service_contracts.operator_authentication import OperatorAuthenticationEvidenceClass
from tests.core.operational_evidence.support import (
    NOW,
    REQUESTER,
    REQUESTER_GROUP,
    SCOPE,
    MemoryProofStore,
    anchors,
    grant_document,
    history,
    receipt,
)


@dataclass
class _ReceiptSource:
    rows: tuple[SemanticAuthenticationReceiptRow, ...]

    async def receipts_for_request(
        self, receipt_digest: str, request_id: str
    ) -> tuple[SemanticAuthenticationReceiptRow, ...]:
        return tuple(
            row
            for row in self.rows
            if row.receipt_digest == receipt_digest and row.request_id == request_id
        )


@dataclass
class _UnfilteredReceiptSource:
    rows: tuple[SemanticAuthenticationReceiptRow, ...]

    async def receipts_for_request(
        self, receipt_digest: str, request_id: str
    ) -> tuple[SemanticAuthenticationReceiptRow, ...]:
        del request_id
        return tuple(row for row in self.rows if row.receipt_digest == receipt_digest)


def _registry(*, grant_overrides: dict[str, object] | None = None, include_grant: bool = True):
    document = grant_document()
    document["case_scopes"][0]["purposes"] = [
        *document["case_scopes"][0]["purposes"],
        "case-history-read",
    ]
    if include_grant:
        document["principal_grants"].append(
            {
                "grant_id": "g-case-read",
                "selector": {"kind": "group", "value": REQUESTER_GROUP},
                "case_scopes": ["cs-test"],
                "operations": ["case-history.read"],
                "purposes": ["case-history-read"],
                "reviewer": "grant-reviewer-one",
                **document["principal_grants"][0],
                **(grant_overrides or {}),
            }
        )
        document["principal_grants"][-1]["grant_id"] = "g-case-read"
        document["principal_grants"][-1]["operations"] = ["case-history.read"]
        document["principal_grants"][-1]["purposes"] = ["case-history-read"]
    return history(document)


def _request(
    receipt_ref: str,
    *,
    group: str = REQUESTER_GROUP,
    scope: str = SCOPE,
    request_ref: str = "semantic-request-1",
) -> OperationalEvidenceIssuanceRequest:
    arguments = {
        "access_scope_digest": scope,
        "purpose": "operations-review",
        "failure_fingerprint": None,
        "limit": 5,
    }
    context = {
        "caller_agent": "Bragi",
        "caller_role": "reader",
        "purposes": ["operations-review"],
        "principal_ref": REQUESTER,
        "principal_groups": [group],
        "principal_scope_digest": content_digest(
            {"principal": REQUESTER, "purpose": "operations-review"}
        ),
        "authentication_receipt_ref": receipt_ref,
        "authentication_request_ref": "semantic-request-1",
    }
    evidence_digest = content_digest({"arguments": arguments, "principal": context})
    scope_digest = content_digest(
        {
            "principal_scope": context["principal_scope_digest"],
            "case_scope": scope,
            "purpose": "operations-review",
        }
    )
    return OperationalEvidenceIssuanceRequest(
        attempt_id="1" * 32,
        lookup=OperationalEvidenceLookup(
            evidence_digest=evidence_digest,
            scope_digest=scope_digest,
            purpose_id="case-history-read",
            source_revision="sha256:" + "a" * 64,
        ),
        locator=OperationalEvidenceLocator(
            purpose_id="case-history-read",
            coordinates={
                "principal_ref": REQUESTER,
                "request_ref": request_ref,
                "case_scope_digest": "sha256:" + scope,
                "authentication_receipt_ref": receipt_ref,
                "principal_groups_digest": content_digest([group]),
                "purpose": "operations-review",
            },
        ),
        producer_id="core-control-plane",
        producer_version="1.0.0",
        requested_at=NOW,
    )


async def test_case_history_read_issues_with_current_receipt_and_grant() -> None:
    auth = receipt(REQUESTER, REQUESTER_GROUP, ("Reader",), issued_at=NOW)
    source = _ReceiptSource(
        (
            SemanticAuthenticationReceiptRow(
                receipt_digest=auth.receipt_digest,
                request_id="semantic-request-1",
                principal_id=REQUESTER,
                receipt=auth.model_dump(mode="json"),
                recorded_at=NOW,
            ),
        )
    )
    proofs = MemoryProofStore()
    engine = OperationalEvidenceVerifierEngine(
        identity=VerifierIdentity("operational-evidence-verifier", "1.0.0"),
        history=_registry,
        anchors=anchors(),
        readbacks=(CaseHistoryReadback(receipts=source),),
        writer=proofs,
        clock=lambda: NOW,
    )

    response = await engine.issue(_request(auth.receipt_digest), caller_principal="fdai_core")

    assert response.status is OperationalEvidenceIssuanceStatus.ISSUED
    assert proofs.admissions[0][0].purpose_id == "case-history-read"
    assert proofs.admissions[0][0].binding.matched_grants == ("g-case-read",)


async def test_case_history_read_rejects_group_mismatch() -> None:
    auth = receipt(REQUESTER, REQUESTER_GROUP, ("Reader",), issued_at=NOW)
    source = _ReceiptSource(
        (
            SemanticAuthenticationReceiptRow(
                receipt_digest=auth.receipt_digest,
                request_id="semantic-request-1",
                principal_id=REQUESTER,
                receipt=auth.model_dump(mode="json"),
                recorded_at=NOW,
            ),
        )
    )
    proofs = MemoryProofStore()
    engine = OperationalEvidenceVerifierEngine(
        identity=VerifierIdentity("operational-evidence-verifier", "1.0.0"),
        history=_registry,
        anchors=anchors(),
        readbacks=(CaseHistoryReadback(receipts=source),),
        writer=proofs,
        clock=lambda: NOW,
    )

    response = await engine.issue(
        _request(auth.receipt_digest, group="another-group"), caller_principal="fdai_core"
    )

    assert response.status is OperationalEvidenceIssuanceStatus.REJECTED
    assert proofs.rejections[0].rejection_class is OperationalEvidenceRejectionClass.CROSS_SCOPE
    assert proofs.rejections[0].reason_codes == ("principal_groups_mismatch",)


async def test_case_history_read_rejects_stale_receipt() -> None:
    auth = receipt(REQUESTER, REQUESTER_GROUP, ("Reader",), issued_at=NOW - timedelta(hours=2))
    source = _ReceiptSource(
        (
            SemanticAuthenticationReceiptRow(
                receipt_digest=auth.receipt_digest,
                request_id="semantic-request-1",
                principal_id=REQUESTER,
                receipt=auth.model_dump(mode="json"),
                recorded_at=NOW,
            ),
        )
    )
    proofs = MemoryProofStore()
    engine = OperationalEvidenceVerifierEngine(
        identity=VerifierIdentity("operational-evidence-verifier", "1.0.0"),
        history=_registry,
        anchors=anchors(),
        readbacks=(CaseHistoryReadback(receipts=source),),
        writer=proofs,
        clock=lambda: NOW,
    )

    response = await engine.issue(_request(auth.receipt_digest), caller_principal="fdai_core")

    assert response.status is OperationalEvidenceIssuanceStatus.REJECTED
    assert proofs.rejections[0].rejection_class is OperationalEvidenceRejectionClass.STALE


async def test_case_history_read_rejects_missing_grant() -> None:
    auth = receipt(REQUESTER, REQUESTER_GROUP, ("Reader",), issued_at=NOW)
    source = _ReceiptSource(
        (
            SemanticAuthenticationReceiptRow(
                receipt_digest=auth.receipt_digest,
                request_id="semantic-request-1",
                principal_id=REQUESTER,
                receipt=auth.model_dump(mode="json"),
                recorded_at=NOW,
            ),
        )
    )
    proofs = MemoryProofStore()
    engine = OperationalEvidenceVerifierEngine(
        identity=VerifierIdentity("operational-evidence-verifier", "1.0.0"),
        history=lambda: _registry(include_grant=False),
        anchors=anchors(),
        readbacks=(CaseHistoryReadback(receipts=source),),
        writer=proofs,
        clock=lambda: NOW,
    )

    response = await engine.issue(_request(auth.receipt_digest), caller_principal="fdai_core")

    assert response.status is OperationalEvidenceIssuanceStatus.REJECTED
    assert proofs.rejections[0].rejection_class is OperationalEvidenceRejectionClass.CROSS_SCOPE
    assert proofs.rejections[0].reason_codes == ("grant_missing",)


async def test_case_history_read_rejects_revoked_grant() -> None:
    auth = receipt(REQUESTER, REQUESTER_GROUP, ("Reader",), issued_at=NOW)
    source = _ReceiptSource(
        (
            SemanticAuthenticationReceiptRow(
                receipt_digest=auth.receipt_digest,
                request_id="semantic-request-1",
                principal_id=REQUESTER,
                receipt=auth.model_dump(mode="json"),
                recorded_at=NOW,
            ),
        )
    )
    proofs = MemoryProofStore()
    engine = OperationalEvidenceVerifierEngine(
        identity=VerifierIdentity("operational-evidence-verifier", "1.0.0"),
        history=lambda: _registry(grant_overrides={"revoked": True}),
        anchors=anchors(),
        readbacks=(CaseHistoryReadback(receipts=source),),
        writer=proofs,
        clock=lambda: NOW,
    )

    response = await engine.issue(_request(auth.receipt_digest), caller_principal="fdai_core")

    assert response.status is OperationalEvidenceIssuanceStatus.REJECTED
    assert proofs.rejections[0].rejection_class is OperationalEvidenceRejectionClass.REVOKED


async def test_case_history_read_rejects_cross_scope() -> None:
    auth = receipt(REQUESTER, REQUESTER_GROUP, ("Reader",), issued_at=NOW)
    source = _ReceiptSource(
        (
            SemanticAuthenticationReceiptRow(
                receipt_digest=auth.receipt_digest,
                request_id="semantic-request-1",
                principal_id=REQUESTER,
                receipt=auth.model_dump(mode="json"),
                recorded_at=NOW,
            ),
        )
    )
    proofs = MemoryProofStore()
    engine = OperationalEvidenceVerifierEngine(
        identity=VerifierIdentity("operational-evidence-verifier", "1.0.0"),
        history=_registry,
        anchors=anchors(),
        readbacks=(CaseHistoryReadback(receipts=source),),
        writer=proofs,
        clock=lambda: NOW,
    )

    response = await engine.issue(
        _request(auth.receipt_digest, scope="b" * 64), caller_principal="fdai_core"
    )

    assert response.status is OperationalEvidenceIssuanceStatus.REJECTED
    assert proofs.rejections[0].rejection_class is OperationalEvidenceRejectionClass.CROSS_SCOPE


async def test_case_history_read_rejects_replayed_receipt_request() -> None:
    """A source that ignores the request key cannot substitute another request's receipt."""
    auth = receipt(REQUESTER, REQUESTER_GROUP, ("Reader",), issued_at=NOW)
    source = _UnfilteredReceiptSource(
        (
            SemanticAuthenticationReceiptRow(
                receipt_digest=auth.receipt_digest,
                request_id="another-request",
                principal_id=REQUESTER,
                receipt=auth.model_dump(mode="json"),
                recorded_at=NOW,
            ),
        )
    )
    proofs = MemoryProofStore()
    engine = OperationalEvidenceVerifierEngine(
        identity=VerifierIdentity("operational-evidence-verifier", "1.0.0"),
        history=_registry,
        anchors=anchors(),
        readbacks=(CaseHistoryReadback(receipts=source),),
        writer=proofs,
        clock=lambda: NOW,
    )

    response = await engine.issue(_request(auth.receipt_digest), caller_principal="fdai_core")

    assert response.status is OperationalEvidenceIssuanceStatus.REJECTED
    assert (
        proofs.rejections[0].rejection_class is OperationalEvidenceRejectionClass.REPLAY_SUBSTITUTED
    )
    assert proofs.rejections[0].reason_codes == ("authentication_receipt_request_mismatch",)


async def test_case_history_read_rejects_local_loopback_receipt_in_deployed_venue() -> None:
    auth = receipt(
        REQUESTER,
        REQUESTER_GROUP,
        ("Reader",),
        issued_at=NOW,
        evidence_class=OperatorAuthenticationEvidenceClass.LOCAL_LOOPBACK,
    )
    source = _ReceiptSource(
        (
            SemanticAuthenticationReceiptRow(
                receipt_digest=auth.receipt_digest,
                request_id="semantic-request-1",
                principal_id=REQUESTER,
                receipt=auth.model_dump(mode="json"),
                recorded_at=NOW,
            ),
        )
    )
    proofs = MemoryProofStore()
    engine = OperationalEvidenceVerifierEngine(
        identity=VerifierIdentity("operational-evidence-verifier", "1.0.0"),
        history=_registry,
        anchors=anchors(venue="deployed", evidence_class="live"),
        readbacks=(CaseHistoryReadback(receipts=source),),
        writer=proofs,
        clock=lambda: NOW,
    )

    response = await engine.issue(_request(auth.receipt_digest), caller_principal="fdai_core")

    assert response.status is OperationalEvidenceIssuanceStatus.REJECTED
    assert proofs.rejections[0].rejection_class is OperationalEvidenceRejectionClass.SYNTHETIC_LIVE


def _row(auth, request_id: str) -> SemanticAuthenticationReceiptRow:
    return SemanticAuthenticationReceiptRow(
        receipt_digest=auth.receipt_digest,
        request_id=request_id,
        principal_id=REQUESTER,
        receipt=auth.model_dump(mode="json"),
        recorded_at=NOW,
    )


def _engine(source, proofs: MemoryProofStore) -> OperationalEvidenceVerifierEngine:
    return OperationalEvidenceVerifierEngine(
        identity=VerifierIdentity("operational-evidence-verifier", "1.0.0"),
        history=_registry,
        anchors=anchors(),
        readbacks=(CaseHistoryReadback(receipts=source),),
        writer=proofs,
        clock=lambda: NOW,
    )


async def test_case_history_read_resolves_one_token_receipt_per_request() -> None:
    """One bearer token's receipt serves every request that retained it, each exactly once."""
    auth = receipt(REQUESTER, REQUESTER_GROUP, ("Reader",), issued_at=NOW)
    source = _ReceiptSource((_row(auth, "semantic-request-1"), _row(auth, "semantic-request-2")))
    proofs = MemoryProofStore()

    response = await _engine(source, proofs).issue(
        _request(auth.receipt_digest, request_ref="semantic-request-2"),
        caller_principal="fdai_core",
    )

    assert response.status is OperationalEvidenceIssuanceStatus.ISSUED


async def test_case_history_read_rejects_a_receipt_retained_for_another_request() -> None:
    auth = receipt(REQUESTER, REQUESTER_GROUP, ("Reader",), issued_at=NOW)
    proofs = MemoryProofStore()

    response = await _engine(_ReceiptSource((_row(auth, "semantic-request-1"),)), proofs).issue(
        _request(auth.receipt_digest, request_ref="semantic-request-2"),
        caller_principal="fdai_core",
    )

    assert response.status is OperationalEvidenceIssuanceStatus.REJECTED
    assert proofs.rejections[0].rejection_class is OperationalEvidenceRejectionClass.PARTIAL
    assert proofs.rejections[0].reason_codes == ("authentication_receipt_missing",)
