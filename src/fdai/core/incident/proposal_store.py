"""Atomic pending-proposal store for cross-replica incident confirmation."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Protocol, runtime_checkable

from fdai.shared.contracts.models import IncidentSeverity

from .intent import IncidentCreationProposal

ProposalTakeStatus = Literal["found", "missing", "expired"]


@dataclass(frozen=True, slots=True)
class ProposalTakeResult:
    """Atomic consume result for one operator/session proposal key."""

    status: ProposalTakeStatus
    proposal: IncidentCreationProposal | None = None


@runtime_checkable
class IncidentProposalStore(Protocol):
    """Persist and atomically consume pending incident proposals."""

    async def save(
        self,
        *,
        operator_id: str,
        session_id: str,
        proposal: IncidentCreationProposal,
    ) -> None: ...

    async def take(
        self,
        *,
        operator_id: str,
        session_id: str,
        now: datetime,
    ) -> ProposalTakeResult: ...


class InMemoryIncidentProposalStore:
    """Bounded atomic proposal store for tests and single-process local use."""

    def __init__(self, *, capacity: int = 1_000) -> None:
        if capacity < 1:
            raise ValueError("incident proposal store capacity MUST be >= 1")
        self._capacity = capacity
        self._entries: dict[tuple[str, str], IncidentCreationProposal] = {}
        self._lock = asyncio.Lock()

    async def save(
        self,
        *,
        operator_id: str,
        session_id: str,
        proposal: IncidentCreationProposal,
    ) -> None:
        key = _proposal_key(operator_id, session_id)
        if proposal.requested_by != operator_id:
            raise ValueError("incident proposal requester MUST match operator_id")
        async with self._lock:
            self._entries[key] = proposal
            while len(self._entries) > self._capacity:
                oldest = min(self._entries, key=lambda item: self._entries[item].expires_at)
                self._entries.pop(oldest, None)

    async def take(
        self,
        *,
        operator_id: str,
        session_id: str,
        now: datetime,
    ) -> ProposalTakeResult:
        key = _proposal_key(operator_id, session_id)
        _require_aware(now, "now")
        async with self._lock:
            proposal = self._entries.pop(key, None)
        if proposal is None:
            return ProposalTakeResult(status="missing")
        if now > proposal.expires_at:
            return ProposalTakeResult(status="expired")
        return ProposalTakeResult(status="found", proposal=proposal)


def _proposal_key(operator_id: str, session_id: str) -> tuple[str, str]:
    if not operator_id:
        raise ValueError("incident proposal operator_id MUST be non-empty")
    if not session_id:
        raise ValueError("incident proposal session_id MUST be non-empty")
    return operator_id, session_id


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None:
        raise ValueError(f"incident proposal {name} MUST be timezone-aware")


def proposal_to_record(proposal: IncidentCreationProposal) -> dict[str, object]:
    """Serialize a pending proposal into a stable JSON-compatible record."""
    return {
        "schema_version": "1.0.0",
        "requested_by": proposal.requested_by,
        "correlation_keys": list(proposal.correlation_keys),
        "severity": proposal.severity.value,
        "source_sha256": hashlib.sha256(proposal.source_text.encode("utf-8")).hexdigest(),
        "requested_at": proposal.requested_at.isoformat(),
        "expires_at": proposal.expires_at.isoformat(),
    }


def proposal_from_record(record: Mapping[str, Any]) -> IncidentCreationProposal:
    """Validate and deserialize one untrusted persistence record."""
    try:
        if record.get("schema_version") != "1.0.0":
            raise ValueError("unsupported schema_version")
        requested_by = _required_string(record, "requested_by")
        source_sha256 = _required_string(record, "source_sha256")
        if len(source_sha256) != 64 or any(
            character not in "0123456789abcdef" for character in source_sha256
        ):
            raise ValueError("source_sha256 MUST be a lowercase SHA-256 digest")
        raw_keys = record["correlation_keys"]
        if (
            not isinstance(raw_keys, list)
            or not raw_keys
            or not all(isinstance(key, str) and key for key in raw_keys)
        ):
            raise ValueError("correlation_keys MUST be a non-empty string list")
        severity = IncidentSeverity(_required_string(record, "severity"))
        requested_at = datetime.fromisoformat(_required_string(record, "requested_at"))
        expires_at = datetime.fromisoformat(_required_string(record, "expires_at"))
        if requested_at.tzinfo is None or expires_at.tzinfo is None:
            raise ValueError("proposal timestamps MUST be timezone-aware")
        if expires_at <= requested_at:
            raise ValueError("expires_at MUST be later than requested_at")
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"invalid incident proposal record: {exc}") from exc
    return IncidentCreationProposal(
        requested_by=requested_by,
        correlation_keys=tuple(raw_keys),
        severity=severity,
        source_text="",
        requested_at=requested_at,
        expires_at=expires_at,
    )


def _required_string(record: Mapping[str, Any], key: str) -> str:
    value = record[key]
    if not isinstance(value, str) or not value:
        raise ValueError(f"{key} MUST be a non-empty string")
    return value


__all__ = [
    "IncidentProposalStore",
    "InMemoryIncidentProposalStore",
    "ProposalTakeResult",
    "ProposalTakeStatus",
    "proposal_from_record",
    "proposal_to_record",
]
