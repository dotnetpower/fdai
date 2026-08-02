"""Manual distillation seam - compile prose manuals into rule candidates.

Design contract:
``docs/roadmap/rules-and-detection/manual-distillation.md``. This seam is the
*compile-side* complement of the *retrieve-side* :mod:`knowledge` seam: instead
of embedding an operator manual for runtime RAG, a :class:`Distiller` extracts
deterministic **candidates** (rules, workflows, action-types, policies) from the
manual at build time, each carrying provenance back to the manual span it derives
from.

Layering
--------

This module lives under ``shared/providers`` and MUST NOT import ``core/``. It
declares only plain contract dataclasses plus the :class:`Distiller` Protocol.
The deterministic false-negative guard (coverage analysis) lives in the pipeline
layer (``rule_catalog.pipeline.distill.coverage``), which imports the contract
types from here - never the reverse.

The upstream default binding is :class:`AbstainingDistiller`: it extracts nothing
and returns an empty result. Distillation runs an LLM (a T2 judgement), and
upstream ships no model, so the fail-safe default is "distill nothing -> promote
nothing", never a fabricated rule. A fork registers an LLM-backed
:class:`Distiller` at the composition root (see
``docs/roadmap/fork-and-sequencing/downstream-fork-guide.md``). The manual text
itself is customer data and lives only in the fork.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable


class CandidateKind(StrEnum):
    """The compiled target a distilled fragment normalizes to.

    Mirrors the "What gets compiled" table in the design doc: each manual
    statement becomes exactly one of these artifact kinds.
    """

    RULE = "rule"
    WORKFLOW = "workflow"
    ACTION_TYPE = "action_type"
    POLICY = "policy"
    ONTOLOGY_OBJECT = "ontology_object"
    ONTOLOGY_LINK = "ontology_link"


@dataclass(frozen=True, slots=True)
class ManualDocument:
    """One operator / deployment manual to distill.

    ``source_ref`` is the citation handle (a URI, a wiki page id, a file path)
    echoed onto every candidate so a promoted rule can point at its provenance.
    ``content_sha`` pins the manual revision so a re-distilled candidate is
    reproducible and a changed manual re-enters the pipeline. ``metadata`` is
    adapter-neutral and never carries secrets.
    """

    doc_id: str
    text: str
    source_ref: str
    content_sha: str = ""
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DistilledCandidate:
    """One candidate extracted from a manual span - inert until the gate promotes it.

    ``source_lines`` is the 1-based inclusive line range in the manual the
    candidate was distilled from; the coverage analyzer uses it to decide which
    manual obligations were covered. ``body`` is the normalized artifact payload
    (rule / workflow / action-type / policy YAML shape) - opaque to this seam and
    validated downstream against the matching schema, never here.
    """

    kind: CandidateKind
    candidate_id: str
    source_ref: str
    source_section: str
    source_lines: tuple[int, int]
    content_sha: str = ""
    body: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        start, end = self.source_lines
        if start < 1 or end < start:
            raise ValueError(
                "DistilledCandidate.source_lines MUST be a 1-based inclusive "
                f"(start <= end) range, got {self.source_lines!r}"
            )


@dataclass(frozen=True, slots=True)
class CoverageGap:
    """One manual obligation no candidate was distilled from (a false-negative risk)."""

    line: int
    text: str
    kind: str  # "heading" | "imperative"


@dataclass(frozen=True, slots=True)
class CoverageReport:
    """Deterministic completeness measure over one manual.

    ``total`` is the number of obligations the analyzer found (section headings +
    imperative statements); ``covered`` is how many fall inside a distilled
    candidate's line range. ``gaps`` enumerates the uncovered obligations for
    human review - the honest residual the design doc calls out, since a rule the
    manual states but distillation never extracted cannot be shadow-tested.
    """

    total: int
    covered: int
    gaps: tuple[CoverageGap, ...] = ()

    @property
    def coverage_ratio(self) -> float:
        """Fraction of obligations covered; ``1.0`` when the manual has none."""
        if self.total <= 0:
            return 1.0
        return self.covered / self.total


@dataclass(frozen=True, slots=True)
class DistillationResult:
    """The output of distilling one manual: candidates plus a coverage measure."""

    candidates: tuple[DistilledCandidate, ...] = ()
    coverage: CoverageReport = field(default_factory=lambda: CoverageReport(total=0, covered=0))


@runtime_checkable
class Distiller(Protocol):
    """Compile a prose manual into inert rule candidates (build-time, LLM-backed).

    An empty :class:`DistillationResult` is a valid answer (nothing distilled),
    NOT an error - the pipeline then promotes nothing, which is the fail-safe.
    """

    async def distill(self, document: ManualDocument) -> DistillationResult:
        """Extract candidates from ``document`` with provenance back to its spans."""
        ...


class AbstainingDistiller:
    """Upstream default - extracts nothing and returns an empty result.

    Distillation needs an LLM that upstream does not ship, so the default
    degrades to "no candidates -> nothing to promote", never to a fabricated
    rule. A fork swaps in an LLM-backed :class:`Distiller`.
    """

    async def distill(self, document: ManualDocument) -> DistillationResult:  # noqa: ARG002
        return DistillationResult()


__all__ = [
    "AbstainingDistiller",
    "CandidateKind",
    "CoverageGap",
    "CoverageReport",
    "DistillationResult",
    "DistilledCandidate",
    "Distiller",
    "ManualDocument",
]
