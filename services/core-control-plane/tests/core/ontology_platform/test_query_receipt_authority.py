"""Secured query receipt issuance authority tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from fdai.core.ontology_platform.functions import FunctionInvocationContext
from fdai.core.ontology_platform.query_gateway import SecuredObjectSetQueryResult
from fdai.core.ontology_platform.query_receipt_authority import (
    SecuredQueryReceiptAuthority,
    secured_query_scope_digest,
)
from fdai.shared.contracts.models import CeilingRole
from fdai.shared.providers.decision_evidence_verifier import DecisionEvidenceAdmission
from tests.core.ontology_platform.test_network_path import _resource, _secured_result

_NOW = datetime(2026, 8, 29, 8, 0, tzinfo=UTC)


def _context(digest: str) -> FunctionInvocationContext:
    return FunctionInvocationContext(
        caller_agent="Bragi",
        caller_role=CeilingRole.READER,
        purposes=("network-path-verification",),
        evidence_refs=(digest,),
    )


def _admission(result: SecuredObjectSetQueryResult) -> DecisionEvidenceAdmission:
    receipt = result.receipt
    return DecisionEvidenceAdmission(
        receipt_digest="sha256:" + "d" * 64,
        verification_bundle_digest="sha256:" + "e" * 64,
        evidence_digest=receipt.projected_result_digest,
        scope_digest=secured_query_scope_digest(receipt),
        purpose_id=receipt.purpose,
        source_revision=receipt.ontology_release.digest,
        verified_at=_NOW - timedelta(minutes=1),
        valid_until=_NOW + timedelta(minutes=1),
    )


def _authority(*, max_receipts: int = 4096) -> SecuredQueryReceiptAuthority:
    return SecuredQueryReceiptAuthority(max_receipts=max_receipts, now=lambda: _NOW)


def test_only_issued_receipt_and_opaque_context_are_accepted() -> None:
    result = _secured_result(objects=(_resource("resource-a", "network.nic"),), links=())
    authority = _authority()
    digest = result.receipt.projected_result_digest
    arguments = {
        "receipt": result.receipt,
        "invocation_context": _context(digest),
        "expected_release": result.receipt.ontology_release,
        "expected_purpose": result.receipt.purpose,
        "expected_result_digest": digest,
    }

    assert (
        authority.verify(**arguments, verification_context=authority.verification_context) is False
    )
    authority.issue(result, _admission(result))
    assert (
        authority.verify(**arguments, verification_context=authority.verification_context) is True
    )
    assert authority.verify(**arguments, verification_context=object()) is False


def test_receipt_bound_evicts_oldest_issue() -> None:
    first = _secured_result(objects=(_resource("resource-a", "network.nic"),), links=())
    second = _secured_result(
        objects=(_resource("resource-b", "network.nic"),),
        links=(),
        complete=False,
    )
    authority = _authority(max_receipts=1)
    authority.issue(first, _admission(first))
    authority.issue(second, _admission(second))

    first_digest = first.receipt.projected_result_digest
    assert (
        authority.verify(
            receipt=first.receipt,
            invocation_context=_context(first_digest),
            expected_release=first.receipt.ontology_release,
            expected_purpose=first.receipt.purpose,
            expected_result_digest=first_digest,
            verification_context=authority.verification_context,
        )
        is False
    )


def test_output_receipt_marker_selects_one_result_from_preserved_lineage() -> None:
    first = _secured_result(objects=(_resource("resource-a", "network.nic"),), links=())
    second = _secured_result(objects=(_resource("resource-b", "network.nic"),), links=())
    authority = _authority()
    authority.issue(first, _admission(first))
    authority.issue(second, _admission(second))

    resolved = authority.resolve(
        (
            f"ontology-object-set:{first.receipt.projected_result_digest}",
            f"ontology-object-set:{second.receipt.projected_result_digest}",
            f"ontology-object-set-output:{second.receipt.projected_result_digest}",
        )
    )

    assert resolved.receipt.projected_result_digest == second.receipt.projected_result_digest


def test_issued_receipt_accepts_an_exact_multi_dependency_context() -> None:
    first = _secured_result(objects=(_resource("resource-a", "network.nic"),), links=())
    second = _secured_result(objects=(_resource("resource-b", "network.nic"),), links=())
    authority = _authority()
    authority.issue(first, _admission(first))
    authority.issue(second, _admission(second))
    context = _context(first.receipt.projected_result_digest).model_copy(
        update={
            "evidence_refs": (
                first.receipt.projected_result_digest,
                second.receipt.projected_result_digest,
            )
        }
    )

    assert authority.verify(
        receipt=second.receipt,
        invocation_context=context,
        expected_release=second.receipt.ontology_release,
        expected_purpose=second.receipt.purpose,
        expected_result_digest=second.receipt.projected_result_digest,
        verification_context=authority.verification_context,
    )


def test_unverified_mismatched_or_expired_admission_fails_closed() -> None:
    result = _secured_result(objects=(_resource("resource-a", "network.nic"),), links=())
    digest = result.receipt.projected_result_digest
    arguments = {
        "receipt": result.receipt,
        "invocation_context": _context(digest),
        "expected_release": result.receipt.ontology_release,
        "expected_purpose": result.receipt.purpose,
        "expected_result_digest": digest,
    }

    for admission in (
        None,
        replace(_admission(result), evidence_digest="sha256:" + "f" * 64),
        DecisionEvidenceAdmission(
            receipt_digest="sha256:" + "d" * 64,
            verification_bundle_digest="sha256:" + "e" * 64,
            evidence_digest=digest,
            scope_digest=secured_query_scope_digest(result.receipt),
            purpose_id=result.receipt.purpose,
            source_revision=result.receipt.ontology_release.digest,
            verified_at=_NOW - timedelta(minutes=2),
            valid_until=_NOW - timedelta(minutes=1),
        ),
    ):
        authority = _authority()
        authority.issue(result, admission)
        assert (
            authority.verify(
                **arguments,
                verification_context=authority.verification_context,
            )
            is False
        )
        try:
            authority.resolve((f"ontology-object-set-output:{digest}",))
        except PermissionError as exc:
            assert "verified decision evidence" in str(exc)
        else:  # pragma: no cover - explicit fail-closed assertion
            raise AssertionError("unverified query result resolved")
