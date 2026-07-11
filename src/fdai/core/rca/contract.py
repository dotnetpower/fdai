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

from dataclasses import dataclass
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


@dataclass(frozen=True, slots=True)
class Citation:
    """One grounded evidence reference backing a hypothesis.

    ``ref`` is an opaque id (a rule id, event id, metric name, or
    incident id) - never a raw payload or secret.
    """

    kind: CitationKind
    ref: str


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
    "RcaOutcome",
    "RcaResult",
    "RcaTier",
    "RootCauseHypothesis",
]
