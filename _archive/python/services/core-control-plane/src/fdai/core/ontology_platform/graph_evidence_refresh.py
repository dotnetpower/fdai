"""Reduce graph, live, and archive evidence to one read-only refresh outcome."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum

from fdai.core.ontology_platform.archive_retention import ArchiveHistoryStatus


class GraphQueryIntent(StrEnum):
    """Distinguish current-state reads from explicit historical retrieval."""

    CURRENT = "current"
    HISTORICAL = "historical"


class GraphEvidenceFreshness(StrEnum):
    """Describe current graph evidence at the trusted query cutoff."""

    CURRENT = "current"
    STALE = "stale"
    UNKNOWN = "unknown"
    UNAVAILABLE = "unavailable"


class GraphEvidenceRefreshOutcome(StrEnum):
    """Name the only allowed graph evidence refresh outcomes."""

    USE_GRAPH = "use_graph"
    REFRESH_THEN_QUERY = "refresh_then_query"
    USE_LIVE_EVIDENCE = "use_live_evidence"
    QUERY_ARCHIVE = "query_archive"
    HOLD = "hold"


@dataclass(frozen=True, slots=True)
class GraphEvidenceRefreshInput:
    """Carry verified policy inputs without provider commands or query text."""

    query_intent: GraphQueryIntent
    requested_ontology_release_digest: str
    graph_ontology_release_digest: str | None
    graph_available: bool
    graph_freshness: GraphEvidenceFreshness
    graph_complete: bool
    graph_truncated: bool
    graph_synthetic: bool
    graph_conflict_count: int
    explicit_live_read: bool
    live_read_permitted: bool
    verified_live_receipt: bool
    live_receipt_principal_scoped: bool
    deadline_remaining_ms: int
    live_read_budget_ms: int
    projection_budget_ms: int
    archive_status: ArchiveHistoryStatus
    archive_principal_scoped: bool

    def __post_init__(self) -> None:
        _digest(
            self.requested_ontology_release_digest,
            "requested_ontology_release_digest",
        )
        if self.graph_ontology_release_digest is not None:
            _digest(
                self.graph_ontology_release_digest,
                "graph_ontology_release_digest",
            )
        for name in (
            "deadline_remaining_ms",
            "live_read_budget_ms",
            "projection_budget_ms",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or value < 0:
                raise ValueError(f"graph refresh {name} MUST NOT be negative")
        if self.graph_conflict_count < 0:
            raise ValueError("graph refresh conflict_count MUST NOT be negative")
        if self.verified_live_receipt and not self.live_receipt_principal_scoped:
            raise ValueError("verified live receipt MUST be principal scoped")


@dataclass(frozen=True, slots=True)
class GraphEvidenceRefreshDecision:
    """Record one deterministic no-authority refresh decision."""

    outcome: GraphEvidenceRefreshOutcome
    reason_codes: tuple[str, ...]
    digest: str
    observation_authority: bool = False
    mutation_authority: bool = False
    execution_authority: bool = False


def decide_graph_evidence_refresh(
    evidence: GraphEvidenceRefreshInput,
) -> GraphEvidenceRefreshDecision:
    """Select the least expensive verified read path and otherwise hold."""

    if evidence.query_intent is GraphQueryIntent.HISTORICAL:
        if (
            evidence.archive_status is ArchiveHistoryStatus.ARCHIVED
            and evidence.archive_principal_scoped
        ):
            return _decision(GraphEvidenceRefreshOutcome.QUERY_ARCHIVE, ("archive_verified",))
        reason = (
            "archive_absent"
            if evidence.archive_status is ArchiveHistoryStatus.ABSENT
            else "archive_scope_unverified"
            if not evidence.archive_principal_scoped
            else "archive_unavailable"
        )
        return _decision(GraphEvidenceRefreshOutcome.HOLD, (reason,))

    graph_reasons = _graph_reasons(evidence)
    if not graph_reasons and not evidence.explicit_live_read:
        return _decision(GraphEvidenceRefreshOutcome.USE_GRAPH, ("graph_verified",))

    if (
        evidence.live_read_permitted
        and evidence.verified_live_receipt
        and evidence.deadline_remaining_ms > 0
    ):
        return _decision(
            GraphEvidenceRefreshOutcome.USE_LIVE_EVIDENCE,
            ("verified_live_receipt", *graph_reasons),
        )

    required_refresh_ms = evidence.live_read_budget_ms + evidence.projection_budget_ms
    if (
        evidence.live_read_permitted
        and not evidence.verified_live_receipt
        and required_refresh_ms > 0
        and evidence.deadline_remaining_ms >= required_refresh_ms
    ):
        return _decision(
            GraphEvidenceRefreshOutcome.REFRESH_THEN_QUERY,
            ("bounded_refresh_available", *graph_reasons),
        )

    reasons = list(graph_reasons or ("explicit_live_read_unavailable",))
    if not evidence.live_read_permitted:
        reasons.append("live_read_not_permitted")
    elif evidence.deadline_remaining_ms < required_refresh_ms:
        reasons.append("deadline_insufficient")
    else:
        reasons.append("live_evidence_unavailable")
    return _decision(GraphEvidenceRefreshOutcome.HOLD, tuple(dict.fromkeys(reasons)))


def _graph_reasons(evidence: GraphEvidenceRefreshInput) -> tuple[str, ...]:
    reasons: list[str] = []
    if not evidence.graph_available:
        reasons.append("graph_unavailable")
    if evidence.graph_ontology_release_digest != evidence.requested_ontology_release_digest:
        reasons.append("ontology_release_mismatch")
    if evidence.graph_freshness is not GraphEvidenceFreshness.CURRENT:
        reasons.append(f"graph_{evidence.graph_freshness.value}")
    if not evidence.graph_complete:
        reasons.append("graph_incomplete")
    if evidence.graph_truncated:
        reasons.append("graph_truncated")
    if evidence.graph_synthetic:
        reasons.append("graph_synthetic")
    if evidence.graph_conflict_count:
        reasons.append("graph_conflicting")
    return tuple(reasons)


def _decision(
    outcome: GraphEvidenceRefreshOutcome,
    reasons: tuple[str, ...],
) -> GraphEvidenceRefreshDecision:
    body = {
        "outcome": outcome.value,
        "reason_codes": reasons,
        "observation_authority": False,
        "mutation_authority": False,
        "execution_authority": False,
    }
    return GraphEvidenceRefreshDecision(
        outcome=outcome,
        reason_codes=reasons,
        digest="sha256:"
        + hashlib.sha256(
            json.dumps(
                body,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode("utf-8")
        ).hexdigest(),
    )


def _digest(value: str, name: str) -> None:
    if (
        len(value) != 71
        or not value.startswith("sha256:")
        or any(character not in "0123456789abcdef" for character in value[7:])
    ):
        raise ValueError(f"graph refresh {name} MUST be a canonical SHA-256 digest")


__all__ = [
    "GraphEvidenceFreshness",
    "GraphEvidenceRefreshDecision",
    "GraphEvidenceRefreshInput",
    "GraphEvidenceRefreshOutcome",
    "GraphQueryIntent",
    "decide_graph_evidence_refresh",
]
