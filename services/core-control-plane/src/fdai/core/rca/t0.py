"""T0 deterministic root-cause analysis.

The lowest tier of RCA (observability-and-detection.md section 4): when a
rule matches, the rule itself *names* the direct cause - the violated
control (its check-logic reference) and the remediation it implies. No
model call; the hypothesis is fully grounded on the matched rule and is
deterministic (the same rule + resource always yields the same cause).
"""

from __future__ import annotations

from fdai.core.rca.contract import (
    Citation,
    CitationKind,
    RcaTier,
    RootCauseHypothesis,
)
from fdai.shared.contracts.models import Rule


def t0_root_cause(
    *,
    rule: Rule,
    resource_type: str,
    event_id: str | None = None,
) -> RootCauseHypothesis:
    """Build a deterministic T0 root-cause hypothesis from a matched rule.

    The hypothesis cites the rule (always) and records the check-logic
    reference plus the triggering event id as evidence. Confidence is
    ``1.0`` because a T0 match is a deterministic control violation, not
    an inference. ``remediation_ref`` is the ActionType the rule declares
    via ``remediates`` so the normal pipeline can act on it under the
    risk gate.
    """
    citations = (Citation(kind=CitationKind.RULE, ref=rule.id),)
    evidence: tuple[str, ...] = (rule.check_logic.reference,)
    if event_id:
        evidence = (*evidence, event_id)
    cause = (
        f"{rule.category.value} control violated: rule '{rule.id}' matched on "
        f"resource-type '{resource_type}' via {rule.check_logic.reference}"
    )
    return RootCauseHypothesis(
        tier=RcaTier.T0,
        cause=cause,
        confidence=1.0,
        citations=citations,
        evidence_refs=evidence,
        remediation_ref=rule.remediates,
    )


__all__ = ["t0_root_cause"]
