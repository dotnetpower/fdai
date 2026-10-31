"""RCA grounding gate - citation-or-abstain.

Enforces the architecture rule "an RCA that cannot be grounded abstains
and routes to HIL"
([architecture.instructions.md](../../../../.github/instructions/architecture.instructions.md)
section Human Override / LLM Quality Gate). A hypothesis with no citation
- or one below a configured confidence floor - never drives an
autonomous action; it hands off to a human.

This gate is deterministic and authoritative over any model text: a T2
reasoner may *propose* a hypothesis, but this function (plus the downstream
risk-gate verifier) decides whether it is actionable, never the model's
prose.
"""

from __future__ import annotations

from fdai.core.rca.citations import admitted_citations
from fdai.core.rca.contract import (
    RcaOutcome,
    RcaResult,
    RootCauseHypothesis,
)

MAX_RCA_CAUSE_BYTES = 4 * 1024


def valid_confidence(value: float) -> bool:
    """Accept numeric uncertainty only; booleans are not confidence values."""
    return not isinstance(value, bool) and isinstance(value, (int, float)) and 0.0 <= value <= 1.0


def valid_cause(cause: str) -> bool:
    if not cause.strip():
        return False
    try:
        return len(cause.encode("utf-8")) <= MAX_RCA_CAUSE_BYTES
    except UnicodeEncodeError:
        return False


def enforce_grounding(
    hypothesis: RootCauseHypothesis,
    *,
    min_confidence: float = 0.0,
) -> RcaResult:
    """Return :class:`RcaResult` - grounded, or abstained toward HIL.

    Holds missing or conflicting citations, invalid or oversized cause text,
    invalid uncertainty, or confidence below the configured floor. Invalid
    floor configuration raises even when the hypothesis has no evidence.
    An admissible hypothesis passes through unchanged.
    """
    if not valid_confidence(min_confidence):
        raise ValueError("min_confidence MUST be in [0, 1]")
    if not hypothesis.grounded:
        return RcaResult(
            outcome=RcaOutcome.ABSTAINED,
            hypothesis=None,
            reason="ungrounded_rca_no_citation_routed_to_hil",
        )
    if not valid_confidence(hypothesis.confidence):
        return RcaResult(
            outcome=RcaOutcome.ABSTAINED,
            hypothesis=None,
            reason="invalid_confidence",
        )
    if not valid_cause(hypothesis.cause) or admitted_citations(hypothesis.citations) is None:
        return RcaResult(
            outcome=RcaOutcome.ABSTAINED,
            hypothesis=None,
            reason="invalid_rca_cause_or_citations",
        )
    if hypothesis.confidence < min_confidence:
        return RcaResult(
            outcome=RcaOutcome.ABSTAINED,
            hypothesis=None,
            reason=(f"confidence_{hypothesis.confidence:.2f}_below_min_{min_confidence:.2f}"),
        )
    return RcaResult(
        outcome=RcaOutcome.GROUNDED,
        hypothesis=hypothesis,
        reason="grounded",
    )


__all__ = ["enforce_grounding"]
