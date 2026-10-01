"""Authenticated operator-request receipt verification for Huginn ingress."""

from __future__ import annotations

import hmac
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import uuid4

from fdai_service_contracts.operator_request_receipt import (
    OperatorRequestReceipt,
    OperatorRequestReceiptBody,
    canonical_params_digest,
    canonical_workflow_action_digest,
    operator_request_receipt_signing_bytes,
    verify_operator_request_receipt_with_public_key,
)

from fdai.shared.providers.state_store import StateStore, StateStoreKeysetReader

_REPLAY_PREFIX = "pantheon/huginn/operator-request-receipts/"
_REPLAY_SUMMARY_KEY = "pantheon/huginn/operator-request-receipt-summary"
_REPLAY_CLEANUP_LIMIT = 128
_REPLAY_CLOCK_SKEW = timedelta(minutes=2)


class OperatorRequestReceiptVerifier(Protocol):
    """Verify receipt signing bytes without exposing trust-root material."""

    def verify_operator_request_receipt(
        self,
        *,
        receipt: OperatorRequestReceipt,
        signing_bytes: bytes,
    ) -> bool: ...


@dataclass(frozen=True, slots=True)
class VerifiedOperatorRequestReceipt:
    """Receipt verified against the raw request but not yet replay-fenced."""

    receipt: OperatorRequestReceipt
    replay_key: str


@dataclass(frozen=True, slots=True)
class ReservedOperatorRequestReceipt:
    """Durable pending replay fence held by one publish attempt."""

    verified: VerifiedOperatorRequestReceipt
    reservation_id: str


