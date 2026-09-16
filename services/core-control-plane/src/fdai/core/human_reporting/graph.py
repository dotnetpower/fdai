"""Validated current human reporting graph and traversal."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime

from fdai.core.human_reporting.model import (
    ReportingLineCase,
    ReportingLineCaseState,
    ReportingLineModelError,
    normalize_principal,
    reporting_instant,
)


@dataclass(frozen=True, slots=True)
class ReportingGraphEdge:
    """One effective reviewed edge in a current graph snapshot."""

    case_id: str
    edge_digest: str
    subject_ref: str
    manager_ref: str
    effective_from: datetime
    effective_until: datetime


@dataclass(frozen=True, slots=True)
class ReportingGraphSnapshot:
    """Acyclic current primary-manager graph with a content-derived revision."""

    revision: str
    observed_at: datetime
    edges: tuple[ReportingGraphEdge, ...]

    def manager_chain(
        self,
        subject_ref: str,
        *,
        maximum_depth: int = 8,
    ) -> tuple[ReportingGraphEdge, ...]:
        """Return the direct-to-highest manager path without guessing across a gap."""

        if isinstance(maximum_depth, bool) or not 1 <= maximum_depth <= 32:
            raise ReportingLineModelError("reporting-line traversal depth MUST be in [1, 32]")
        current = normalize_principal(subject_ref)
        by_subject = {edge.subject_ref: edge for edge in self.edges}
        path: list[ReportingGraphEdge] = []
        seen = {current}
        while current in by_subject:
            if len(path) >= maximum_depth:
                raise ReportingLineModelError("reporting-line traversal exceeds its depth limit")
            edge = by_subject[current]
            if edge.manager_ref in seen:
                raise ReportingLineModelError("reporting-line graph contains a cycle")
            path.append(edge)
            seen.add(edge.manager_ref)
            current = edge.manager_ref
        return tuple(path)


def build_reporting_graph(
    cases: tuple[ReportingLineCase, ...],
    *,
    at: datetime,
) -> ReportingGraphSnapshot:
    """Build one current graph or fail closed on overlap, cycles, or stale supersession."""

    observed_at = reporting_instant(at)
    approved = [case for case in cases if case.state is ReportingLineCaseState.ACTIVE]
    superseded = {
        case.supersedes_case_id
        for case in approved
        if case.supersedes_case_id is not None and case.effective_from <= observed_at
    }
    current = [
        case
        for case in approved
        if case.case_id not in superseded
        and case.effective_from <= observed_at < case.effective_until
    ]
    by_subject: dict[str, ReportingLineCase] = {}
    for case in current:
        previous = by_subject.get(case.subject_ref)
        if previous is not None:
            raise ReportingLineModelError(
                "reporting-line graph has multiple active primary managers for one subject"
            )
        by_subject[case.subject_ref] = case
    edges = tuple(
        ReportingGraphEdge(
            case_id=case.case_id,
            edge_digest=case.edge_digest,
            subject_ref=case.subject_ref,
            manager_ref=case.manager_ref,
            effective_from=case.effective_from,
            effective_until=case.effective_until,
        )
        for case in sorted(current, key=lambda item: (item.subject_ref, item.manager_ref))
    )
    snapshot = ReportingGraphSnapshot(
        revision=_graph_revision(edges),
        observed_at=observed_at,
        edges=edges,
    )
    for subject in by_subject:
        snapshot.manager_chain(subject, maximum_depth=max(1, len(edges)))
    return snapshot


def _graph_revision(edges: tuple[ReportingGraphEdge, ...]) -> str:
    material = [
        {
            "case_id": edge.case_id,
            "edge_digest": edge.edge_digest,
            "subject_ref": edge.subject_ref,
            "manager_ref": edge.manager_ref,
            "effective_from": edge.effective_from.isoformat(),
            "effective_until": edge.effective_until.isoformat(),
        }
        for edge in edges
    ]
    return hashlib.sha256(
        json.dumps(material, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


__all__ = [
    "ReportingGraphEdge",
    "ReportingGraphSnapshot",
    "build_reporting_graph",
]
