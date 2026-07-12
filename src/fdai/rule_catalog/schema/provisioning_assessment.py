"""assess_provisioning - is every registry capability actually deployed?

The bootstrap resolver (:mod:`fdai.rule_catalog.schema.llm_resolver`)
degrades an unprovisionable capability to ``hil-only`` and keeps going, so
a partial deployment is *silent*: ``resolved-models.json`` can carry only
``t1.embedding`` + ``t1.judge`` + ``t2.reasoner.primary`` while the
registry declares a secondary reasoner, a critic, an RCA reasoner, and an
escalation ceiling. At runtime the composition root then quietly falls
back to a forced-disagree cross-check and every T2 case routes to HIL -
with no signal at deploy time that the reasoning tier is effectively off.

This module closes that gap. Given the authoritative
:class:`~fdai.rule_catalog.schema.llm_registry.LlmRegistry` (the *intended*
capability set) and the :class:`~fdai.rule_catalog.schema.llm_resolver.ResolvedModels`
(what was *actually* provisioned), :func:`assess_provisioning` returns a
deterministic :class:`ProvisioningReport` classifying every capability as
``resolved`` / ``capacity-reduced`` / ``hil-only`` / ``missing``, deciding
whether the mixed-model T2 quorum can form, and rolling the whole thing up
to a single :class:`ProvisioningSeverity` the deploy pipeline gates on and
the audit log records.

Pure function: no I/O, no wall-clock, no SDK. Same registry + resolved ->
same report, so a CI check and a deploy-time gate agree.

Design reference:
- ``docs/roadmap/architecture/llm-strategy.md`` (Bootstrap Provisioner).
- ``docs/roadmap/deployment/dev-and-deploy-parity.md`` (Deployer-Scoped
  LLM Provisioning).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from fdai.rule_catalog.schema.llm_registry import LlmRegistry, MixedModelMode
from fdai.rule_catalog.schema.llm_resolver import (
    CapabilityStatus,
    ResolvedModels,
)

# Capabilities whose absence breaks a core tier outright.
_CORE_REQUIRED: frozenset[str] = frozenset({"t1.embedding", "t1.judge", "t2.reasoner.primary"})
# The capability that lets the T2 cross-check reach a mixed-model quorum.
_QUORUM_REQUIRED: frozenset[str] = frozenset({"t2.reasoner.secondary"})

# What a caller loses when a capability is not fully provisioned. Keyed by
# the registry capability name; capabilities absent here are treated as
# optional with a generic impact string.
_IMPACT: dict[str, str] = {
    "t1.embedding": "T1 similarity retrieval and vector reuse unavailable",
    "t1.judge": "T1 classification and the console narrator mini tier unavailable",
    "t2.reasoner.primary": "T2 reasoning unavailable - novel cases route to HIL",
    "t2.reasoner.secondary": ("T2 mixed-model quorum cannot form - every T2 case routes to HIL"),
    "t2.reasoner.escalated": "escalation ladder cannot climb to a stronger model",
    "t2.critic": "debate critic unavailable - cross-check disagreements route to HIL",
    "t2.rca": "LLM root-cause reasoner unavailable - RCA stays deterministic-only",
    "t2.rubric.judge": "hallucination rubric filter unavailable",
}


class ProvisioningState(StrEnum):
    """Per-capability outcome, extending resolver statuses with MISSING.

    ``MISSING`` means the registry declares the capability but
    ``resolved-models.json`` has no entry for it at all - distinct from
    ``HIL_ONLY`` (present but degraded, so the audit shows *why*).
    """

    RESOLVED = "resolved"
    CAPACITY_REDUCED = "capacity-reduced"
    HIL_ONLY = "hil-only"
    MISSING = "missing"


class CapabilityTier(StrEnum):
    """How important a capability is to a complete deployment."""

    CORE = "core"
    QUORUM = "quorum"
    OPTIONAL = "optional"


class ProvisioningSeverity(StrEnum):
    """Roll-up verdict the deploy pipeline gates on.

    ``OK`` - every declared capability is resolved. ``DEGRADED`` - only
    optional capabilities are missing / hil-only (debate, RCA, escalation,
    rubric); the core loop and T2 quorum still work. ``CRITICAL`` - a core
    capability is missing / hil-only, or the mixed-model quorum cannot
    form, so T2 is effectively off.
    """

    OK = "ok"
    DEGRADED = "degraded"
    CRITICAL = "critical"


@dataclass(frozen=True, slots=True)
class CapabilityAssessment:
    """One capability's provisioning outcome + its blast radius."""

    name: str
    tier: CapabilityTier
    state: ProvisioningState
    impact: str | None

    @property
    def is_available(self) -> bool:
        return self.state in (
            ProvisioningState.RESOLVED,
            ProvisioningState.CAPACITY_REDUCED,
        )


