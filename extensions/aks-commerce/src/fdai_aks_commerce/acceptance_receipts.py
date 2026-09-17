"""Public-key-only authentication of retained order-acceptance observation receipts."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from fdai.shared.providers.state_store import StateStore

from fdai_aks_commerce.acceptance import OrderAcceptanceIntent

RECEIPT_PREFIX = "aks-commerce:acceptance-receipt:v1:"
REVOCATION_PREFIX = "aks-commerce:acceptance-trust:v1:"
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_FIELDS = frozenset(
    {
        "type",
        "schema_version",
        "verification_ref",
        "evidence_digest",
        "policy_ref",
        "resource_ref",
        "issuer",
        "source_identity",
        "key_id",
        "verified_at",
        "expires_at",
        "authorization_refs",
        "signature",
    }
)


@dataclass(frozen=True, slots=True)
class AcceptanceTrustBinding:
    """Deployment-pinned public key and independent collector identity, without signing access."""

    issuer: str
    source_identity: str
    public_key: Ed25519PublicKey


def acceptance_receipt_payload(record: Mapping[str, object]) -> bytes:
    """Encode the closed receipt shape deterministically, excluding only its signature."""
    if set(record) != _FIELDS:
        raise ValueError("acceptance receipt fields do not match version 1.0.0")
    return json.dumps(
        {name: value for name, value in record.items() if name != "signature"},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")


class StoredOrderAcceptanceReceiptVerifier:
    """Verify exact, unexpired evidence using pinned keys and a current revocation read.

    Receipt and trust-state reads use the existing state-store adapter. The deployment must grant
    their writer only to the independent observer/trust owner; the analyzer receives read access.
    A signature authenticates the observer's attestation, not the underlying observation itself.
    """

    def __init__(
        self,
        *,
        store: StateStore,
        intent: OrderAcceptanceIntent,
        trust: Mapping[str, AcceptanceTrustBinding],
        executor_identity: str,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not 1 <= len(trust) <= 8 or not executor_identity:
            raise ValueError("acceptance verification requires bounded deployment trust")
        for key_id, binding in trust.items():
            if re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", key_id) is None:
                raise ValueError("acceptance verifier key id is invalid")
            identities = (binding.issuer, binding.source_identity, executor_identity)
            if any(not identity or len(identity) > 512 for identity in identities):
                raise ValueError("acceptance verifier identities must be bounded")
            if len({identity.casefold() for identity in identities}) != 3:
                raise ValueError("acceptance verifier, source and executor must be distinct")
        self._store = store
        self._intent = intent
        self._trust = dict(trust)
        self._clock = clock or (lambda: datetime.now(UTC))

    async def verify(self, *, verification_ref: str, evidence_digest: str) -> bool:
        """Reject malformed, revoked, stale or mismatched receipts; propagate I/O failure."""
        if (
            _DIGEST.fullmatch(verification_ref) is None
            or _DIGEST.fullmatch(evidence_digest) is None
        ):
            return False
        record = await self._store.read_state(RECEIPT_PREFIX + verification_ref)
        if record is None:
            return False
        return await self.verify_record(
            record, verification_ref=verification_ref, evidence_digest=evidence_digest
        )

    async def verify_record(
        self,
        record: Mapping[str, object],
        *,
        verification_ref: str,
        evidence_digest: str,
    ) -> bool:
        """Verify supplied bytes before persistence using the same current trust-state read."""
        if (
            _DIGEST.fullmatch(verification_ref) is None
            or _DIGEST.fullmatch(evidence_digest) is None
            or set(record) != _FIELDS
        ):
            return False
        key_id = record.get("key_id")
        binding = self._trust.get(key_id) if isinstance(key_id, str) else None
        if binding is None:
            return False
        if any(
            record.get(name) != expected
            for name, expected in {
                "type": "aks-commerce.acceptance-receipt",
                "schema_version": "1.0.0",
                "verification_ref": verification_ref,
                "evidence_digest": evidence_digest,
                "policy_ref": self._intent.policy_ref,
                "resource_ref": self._intent.resource_ref,
                "issuer": binding.issuer,
                "source_identity": binding.source_identity,
            }.items()
        ):
            return False
        authorization_refs = record.get("authorization_refs")
        if (
            not isinstance(authorization_refs, list)
            or not 1 <= len(authorization_refs) <= 10
            or any(
                not isinstance(item, str) or not item or len(item) > 512
                for item in authorization_refs
            )
            or len(set(authorization_refs)) != len(authorization_refs)
        ):
            return False
        try:
            verified_at = _time(record["verified_at"])
            expires_at = _time(record["expires_at"])
            now = self._clock()
            if (
                now.tzinfo is None
                or now.utcoffset() is None
                or not self._intent.valid_from
                <= verified_at
                <= now
                < expires_at
                <= self._intent.valid_until
                or expires_at - verified_at > timedelta(seconds=self._intent.max_age_seconds)
            ):
                return False
            signature = record["signature"]
            if not isinstance(signature, str) or re.fullmatch(r"[0-9a-f]{128}", signature) is None:
                return False
            binding.public_key.verify(bytes.fromhex(signature), acceptance_receipt_payload(record))
        except (InvalidSignature, ValueError, TypeError):
            return False
        state = await self._store.read_state(REVOCATION_PREFIX + str(key_id))
        if state is None or set(state) != {"key_id", "revoked", "valid_until"}:
            return False
        try:
            return (
                state["key_id"] == key_id
                and state["revoked"] is False
                and now <= self._clock() < min(expires_at, _time(state["valid_until"]))
            )
        except (ValueError, TypeError):
            return False


def _time(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("acceptance receipt timestamp must be ISO text")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("acceptance receipt timestamp must be timezone-aware")
    return parsed
