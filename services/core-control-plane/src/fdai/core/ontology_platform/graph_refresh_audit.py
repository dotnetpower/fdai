"""Audit contract for graph-first semantic evidence refresh decisions."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from .graph_evidence_refresh import GraphEvidenceRefreshDecision


class GraphEvidenceStatus(StrEnum):
    """Preserve the five operator-visible evidence states without authority."""

    COMPLETE = "complete"
    INCOMPLETE = "incomplete"
    STALE = "stale"
    CONFLICTING = "conflicting"
    UNAVAILABLE = "unavailable"


class GraphRefreshAuditPhase(StrEnum):
    """Locate one decision in the bounded refresh and re-query sequence."""

    EVALUATED = "evaluated"
    REQUERY = "requery"
    TERMINAL = "terminal"


@dataclass(frozen=True, slots=True)
class GraphEvidenceRefreshAuditRecord:
    """Content-addressed, authority-free graph refresh audit material."""

    phase: GraphRefreshAuditPhase
    evidence_status: GraphEvidenceStatus
    decision: GraphEvidenceRefreshDecision
    ontology_release_digest: str
    principal_scope_digest: str | None
    source_revisions: tuple[str, ...]
    digest: str

    @classmethod
    def build(
        cls,
        *,
        phase: GraphRefreshAuditPhase,
        evidence_status: GraphEvidenceStatus,
        decision: GraphEvidenceRefreshDecision,
        ontology_release_digest: str,
        principal_scope_digest: str | None,
        source_revisions: tuple[str, ...],
    ) -> GraphEvidenceRefreshAuditRecord:
        """Build one canonical record and reject ambiguous generation evidence."""

        _digest(ontology_release_digest, "ontology release")
        if principal_scope_digest is not None:
            _digest(principal_scope_digest, "principal scope")
        if source_revisions != tuple(sorted(set(source_revisions))) or any(
            not value.strip() or len(value) > 256 for value in source_revisions
        ):
            raise ValueError("graph refresh source revisions MUST be unique bounded values")
        body = {
            "phase": phase.value,
            "evidence_status": evidence_status.value,
            "decision_digest": decision.digest,
            "decision_outcome": decision.outcome.value,
            "decision_reason_codes": decision.reason_codes,
            "ontology_release_digest": ontology_release_digest,
            "principal_scope_digest": principal_scope_digest,
            "source_revisions": source_revisions,
            "observation_authority": False,
            "mutation_authority": False,
            "execution_authority": False,
        }
        digest = (
            "sha256:"
            + hashlib.sha256(
                json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
        )
        return cls(
            phase=phase,
            evidence_status=evidence_status,
            decision=decision,
            ontology_release_digest=ontology_release_digest,
            principal_scope_digest=principal_scope_digest,
            source_revisions=source_revisions,
            digest=digest,
        )


class GraphEvidenceRefreshAuditor(Protocol):
    """Append one graph refresh decision to an authoritative audit sink."""

    async def record(self, record: GraphEvidenceRefreshAuditRecord) -> None: ...


def _digest(value: str, label: str) -> None:
    if (
        len(value) != 71
        or not value.startswith("sha256:")
        or any(character not in "0123456789abcdef" for character in value[7:])
    ):
        raise ValueError(f"graph refresh {label} MUST be a canonical SHA-256 digest")


__all__ = [
    "GraphEvidenceRefreshAuditRecord",
    "GraphEvidenceRefreshAuditor",
    "GraphEvidenceStatus",
    "GraphRefreshAuditPhase",
]
