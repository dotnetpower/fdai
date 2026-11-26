"""Operator-side signing for Core ingress request receipts."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from fdai_service_contracts.operator_request_receipt import (
    OperatorRequestReceipt,
    operator_request_receipt_body_from_event,
    operator_request_receipt_signing_bytes,
    sign_operator_request_receipt,
)


class OperatorRequestReceiptSigner(Protocol):
    """Sign canonical Operator request receipt bytes."""

    def sign_operator_request_receipt(self, signing_bytes: bytes) -> bytes: ...


@dataclass(frozen=True, slots=True)
class OperatorRequestReceiptIssuer:
    """Issue bounded signed receipts for flat operator_request events."""

    signer: OperatorRequestReceiptSigner
    producer_service_identity: str
    clock: Callable[[], datetime]
    lifetime: timedelta = timedelta(minutes=5)

    def issue(self, event: dict[str, object]) -> OperatorRequestReceipt:
        """Return a signature-bound receipt for the exact event fields."""

        issued_at = self.clock().astimezone(UTC)
        body = operator_request_receipt_body_from_event(
            event,
            producer_service_identity=self.producer_service_identity,
            issued_at=issued_at,
            expires_at=issued_at + self.lifetime,
        )
        if isinstance(self.signer, SeedOperatorRequestReceiptSigner):
            return self.signer.issue(
                event=event,
                producer_service_identity=self.producer_service_identity,
                issued_at=issued_at,
                expires_at=issued_at + self.lifetime,
            )
        signature = self.signer.sign_operator_request_receipt(
            operator_request_receipt_signing_bytes(body)
        )
        return OperatorRequestReceipt.create(body=body, signature=signature)


class SeedOperatorRequestReceiptSigner:
    """Sign receipts with a deployment-provided Ed25519 seed."""

    def __init__(self, private_key_seed: str) -> None:
        self._private_key_seed = private_key_seed

    def sign_operator_request_receipt(self, signing_bytes: bytes) -> bytes:
        raise NotImplementedError(
            "SeedOperatorRequestReceiptSigner signs through OperatorRequestReceiptIssuer"
        )

    def issue(
        self,
        *,
        event: dict[str, object],
        producer_service_identity: str,
        issued_at: datetime,
        expires_at: datetime,
    ) -> OperatorRequestReceipt:
        return sign_operator_request_receipt(
            event,
            producer_service_identity=producer_service_identity,
            private_key_seed=self._private_key_seed,
            issued_at=issued_at,
            expires_at=expires_at,
        )


__all__ = [
    "OperatorRequestReceiptIssuer",
    "OperatorRequestReceiptSigner",
    "SeedOperatorRequestReceiptSigner",
]
