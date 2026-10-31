"""T0 deterministic root-cause analysis.

The lowest tier of RCA (observability-and-detection.md section 4): when a
rule matches, the rule itself *names* the direct cause - the violated
control (its check-logic reference) and the remediation it implies. No
model call; the hypothesis is fully grounded on the matched rule and is
deterministic (the same rule + resource always yields the same cause).
"""

from __future__ import annotations

from fdai.core.rca.contract import (
    CauseDomain,
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
    cause_domain: CauseDomain = CauseDomain.INFRASTRUCTURE,
) -> RootCauseHypothesis:
    """Build a deterministic T0 root-cause hypothesis from a matched rule.

    The hypothesis cites the rule (always) and records the check-logic
    reference plus the triggering event id as evidence. Confidence is
    ``1.0`` because a T0 match is a deterministic control violation, not
    an inference. ``remediation_ref`` is the ActionType the rule declares
    via ``remediates`` so the normal pipeline can act on it under the
    risk gate.
    """
    rule_id = rule.id.strip() if isinstance(rule.id, str) else ""
    if not rule_id:
        raise ValueError("t0_root_cause requires a non-empty rule.id")
    normalized_resource_type = resource_type.strip() if isinstance(resource_type, str) else ""
    if not normalized_resource_type:
        raise ValueError("t0_root_cause requires a non-empty resource_type")
    check_ref = (
        rule.check_logic.reference.strip() if isinstance(rule.check_logic.reference, str) else ""
    )
    citations = (Citation(kind=CitationKind.RULE, ref=rule_id),)
    evidence_list: list[str] = [check_ref] if check_ref else []
    normalized_event_id = event_id.strip() if isinstance(event_id, str) else ""
    if normalized_event_id and normalized_event_id not in evidence_list:
        evidence_list.append(normalized_event_id)
    remediation_ref = (
        rule.remediates.strip()
        if isinstance(rule.remediates, str) and rule.remediates.strip()
        else None
    )
    cause = (
        f"{rule.category.value} control violated: rule '{rule_id}' matched on "
        f"resource-type '{normalized_resource_type}' via {check_ref}"
    )
    return RootCauseHypothesis(
        tier=RcaTier.T0,
        cause=cause,
        confidence=1.0,
        citations=citations,
        cause_domain=cause_domain,
        evidence_refs=tuple(evidence_list),
        remediation_ref=remediation_ref,
    )


__all__ = ["t0_root_cause"]
