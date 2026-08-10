from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fdai.core.ontology_platform.functions import FunctionInvocationContext
from fdai.core.ontology_platform.query_gateway import (
    ObjectSetRedactionSummary,
    SecuredObjectSetQueryReceipt,
)
from fdai.delivery.ontology_query_receipts import HmacNetworkQueryReceiptAuthority
from fdai.shared.contracts.models import CeilingRole, OntologyReleaseRef

_NOW = datetime(2026, 8, 10, tzinfo=UTC)
_RELEASE = OntologyReleaseRef(digest="sha256:" + "a" * 64)
_RESULT = "sha256:" + "b" * 64


def _receipt() -> SecuredObjectSetQueryReceipt:
    return SecuredObjectSetQueryReceipt(
        ontology_release=_RELEASE,
        projected_result_digest=_RESULT,
        purpose="network-path-verification",
        caller_role=CeilingRole.READER,
        observation_cutoff=_NOW,
        as_of_skew_seconds=0,
        returned_object_count=2,
        returned_link_count=1,
        complete=True,
        truncated=False,
        redactions=ObjectSetRedactionSummary(
            objects_with_redactions=0,
            redacted_identity_count=0,
            access_scope_count=0,
            purpose_binding_count=0,
            undeclared_property_count=0,
            links_with_redactions=0,
            redacted_link_property_count=0,
            removed_link_count=0,
        ),
    )


def _invocation() -> FunctionInvocationContext:
    return FunctionInvocationContext(
        caller_agent="Forseti",
        caller_role=CeilingRole.READER,
        purposes=("network-path-verification",),
        evidence_refs=(_RESULT,),
    )


def _verify(
    authority: HmacNetworkQueryReceiptAuthority,
    receipt: SecuredObjectSetQueryReceipt,
    *,
    context: object | None = None,
) -> bool:
    return authority.verify(
        receipt=receipt,
        invocation_context=_invocation(),
        expected_release=_RELEASE,
        expected_purpose="network-path-verification",
        expected_result_digest=_RESULT,
        verification_context=(authority.verification_context if context is None else context),
    )


def test_authority_accepts_only_issuer_sealed_receipt() -> None:
    authority = HmacNetworkQueryReceiptAuthority(
        key=b"k" * 32,
        clock=lambda: _NOW,
    )
    receipt = _receipt()

    assert _verify(authority, receipt) is False

    authority.issue(receipt)

    assert _verify(authority, receipt) is True


def test_authority_rejects_wrong_opaque_context_and_other_issuer() -> None:
    authority = HmacNetworkQueryReceiptAuthority(key=b"k" * 32, clock=lambda: _NOW)
    other = HmacNetworkQueryReceiptAuthority(key=b"k" * 32, clock=lambda: _NOW)
    receipt = _receipt()
    authority.issue(receipt)

    assert _verify(authority, receipt, context=object()) is False
    assert _verify(other, receipt) is False


def test_authority_expires_receipt_without_persisting_secret_or_seal() -> None:
    clock = [_NOW]
    authority = HmacNetworkQueryReceiptAuthority(
        key=b"k" * 32,
        max_receipt_age=timedelta(minutes=5),
        clock=lambda: clock[0],
    )
    receipt = _receipt()
    authority.issue(receipt)
    clock[0] = _NOW + timedelta(minutes=6)

    assert _verify(authority, receipt) is False
