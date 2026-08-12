"""Secured query receipt issuance authority tests."""

from __future__ import annotations

from fdai.core.ontology_platform.functions import FunctionInvocationContext
from fdai.core.ontology_platform.query_receipt_authority import SecuredQueryReceiptAuthority
from fdai.shared.contracts.models import CeilingRole
from tests.core.ontology_platform.test_network_path import _resource, _secured_result


def _context(digest: str) -> FunctionInvocationContext:
    return FunctionInvocationContext(
        caller_agent="Bragi",
        caller_role=CeilingRole.READER,
        purposes=("network-path-verification",),
        evidence_refs=(digest,),
    )


def test_only_issued_receipt_and_opaque_context_are_accepted() -> None:
    result = _secured_result(objects=(_resource("resource-a", "network.nic"),), links=())
    authority = SecuredQueryReceiptAuthority()
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
    authority.issue(result)
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
    authority = SecuredQueryReceiptAuthority(max_receipts=1)
    authority.issue(first)
    authority.issue(second)

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