@dataclass(frozen=True, slots=True)
class OperatorRequestReceiptGate:
    """Fail-closed gate for raw-ingress operator requests."""

    verifier: OperatorRequestReceiptVerifier
    state_store: StateStore
    clock: Callable[[], datetime]
    trusted_producer_public_keys: Mapping[str, str] | None = None

    cleanup_limit: int = _REPLAY_CLEANUP_LIMIT
    clock_skew: timedelta = _REPLAY_CLOCK_SKEW

    async def verify(self, raw: Mapping[str, Any]) -> VerifiedOperatorRequestReceipt:
        """Verify exact binding, expiry, signature, and live replay state."""

        raw_receipt = raw.get("operator_request_receipt")
        if not isinstance(raw_receipt, Mapping):
            raise ValueError("missing")
        receipt = OperatorRequestReceipt.model_validate(raw_receipt)
        workflow_action = raw.get("workflow_action")
        if receipt.schema_version == "1.0.0" and isinstance(workflow_action, Mapping):
            raise ValueError("unsigned_workflow_action")
        expected = OperatorRequestReceiptBody.model_validate(
            {
                "schema_version": receipt.schema_version,
                "idempotency_key": raw.get("idempotency_key"),
                "correlation_id": raw.get("correlation_id"),
                "initiator_principal": raw.get("initiator_principal"),
                "action_type": raw.get("action_type"),
                "canonical_params_digest": canonical_params_digest(
                    raw.get("params") if isinstance(raw.get("params"), Mapping) else None
                ),
                "resource_id": raw.get("resource_id"),
                "canonical_workflow_action_digest": (
                    canonical_workflow_action_digest(
                        workflow_action if isinstance(workflow_action, Mapping) else None
                    )
                    if receipt.schema_version == "1.1.0"
                    else None
                ),
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
        replay_key = _replay_key(receipt)
        existing = await self.state_store.read_state(replay_key)
        if existing is not None:
            raise ValueError("replayed")
        return VerifiedOperatorRequestReceipt(receipt=receipt, replay_key=replay_key)

    async def reserve(
        self,
        verified: VerifiedOperatorRequestReceipt,
    ) -> ReservedOperatorRequestReceipt:
        """Durably reserve one verified receipt before authority-bearing publication."""

        receipt = verified.receipt
        await self.cleanup_expired()
        now = self.clock().astimezone(UTC)
        if now >= receipt.expires_at:
            raise ValueError("expired")
        reservation_id = str(uuid4())
        created = await self.state_store.write_state_if_absent(
            verified.replay_key,
            {
                "schema_version": "1.0.0",
                "kind": "huginn.operator_request_receipt_replay_fence",
                "state": "pending",
                "replay_key": verified.replay_key,
                "reservation_id": reservation_id,
                "receipt_digest": receipt.receipt_digest,
                "producer_service_identity": receipt.producer_service_identity,
                "issued_at": receipt.issued_at.isoformat(),
                "expires_at": receipt.expires_at.isoformat(),
                "reserved_at": now.isoformat(),
                "revision": 1,
            },
        )
        if not created:
            existing = await self.state_store.read_state(verified.replay_key)
            if _expired(existing or {}, now=now, skew=self.clock_skew):
                await self.state_store.delete_state(verified.replay_key)
                return await self.reserve(verified)
            raise ValueError("replayed")
        return ReservedOperatorRequestReceipt(
            verified=verified,
            reservation_id=reservation_id,
        )

    async def finalize(
        self,
        reserved: ReservedOperatorRequestReceipt,
    ) -> OperatorRequestReceipt:
        """Commit one pending replay fence after publication is durably checkpointed."""

        receipt = reserved.verified.receipt
        now = self.clock().astimezone(UTC)
        existing = await self.state_store.read_state(reserved.verified.replay_key)
        if not _is_pending_reservation(existing, reserved.reservation_id):
            raise ValueError("replayed")
        if now >= receipt.expires_at + self.clock_skew:
            raise ValueError("expired")
        finalized = {
            **dict(existing or {}),
            "state": "committed",
            "committed_at": now.isoformat(),
            "revision": 2,
        }
        if not await self.state_store.compare_and_set_state(
            reserved.verified.replay_key,
            finalized,
            expected_revision=1,
        ):
            raise ValueError("replayed")
        await self.cleanup_expired()
        return receipt

    async def release(self, reserved: ReservedOperatorRequestReceipt) -> bool:
        """Release one pending reservation after publication fails before visibility."""

        existing = await self.state_store.read_state(reserved.verified.replay_key)
        if not _is_pending_reservation(existing, reserved.reservation_id):
            return False
        return await self.state_store.delete_state(reserved.verified.replay_key)

    async def commit(self, verified: VerifiedOperatorRequestReceipt) -> OperatorRequestReceipt:
        """Reserve and commit one verified receipt before a non-publication side effect."""

        return await self.finalize(await self.reserve(verified))

    async def cleanup_expired(self) -> int:
        """Compact expired replay rows and retain a bounded audit summary."""

        if not isinstance(self.state_store, StateStoreKeysetReader):
            raise RuntimeError("operator request receipt cleanup requires keyset state reads")
        now = self.clock().astimezone(UTC)
        deleted = 0
        keys = await self.state_store.read_state_keys(_REPLAY_PREFIX, limit=self.cleanup_limit)
        for replay_key in keys:
            row = await self.state_store.read_state(replay_key)
            if row is None:
                continue
            if row.get("kind") != "huginn.operator_request_receipt_replay_fence" or not _expired(
                row,
                now=now,
                skew=self.clock_skew,
            ):
                break
            if await self.state_store.delete_state(replay_key):
                deleted += 1
        if deleted:
            summary = await self.state_store.read_state(_REPLAY_SUMMARY_KEY)
            prior_expired = int(summary.get("expired_rows", 0)) if summary else 0
            await self.state_store.write_state(
                _REPLAY_SUMMARY_KEY,
                {
                    "schema_version": "1.0.0",
                    "kind": "huginn.operator_request_receipt_replay_fence_summary",
                    "expired_rows": prior_expired + deleted,
                    "last_compacted_at": now.isoformat(),
                },
            )
        return deleted


def _expired(row: Mapping[str, Any], *, now: datetime, skew: timedelta) -> bool:
    raw_expires_at = row.get("expires_at")
    if not isinstance(raw_expires_at, str):
        return False
    try:
        expires_at = datetime.fromisoformat(raw_expires_at)
    except ValueError:
        return False
    if expires_at.tzinfo is None or expires_at.utcoffset() is None:
        return False
    return expires_at.astimezone(UTC) + skew <= now


def _is_pending_reservation(row: Mapping[str, Any] | None, reservation_id: str) -> bool:
    return (
        row is not None
        and row.get("kind") == "huginn.operator_request_receipt_replay_fence"
        and row.get("state") == "pending"
        and row.get("reservation_id") == reservation_id
        and row.get("revision") == 1
    )


def _replay_key(receipt: OperatorRequestReceipt) -> str:
    expires_at = receipt.expires_at.astimezone(UTC)
    expiry_token = expires_at.strftime("%Y%m%dT%H%M%S.%fZ")
    return f"{_REPLAY_PREFIX}{expiry_token}/{receipt.receipt_digest}"


__all__ = [
    "OperatorRequestReceiptGate",
    "OperatorRequestReceiptVerifier",
    "ReservedOperatorRequestReceipt",
    "VerifiedOperatorRequestReceipt",
]