@dataclass(frozen=True, slots=True)
class ProvisioningReport:
    """Deterministic assessment of a resolved-models deployment."""

    severity: ProvisioningSeverity
    quorum_ok: bool
    capabilities: tuple[CapabilityAssessment, ...]
    reasons: tuple[str, ...]

    @property
    def is_complete(self) -> bool:
        """True iff every declared capability resolved (severity OK)."""

        return self.severity is ProvisioningSeverity.OK

    @property
    def degraded(self) -> tuple[CapabilityAssessment, ...]:
        return tuple(c for c in self.capabilities if not c.is_available)


def _tier_of(name: str) -> CapabilityTier:
    if name in _CORE_REQUIRED:
        return CapabilityTier.CORE
    if name in _QUORUM_REQUIRED:
        return CapabilityTier.QUORUM
    return CapabilityTier.OPTIONAL


def _state_of(status: CapabilityStatus) -> ProvisioningState:
    return {
        CapabilityStatus.RESOLVED: ProvisioningState.RESOLVED,
        CapabilityStatus.CAPACITY_REDUCED: ProvisioningState.CAPACITY_REDUCED,
        CapabilityStatus.HIL_ONLY: ProvisioningState.HIL_ONLY,
    }[status]


def assess_provisioning(
    *,
    registry: LlmRegistry,
    resolved: ResolvedModels,
) -> ProvisioningReport:
    """Compare intended (registry) vs actual (resolved) capabilities.

    The registry is the source of truth for *what should exist*; the
    resolved record is *what does*. Every capability the registry declares
    is assessed; a resolved entry for a capability the registry does not
    declare is ignored (a stale entry is a separate concern).
    """

    resolved_map = {c.name: c for c in resolved.capabilities}
    hil_only_mode = resolved.mixed_model_mode == MixedModelMode.HIL_ONLY.value

    assessments: list[CapabilityAssessment] = []
    for name in sorted(registry.models):
        tier = _tier_of(name)
        entry = resolved_map.get(name)
        state = ProvisioningState.MISSING if entry is None else _state_of(entry.status)
        impact = (
            None
            if state
            in (
                ProvisioningState.RESOLVED,
                ProvisioningState.CAPACITY_REDUCED,
            )
            else _IMPACT.get(name, f"{name} unavailable")
        )
        assessments.append(CapabilityAssessment(name=name, tier=tier, state=state, impact=impact))

    by_name = {a.name: a for a in assessments}

    def _available(name: str) -> bool:
        a = by_name.get(name)
        return a is not None and a.is_available

    # Mixed-model quorum needs both reasoners available and, per the
    # registry invariant, distinct publishers. In hil-only mode there is
    # no secondary by design, so quorum is not expected.
    quorum_ok = (
        not hil_only_mode
        and _available("t2.reasoner.primary")
        and _available("t2.reasoner.secondary")
    )

    reasons: list[str] = []
    critical = False
    for a in assessments:
        if a.is_available:
            continue
        # A missing QUORUM capability is only critical when a quorum is
        # expected; in hil-only mode there is no secondary by design.
        critical_tier = a.tier is CapabilityTier.CORE or (
            a.tier is CapabilityTier.QUORUM and not hil_only_mode
        )
        if critical_tier:
            critical = True
        reasons.append(f"{a.name}:{a.state.value}:{a.impact}")

    if not hil_only_mode and not quorum_ok:
        critical = True
        reasons.append(
            "t2.quorum:unavailable:mixed-model cross-check cannot form - T2 routes to HIL"
        )

    if critical:
        severity = ProvisioningSeverity.CRITICAL
    elif reasons:
        severity = ProvisioningSeverity.DEGRADED
    else:
        severity = ProvisioningSeverity.OK

    return ProvisioningReport(
        severity=severity,
        quorum_ok=quorum_ok,
        capabilities=tuple(assessments),
        reasons=tuple(reasons),
    )


__all__ = [
    "CapabilityAssessment",
    "CapabilityTier",
    "ProvisioningReport",
    "ProvisioningSeverity",
    "ProvisioningState",
    "assess_provisioning",
]
