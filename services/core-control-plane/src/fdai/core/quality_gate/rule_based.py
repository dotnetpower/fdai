"""Rule-catalog-backed :class:`VerifierPolicy` - the first non-fake verifier.

The T2 quality gate MUST verify a candidate action **deterministically**
before it can execute; the model's own text is inadmissible. The verifier
in this module answers a narrow, testable question:

    Does at least one cited rule authorize this action_type on this
    resource type?

Concretely:

- **True** - a cited rule exists, its ``resource_type`` matches the
  candidate's target type, and its ``remediates`` or ``alternatives[]``
  contains the candidate's ``action_type``. The rule authorized this
  remediation intent; the gate MAY proceed.
- **False** - cited rules exist but NONE authorize the candidate's
  ``action_type`` on the target type. The model invented an action the
  catalog does not sanction - an explicit deny (safest posture).
- **None** - no cited rules or none resolvable to the catalog. The
  grounding leg handles that case; the verifier abstains rather than
  duplicating the message.

This verifier is intentionally lightweight - it closes the biggest
class of LLM-invention risk (proposing an action_type no rule
authorizes) without needing per-ActionType what-if projectors. A
future cycle adds a Rego-backed post-state verifier (project the
action's effect, re-run the rule's Rego, expect ``deny=false``); the
:class:`VerifierPolicy` seam is the same, so that upgrade is additive.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from fdai.core.quality_gate.gate import QualityCandidate, VerifierPolicy
from fdai.shared.contracts.models import Rule


@dataclass(frozen=True, slots=True)
class RuleBasedVerifier(VerifierPolicy):
    """Verify a candidate against the rule catalog's authorized remediations.

    ``rules_by_id`` MUST be the same catalog the T0 engine + risk-gate
    load; passing a subset would let a partially-loaded fork silently
    authorize actions the full catalog does not. The composition root
    is the only correct binding point.

    ``target_resource_type_lookup`` maps ``QualityCandidate.target_resource_ref``
    to the CSP-neutral ``resource_type`` of the target resource. Kept
    injectable so the verifier does not couple to any specific
    inventory implementation; typically wired to the ontology's
    resource lookup (``ontology_resource.type``).
    """

    rules_by_id: Mapping[str, Rule]
    target_resource_type_lookup: Mapping[str, str] | None = None

    def verify(self, candidate: QualityCandidate) -> bool | None:
        cited: Final[tuple[Rule, ...]] = tuple(
            rule
            for rule_id in candidate.cited_rule_ids
            if (rule := self.rules_by_id.get(rule_id)) is not None
        )
        if not cited:
            # Grounding leg surfaces "no cited rules" / "unknown citation"
            # - verifier abstains to keep the audit message clean.
            return None

        target_type = candidate.target_resource_type or self._resolve_target_type(
            candidate.target_resource_ref
        )
        if target_type is None:
            return None

        for rule in cited:
            if rule.resource_type != target_type:
                # Cited rule doesn't apply to this resource type - skip.
                continue
            if candidate.action_type == rule.remediates:
                return True
            if rule.alternatives and candidate.action_type in rule.alternatives:
                return True

        # At least one cited rule loaded, but none authorized this
        # action_type on this target - explicit deny.
        return False

    def _resolve_target_type(self, resource_ref: str) -> str | None:
        if self.target_resource_type_lookup is None:
            return None
        return self.target_resource_type_lookup.get(resource_ref)


__all__ = ["RuleBasedVerifier"]
