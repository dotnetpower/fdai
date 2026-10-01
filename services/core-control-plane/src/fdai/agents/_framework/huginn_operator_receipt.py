"""Authenticated operator-request receipt verification for Huginn ingress."""

from __future__ import annotations

import hmac
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from fdai_service_contracts.operator_request_receipt import (
    OperatorRequestReceipt,
    OperatorRequestReceiptBody,
    canonical_params_digest,
    operator_request_receipt_signing_bytes,
    verify_operator_request_receipt_with_public_key,
)

from fdai.shared.providers.state_store import StateStore

_REPLAY_PREFIX = "pantheon/huginn/operator-request-receipts/"


class OperatorRequestReceiptVerifier(Protocol):
    """Verify receipt signing bytes without exposing trust-root material."""

    def verify_operator_request_receipt(
        self,
        *,
        receipt: OperatorRequestReceipt,
        signing_bytes: bytes,
    ) -> bool: ...


@dataclass(frozen=True, slots=True)
class OperatorRequestReceiptGate:
    """Fail-closed gate for raw-ingress operator requests."""

    verifier: OperatorRequestReceiptVerifier
    state_store: StateStore
    clock: Callable[[], datetime]
    trusted_producer_public_keys: Mapping[str, str] | None = None

    async def verify(self, raw: Mapping[str, Any]) -> OperatorRequestReceipt:
        """Verify exact binding, expiry, signature, and replay before publication."""

        raw_receipt = raw.get("operator_request_receipt")
        if not isinstance(raw_receipt, Mapping):
            raise ValueError("missing")
        receipt = OperatorRequestReceipt.model_validate(raw_receipt)
        expected = OperatorRequestReceiptBody.model_validate(
            {
                "idempotency_key": raw.get("idempotency_key"),
                "correlation_id": raw.get("correlation_id"),
                "initiator_principal": raw.get("initiator_principal"),
                "action_type": raw.get("action_type"),
                "canonical_params_digest": canonical_params_digest(
                    raw.get("params") if isinstance(raw.get("params"), Mapping) else None
                ),
                "resource_id": raw.get("resource_id"),
                "producer_service_identity": receipt.producer_service_identity,
                "issued_at": receipt.issued_at,
                "expires_at": receipt.expires_at,
            }
        )
        if not hmac.compare_digest(
            receipt.model_dump_json(exclude={"signature", "signature_alg"}),
            OperatorRequestReceipt.create(
                body=expected,
                signature=receipt.signature_bytes(),
            ).model_dump_json(exclude={"signature", "signature_alg"}),
        ):
            raise ValueError("mismatch")
        now = self.clock().astimezone(UTC)
        if now < receipt.issued_at or now >= receipt.expires_at:
            raise ValueError("expired")
        signing_bytes = operator_request_receipt_signing_bytes(expected)
        if self.trusted_producer_public_keys is not None:
            public_key = self.trusted_producer_public_keys.get(receipt.producer_service_identity)
            if public_key is None:
                raise ValueError("unknown_producer")
            verified = verify_operator_request_receipt_with_public_key(
                receipt=receipt,
                signing_bytes=signing_bytes,
                public_key=public_key,
            )
        else:
            verified = self.verifier.verify_operator_request_receipt(
                receipt=receipt,
                signing_bytes=signing_bytes,
            )
        if not verified:
            raise ValueError("unverifiable")
        replay_key = _REPLAY_PREFIX + receipt.receipt_digest
        created = await self.state_store.write_state_if_absent(
            replay_key,
            {
                "schema_version": "1.0.0",
                "kind": "huginn.operator_request_receipt_replay_fence",
                "receipt_digest": receipt.receipt_digest,
                "producer_service_identity": receipt.producer_service_identity,
                "expires_at": receipt.expires_at.isoformat(),
            },
        )
        if not created:
            raise ValueError("replayed")
        return receipt


__all__ = [
    "OperatorRequestReceiptGate",
    "OperatorRequestReceiptVerifier",
]
