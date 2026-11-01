"""Opaque transport-only Hub entitlement carrier handoff and governed rotation contract.

The Hub is never an entitlement issuer or execution authority. It stages an already-sealed
entitlement carrier onto a lifecycle Plan for a specific installation and deployment binding,
refuses silent replacement without a separately governed rotation receipt, and forbids clearing
or deleting installation entitlement grants.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, NoReturn

from fdai_lifecycle_hub.errors import HubStoreError

_SHA256_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}\Z", re.ASCII)
_MAX_ID_LENGTH = 256
_MAX_REASON_LENGTH = 512
_MAX_CIPHERTEXT_BYTES = 16_384


class EntitlementHandoffGovernanceError(HubStoreError, ValueError):
    """The Hub refused an entitlement handoff, rotation, or deletion request."""


def _require_identifier(name: str, value: object, *, max_length: int = _MAX_ID_LENGTH) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > max_length:
        raise EntitlementHandoffGovernanceError(
            f"{name} MUST be non-empty bounded text (<= {max_length} chars)"
        )
    if value != value.strip():
        raise EntitlementHandoffGovernanceError(
            f"{name} MUST NOT have leading or trailing whitespace"
        )
    return value


def _require_sha256_digest(name: str, value: object) -> str:
    if not isinstance(value, str) or _SHA256_DIGEST.fullmatch(value) is None:
        raise EntitlementHandoffGovernanceError(
            f"{name} MUST be a canonical sha256:<64 hex> digest"
        )
    return value


def _require_positive_int(name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise EntitlementHandoffGovernanceError(f"{name} MUST be a positive integer")
    return value


def _require_aware_datetime(name: str, value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise EntitlementHandoffGovernanceError(f"{name} MUST be a timezone-aware datetime")
    return value


def _require_base64_field(
    name: str,
    value: object,
    *,
    min_bytes: int = 1,
    max_bytes: int = _MAX_CIPHERTEXT_BYTES,
) -> str:
    if not isinstance(value, str) or not value:
        raise EntitlementHandoffGovernanceError(f"{name} MUST be non-empty base64 text")
    try:
        decoded = base64.b64decode(value.encode("ascii"), validate=True)
    except (UnicodeEncodeError, binascii.Error, ValueError) as exc:
        raise EntitlementHandoffGovernanceError(f"{name} MUST be valid canonical base64") from exc
    if not min_bytes <= len(decoded) <= max_bytes:
        raise EntitlementHandoffGovernanceError(
            f"{name} decoded length MUST be between {min_bytes} and {max_bytes} bytes"
        )
    return value


@dataclass(frozen=True, slots=True)
class OpaqueEntitlementCarrierHandoff:
    """Opaque encrypted entitlement carrier staged onto a Hub Plan without issuer authority."""

    handoff_id: str
    installation_id: str
    deployment_id: str
    plan_id: str
    carrier_digest: str
    ciphertext_b64: str
    ephemeral_public_key_b64: str
    nonce_b64: str
    sequence: int
    recorded_at: datetime
    hub_is_issuer: Literal[False] = False
    execution_authority: Literal["none"] = "none"

    def __post_init__(self) -> None:
        _require_identifier("handoff_id", self.handoff_id)
        _require_identifier("installation_id", self.installation_id)
        _require_identifier("deployment_id", self.deployment_id)
        _require_identifier("plan_id", self.plan_id)
        _require_sha256_digest("carrier_digest", self.carrier_digest)
        _require_base64_field("ciphertext_b64", self.ciphertext_b64, min_bytes=1)
        _require_base64_field(
            "ephemeral_public_key_b64",
            self.ephemeral_public_key_b64,
            min_bytes=1,
            max_bytes=128,
        )
        _require_base64_field("nonce_b64", self.nonce_b64, min_bytes=1, max_bytes=64)
        _require_positive_int("sequence", self.sequence)
        _require_aware_datetime("recorded_at", self.recorded_at)
        if self.hub_is_issuer is not False:
            raise EntitlementHandoffGovernanceError(
                "Hub is transport-only and MUST NOT claim entitlement issuer authority"
            )
        if self.execution_authority != "none":
            raise EntitlementHandoffGovernanceError(
                "Hub entitlement handoff MUST NOT carry execution authority"
            )

    def to_plan_attachment(self) -> dict[str, object]:
        """Serialize the opaque Plan handoff payload for transport to the installation agent."""
        return {
            "schema_version": "fdai.hub.entitlement-plan-handoff.v1",
            "handoff_id": self.handoff_id,
            "installation_id": self.installation_id,
            "deployment_id": self.deployment_id,
            "plan_id": self.plan_id,
            "carrier_digest": self.carrier_digest,
            "ciphertext_b64": self.ciphertext_b64,
            "ephemeral_public_key_b64": self.ephemeral_public_key_b64,
            "nonce_b64": self.nonce_b64,
            "sequence": self.sequence,
            "recorded_at": self.recorded_at.astimezone(UTC).isoformat(),
            "hub_is_issuer": False,
            "execution_authority": "none",
        }


@dataclass(frozen=True, slots=True)
class GovernedEntitlementRotationReceipt:
    """Separately governed approval receipt permitting one exact carrier digest transition."""

    rotation_id: str
    installation_id: str
    deployment_id: str
    prior_carrier_digest: str
    next_carrier_digest: str
    sequence: int
    approver_id: str
    requester_id: str
    approval_digest: str
    reason: str
    approved_at: datetime

    def __post_init__(self) -> None:
        _require_identifier("rotation_id", self.rotation_id)
        _require_identifier("installation_id", self.installation_id)
        _require_identifier("deployment_id", self.deployment_id)
        _require_sha256_digest("prior_carrier_digest", self.prior_carrier_digest)
        _require_sha256_digest("next_carrier_digest", self.next_carrier_digest)
        _require_positive_int("sequence", self.sequence)
        _require_identifier("approver_id", self.approver_id)
        _require_identifier("requester_id", self.requester_id)
        _require_sha256_digest("approval_digest", self.approval_digest)
        _require_identifier("reason", self.reason, max_length=_MAX_REASON_LENGTH)
        _require_aware_datetime("approved_at", self.approved_at)
        if self.approver_id == self.requester_id:
            raise EntitlementHandoffGovernanceError(
                "governed entitlement rotation forbids self-approval (approver_id == requester_id)"
            )
        if self.prior_carrier_digest == self.next_carrier_digest:
            raise EntitlementHandoffGovernanceError(
                "governed entitlement rotation requires distinct prior and next carrier digests"
            )

    def to_audit_entry(self) -> dict[str, object]:
        """Return the canonical audit representation for the rotation approval."""
        payload = {
            "rotation_id": self.rotation_id,
            "installation_id": self.installation_id,
            "deployment_id": self.deployment_id,
            "prior_carrier_digest": self.prior_carrier_digest,
            "next_carrier_digest": self.next_carrier_digest,
            "sequence": self.sequence,
            "approver_id": self.approver_id,
            "requester_id": self.requester_id,
            "approval_digest": self.approval_digest,
            "reason": self.reason,
            "approved_at": self.approved_at.astimezone(UTC).isoformat(),
            "hub_is_issuer": False,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return {
            **payload,
            "receipt_digest": "sha256:" + hashlib.sha256(encoded).hexdigest(),
        }


class HubEntitlementHandoffStore:
    """In-memory and audit-backed store for Hub Plan entitlement handoffs and governed rotations."""

    def __init__(self) -> None:
        self._active_by_installation: dict[str, OpaqueEntitlementCarrierHandoff] = {}
        self._by_plan_id: dict[str, OpaqueEntitlementCarrierHandoff] = {}
        self._pending_rotation_by_installation: dict[str, GovernedEntitlementRotationReceipt] = {}
        self._rotation_history: dict[str, list[GovernedEntitlementRotationReceipt]] = {}
        self._audit_log: list[dict[str, object]] = []

    @property
    def audit_log(self) -> tuple[dict[str, object], ...]:
        """Return the append-only governance audit log."""
        return tuple(dict(entry) for entry in self._audit_log)

    def get_handoff(self, installation_id: str) -> OpaqueEntitlementCarrierHandoff | None:
        """Return the current staged handoff for an installation, if any."""
        _require_identifier("installation_id", installation_id)
        return self._active_by_installation.get(installation_id)

    def get_plan_handoff(self, plan_id: str) -> OpaqueEntitlementCarrierHandoff | None:
        """Return the opaque entitlement handoff attached to a specific Plan ID."""
        _require_identifier("plan_id", plan_id)
        return self._by_plan_id.get(plan_id)

    def rotation_history(
        self, installation_id: str
    ) -> tuple[GovernedEntitlementRotationReceipt, ...]:
        """Return all governed rotation receipts recorded for an installation."""
        _require_identifier("installation_id", installation_id)
        return tuple(self._rotation_history.get(installation_id, ()))

    def stage_plan_handoff(
        self,
        handoff: OpaqueEntitlementCarrierHandoff | None = None,
        **kwargs: object,
    ) -> OpaqueEntitlementCarrierHandoff:
        """Bind an opaque entitlement carrier to a Plan without minting or reinterpreting grants."""
        if handoff is None:
            try:
                candidate = OpaqueEntitlementCarrierHandoff(**kwargs)  # type: ignore[arg-type]
            except TypeError as exc:
                raise EntitlementHandoffGovernanceError(
                    "stage_plan_handoff requires an OpaqueEntitlementCarrierHandoff or all fields"
                ) from exc
        elif isinstance(handoff, OpaqueEntitlementCarrierHandoff) and not kwargs:
            candidate = handoff
        else:
            raise EntitlementHandoffGovernanceError(
                "handoff MUST be an OpaqueEntitlementCarrierHandoff instance"
            )

        existing = self._active_by_installation.get(candidate.installation_id)
        if existing is None:
            self._active_by_installation[candidate.installation_id] = candidate
            self._by_plan_id[candidate.plan_id] = candidate
            self._audit_log.append(
                {"event": "hub.entitlement_handoff.staged", **candidate.to_plan_attachment()}
            )
            return candidate

        if existing.deployment_id != candidate.deployment_id:
            raise EntitlementHandoffGovernanceError(
                "entitlement handoff cannot rebind installation to a different deployment_id"
            )
        if existing.carrier_digest == candidate.carrier_digest:
            if (
                existing.ciphertext_b64 != candidate.ciphertext_b64
                or existing.ephemeral_public_key_b64 != candidate.ephemeral_public_key_b64
                or existing.nonce_b64 != candidate.nonce_b64
            ):
                raise EntitlementHandoffGovernanceError(
                    "idempotent entitlement replay cannot alter carrier cryptographic fields"
                )
            self._by_plan_id.setdefault(candidate.plan_id, existing)
            return existing

        pending = self._pending_rotation_by_installation.get(candidate.installation_id)
        if pending is None:
            raise EntitlementHandoffGovernanceError(
                "automatic entitlement replacement is forbidden without a governed rotation receipt"
            )
        if (
            pending.prior_carrier_digest != existing.carrier_digest
            or pending.next_carrier_digest != candidate.carrier_digest
            or pending.deployment_id != candidate.deployment_id
        ):
            raise EntitlementHandoffGovernanceError(
                "staged carrier digest does not match the governed rotation receipt"
            )
        if candidate.sequence < pending.sequence or candidate.sequence <= existing.sequence:
            raise EntitlementHandoffGovernanceError(
                "rotated entitlement handoff sequence MUST advance monotonically"
            )

        del self._pending_rotation_by_installation[candidate.installation_id]
        self._active_by_installation[candidate.installation_id] = candidate
        self._by_plan_id[candidate.plan_id] = candidate
        self._audit_log.append(
            {
                "event": "hub.entitlement_handoff.rotated",
                "rotation_id": pending.rotation_id,
                **candidate.to_plan_attachment(),
            }
        )
        return candidate

    def record_governed_rotation(
        self,
        receipt: GovernedEntitlementRotationReceipt | None = None,
        **kwargs: object,
    ) -> GovernedEntitlementRotationReceipt:
        """Validate and record a separately governed rotation receipt for an active installation."""
        if receipt is None:
            try:
                validated = GovernedEntitlementRotationReceipt(**kwargs)  # type: ignore[arg-type]
            except TypeError as exc:
                raise EntitlementHandoffGovernanceError(
                    "record_governed_rotation requires a receipt or all rotation fields"
                ) from exc
        elif isinstance(receipt, GovernedEntitlementRotationReceipt) and not kwargs:
            validated = receipt
        else:
            raise EntitlementHandoffGovernanceError(
                "receipt MUST be a GovernedEntitlementRotationReceipt instance"
            )

        existing = self._active_by_installation.get(validated.installation_id)
        if existing is None:
            raise EntitlementHandoffGovernanceError(
                "governed rotation requires an existing staged entitlement handoff"
            )
        if existing.deployment_id != validated.deployment_id:
            raise EntitlementHandoffGovernanceError(
                "governed rotation deployment_id does not match the active installation binding"
            )
        if existing.carrier_digest != validated.prior_carrier_digest:
            raise EntitlementHandoffGovernanceError(
                "governed rotation prior_carrier_digest does not match active carrier_digest"
            )
        history = self._rotation_history.get(validated.installation_id, [])
        highest_sequence = max([existing.sequence, *(item.sequence for item in history)])
        if validated.sequence <= highest_sequence:
            raise EntitlementHandoffGovernanceError(
                "governed rotation sequence MUST strictly exceed "
                "current handoff and prior rotations"
            )

        self._pending_rotation_by_installation[validated.installation_id] = validated
        self._rotation_history.setdefault(validated.installation_id, []).append(validated)
        self._audit_log.append(
            {"event": "hub.entitlement_rotation.recorded", **validated.to_audit_entry()}
        )
        return validated

    def delete_entitlement(self, *args: object, **kwargs: object) -> NoReturn:
        """Explicitly forbid entitlement deletion on the Hub."""
        del args, kwargs
        raise EntitlementHandoffGovernanceError(
            "Hub cannot clear or delete installation entitlement grants"
        )

    def clear_entitlement(self, *args: object, **kwargs: object) -> NoReturn:
        """Explicitly forbid entitlement clearing on the Hub."""
        del args, kwargs
        raise EntitlementHandoffGovernanceError(
            "Hub cannot clear or delete installation entitlement grants"
        )


__all__ = [
    "EntitlementHandoffGovernanceError",
    "GovernedEntitlementRotationReceipt",
    "HubEntitlementHandoffStore",
    "OpaqueEntitlementCarrierHandoff",
]
