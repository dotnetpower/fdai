"""Risk-gate — the final safety-invariant enforcement point.

Phase 2 risk-gate (see
[`architecture.instructions.md § Risk-Gated Autonomy`] and
[`docs/roadmap/risk-classification.md`]).

Contract
--------

Given a proposed :class:`Action` + the referenced :class:`Rule` + the
matched :class:`OntologyActionType`, the risk gate produces a
:class:`RiskDecision`:

- ``auto`` — safety invariants + preconditions + blast radius all clean,
  and the ActionType has been **promoted to enforce** through the
  per-action promotion gate. Executor may apply.
- ``hil`` — high-risk (irreversible, over blast-radius cap, or
  precondition unresolved). Human-in-the-loop approval required.
- ``deny`` — an explicit deny signal (verifier from the T2 quality gate,
  or the ActionType's `preconditions` explicitly false).
- ``abstain`` — insufficient information to decide; no-op audit + HIL
  hand-off.

Every path writes an audit entry (the caller is expected to persist it
via :class:`~aiopspilot.shared.providers.state_store.StateStore`).

Promotion gate
--------------

An ActionType ships shadow-first. Promotion to enforce is a **separate**
decision keyed on measured metrics:

- ``min_shadow_days`` elapsed since first shadow deployment.
- ``min_samples`` shadow executions observed.
- ``min_accuracy`` (== 1 - false-positive rate) held over the window.
- ``max_policy_escapes`` == 0 in the window.

The :class:`ActionPromotionRegistry` records the current per-ActionType
mode + the promotion metric report the last decision was based on. The
risk gate reads that registry — it does NOT re-measure. Measurement is
the pipeline / KPI job's responsibility (P2-A + phase-0 KPI dashboard).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Literal

from aiopspilot.shared.contracts.models import (
    Action,
    Mode,
    OntologyActionType,
    Rule,
)
from aiopspilot.shared.providers.exemption import (
    ExemptionRegistry,
    empty_exemption_registry,
)


class RiskDecisionOutcome(StrEnum):
    AUTO = "auto"
    HIL = "hil"
    DENY = "deny"
    ABSTAIN = "abstain"


@dataclass(frozen=True, slots=True)
class PromotionMetrics:
    """Measured metrics for one ActionType's shadow window.

    Consumed by :class:`ActionPromotionRegistry.consider_promotion`.
    """

    action_type: str
    shadow_days: int
    samples: int
    accuracy: float
    policy_escapes: int


@dataclass(frozen=True, slots=True)
class ActionModeRecord:
    """Current effective mode for one ActionType + provenance."""

    action_type: str
    mode: Mode
    promoted_at: datetime | None = None
    demoted_at: datetime | None = None
    metrics: PromotionMetrics | None = None


class ActionPromotionRegistry:
    """In-process registry of per-ActionType enforce/shadow state.

    A fork MAY back this with the state store; the P1/P2 default is
    in-memory so tests don't need Postgres. The registry NEVER mutates
    the ActionType YAML — a promotion is a runtime state change, not a
    catalog edit.
    """

    def __init__(self) -> None:
        self._records: dict[str, ActionModeRecord] = {}

    def mode_of(self, action_type: str) -> Mode:
        record = self._records.get(action_type)
        return record.mode if record is not None else Mode.SHADOW

    def record(self, action_type: str) -> ActionModeRecord | None:
        return self._records.get(action_type)

    def consider_promotion(
        self,
        *,
        action_type: OntologyActionType,
        metrics: PromotionMetrics,
    ) -> ActionModeRecord:
        """Promote the ActionType if metrics clear its ``promotion_gate``.

        Metrics that fail the gate demote back to shadow (or leave shadow
        untouched when nothing was promoted yet). Every call writes a
        record; the caller audits it.
        """
        if metrics.action_type != action_type.name:
            raise ValueError(
                f"metrics.action_type {metrics.action_type!r} != "
                f"action_type.name {action_type.name!r}"
            )
        gate = action_type.promotion_gate
        now = datetime.now(tz=UTC)
        passes = (
            metrics.shadow_days >= gate.min_shadow_days
            and metrics.samples >= gate.min_samples
            and metrics.accuracy >= gate.min_accuracy
            and metrics.policy_escapes <= gate.max_policy_escapes
        )
        if passes:
            record = ActionModeRecord(
                action_type=action_type.name,
                mode=Mode.ENFORCE,
                promoted_at=now,
                metrics=metrics,
            )
        else:
            prior = self._records.get(action_type.name)
            demoted_at = now if prior is not None and prior.mode is Mode.ENFORCE else None
            record = ActionModeRecord(
                action_type=action_type.name,
                mode=Mode.SHADOW,
                promoted_at=(prior.promoted_at if prior else None),
                demoted_at=demoted_at,
                metrics=metrics,
            )
        self._records[action_type.name] = record
        return record

    def demote(
        self,
        action_type_name: str,
        *,
        metrics: PromotionMetrics | None = None,
    ) -> ActionModeRecord:
        """Force an ActionType back to shadow (regression / override path).

        Idempotent: demoting an ActionType that has never been recorded
        creates a shadow record; demoting one already in shadow leaves
        ``demoted_at`` at its prior value. ``demoted_at`` is stamped only
        when this call transitions the record out of ``ENFORCE`` — that
        keeps the audit trail meaningful (a "demotion" against an
        already-shadow entry is not a state change).

        The optional ``metrics`` argument records the measurement that
        justified the demotion so the audit consumer can render the same
        reason the regression detector produced.
        """
        if not action_type_name:
            raise ValueError("action_type_name MUST NOT be empty")
        now = datetime.now(tz=UTC)
        prior = self._records.get(action_type_name)
        demoted_at: datetime | None
        if prior is None:
            demoted_at = None
            promoted_at: datetime | None = None
            prior_metrics = None
        else:
            demoted_at = now if prior.mode is Mode.ENFORCE else prior.demoted_at
            promoted_at = prior.promoted_at
            prior_metrics = prior.metrics
        record = ActionModeRecord(
            action_type=action_type_name,
            mode=Mode.SHADOW,
            promoted_at=promoted_at,
            demoted_at=demoted_at,
            metrics=metrics if metrics is not None else prior_metrics,
        )
        self._records[action_type_name] = record
        return record


@dataclass(frozen=True, slots=True)
class RiskGateConfig:
    """Executor-side caps applied at the risk gate."""

    max_affected_resources: int = 10
    max_rate_per_minute: int = 30
    max_precondition_age_seconds: int = 900


@dataclass(frozen=True, slots=True)
class RiskDecision:
    """Frozen record emitted by :meth:`RiskGate.evaluate`."""

    outcome: RiskDecisionOutcome
    action_id: str
    effective_mode: Mode
    reasons: tuple[str, ...] = field(default_factory=tuple)
    """Every reason contributing to the outcome — empty on clean AUTO."""


class RiskGate:
    """Compose the four safety-invariant checks + promotion mode read."""

    def __init__(
        self,
        *,
        registry: ActionPromotionRegistry,
        config: RiskGateConfig | None = None,
        exemption_registry: ExemptionRegistry | None = None,
    ) -> None:
        cfg = config or RiskGateConfig()
        if cfg.max_affected_resources < 1:
            raise ValueError("max_affected_resources MUST be >= 1")
        if cfg.max_rate_per_minute < 1:
            raise ValueError("max_rate_per_minute MUST be >= 1")
        if cfg.max_precondition_age_seconds < 0:
            raise ValueError("max_precondition_age_seconds MUST be >= 0")
        self._registry = registry
        self._config = cfg
        self._exemptions = exemption_registry or empty_exemption_registry()

    def evaluate(
        self,
        *,
        action: Action,
        rule: Rule,
        action_type: OntologyActionType,
        inventory_age_seconds: int | None = None,
        upstream_signal: Literal["deny", "abstain"] | None = None,
    ) -> RiskDecision:
        """Return a :class:`RiskDecision` for the proposed action.

        ``upstream_signal`` propagates a terminal signal from the T2
        quality gate (``deny`` -> :attr:`RiskDecisionOutcome.DENY`;
        ``abstain`` -> :attr:`RiskDecisionOutcome.ABSTAIN` when no other
        reason applies). A deny short-circuits every other check.
        ``inventory_age_seconds`` MUST be supplied when the ActionType
        declares a ``graph_fresh_within_seconds`` precondition; a
        missing age fails **closed** to HIL (see coding-conventions).
        """
        # Rule metadata (severity/category) is reserved for a future
        # scoring model that adjusts blast-radius caps by severity; see
        # risk-classification.md. Kept in the signature so callers do
        # not have to change when that lands.
        del rule
        reasons: list[str] = []

        # 0. Upstream deny short-circuits (T2 verifier explicit reject).
        if upstream_signal == "deny":
            return RiskDecision(
                outcome=RiskDecisionOutcome.DENY,
                action_id=str(action.action_id),
                effective_mode=self._registry.mode_of(action_type.name),
                reasons=("upstream_verifier_deny",),
            )

        # 0.5. Human override (Exemption). An active exemption on the
        # cited rule + target scope suppresses execution but NEVER hides
        # the finding (architecture.instructions § Human Override).
        # Every citing rule is checked; the first match wins.
        for cited in action.citing_rules:
            match = self._exemptions.find_match(
                rule_id=cited,
                resource_ref=action.target_resource_ref,
                resource_group=_extract_resource_group(action.target_resource_ref),
            )
            if match is not None:
                return RiskDecision(
                    outcome=RiskDecisionOutcome.ABSTAIN,
                    action_id=str(action.action_id),
                    effective_mode=self._registry.mode_of(action_type.name),
                    reasons=(
                        f"human_override:exemption={match.exemption_id}"
                        f":scope={match.scope_summary}",
                    ),
                )

        # 1. Explicit irreversible → HIL + quorum (P1 policy).
        if action_type.irreversible:
            reasons.append("action_type_irreversible_requires_hil")

        # 2. Blast-radius caps.
        count = action.blast_radius.count
        if count is not None and count > self._config.max_affected_resources:
            reasons.append(f"blast_radius_count={count}>max={self._config.max_affected_resources}")
        rpm = action.blast_radius.rate_per_minute
        if rpm is not None and rpm > self._config.max_rate_per_minute:
            reasons.append(f"blast_radius_rate={rpm}>max={self._config.max_rate_per_minute}")

        # 3. Precondition freshness — a stale inventory read blocks
        # graph-derived preconditions per the ActionType contract.
        # Fail-close: if the ActionType demands the check but the caller
        # did not supply an age, treat the precondition as unresolved.
        requires_fresh = any(
            p.kind.value == "graph_fresh_within_seconds" for p in action_type.preconditions
        )
        if requires_fresh:
            if inventory_age_seconds is None:
                reasons.append("graph_fresh_precondition_unknown_age")
            else:
                declared = _declared_graph_fresh_seconds(action_type)
                floor = min(declared, self._config.max_precondition_age_seconds)
                if inventory_age_seconds > floor:
                    reasons.append(
                        f"graph_fresh_precondition_stale:age={inventory_age_seconds}>max={floor}"
                    )

        # 4. Missing safety-invariant fields (defense in depth against a
        # partial Action that slipped past pydantic; unreachable via the
        # public API).
        if not action.stop_condition.strip():  # pragma: no cover
            reasons.append("missing_stop_condition")
        if not action.citing_rules:  # pragma: no cover
            reasons.append("missing_citing_rules")

        # 5. Effective mode from the promotion registry. Shadow mode is
        # a hard reason (an autonomous auto in shadow contradicts itself),
        # recorded BEFORE the upstream-abstain check so a shadow-mode
        # action never masquerades as a soft ABSTAIN.
        effective_mode = self._registry.mode_of(action_type.name)
        if effective_mode is not Mode.ENFORCE:
            reasons.append("action_type_in_shadow_mode")

        # 6. Upstream abstain → ABSTAIN when nothing else already forced HIL.
        if upstream_signal == "abstain" and not reasons:
            return RiskDecision(
                outcome=RiskDecisionOutcome.ABSTAIN,
                action_id=str(action.action_id),
                effective_mode=effective_mode,
                reasons=("upstream_verifier_abstain",),
            )

        if reasons:
            outcome = RiskDecisionOutcome.HIL
        else:
            outcome = RiskDecisionOutcome.AUTO

        return RiskDecision(
            outcome=outcome,
            action_id=str(action.action_id),
            effective_mode=effective_mode,
            reasons=tuple(reasons),
        )


def _declared_graph_fresh_seconds(action_type: OntologyActionType) -> int:
    """Return the smallest ``graph_fresh_within_seconds`` precondition value.

    Assumes the caller has already verified at least one precondition of
    that kind exists on ``action_type`` — raises when the values are not
    numeric so a malformed ActionType surfaces at first use instead of
    being silently ignored.
    """
    values: list[int] = []
    for precondition in action_type.preconditions:
        if precondition.kind.value != "graph_fresh_within_seconds":
            continue
        val = precondition.value
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            values.append(int(val))
    if not values:
        raise ValueError(
            f"ActionType {action_type.name!r} declares a graph_fresh_within_seconds "
            "precondition but no numeric value was found"
        )
    return min(values)


def _extract_resource_group(resource_ref: str) -> str | None:
    """Parse the resource-group segment from an ARM resource id.

    Returns ``None`` when the reference is not an ARM id or does not
    include a ``resourceGroups/<name>`` segment. Case-insensitive on the
    segment key — ARM ids may appear as ``resourcegroups`` in the wild.
    """
    lowered = resource_ref.lower()
    marker = "/resourcegroups/"
    idx = lowered.find(marker)
    if idx < 0:
        return None
    tail = resource_ref[idx + len(marker) :]
    slash = tail.find("/")
    if slash < 0:
        candidate = tail
    else:
        candidate = tail[:slash]
    return candidate or None


def duration_since(dt: datetime) -> timedelta:
    """Elapsed time since ``dt`` (helper for the promotion metric caller)."""
    return datetime.now(tz=UTC) - dt


__all__ = [
    "ActionModeRecord",
    "ActionPromotionRegistry",
    "PromotionMetrics",
    "RiskDecision",
    "RiskDecisionOutcome",
    "RiskGate",
    "RiskGateConfig",
    "duration_since",
]
