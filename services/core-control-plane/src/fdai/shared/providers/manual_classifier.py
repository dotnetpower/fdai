"""Manual classifier seam - "is this an operational procedure?" (build-time, LLM).

Design contract:
``docs/roadmap/rules-and-detection/manual-distillation.md`` § "Discovery and
triage at scale", step 2 (the cheap T1-grade classifier). After the deterministic
:mod:`~fdai.rule_catalog.pipeline.distill.triage` filter discards the dead long
tail, a small model decides which survivors are actually operational procedures
worth the expensive distillation pass. That decision needs a model, so it lives
behind this seam.

Layering
--------

This module lives under ``shared/providers`` and MUST NOT import ``core/``. It
consumes :class:`ManualCandidate` from the sibling :mod:`manual_source` seam.

The upstream default binding is :class:`AbstainingManualClassifier`: it returns
:attr:`ProcedureVerdict.UNCERTAIN` for every candidate. The fail-safe is that an
unwired classifier auto-selects nothing - uncertain candidates route to the
human triage queue (``O(dozens)`` confirmations), never straight to
distillation. A fork registers a small-model classifier at the composition root.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable

from fdai.shared.providers.manual_source import ManualCandidate


class ProcedureVerdict(StrEnum):
    """Whether a candidate is an operational procedure worth distilling."""

    PROCEDURE = "procedure"
    NOT_PROCEDURE = "not_procedure"
    UNCERTAIN = "uncertain"


@dataclass(frozen=True, slots=True)
class ClassifiedManual:
    """A candidate paired with the classifier's verdict and confidence."""

    candidate: ManualCandidate
    verdict: ProcedureVerdict
    confidence: float = 0.0

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("ClassifiedManual.confidence MUST be within [0.0, 1.0]")


@runtime_checkable
class ManualClassifier(Protocol):
    """Classify candidates as procedure / not-procedure / uncertain (async)."""

    async def classify(self, candidates: Sequence[ManualCandidate]) -> Sequence[ClassifiedManual]:
        """Return one :class:`ClassifiedManual` per input candidate, in order."""
        ...


class AbstainingManualClassifier:
    """Upstream default - marks every candidate UNCERTAIN (routes to human triage).

    An unwired classifier never auto-selects a manual for distillation; the
    uncertain verdicts land in the HIL triage queue instead. This is the
    fail-safe: no model means no auto-decision, never a fabricated "yes".
    """

    async def classify(self, candidates: Sequence[ManualCandidate]) -> Sequence[ClassifiedManual]:
        return tuple(
            ClassifiedManual(candidate=c, verdict=ProcedureVerdict.UNCERTAIN) for c in candidates
        )


__all__ = [
    "AbstainingManualClassifier",
    "ClassifiedManual",
    "ManualClassifier",
    "ProcedureVerdict",
]
