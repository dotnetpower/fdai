from __future__ import annotations

from typing import Any

import pytest
from fdai.core.hil_resume.operator_receipt import (
    OPERATOR_RECEIPT_PREFIX,
    OperatorReceiptRefusal,
    operator_receipt_key,
    operator_receipt_refusal,
)


def _message(**overrides: Any) -> dict[str, Any]:
    message: dict[str, Any] = {
        "approval_id": "approval-1",
        "idempotency_key": "park-key-1",
        "decision": "approve",
        "approver_oid": "approver-a",
        "justification": "Reviewed the exact action.",
        "decided_at": "2026-09-29T01:00:00+00:00",
        "receipt_ref": "operator-receipt-1",
    }
    message.update(overrides)
    return message


def _receipt(**overrides: Any) -> dict[str, Any]:
    receipt = {**_message(), "already_recorded": False, "delivered": True}
    receipt.update(overrides)
    return receipt


def test_receipt_key_matches_the_operator_record() -> None:
    assert OPERATOR_RECEIPT_PREFIX == "operator-hil-decision:"
    assert operator_receipt_key("approval-1") == "operator-hil-decision:approval-1"


def test_matching_receipt_admits_the_published_decision() -> None:
    assert operator_receipt_refusal(_receipt(), _message()) is None


def test_decided_at_compares_instants_not_renderings() -> None:
    assert (
        operator_receipt_refusal(_receipt(), _message(decided_at="2026-09-29T10:00:00+09:00"))
        is None
    )
    assert operator_receipt_refusal(_receipt(), _message(decided_at="2026-09-29T01:00:00Z")) is None


@pytest.mark.parametrize(
    ("recorded", "published"),
    [
        ("2026-09-29T01:00:00+00:00", "2026-09-29T01:00:01+00:00"),
        ("2026-09-29T01:00:00+00:00", None),
        (None, "2026-09-29T01:00:00+00:00"),
        (None, None),
        ("2026-09-29T01:00:00+00:00", "not-a-timestamp"),
        ("2026-09-29T01:00:00", "2026-09-29T01:00:00"),
        ("2026-09-29T01:00:00+00:00", 1_790_000_000),
    ],
)
def test_decided_at_must_name_the_same_aware_instant(recorded: object, published: object) -> None:
    receipt = _receipt(decided_at=recorded)
    message = _message(decided_at=published)
    if recorded is None:
        del receipt["decided_at"]
    if published is None:
        del message["decided_at"]

    assert operator_receipt_refusal(receipt, message) is OperatorReceiptRefusal.DECIDED_AT_MISMATCH


def test_approver_comparison_ignores_case_and_surrounding_space() -> None:
    assert operator_receipt_refusal(_receipt(), _message(approver_oid=" Approver-A ")) is None


@pytest.mark.parametrize(
    ("receipt", "expected"),
    [
        (None, OperatorReceiptRefusal.MISSING),
        ("approve", OperatorReceiptRefusal.MALFORMED),
        (_receipt(approval_id="approval-2"), OperatorReceiptRefusal.APPROVAL_MISMATCH),
        (_receipt(idempotency_key="park-key-2"), OperatorReceiptRefusal.IDENTITY_MISMATCH),
        (_receipt(receipt_ref="operator-receipt-2"), OperatorReceiptRefusal.IDENTITY_MISMATCH),
        (_receipt(decision="reject"), OperatorReceiptRefusal.DECISION_MISMATCH),
        (_receipt(approver_oid="approver-b"), OperatorReceiptRefusal.APPROVER_MISMATCH),
        (_receipt(justification="Other reason."), OperatorReceiptRefusal.JUSTIFICATION_MISMATCH),
    ],
)
def test_divergent_or_missing_receipt_refuses_the_decision(
    receipt: object,
    expected: OperatorReceiptRefusal,
) -> None:
    assert operator_receipt_refusal(receipt, _message()) is expected


@pytest.mark.parametrize("field", ["approval_id", "idempotency_key", "receipt_ref", "decision"])
def test_identity_fields_absent_on_both_sides_never_match(field: str) -> None:
    receipt = _receipt()
    message = _message()
    del receipt[field]
    del message[field]

    assert operator_receipt_refusal(receipt, message) is not None


def test_empty_approver_never_matches() -> None:
    assert (
        operator_receipt_refusal(_receipt(approver_oid=" "), _message(approver_oid=" "))
        is OperatorReceiptRefusal.APPROVER_MISMATCH
    )


def test_missing_justification_matches_only_an_empty_one() -> None:
    receipt = _receipt()
    message = _message()
    del receipt["justification"]
    del message["justification"]

    assert operator_receipt_refusal(receipt, message) is None
    assert operator_receipt_refusal(receipt, _message(justification="")) is None
    assert (
        operator_receipt_refusal(receipt, _message(justification=7))
        is OperatorReceiptRefusal.JUSTIFICATION_MISMATCH
    )


def test_development_attestation_must_match_exactly() -> None:
    attestation = {"approval_id": "approval-1", "block_digest": "sha256:abc"}
    recorded = _receipt(development_attestation=attestation)

    assert (
        operator_receipt_refusal(recorded, _message(development_attestation=dict(attestation)))
        is None
    )
    assert (
        operator_receipt_refusal(recorded, _message())
        is OperatorReceiptRefusal.ATTESTATION_MISMATCH
    )
    assert (
        operator_receipt_refusal(_receipt(), _message(development_attestation=attestation))
        is OperatorReceiptRefusal.ATTESTATION_MISMATCH
    )
    assert (
        operator_receipt_refusal(
            recorded,
            _message(development_attestation={**attestation, "block_digest": "sha256:def"}),
        )
        is OperatorReceiptRefusal.ATTESTATION_MISMATCH
    )
    assert (
        operator_receipt_refusal(
            _receipt(development_attestation="x"),
            _message(development_attestation="x"),
        )
        is OperatorReceiptRefusal.ATTESTATION_MISMATCH
    )
