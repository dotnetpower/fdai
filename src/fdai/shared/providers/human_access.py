"""Provider-neutral human role-group membership mutation contract."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable

_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,256}$")
_DIGEST_PATTERN = re.compile(r"^[a-f0-9]{64}$")


class HumanAccessOperation(StrEnum):
    GRANT = "grant"
    REVOKE = "revoke"


class HumanAccessOutcome(StrEnum):
    APPLIED = "applied"
    ALREADY_APPLIED = "already_applied"
    ROLLED_BACK = "rolled_back"


@dataclass(frozen=True, slots=True)
class HumanAccessPlan:
    case_id: str
    subject_id: str
    group_id: str
    operation: HumanAccessOperation
    idempotency_key: str

    def __post_init__(self) -> None:
        for name in ("case_id", "subject_id", "group_id", "idempotency_key"):
            value = str(getattr(self, name))
            if not _IDENTIFIER_PATTERN.fullmatch(value):
                raise ValueError(f"HumanAccessPlan.{name} MUST be a bounded safe identifier")

    @property
    def desired_membership(self) -> bool:
        return self.operation is HumanAccessOperation.GRANT


@dataclass(frozen=True, slots=True)
class HumanAccessReceipt:
    outcome: HumanAccessOutcome
    receipt_ref: str
    digest: str

    def __post_init__(self) -> None:
        if not _IDENTIFIER_PATTERN.fullmatch(self.receipt_ref):
            raise ValueError("HumanAccessReceipt.receipt_ref MUST be a bounded safe identifier")
        if not _DIGEST_PATTERN.fullmatch(self.digest):
            raise ValueError("HumanAccessReceipt.digest MUST be a lowercase SHA-256 digest")


@runtime_checkable
class HumanAccessProvisioner(Protocol):
    async def apply(self, plan: HumanAccessPlan) -> HumanAccessReceipt: ...
    async def verify(self, plan: HumanAccessPlan) -> bool: ...
    async def rollback(self, plan: HumanAccessPlan) -> HumanAccessReceipt: ...


__all__ = [
    "HumanAccessOperation",
    "HumanAccessOutcome",
    "HumanAccessPlan",
    "HumanAccessProvisioner",
    "HumanAccessReceipt",
]
