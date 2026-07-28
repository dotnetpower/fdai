"""T0 deterministic engine - verdict emitter.

The engine assembles a :class:`Verdict` for one incoming Signal:

1. Look up candidate rules through :class:`RuleIndex` (O(indexed)).
2. Ask each rule's :class:`PolicyEvaluator` whether the check_logic
   evaluates to *deny* on the current resource properties. In P1 W-2 the
   default evaluator is :class:`AbstainEvaluator` - it always abstains,
   so the engine emits an :attr:`PipelineStage.ABSTAIN` verdict with the
   candidate rule ids as citations. The OPA/Rego runner lands in P1 W-3
   behind the same Protocol.
3. On any positive match, emit a :class:`Finding` per rule and an
   :class:`AuditHint` with :attr:`PipelineStage.L1_EVALUATE`.

Safety invariants held here (P1, shadow-mode)
---------------------------------------------
- **Never mutates**: the engine only produces data; it does not call an
  executor or a delivery adapter.
- **Fail-closed**: if an evaluator raises, the engine records an
  ``abstain`` verdict for that rule instead of skipping it silently.
- **Deterministic ordering**: findings are ordered by severity desc,
  then rule_id - matches :mod:`.index` ordering.
- **Shadow mode**: every emitted :class:`AuditHint` carries
  ``mode=Mode.SHADOW`` because P1 does not have an enforce path.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from fdai.core.tiers.t0_deterministic.index import RuleIndex
from fdai.core.tiers.t0_deterministic.models import (
    AuditHint,
    Finding,
    PipelineStage,
    Verdict,
)
from fdai.shared.contracts.models import Mode, Rule, Severity


@runtime_checkable
class PolicyEvaluator(Protocol):
    """Evaluate a rule's ``check_logic`` against resource properties.

    Kept as a Protocol so P1 W-3 can swap in an OPA/Rego runner without
    touching :class:`T0Engine`. Implementations MUST be pure functions of
    ``(rule, resource_props)`` - no I/O, no state - and MUST return
    ``None`` to abstain (grounding unavailable) rather than guessing.
    """

    def evaluate(self, rule: Rule, resource_props: Mapping[str, Any]) -> PolicyResult | None:
        """Return the deny/allow outcome or ``None`` to abstain."""
        ...


@dataclass(frozen=True, slots=True)
class PolicyResult:
    """Deterministic outcome of a single rule's ``check_logic``."""

    denied: bool
    """True when the rule's check_logic evaluates to a violation."""

    context: dict[str, Any]
    """Inert, JSON-safe context (which property failed, threshold used, ...)."""


class AbstainEvaluator:
    """Default P1 W-2 evaluator - always abstains.

    The Rego runner is P1 W-3. Until then, T0 records that the rules
    *would* have been considered and hands the case to HIL through the
    ``abstain`` pipeline stage. This is intentional: an ungrounded auto
    would violate the "abstain when unsupported" rule in
    ``architecture.instructions.md``.
    """

    def evaluate(self, rule: Rule, resource_props: Mapping[str, Any]) -> PolicyResult | None:
        del rule, resource_props
        return None


class T0Engine:
    """Deterministic engine - one call, one :class:`Verdict`."""

    def __init__(
        self,
        *,
        index: RuleIndex,
        evaluator: PolicyEvaluator | None = None,
    ) -> None:
        self._index = index
        self._evaluator: PolicyEvaluator = evaluator or AbstainEvaluator()

    def evaluate(
        self,
        *,
        event_id: str,
        signal_id: str,
        resource_id: str,
        resource_type: str,
        resource_props: Mapping[str, Any],
        signal_type: str | None = None,
    ) -> Verdict:
        """Evaluate every rule that applies to this Signal.

        Returns a :class:`Verdict` with:
        - :attr:`Verdict.findings` populated when at least one rule
          evaluated to a violation, ordered by severity desc / rule_id;
        - an :class:`AuditHint` carrying the pipeline stage that was
          reached (``L1_evaluate`` on match, ``abstain`` otherwise).

        The engine NEVER raises for a rule-evaluation error; it downgrades
        that rule's outcome to an abstain and continues, so a single
        broken rule cannot silence the rest of the catalog.
        """
        candidates = self._index.rules_for_signal(
            resource_type=resource_type, signal_type=signal_type
        )
        findings: list[Finding] = []
        citing: list[str] = []
        abstained: list[str] = []

        for rule in candidates:
            citing.append(rule.id)
            try:
                result = self._evaluator.evaluate(rule, resource_props)
            except Exception:  # noqa: BLE001 - fail-closed: log-and-abstain
                # Fail closed: one bad evaluator MUST NOT crash the loop.
                # The rule is abstained; the audit hint records that.
                abstained.append(rule.id)
                continue

            if result is None:
                abstained.append(rule.id)
                continue
            if not result.denied:
                continue

            findings.append(
                Finding(
                    finding_id=_finding_id(rule=rule, resource_id=resource_id, signal_id=signal_id),
                    rule_id=rule.id,
                    rule_version=rule.version,
                    resource_id=resource_id,
                    signal_id=signal_id,
                    severity=rule.severity,
                    context=dict(result.context),
                )
            )

        findings = sorted(
            findings,
            key=lambda f: (-_severity_rank(f.severity), f.rule_id),
        )

        audit = AuditHint(
            event_id=event_id,
            pipeline_stage=(PipelineStage.L1_EVALUATE if findings else PipelineStage.ABSTAIN),
            tier="t0",
            mode=Mode.SHADOW,
            citing_rule_ids=tuple(citing),
            reason=_abstain_reason(candidates, abstained, findings),
        )

        return Verdict(findings=tuple(findings), audit_hint=audit)


def _finding_id(*, rule: Rule, resource_id: str, signal_id: str) -> str:
    # Stable, human-readable id keyed on (rule, resource, signal). The
    # audit store will hash-chain, but the id itself needs to survive
    # replays: same inputs -> same finding_id.
    return f"{rule.id}::{rule.version}::{resource_id}::{signal_id}"


_SEVERITY_RANK: dict[Severity, int] = {
    Severity.CRITICAL: 4,
    Severity.HIGH: 3,
    Severity.MEDIUM: 2,
    Severity.LOW: 1,
}


def _severity_rank(severity: Severity) -> int:
    return _SEVERITY_RANK[severity]


def _abstain_reason(
    candidates: tuple[Rule, ...],
    abstained: list[str],
    findings: list[Finding],
) -> str | None:
    if findings:
        return None
    if not candidates:
        return "no_rule_matched_resource_type"
    if len(abstained) == len(candidates):
        return "evaluator_abstained_on_all_candidates"
    if abstained:
        return "evaluator_abstained_on_some_candidates"
    return "no_rule_denied"


__all__ = [
    "AbstainEvaluator",
    "PolicyEvaluator",
    "PolicyResult",
    "T0Engine",
]
