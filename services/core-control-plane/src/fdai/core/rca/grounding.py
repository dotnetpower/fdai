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

from fdai.core.rca.contract import (
    RcaOutcome,
    RcaResult,
    RootCauseHypothesis,
)


def enforce_grounding(
    hypothesis: RootCauseHypothesis,
    *,
    min_confidence: float = 0.0,
) -> RcaResult:
    """Return :class:`RcaResult` - grounded, or abstained toward HIL.

    Abstains (fail-closed) when the hypothesis has no citation, carries a
    confidence outside ``[0, 1]``, or falls below ``min_confidence``. A
    grounded, in-bounds hypothesis passes through unchanged.
    """
    if not hypothesis.grounded:
        return RcaResult(
            outcome=RcaOutcome.ABSTAINED,
            hypothesis=None,
            reason="ungrounded_rca_no_citation_routed_to_hil",
        )
    if not 0.0 <= hypothesis.confidence <= 1.0:
        return RcaResult(
            outcome=RcaOutcome.ABSTAINED,
            hypothesis=None,
            reason=f"invalid_confidence_{hypothesis.confidence!r}",
        )
    if not 0.0 <= min_confidence <= 1.0:
        raise ValueError("min_confidence MUST be in [0, 1]")
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
