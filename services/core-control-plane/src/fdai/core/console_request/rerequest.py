"""Operator re-request gate - may an operator re-submit a prior action?

Scenario B (permission-based operator request) lets a Contributor ask the
pipeline for a runtime action (``restart vm-1``) through the write-direction
console path. The action re-enters the typed pantheon pipeline and is judged
there; the console never executes anything itself. This module codifies the
one policy that governs a **repeat** of that request, in one pure, testable
place (mirroring :mod:`fdai.core.hil_resume.delegation`):

- When the pipeline previously concluded the action was a **no-op**
  (unnecessary - the target was already in the desired state), the operator
  MAY re-request it. Conditions drift, so a later re-request is legitimate.
- When the pipeline previously **denied** the action (judged unsafe by
  policy / the risk gate), the operator MUST NOT be able to override that by
  simply re-asking. A deny is authoritative; only a rule / policy / override
  change (a governed path) can lift it, never a repeat console request.
- With no prior terminal verdict (or any other non-deny outcome), the request
  proceeds normally and the pipeline judges it fresh.

Pure function: no I/O. The console action submitter calls it before publishing
a proposal so the rule lives in one place and is unit-testable in isolation.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class PriorRequestOutcome(StrEnum):
    """The pipeline's last terminal conclusion for an operator's request.

    Scoped to one ``(initiator, resource, action_type)`` tuple. Only the
    distinction the operator can act on is modeled; the risk gate's full
    ``auto / hil / deny / abstain`` vocabulary is deliberately not mirrored
    here - this gate only asks "does the prior outcome block a repeat?".
    """

    NONE = "none"
    """No prior terminal verdict for this request; judge it fresh."""

    NO_OP = "no_op"
    """The action was judged unnecessary (target already satisfied)."""

    DENIED = "denied"
    """The action was denied as unsafe; a repeat MUST NOT override it."""


class RerequestRefusal(StrEnum):
    """Why a re-request was refused before any proposal was published."""

    DENY_OVERRIDE_FORBIDDEN = "deny_override_forbidden"
    """A prior deny is authoritative; a repeat request cannot lift it."""


@dataclass(frozen=True, slots=True)
class RerequestDecision:
    """The verdict of :func:`evaluate_operator_rerequest`."""

    allowed: bool
    refusal: RerequestRefusal | None = None


def evaluate_operator_rerequest(
    *,
    prior_outcome: PriorRequestOutcome,
) -> RerequestDecision:
    """Decide whether an operator may re-submit a previously judged action.

    Fail-closed on the one authoritative block:

    - ``DENIED`` -> refuse (``deny_override_forbidden``); a governed
      rule / policy / override change is the only way to lift a deny.
    - ``NO_OP`` / ``NONE`` (or any non-deny outcome) -> allowed; the
      pipeline judges the fresh request as usual.

    The console submitter still applies RBAC (``author-draft-pr``) and the
    downstream pantheon re-judges every proposal, so this gate only adds the
    deny-override block on top - it never grants authority a role lacks.
    """
    if prior_outcome is PriorRequestOutcome.DENIED:
        return RerequestDecision(allowed=False, refusal=RerequestRefusal.DENY_OVERRIDE_FORBIDDEN)
    return RerequestDecision(allowed=True)


__all__ = [
    "PriorRequestOutcome",
    "RerequestDecision",
    "RerequestRefusal",
    "evaluate_operator_rerequest",
]
