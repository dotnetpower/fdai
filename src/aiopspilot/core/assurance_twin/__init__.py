"""Assurance Twin - queryable read-only projection over the estate.

Implements the [assurance-twin.md](../../../../docs/roadmap/assurance-twin.md)
subsystem: a text-to-query surface + ambient PR review + whole-graph
what-if simulation, all backed by the shared
:class:`~aiopspilot.shared.providers.projection.ScratchProjection`
primitive (R4).

Wave scope:

- **Groundwork (this module)**: package marker, in-memory
  :class:`InMemoryProjection` primitive that satisfies the Protocol so
  Twin + Preflight callers have something to bind at composition
  time. The subsystem is intentionally light-weight: no adapter, no
  cloud SDK, no LLM.
- **P2**: text-to-query compiler + verifier (Twin's `query.py`),
  grounded answer rendering, discovery-loop hook.
- **P3**: ambient per-change review posting Checks-API annotations,
  whole-graph what-if for the three verticals, and the
  :class:`PostureAssessmentReport` panel.

The subsystem holds no privileged identity and never mutates.
"""

from __future__ import annotations

from aiopspilot.core.assurance_twin.projection import (
    InMemoryProjection,
    build_baseline_projection,
)
from aiopspilot.core.assurance_twin.query import (
    AbstainCode,
    AbstainResult,
    CompiledQuery,
    DeterministicPatternCompiler,
    NlQueryCompiler,
    Predicate,
    PredicateOp,
    QueryKind,
    QueryResult,
    QueryRow,
    QueryVerificationError,
    QueryVerifier,
    TypedQuery,
    execute_query,
)
from aiopspilot.core.assurance_twin.report import (
    PostureAssessmentReport,
    PostureVerdict,
    build_posture_assessment_report,
)
from aiopspilot.core.assurance_twin.review import (
    ReviewOutcome,
    ReviewResult,
    publish_review,
)

__all__ = [
    "AbstainCode",
    "AbstainResult",
    "CompiledQuery",
    "DeterministicPatternCompiler",
    "InMemoryProjection",
    "NlQueryCompiler",
    "PostureAssessmentReport",
    "PostureVerdict",
    "Predicate",
    "PredicateOp",
    "QueryKind",
    "QueryResult",
    "QueryRow",
    "QueryVerificationError",
    "QueryVerifier",
    "ReviewOutcome",
    "ReviewResult",
    "TypedQuery",
    "build_baseline_projection",
    "build_posture_assessment_report",
    "execute_query",
    "publish_review",
]
