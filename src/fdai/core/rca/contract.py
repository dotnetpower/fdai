"""Root-cause analysis contract - a hypothesis with citations.

Makes RCA a first-class output of the tiers per
[observability-and-detection.md](../../../../docs/roadmap/rules-and-detection/observability-and-detection.md)
section 4. An RCA result is a **hypothesis with citations**, never an
authoritative verdict: execution eligibility is still granted by
deterministic verification (the risk gate + verifier), never by the RCA
text alone.

Grounding is mandatory. A hypothesis with no citation is not actionable
and abstains (routes to HIL) - see
:func:`fdai.core.rca.grounding.enforce_grounding`.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum


class RcaTier(StrEnum):
    """Which tier produced the hypothesis."""

    T0 = "t0"
    """Direct cause: the matched rule/policy names the violated control."""

    T1 = "t1"
    """Correlation cause: reuse of a prior resolved incident's cause."""

    T2 = "t2"
    """Reasoning cause: a grounded hypothesis for a novel/ambiguous case."""


class CitationKind(StrEnum):
    """The kind of evidence a citation points at."""

    RULE = "rule"
    EVENT = "event"
    TELEMETRY = "telemetry"
    INCIDENT = "incident"
    CHANGE = "change"
    """A correlated deploy / commit / config change - see
    :class:`~fdai.core.rca.change_evidence.ChangeEvidenceGatherer`."""
    SCENARIO = "scenario"
    """A catalog chaos scenario that would produce the same symptom (per
    the compiled symptom index). Emitted by
    :mod:`fdai.core.rca.scenario_context`; the ``ref`` is the scenario
    ``id`` (``chaos.<namespace>.<slug>``). Consumed by the T2 reasoner
    as a candidate cause; the reasoner still cannot execute anything
    on its own."""
    KNOWLEDGE = "knowledge"
    """A chunk of a free-form operator document (runbook, architecture
    note, resource plan) retrieved from the
    :class:`~fdai.shared.providers.knowledge.KnowledgeSource`. Emitted by
    :class:`~fdai.core.rca.knowledge_evidence.KnowledgeEvidenceGatherer`;
    the ``ref`` is the opaque ``knowledge:<source_ref>#<chunk_id>`` handle
    pointing back at the ingested document's provenance. Consumed by the
    T2 reasoner as candidate grounding; it never grants execution on its
    own."""


@dataclass(frozen=True, slots=True)
class Citation:
    """One grounded evidence reference backing a hypothesis.

    ``ref`` is an opaque id (a rule id, event id, metric name, or
    incident id) - never a raw payload or secret.
    """

    kind: CitationKind
    ref: str


@dataclass(frozen=True, slots=True)
class RcaCausalHop:
    """One transport-safe edge in a reconstructed RCA causal chain."""

    cause_event_id: str
    effect_event_id: str
    cause_resource_ref: str
    effect_resource_ref: str
    lead_seconds: float
    relationship: str
    confidence: float

    def to_dict(self) -> dict[str, object]:
        """Return the audit-safe wire representation."""
        return asdict(self)


@dataclass(frozen=True, slots=True)
class RcaCausalChain:
    """Structured T1 causal chain retained alongside the hypothesis prose."""

    root_event_id: str
    failure_event_id: str
    hops: tuple[RcaCausalHop, ...]
    confidence: float
    ambiguity: int

    def to_dict(self) -> dict[str, object]:
        """Return the append-only audit representation."""
        return {
            "root_event_id": self.root_event_id,
            "failure_event_id": self.failure_event_id,
            "confidence": self.confidence,
            "ambiguity": self.ambiguity,
            "hops": [hop.to_dict() for hop in self.hops],
        }


@dataclass(frozen=True, slots=True)
class RootCauseHypothesis:
    """A root-cause hypothesis with grounded citations.

    ``confidence`` is a stated uncertainty in ``[0, 1]``; it never grants
    execution eligibility on its own. ``remediation_ref`` is the
    ActionType the cause implies (if any), which the normal pipeline
    (ActionBuilder + risk gate) may act on - the RCA layer answers
    "why", not "execute".
    """

    tier: RcaTier
    cause: str
    confidence: float
    citations: tuple[Citation, ...]
    evidence_refs: tuple[str, ...] = ()
    remediation_ref: str | None = None
    causal_chain: RcaCausalChain | None = None

    @property
    def grounded(self) -> bool:
        """True iff at least one citation backs the hypothesis."""
        return len(self.citations) > 0


class RcaOutcome(StrEnum):
    """Terminal outcome of the grounding gate."""

    GROUNDED = "grounded"
    """The hypothesis is grounded and within confidence bounds."""

    ABSTAINED = "abstained"
    """Ungrounded or below the confidence floor - routes to HIL, never
    an autonomous action."""


@dataclass(frozen=True, slots=True)
class RcaResult:
    """The grounding gate's decision over one hypothesis."""

    outcome: RcaOutcome
    hypothesis: RootCauseHypothesis | None
    reason: str

    @property
    def is_grounded(self) -> bool:
        return self.outcome is RcaOutcome.GROUNDED


__all__ = [
    "Citation",
    "CitationKind",
    "RcaCausalChain",
    "RcaCausalHop",
    "RcaOutcome",
    "RcaResult",
    "RcaTier",
    "RootCauseHypothesis",
]
