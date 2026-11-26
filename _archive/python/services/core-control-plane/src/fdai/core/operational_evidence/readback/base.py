"""Shared readback contracts between the verifier engine and source-specific readbacks."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from fdai_service_contracts.operational_evidence import OperationalEvidenceIssuanceRequest

from ..grant_registry import CaseScopeGrantRegistry
from ..rejections import ReadbackRejection
from ..revision_history import LineageBinding, RegistryHistory
from ..trust_registry import PurposeTrust, Venue


class ReadbackUnavailableError(RuntimeError):
    """A declared source cannot be read now; the attempt ends as unavailable."""


@dataclass(frozen=True, slots=True)
class ReadbackFacts:
    """Content-free facts the verifier derived only from sources it read itself.

    Every mapping must hold JSON-native values only; the engine content-addresses each one
    as the subject of exactly one proof.
    """

    evidence_digest: str
    source_identity: str
    authentication: Mapping[str, object]
    completeness: Mapping[str, object]
    conflict: Mapping[str, object]
    provenance: Mapping[str, object]
    event_at: datetime
    evidence_cutoff: datetime
    valid_until_cap: datetime | None = None
    matched_grants: tuple[str, ...] = field(default_factory=tuple)
    authentication_receipts: tuple[Mapping[str, object], ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class LineageRecord:
    """A prior admission the verifier itself wrote, read back for lineage checks."""

    purpose_id: str
    lookup_digest: str
    receipt_digest: str
    pins_digest: str
    binding: LineageBinding
    verified_at: datetime
    valid_until: datetime


class ProofLineageReader(Protocol):
    """Read the verifier's own immutable admissions by receipt digest."""

    async def admission_by_receipt(self, receipt_digest: str) -> LineageRecord | None: ...


@dataclass(frozen=True, slots=True)
class ReadbackContext:
    """Everything a readback may consult; none of it comes from the requester's body."""

    request: OperationalEvidenceIssuanceRequest
    trust: PurposeTrust
    grants: CaseScopeGrantRegistry
    history: RegistryHistory
    venue: Venue
    read_at: datetime
    clock: Callable[[], datetime]
    lineage: ProofLineageReader | None = None

    @property
    def access_scope_digest(self) -> str:
        """Return the opaque scope named by the exact lookup, without its prefix."""

        return self.request.lookup.scope_digest.removeprefix("sha256:")


class PurposeReadback(Protocol):
    """Read one purpose's authoritative sources under the verifier's own identity."""

    purposes: frozenset[str]

    async def read(self, context: ReadbackContext) -> ReadbackFacts | ReadbackRejection: ...


__all__ = [
    "LineageRecord",
    "ProofLineageReader",
    "PurposeReadback",
    "ReadbackContext",
    "ReadbackFacts",
    "ReadbackRejection",
    "ReadbackUnavailableError",
]
