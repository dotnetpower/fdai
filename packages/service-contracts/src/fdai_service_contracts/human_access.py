"""Provider-neutral membership plans, receipts and ports without execution authority.

The receipt target digest preserves the original Core wire identity. The separate
membership lock excludes case, operation and retry identity: different requests
for the same normalized subject/group must serialize at the actual effect target.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable

_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,256}$")
_DIGEST_PATTERN = re.compile(r"^[a-f0-9]{64}$")


class HumanAccessOperation(StrEnum):
    """One allowlisted membership direction, never an arbitrary directory operation."""

    GRANT = "grant"
    REVOKE = "revoke"


class HumanAccessOutcome(StrEnum):
    """Provider acknowledgement; independent observation still gates assignment success."""

    APPLIED = "applied"
    ALREADY_APPLIED = "already_applied"
    ROLLED_BACK = "rolled_back"


def parse_human_access_role_groups(raw: str) -> dict[str, str]:
    """Require one complete normalized role map at both Core and Executor configuration boundaries."""
    if len(raw) > 4096:
        raise ValueError("human access role-group configuration exceeds its bound")

    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in items:
            if key in result:
                raise ValueError("human access role-group configuration has duplicate keys")
            result[key] = value
        return result

    payload = json.loads(raw, object_pairs_hook=pairs)
    if (
        not isinstance(payload, dict)
        or set(payload) != {"Reader", "Contributor", "Approver", "Owner"}
        or any(
            not isinstance(value, str) or re.fullmatch(r"[a-z0-9._:-]{1,256}", value) is None
            for value in payload.values()
        )
        or len(set(payload.values())) != 4
    ):
        raise ValueError("human access requires four exact normalized distinct routine role groups")
    return payload


@dataclass(frozen=True, slots=True)
class HumanAccessPlan:
    """An exact private membership target; constructing it grants no authority or identity."""

    case_id: str
    subject_id: str
    group_id: str
    operation: HumanAccessOperation
    idempotency_key: str

    def __post_init__(self) -> None:
        for name in ("case_id", "subject_id", "group_id", "idempotency_key"):
            value = getattr(self, name)
            if not isinstance(value, str) or not _IDENTIFIER_PATTERN.fullmatch(value):
                raise ValueError(f"HumanAccessPlan.{name} MUST be a bounded safe identifier")
        if not isinstance(self.operation, HumanAccessOperation):
            raise ValueError("HumanAccessPlan.operation MUST be a typed membership operation")

    @property
    def target_digest(self) -> str:
        """Keep legacy case/subject/group/operation receipt identity byte-compatible."""
        return _digest(
            {
                "case_id": self.case_id,
                "subject_id": self.subject_id,
                "group_id": self.group_id,
                "operation": self.operation.value,
            }
        )

    @property
    def membership_lock_key(self) -> str:
        """Serialize all cases and both operations on the same normalized Entra membership."""
        target = _digest(
            {
                "provider": "entra",
                "subject_id": self.subject_id.casefold(),
                "group_id": self.group_id.casefold(),
            }
        )
        return f"fdai:resource:human-membership:{target}"

    @property
    def desired_membership(self) -> bool:
        """Return the expected membership value, not an observed postcondition."""
        return self.operation is HumanAccessOperation.GRANT


@dataclass(frozen=True, slots=True)
class HumanAccessReceipt:
    """Content-free exact provider acknowledgement, never independent effect proof."""

    outcome: HumanAccessOutcome
    receipt_ref: str
    digest: str

    def __post_init__(self) -> None:
        if not isinstance(self.outcome, HumanAccessOutcome):
            raise ValueError("HumanAccessReceipt.outcome MUST be a typed acknowledgement")
        if not isinstance(self.receipt_ref, str) or not _IDENTIFIER_PATTERN.fullmatch(
            self.receipt_ref
        ):
            raise ValueError("HumanAccessReceipt.receipt_ref MUST be a bounded safe identifier")
        if not isinstance(self.digest, str) or not _DIGEST_PATTERN.fullmatch(self.digest):
            raise ValueError("HumanAccessReceipt.digest MUST be a lowercase SHA-256 digest")


@runtime_checkable
class HumanAccessProvisioner(Protocol):
    """Mutation port restricted to an independently authorized Executor composition."""

    async def apply(self, plan: HumanAccessPlan) -> HumanAccessReceipt:
        """Dispatch the exact membership; acknowledgement cannot activate a case."""
        ...

    async def verify(self, plan: HumanAccessPlan) -> bool:
        """Check provider state without claiming independent observer authority."""
        ...

    async def rollback(self, plan: HumanAccessPlan) -> HumanAccessReceipt:
        """Restore only a proven owned mutation under its reviewed recovery contract."""
        ...


def _digest(value: dict[str, str]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


__all__ = [
    "HumanAccessOperation",
    "HumanAccessOutcome",
    "HumanAccessPlan",
    "HumanAccessProvisioner",
    "HumanAccessReceipt",
    "parse_human_access_role_groups",
]
