"""Secured query receipt issuance authority tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.ontology_platform.functions import FunctionInvocationContext
from fdai.core.ontology_platform.query_gateway import (
    SecuredObjectSetQueryResult,
    _projected_result_digest,
)
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


def _presentation_result(
    *, role: CeilingRole = CeilingRole.READER, scope: str | None = None
) -> SecuredObjectSetQueryResult:
    original = _secured_result(objects=(_resource("resource-a", "network.nic"),), links=())
    definition = original.materialization.definition.model_copy(
        update={"purpose": "operations-review"}
    )
    materialization = original.materialization.model_copy(update={"definition": definition})
    return original.model_copy(
        update={
            "materialization": materialization,
            "receipt": original.receipt.model_copy(
                update={
                    "purpose": "operations-review",
                    "caller_role": role,
                    "principal_scope_digest": scope,
                    "projected_result_digest": _projected_result_digest(materialization),
                }
            ),
        }
    )


def test_presentation_read_accepts_only_exact_bragi_operations_scope() -> None:
    result = _presentation_result()
    digest = result.receipt.projected_result_digest
    authority = _authority()
    authority.issue(result)

    resolved = authority.resolve_presentation_read(
        (f"ontology-object-set:{digest}",),
        invocation_context=FunctionInvocationContext(
            caller_agent="Bragi",
            caller_role=result.receipt.caller_role,
            purposes=("operations-review",),
        ),
        expected_release=result.receipt.ontology_release,
        expected_purpose="operations-review",
    )

    assert resolved == result
    for context, purpose in (
        (
            FunctionInvocationContext(
                caller_agent="Thor",
                caller_role=result.receipt.caller_role,
                purposes=("operations-review",),
            ),
            "operations-review",
        ),
        (
            FunctionInvocationContext(
                caller_agent="Bragi",
                caller_role=result.receipt.caller_role,
                purposes=("scenario-review",),
            ),
            "scenario-review",
        ),
    ):
        try:
            authority.resolve_presentation_read(
                (f"ontology-object-set:{digest}",),
                invocation_context=context,
                expected_release=result.receipt.ontology_release,
                expected_purpose=purpose,
            )
        except PermissionError as exc:
            assert "presentation read dependency scope does not match" in str(exc)
        else:  # pragma: no cover - explicit fail-closed assertion
            raise AssertionError("mismatched presentation read scope resolved")


def test_identical_results_are_isolated_by_role_and_principal_scope() -> None:
    results = tuple(
        _presentation_result(role=role, scope="sha256:" + marker * 64)
        for role, marker in (
            (CeilingRole.READER, "a"),
            (CeilingRole.OWNER, "a"),
            (CeilingRole.READER, "b"),
        )
    )
    authority = SecuredQueryReceiptAuthority(now=lambda: results[0].receipt.observation_cutoff)
    for result in results:
        authority.issue(result)
    for result in results:
        assert (
            authority.resolve_presentation_read(
                (f"ontology-object-set:{result.receipt.projected_result_digest}",),
                invocation_context=FunctionInvocationContext(
                    caller_agent="Bragi",
                    caller_role=result.receipt.caller_role,
                    purposes=("operations-review",),
                    principal_scope_digest=result.receipt.principal_scope_digest,
                ),
                expected_release=result.receipt.ontology_release,
                expected_purpose="operations-review",
            )
            == result
        )
    with pytest.raises(PermissionError, match="one issued ObjectSet"):
        authority.resolve((f"ontology-object-set:{results[0].receipt.projected_result_digest}",))


@pytest.mark.parametrize("age_seconds", [-1, 91])
def test_scoped_presentation_receipt_rejects_future_or_expired_evidence(age_seconds: int) -> None:
    result = _presentation_result(scope="sha256:" + "a" * 64)
    authority = SecuredQueryReceiptAuthority(
        now=lambda: result.receipt.observation_cutoff + timedelta(seconds=age_seconds)
    )
    authority.issue(result)
    with pytest.raises(PermissionError, match="validity window"):
        authority.resolve_presentation_read(
            (f"ontology-object-set:{result.receipt.projected_result_digest}",),
            invocation_context=FunctionInvocationContext(
                caller_agent="Bragi",
                caller_role=CeilingRole.READER,
                purposes=("operations-review",),
                principal_scope_digest=result.receipt.principal_scope_digest,
            ),
            expected_release=result.receipt.ontology_release,
            expected_purpose="operations-review",
        )


def test_presentation_receipt_rejects_another_principal_before_returning_rows() -> None:
    result = _presentation_result(scope="sha256:" + "a" * 64)
    authority = SecuredQueryReceiptAuthority(now=lambda: result.receipt.observation_cutoff)
    authority.issue(result)
    with pytest.raises(PermissionError, match="one issued ObjectSet"):
        authority.resolve_presentation_read(
            (f"ontology-object-set:{result.receipt.projected_result_digest}",),
            invocation_context=FunctionInvocationContext(
                caller_agent="Bragi",
                caller_role=CeilingRole.READER,
                purposes=("operations-review",),
                principal_scope_digest="sha256:" + "b" * 64,
            ),
            expected_release=result.receipt.ontology_release,
            expected_purpose="operations-review",
        )
