"""Independent signing and append-only trust lifecycle for acceptance evidence."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta
from types import MappingProxyType

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fdai.shared.providers.state_store import StateStore

from fdai_aks_commerce.acceptance import (
    OrderAcceptanceEvidence,
    OrderAcceptanceIntent,
    evaluate_order_acceptance,
)
from fdai_aks_commerce.acceptance_receipts import (
    REVOCATION_PREFIX,
    TRUST_REVOCATION_PREFIX,
    acceptance_receipt_payload,
)

_KEY_ID = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")
_REASON = re.compile(r"[a-z][a-z0-9._-]{0,127}")


@dataclass(frozen=True, slots=True)
class IssuedAcceptanceEvidence:
    """Qualified evidence plus its closed independently signed receipt."""

    evidence: OrderAcceptanceEvidence
    receipt: Mapping[str, object]


class AcceptanceReceiptIssuer:
    """Sign already-collected evidence without source, trust-owner, or executor authority."""

    def __init__(
        self,
        *,
        private_key: Ed25519PrivateKey,
        key_id: str,
        issuer_identity: str,
        source_identity: str,
        executor_identity: str,
        intent: OrderAcceptanceIntent,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        identities = (issuer_identity, source_identity, executor_identity)
        if _KEY_ID.fullmatch(key_id) is None:
            raise ValueError("acceptance issuer key id is invalid")
        if any(not value or value != value.strip() or len(value) > 512 for value in identities):
            raise ValueError("acceptance issuer identities must be exact and bounded")
        if len({value.casefold() for value in identities}) != len(identities):
            raise ValueError("acceptance issuer, source and executor identities must be distinct")
        self._private_key = private_key
        self._key_id = key_id
        self._issuer_identity = issuer_identity
        self._source_identity = source_identity
        self._executor_identity = executor_identity
        self._intent = intent
        self._clock = clock or (lambda: datetime.now(UTC))

    @property
    def executor_identity(self) -> str:
        """Expose lineage for composition checks without exposing signing material."""
        return self._executor_identity

    def issue(self, evidence: OrderAcceptanceEvidence) -> IssuedAcceptanceEvidence:
        """Bind one qualified observation and issue a short-lived closed receipt."""
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("acceptance issuer clock must be timezone-aware")
        reference = _verification_ref(evidence)
        bound = replace(evidence, verification_ref=reference)
        assessment = evaluate_order_acceptance(
            self._intent,
            bound,
            now=now,
            window_seconds=self._intent.max_age_seconds,
        )
        if assessment.status == "held":
            raise ValueError("acceptance issuer cannot sign unqualified evidence")
        expires_at = min(
            self._intent.valid_until,
            now + timedelta(seconds=self._intent.max_age_seconds),
        )
        if expires_at <= now:
            raise ValueError("acceptance issuer validity window is closed")
        authorization_refs = sorted({probe.authorization_ref for probe in bound.probes})
        receipt: dict[str, object] = {
            "type": "aks-commerce.acceptance-receipt",
            "schema_version": "1.0.0",
            "verification_ref": reference,
            "evidence_digest": assessment.evidence_digest,
            "policy_ref": self._intent.policy_ref,
            "resource_ref": self._intent.resource_ref,
            "issuer": self._issuer_identity,
            "source_identity": self._source_identity,
            "key_id": self._key_id,
            "verified_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
            "authorization_refs": authorization_refs,
            "signature": "",
        }
        receipt["signature"] = self._private_key.sign(acceptance_receipt_payload(receipt)).hex()
        return IssuedAcceptanceEvidence(bound, MappingProxyType(receipt))


class AcceptanceTrustLifecycle:
    """Activate and revoke one verifier key through immutable audited records."""

    def __init__(
        self,
        *,
        store: StateStore,
        key_id: str,
        trust_owner_identity: str,
        issuer_identity: str,
        source_identity: str,
        executor_identity: str,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        identities = (
            trust_owner_identity,
            issuer_identity,
            source_identity,
            executor_identity,
        )
        if _KEY_ID.fullmatch(key_id) is None:
            raise ValueError("acceptance trust key id is invalid")
        if any(not value or value != value.strip() or len(value) > 512 for value in identities):
            raise ValueError("acceptance trust identities must be exact and bounded")
        if len({value.casefold() for value in identities}) != len(identities):
            raise ValueError("acceptance trust owner, issuer, source and executor must be distinct")
        self._store = store
        self._key_id = key_id
        self._owner = trust_owner_identity
        self._clock = clock or (lambda: datetime.now(UTC))

    async def activate(self, *, valid_until: datetime) -> None:
        """Activate a new key id once; rotation uses another key id."""
        now = self._now()
        if valid_until.tzinfo is None or valid_until.utcoffset() is None or valid_until <= now:
            raise ValueError("acceptance trust validity must end in the future")
        value = {
            "key_id": self._key_id,
            "revoked": False,
            "valid_until": valid_until.isoformat(),
        }
        created = await self._store.write_state_with_audit_if_absent(
            REVOCATION_PREFIX + self._key_id,
            value,
            {
                "actor": self._owner,
                "action_kind": "aks_commerce.acceptance_trust.activated",
                "key_id": self._key_id,
                "execution_authority": False,
            },
        )
        if not created and await self._store.read_state(REVOCATION_PREFIX + self._key_id) != value:
            raise ValueError("acceptance trust key id already binds different activation")

    async def revoke(self, *, reason_code: str) -> None:
        """Append one terminal revocation marker without rewriting activation history."""
        if _REASON.fullmatch(reason_code) is None:
            raise ValueError("acceptance trust revocation reason code is invalid")
        key = TRUST_REVOCATION_PREFIX + self._key_id
        existing = await self._store.read_state(key)
        if existing is not None:
            if (
                existing.get("key_id") == self._key_id
                and existing.get("reason_code") == reason_code
                and isinstance(existing.get("revoked_at"), str)
            ):
                return
            raise ValueError("acceptance trust key id already has another revocation")
        now = self._now()
        value = {
            "key_id": self._key_id,
            "reason_code": reason_code,
            "revoked_at": now.isoformat(),
        }
        created = await self._store.write_state_with_audit_if_absent(
            key,
            value,
            {
                "actor": self._owner,
                "action_kind": "aks_commerce.acceptance_trust.revoked",
                "key_id": self._key_id,
                "reason_code": reason_code,
                "execution_authority": False,
            },
        )
        if not created:
            retained = await self._store.read_state(key)
            if (
                retained is None
                or retained.get("key_id") != self._key_id
                or retained.get("reason_code") != reason_code
                or not isinstance(retained.get("revoked_at"), str)
            ):
                raise ValueError("acceptance trust key id already has another revocation")

    def _now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("acceptance trust clock must be timezone-aware")
        return now


def _verification_ref(evidence: OrderAcceptanceEvidence) -> str:
    payload = asdict(evidence)
    payload["verification_ref"] = ""
    encoded = json.dumps(
        payload,
        default=lambda value: value.isoformat() if isinstance(value, datetime) else value,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


__all__ = [
    "TRUST_REVOCATION_PREFIX",
    "AcceptanceReceiptIssuer",
    "AcceptanceTrustLifecycle",
    "IssuedAcceptanceEvidence",
]
