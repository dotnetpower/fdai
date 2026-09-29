"""Bind a published HIL decision to the Operator's durable decision receipt.

The Operator records every human decision under ``operator-hil-decision:<approval_id>`` in the
shared state store. It writes that receipt in the same transaction that locks and validates the
pending park, and only then enqueues the broker message. A message on ``fdai.hil.decisions`` is
therefore transport, not authority: Core may route a decision only when the durable receipt it
names records the same approval, park idempotency key, receipt reference, decision, approver,
justification, and development attestation.

Anyone who can publish to the topic can forge a message, but not the receipt. A missing,
malformed, or divergent receipt refuses the message before any park, quorum slot, or executor is
touched, so a forged approval can neither dispatch nor consume the pending approval.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum
from typing import Any, Final

from fdai_service_contracts.development_approval import DEVELOPMENT_APPROVAL_ATTESTATION_FIELD

OPERATOR_RECEIPT_PREFIX: Final[str] = "operator-hil-decision:"


class OperatorReceiptRefusal(StrEnum):
    """Why a published decision does not match its durable Operator receipt."""

    MISSING = "receipt_missing"
    MALFORMED = "receipt_malformed"
    APPROVAL_MISMATCH = "approval_mismatch"
    IDENTITY_MISMATCH = "identity_mismatch"
    DECISION_MISMATCH = "decision_mismatch"
    APPROVER_MISMATCH = "approver_mismatch"
    JUSTIFICATION_MISMATCH = "justification_mismatch"
    DECIDED_AT_MISMATCH = "decided_at_mismatch"
    ATTESTATION_MISMATCH = "attestation_mismatch"


def operator_receipt_key(approval_id: str) -> str:
    """Return the shared-store key of the Operator's receipt for one approval."""
    return OPERATOR_RECEIPT_PREFIX + approval_id


def operator_receipt_refusal(
    receipt: object,
    message: Mapping[str, Any],
) -> OperatorReceiptRefusal | None:
    """Return why ``message`` is not backed by ``receipt``, or ``None`` when it is.

    ``message`` is the decoded ``fdai.hil.decisions`` payload. Every compared field must be
    present and equal on both sides. The approver comparison is case-insensitive because the
    Operator stores the approver normalized. ``decided_at`` must name the same timezone-aware
    instant, because the Operator may render one instant with a different UTC offset and Core
    records the published timestamp in quorum claims and audit.
    """
    if receipt is None:
        return OperatorReceiptRefusal.MISSING
    if not isinstance(receipt, Mapping):
        return OperatorReceiptRefusal.MALFORMED
    if not _same_text(receipt.get("approval_id"), message.get("approval_id")):
        return OperatorReceiptRefusal.APPROVAL_MISMATCH
    if not _same_text(receipt.get("idempotency_key"), message.get("idempotency_key")) or (
        not _same_text(receipt.get("receipt_ref"), message.get("receipt_ref"))
    ):
        return OperatorReceiptRefusal.IDENTITY_MISMATCH
    if not _same_text(receipt.get("decision"), message.get("decision")):
        return OperatorReceiptRefusal.DECISION_MISMATCH
    if not _same_principal(receipt.get("approver_oid"), message.get("approver_oid")):
        return OperatorReceiptRefusal.APPROVER_MISMATCH
    if not _same_optional_text(receipt.get("justification"), message.get("justification")):
        return OperatorReceiptRefusal.JUSTIFICATION_MISMATCH
    if not _same_instant(receipt.get("decided_at"), message.get("decided_at")):
        return OperatorReceiptRefusal.DECIDED_AT_MISMATCH
    recorded = receipt.get(DEVELOPMENT_APPROVAL_ATTESTATION_FIELD)
    published = message.get(DEVELOPMENT_APPROVAL_ATTESTATION_FIELD)
    if recorded is None and published is None:
        return None
    if (
        not isinstance(recorded, Mapping)
        or not isinstance(published, Mapping)
        or dict(recorded) != dict(published)
    ):
        return OperatorReceiptRefusal.ATTESTATION_MISMATCH
    return None


def _same_text(recorded: object, published: object) -> bool:
    return isinstance(recorded, str) and bool(recorded) and recorded == published


def _same_principal(recorded: object, published: object) -> bool:
    if not isinstance(recorded, str) or not isinstance(published, str):
        return False
    normalized = recorded.strip().casefold()
    return bool(normalized) and normalized == published.strip().casefold()


def _same_instant(recorded: object, published: object) -> bool:
    recorded_at = _aware_instant(recorded)
    return recorded_at is not None and recorded_at == _aware_instant(published)


def _aware_instant(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.utcoffset() is not None else None


def _same_optional_text(recorded: object, published: object) -> bool:
    recorded_text = "" if recorded is None else recorded
    published_text = "" if published is None else published
    return isinstance(recorded_text, str) and recorded_text == published_text


__all__ = [
    "OPERATOR_RECEIPT_PREFIX",
    "OperatorReceiptRefusal",
    "operator_receipt_key",
    "operator_receipt_refusal",
]
