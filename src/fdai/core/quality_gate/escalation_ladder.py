"""EscalationLadder - decide when a T2 disagreement escalates to a stronger model.

The default T2 path runs a two-model cross-check quorum (primary +
secondary, distinct publishers). When they disagree, the gate today has
two moves: run the Critic + Judge debate (same-tier reasoners, see
:mod:`fdai.core.quality_gate.debate_router`) or route to HIL. Neither
climbs to a **stronger model class** - the ``t2.reasoner.escalated``
capability the registry documents (``rule-catalog/llm-registry.yaml``,
``invocation: on_disagreement``) is provisioned but never invoked.

This module is the missing policy: given a cross-check disagreement (or a
weak self-consistency signal), decide whether to spend the escalated
(Opus / o1-class) reasoner as a tiebreaking third opinion before falling
back to HIL. It mirrors :mod:`fdai.core.quality_gate.debate_router`
exactly - a frozen config + a stateless, deterministic function - so the
policy is testable and auditable on its own.
:class:`~fdai.core.quality_gate.gate.QualityGate` records the decision in
**shadow** (``QualityDecision.escalation_route`` / ``escalation_reason``)
when a config is wired; actually invoking the escalated model is the next
enforce step (the debate_router delta-2a -> delta-2b sequence).

Critique-hardening invariants
-----------------------------
- **The ladder never grants execution eligibility.** It decides only
  whether to *spend a stronger model*. The escalated model's proposal is
  untrusted like every other model vote and re-enters the same quality
  gate (verifier + grounding + quorum). A disagreement is NEVER auto-
  resolved by climbing the ladder - the deterministic verifier remains
  the sole authority (``architecture.instructions.md`` § Quality Gate).
- **Fail-closed.** When the escalated reasoner is unavailable (a fork
  that did not resolve ``t2.reasoner.escalated``), the ladder returns
  :attr:`EscalationRoute.STOP` - never a truthy verdict on an unbound
  model. The caller then routes the unresolved disagreement to HIL.
- **Cost-bounded.** Escalation climbs at most one rung and never past the
  :attr:`EscalationTier.ESCALATED` ceiling, so a single call cannot fan
  out an unbounded number of frontier round-trips. ``enabled=False`` is a
  killswitch a fork flips during a cost spike without a code change.
- **Deterministic.** Same inputs return the same verdict; no wall-clock
  reads, no randomness - so an audited escalation replays identically.
- **``core/``-safe.** Imports only from
  :mod:`fdai.core.quality_gate.gate` and stdlib. No ``delivery.*``
  import, no LLM SDK.

See also
--------
- ``docs/roadmap/architecture/llm-strategy.md`` § Capability Preferences
  Registry (the ``t2.reasoner.escalated`` capability + ``on_disagreement``).
- ``fdai.core.quality_gate.debate_router`` - the sibling policy this mirrors.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum, StrEnum
from typing import Any, Final

from fdai.core.quality_gate.gate import QualityCandidate


class EscalationTier(IntEnum):
    """Model-class rungs of the T2 ladder, ordered cheap -> strong.

    The integer order is the ladder direction: escalation moves *up*
    (``PRIMARY -> SECONDARY -> ESCALATED``). Named to match the
    ``t2.reasoner.*`` capabilities in ``rule-catalog/llm-registry.yaml``
    so a decision maps one-to-one onto a provisioned model.
    """

    PRIMARY = 0
    SECONDARY = 1
    ESCALATED = 2


class EscalationRoute(StrEnum):
    """Router verdict handed back to the caller.

    :attr:`ESCALATE` says "spend the next-stronger reasoner as a
    tiebreaker"; :attr:`STOP` says "do not climb - the caller routes the
    unresolved case to HIL". The router never returns a third value - an
    unavailable escalated model or a ceiling hit collapses to
    :attr:`STOP`, matching the fail-closed rule.
    """

    ESCALATE = "escalate"
    STOP = "stop"


@dataclass(frozen=True, slots=True)
class EscalationLadderConfig:
    """Thresholds + opt-in lists the ladder enforces.

    ``enabled`` is the master killswitch - when ``False`` the ladder
    returns :attr:`EscalationRoute.STOP` unconditionally, so a fork can
    abort escalation during a cost spike without deploying new code.

    ``on_cross_check_disagreement`` (default ``True``) is the primary
    trigger: the two-model quorum could not converge, so a stronger third
    opinion is worth its token cost before HIL.

    ``on_self_consistency_below`` (default ``None`` = disabled) is a
    secondary trigger: when the self-consistency sampler
    (:mod:`fdai.core.quality_gate.self_consistency`) reports an
    action-stability below this threshold, the proposer is wavering - a
    hallucination signal - so escalate even if the two models nominally
    agreed. ``None`` leaves stability out of the decision.

    ``always_for_action_types`` forces escalation for a per-ActionType
    allowlist regardless of the signals (a fork's high-severity set).
    ``never_for_action_types`` is the counterpart denylist for cheap
    idempotent actions where a frontier round-trip is not worth it.
    Denylist wins over allowlist (a defect a fork catches at review time
    beats a silent surprise), enforced disjoint at construction.
    """

    enabled: bool = True
    on_cross_check_disagreement: bool = True
    on_self_consistency_below: float | None = None
    always_for_action_types: tuple[str, ...] = ()
    never_for_action_types: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.on_self_consistency_below is not None and not (
            0.0 <= self.on_self_consistency_below <= 1.0
        ):
            raise ValueError(
                "on_self_consistency_below MUST be in [0.0, 1.0] or None; "
                f"got {self.on_self_consistency_below!r}"
            )
        overlap = set(self.always_for_action_types) & set(self.never_for_action_types)
        if overlap:
            raise ValueError(
                "EscalationLadderConfig: always/never allowlists MUST be disjoint; "
                f"overlap={sorted(overlap)!r}"
            )


@dataclass(frozen=True, slots=True)
class EscalationDecision:
    """Structured record for the audit log and the caller.

    ``reason`` names the axis that produced the verdict (e.g.
    ``"cross_check_disagreement"``, ``"low_self_consistency"``,
    ``"at_ceiling"``, ``"never_list"``) so an operator inspecting the
    audit trail can reconstruct the choice without re-running the policy.
    ``from_tier`` is the highest model class consulted so far;
    ``to_tier`` is the rung to climb to (``None`` on :attr:`STOP`).
    """

    route: EscalationRoute
    reason: str
    action_type: str
    from_tier: EscalationTier
    to_tier: EscalationTier | None = None
    metadata: dict[str, str] = field(default_factory=dict)


_REASON_DISABLED: Final[str] = "disabled"
_REASON_MODEL_UNAVAILABLE: Final[str] = "escalated_model_unavailable"
_REASON_AT_CEILING: Final[str] = "at_ceiling"
_REASON_NEVER_LIST: Final[str] = "never_list"
_REASON_ALWAYS_LIST: Final[str] = "always_list"
_REASON_DISAGREEMENT: Final[str] = "cross_check_disagreement"
_REASON_LOW_STABILITY: Final[str] = "low_self_consistency"
_REASON_DEFAULT_STOP: Final[str] = "default_stop"


def _next_tier(tier: EscalationTier) -> EscalationTier | None:
    """Return the next rung up, or ``None`` at the ceiling.

    The single-rung climb is the cost bound: one call can escalate at most
    one model class, never leapfrog straight to the ceiling from PRIMARY
    and never past ESCALATED.
    """
    if tier is EscalationTier.ESCALATED:
        return None
    return EscalationTier(tier + 1)


def decide_escalation(
    *,
    candidate: QualityCandidate,
    cross_check_disagreed: bool,
    escalated_available: bool,
    current_tier: EscalationTier = EscalationTier.SECONDARY,
    self_consistency: float | None = None,
    config: EscalationLadderConfig | None = None,
) -> EscalationDecision:
    """Return the escalation verdict for one T2 event.

    ``current_tier`` is the highest model class consulted so far; a
    standard two-model cross-check leaves it at
    :attr:`EscalationTier.SECONDARY`. ``self_consistency`` is the optional
    action-stability signal in ``[0.0, 1.0]`` (lower = more wavering).

    Precedence (top wins, short-circuit):

    1. ``escalated_available=False`` -> STOP, reason
       ``escalated_model_unavailable`` (fail-closed).
    2. ``config.enabled=False`` -> STOP, reason ``disabled`` (killswitch).
    3. ``current_tier`` already at the ceiling -> STOP, reason
       ``at_ceiling`` (cost bound - no infinite climb).
    4. ``action_type`` in ``never_for_action_types`` -> STOP, reason
       ``never_list`` (denylist wins over allowlist).
    5. ``action_type`` in ``always_for_action_types`` -> ESCALATE, reason
       ``always_list``.
    6. ``cross_check_disagreed`` AND ``on_cross_check_disagreement`` ->
       ESCALATE, reason ``cross_check_disagreement`` (primary trigger).
    7. ``self_consistency`` below ``on_self_consistency_below`` (when set)
       -> ESCALATE, reason ``low_self_consistency`` (instability trigger).
    8. Fallback -> STOP, reason ``default_stop``.

    Climbing the ladder never resolves the disagreement on its own: the
    escalated model's proposal re-enters the quality gate and the
    deterministic verifier remains the sole grant of execution
    eligibility.
    """
    cfg = config or EscalationLadderConfig()
    action_type = candidate.action_type

    def _stop(reason: str) -> EscalationDecision:
        return EscalationDecision(
            route=EscalationRoute.STOP,
            reason=reason,
            action_type=action_type,
            from_tier=current_tier,
            to_tier=None,
        )

    if not escalated_available:
        return _stop(_REASON_MODEL_UNAVAILABLE)
    if not cfg.enabled:
        return _stop(_REASON_DISABLED)

    to_tier = _next_tier(current_tier)
    if to_tier is None:
        return _stop(_REASON_AT_CEILING)

    if action_type in cfg.never_for_action_types:
        return _stop(_REASON_NEVER_LIST)

    def _escalate(reason: str) -> EscalationDecision:
        return EscalationDecision(
            route=EscalationRoute.ESCALATE,
            reason=reason,
            action_type=action_type,
            from_tier=current_tier,
            to_tier=to_tier,
        )

    if action_type in cfg.always_for_action_types:
        return _escalate(_REASON_ALWAYS_LIST)
    if cross_check_disagreed and cfg.on_cross_check_disagreement:
        return _escalate(_REASON_DISAGREEMENT)
    if (
        cfg.on_self_consistency_below is not None
        and self_consistency is not None
        and self_consistency < cfg.on_self_consistency_below
    ):
        return _escalate(_REASON_LOW_STABILITY)
    return _stop(_REASON_DEFAULT_STOP)


def escalation_decision_audit_fields(decision: EscalationDecision) -> dict[str, Any]:
    """Flatten an :class:`EscalationDecision` into JSON-safe audit fields.

    A wired caller merges these into its per-decision audit entry so an
    operator can reconstruct why a T2 case did (or did not) climb to a
    stronger model - the reproducibility the append-only log promises.
    Every field is a structured id / enum / tier name, never model text,
    so it is safe for the L0 audit surface.
    """
    return {
        "escalation_route": decision.route.value,
        "escalation_reason": decision.reason,
        "escalation_action_type": decision.action_type,
        "escalation_from_tier": decision.from_tier.name,
        "escalation_to_tier": (decision.to_tier.name if decision.to_tier is not None else None),
        **({"escalation_metadata": dict(decision.metadata)} if decision.metadata else {}),
    }


__all__ = [
    "EscalationTier",
    "EscalationRoute",
    "EscalationLadderConfig",
    "EscalationDecision",
    "decide_escalation",
    "escalation_decision_audit_fields",
]
