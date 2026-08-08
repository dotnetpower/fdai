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

from fdai.shared.providers.ontology_council_receipt import OntologyCouncilReceipt


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


class DistillerAvailability(StrEnum):
    """Binding readiness independent from enablement or execution authority."""

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    ABSTAINING = "abstaining"


@dataclass(frozen=True, slots=True)
class DistillerCapabilityDescriptor:
    """Versioned identity and readiness of one Distiller binding."""

    binding_id: str
    binding_version: str
    contract_version: str
    availability: DistillerAvailability
    reason_code: str | None = None

    def __post_init__(self) -> None:
        values = (self.binding_id, self.binding_version, self.contract_version)
        if any(not value.strip() or len(value) > 128 for value in values):
            raise ValueError("distiller capability identity MUST be bounded and non-empty")
        if self.availability is not DistillerAvailability.AVAILABLE and not self.reason_code:
            raise ValueError("unavailable Distiller capability MUST include a reason code")
        if self.reason_code is not None and (
            not self.reason_code.strip() or len(self.reason_code) > 128
        ):
            raise ValueError("distiller capability reason code MUST be bounded and non-empty")


@dataclass(frozen=True, slots=True)
class ManualLineProvenance:
    """Structural source locator for one normalized manual line."""

    line_number: int
    source_format: str
    unit_id: str
    locator: str

    def __post_init__(self) -> None:
        if self.line_number < 1:
            raise ValueError("manual provenance line_number MUST be positive")
        values = (self.source_format, self.unit_id, self.locator)
        if any(not value.strip() for value in values):
            raise ValueError("manual provenance identity fields MUST be non-empty")
        if len(self.source_format) > 64 or len(self.unit_id) > 128 or len(self.locator) > 256:
            raise ValueError("manual provenance identity exceeds the bounded length")


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
    line_provenance: tuple[ManualLineProvenance, ...] = ()

    def __post_init__(self) -> None:
        line_numbers = [item.line_number for item in self.line_provenance]
        if len(line_numbers) != len(set(line_numbers)):
            raise ValueError("manual line provenance MUST contain unique line numbers")
        line_count = len(self.text.splitlines())
        if any(line_number > line_count for line_number in line_numbers):
            raise ValueError("manual line provenance MUST reference an existing line")


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
    council_receipts: tuple[OntologyCouncilReceipt, ...] = ()


@runtime_checkable
class Distiller(Protocol):
    """Compile a prose manual into inert rule candidates (build-time, LLM-backed).

    An empty :class:`DistillationResult` is a valid answer (nothing distilled),
    NOT an error - the pipeline then promotes nothing, which is the fail-safe.
    """

    async def distill(self, document: ManualDocument) -> DistillationResult:
        """Extract candidates from ``document`` with provenance back to its spans."""
        ...


@runtime_checkable
class DescribedDistiller(Protocol):
    """Optional descriptor surface; the existing Distiller Protocol stays unchanged."""

    def distiller_capability(self) -> DistillerCapabilityDescriptor:
        """Return immutable binding identity and readiness."""
        ...


def describe_distiller(distiller: object) -> DistillerCapabilityDescriptor:
    """Describe a binding without treating an undescribed provider as available."""
    if isinstance(distiller, DescribedDistiller):
        return distiller.distiller_capability()
    return DistillerCapabilityDescriptor(
        binding_id=type(distiller).__name__,
        binding_version="unknown",
        contract_version="ontology-distiller-conformance.v1",
        availability=DistillerAvailability.UNAVAILABLE,
        reason_code="descriptor_unavailable",
    )


class AbstainingDistiller:
    """Upstream default - extracts nothing and returns an empty result.

    Distillation needs an LLM that upstream does not ship, so the default
    degrades to "no candidates -> nothing to promote", never to a fabricated
    rule. A fork swaps in an LLM-backed :class:`Distiller`.
    """

    async def distill(self, document: ManualDocument) -> DistillationResult:  # noqa: ARG002
        return DistillationResult()

    def distiller_capability(self) -> DistillerCapabilityDescriptor:
        return DistillerCapabilityDescriptor(
            binding_id="upstream-abstaining-distiller",
            binding_version="1.0.0",
            contract_version="ontology-distiller-conformance.v1",
            availability=DistillerAvailability.ABSTAINING,
            reason_code="provider_unbound",
        )


__all__ = [
    "AbstainingDistiller",
    "CandidateKind",
    "CoverageGap",
    "CoverageReport",
    "DescribedDistiller",
    "DistillationResult",
    "DistilledCandidate",
    "Distiller",
    "DistillerAvailability",
    "DistillerCapabilityDescriptor",
    "ManualDocument",
    "ManualLineProvenance",
    "describe_distiller",
]
