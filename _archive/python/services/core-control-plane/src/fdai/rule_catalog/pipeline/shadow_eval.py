"""Shadow evaluator - replay a candidate rule set against a scenario set.

Phase 2 continuous-update pipeline stage 3 (see
[`docs/roadmap/phases/phase-2-quality-and-t1.md § Shadow eval`]).

Contract
--------

Given a *candidate* rule catalog and a *scenario set*, replay every
scenario through the T0 engine + trust router in **judge-and-log** mode
and return a :class:`ShadowEvalReport` that the regression gate consumes
to decide promote-vs-rollback.

Measured signals per :class:`ShadowEvalReport`:

- **coverage**: fraction of scenarios where at least one candidate rule
  fired (compared later against the baseline coverage).
- **matches / abstains / no-route**: per-tier bucket counts.
- **policy escapes**: scenarios flagged ``should_trigger_policy_violation``
  by the expected guard but where the candidate produced NO finding -
  these MUST be zero for promotion (see phase-2 § Regression gate).
- **expected mismatches**: scenarios whose ``expected.decision`` /
  ``citing_rule_ids`` disagree with what the candidate produced. Non-fatal
  by itself (the regression gate weighs the aggregate), but always
  surfaced for review.

Every replay is judge-and-log by construction: this module never touches
the executor, delivery adapter, or state store. Shadow purity is a
property invariant asserted in the tests.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fdai.core.tiers.t0_deterministic import (
    PipelineStage,
    RuleIndex,
    T0Engine,
    Verdict,
)
from fdai.core.tiers.t0_deterministic.engine import PolicyEvaluator
from fdai.core.trust_router import RoutingTier, TrustRouter
from fdai.shared.contracts.models import Event, Rule

_DEFAULT_MAX_SCENARIOS_PER_REPLAY = 5_000


class ShadowEvalError(RuntimeError):
    """Raised when the shadow-eval cannot complete (malformed scenario, ...)."""


@dataclass(frozen=True, slots=True)
class ScenarioOutcome:
    """Per-scenario result of one shadow-eval run."""

    scenario_id: str
    expected_tier: str
    expected_decision: str
    actual_tier: str
    actual_pipeline_stage: str
    matched_rule_ids: tuple[str, ...] = ()
    expected_rule_ids: tuple[str, ...] = ()
    expected_should_execute: bool = False
    expected_should_trigger_policy_violation: bool = False
    reason: str | None = None

    @property
    def policy_violation_escape(self) -> bool:
        """`True` when the scenario expected a policy violation but nothing fired."""
        return self.expected_should_trigger_policy_violation and not self.matched_rule_ids

    @property
    def tier_matches_expectation(self) -> bool:
        return self.actual_tier == self.expected_tier

    @property
    def decision_matches_expectation(self) -> bool:
        """P1: T0 verdict maps to `auto` on match, `abstain` otherwise."""
        actual = "auto" if self.matched_rule_ids else "abstain"
        return actual == self.expected_decision

    @property
    def rules_match_expectation(self) -> bool:
        """`expected.citing_rule_ids` is a subset of matched (missing = allowed)."""
        if not self.expected_rule_ids:
            return True
        return set(self.expected_rule_ids).issubset(set(self.matched_rule_ids))


@dataclass(frozen=True, slots=True)
class ShadowEvalReport:
    """Aggregate result of one shadow-eval run.

    Consumed by the regression gate; kept as a frozen dataclass so a
    caller cannot mutate the counts between measurement and audit.
    """

    scenario_set_id: str
    """Version tag of the scenario set replayed (e.g. ``v2026.07``)."""

    candidate_rule_ids: tuple[str, ...]
    """Ids of the rules loaded into the candidate index."""

    scenario_count: int
    outcomes: tuple[ScenarioOutcome, ...] = field(default_factory=tuple)

    @property
    def matched_count(self) -> int:
        return sum(1 for o in self.outcomes if o.matched_rule_ids)

    @property
    def coverage(self) -> float:
        if self.scenario_count == 0:
            return 0.0
        return self.matched_count / self.scenario_count

    @property
    def policy_violation_escapes(self) -> int:
        return sum(1 for o in self.outcomes if o.policy_violation_escape)

    @property
    def tier_mismatches(self) -> int:
        return sum(1 for o in self.outcomes if not o.tier_matches_expectation)

    @property
    def decision_mismatches(self) -> int:
        return sum(1 for o in self.outcomes if not o.decision_matches_expectation)

    @property
    def missing_expected_rules(self) -> int:
        return sum(1 for o in self.outcomes if not o.rules_match_expectation)


class ShadowEvaluator:
    """Replay a candidate rule set against a scenario set - judge-and-log only.

    ``candidate_rules`` is the proposed rule catalog under evaluation.
    ``evaluator`` is the T0 policy evaluator (typically ``OpaRegoEvaluator``
    when OPA is installed; ``AbstainEvaluator`` otherwise - abstains never
    count as policy-violation escapes, but they DO leave expected-rule
    mismatches visible in the report).
    """

    def __init__(
        self,
        *,
        candidate_rules: Iterable[Rule],
        evaluator: PolicyEvaluator | None = None,
        max_scenarios_per_replay: int = _DEFAULT_MAX_SCENARIOS_PER_REPLAY,
    ) -> None:
        if max_scenarios_per_replay < 1:
            raise ValueError("max_scenarios_per_replay MUST be >= 1")
        rules_tuple = tuple(candidate_rules)
        self._index = RuleIndex.build(rules_tuple)
        self._rules_by_id = {r.id: r for r in rules_tuple}
        self._router = TrustRouter(index=self._index)
        self._engine = T0Engine(index=self._index, evaluator=evaluator)
        self._max = max_scenarios_per_replay

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate_scenarios(
        self,
        *,
        scenario_set_id: str,
        scenarios: Iterable[Mapping[str, Any]],
    ) -> ShadowEvalReport:
        """Replay every scenario and return a :class:`ShadowEvalReport`.

        Scenarios that fail schema (missing ``event``/``expected``) raise
        :class:`ShadowEvalError` - the pipeline is fail-closed on a
        malformed set rather than silently under-counting.
        """
        outcomes: list[ScenarioOutcome] = []
        for idx, scenario in enumerate(scenarios):
            if idx >= self._max:
                raise ShadowEvalError(
                    f"scenario cap {self._max} exceeded - raise "
                    "max_scenarios_per_replay if the frozen set has grown"
                )
            outcomes.append(self._evaluate_one(scenario))

        return ShadowEvalReport(
            scenario_set_id=scenario_set_id,
            candidate_rule_ids=tuple(self._rules_by_id.keys()),
            scenario_count=len(outcomes),
            outcomes=tuple(outcomes),
        )

    def evaluate_scenario_directory(
        self,
        *,
        scenario_set_id: str,
        directory: Path,
    ) -> ShadowEvalReport:
        """Convenience: load every ``*.json`` scenario in ``directory``."""
        scenarios = []
        for path in sorted(directory.glob("*.json")):
            try:
                scenarios.append(json.loads(path.read_text(encoding="utf-8")))
            except json.JSONDecodeError as exc:
                raise ShadowEvalError(f"scenario {path.name!r} is not valid JSON: {exc}") from exc
        return self.evaluate_scenarios(scenario_set_id=scenario_set_id, scenarios=scenarios)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _evaluate_one(self, scenario: Mapping[str, Any]) -> ScenarioOutcome:
        scenario_id = _require(scenario, "id")
        raw_event = _require(scenario, "event")
        expected = _require(scenario, "expected")

        # Some Phase 0 scenarios don't carry a payload with resource state;
        # we treat them as trust-router abstain (no resource_type).
        try:
            event = Event.model_validate(raw_event)
        except Exception as exc:
            raise ShadowEvalError(
                f"scenario {scenario_id!r} carries an invalid event: {exc}"
            ) from exc

        expected_tier = expected.get("tier", "t0")
        expected_decision = expected.get("decision", "abstain")
        expected_rule_ids = tuple(expected.get("citing_rule_ids", ()) or ())
        guard = expected.get("guard", {}) or {}

        routing = self._router.route(event)
        if routing.tier is RoutingTier.ABSTAIN:
            return ScenarioOutcome(
                scenario_id=scenario_id,
                expected_tier=expected_tier,
                expected_decision=expected_decision,
                actual_tier="abstain",
                actual_pipeline_stage=PipelineStage.ABSTAIN.value,
                matched_rule_ids=(),
                expected_rule_ids=expected_rule_ids,
                expected_should_execute=bool(guard.get("should_execute", False)),
                expected_should_trigger_policy_violation=bool(
                    guard.get("should_trigger_policy_violation", False)
                ),
                reason=routing.reason,
            )

        if routing.tier is RoutingTier.T1:
            return ScenarioOutcome(
                scenario_id=scenario_id,
                expected_tier=expected_tier,
                expected_decision=expected_decision,
                actual_tier="t1",
                actual_pipeline_stage=PipelineStage.ABSTAIN.value,
                matched_rule_ids=(),
                expected_rule_ids=expected_rule_ids,
                expected_should_execute=bool(guard.get("should_execute", False)),
                expected_should_trigger_policy_violation=bool(
                    guard.get("should_trigger_policy_violation", False)
                ),
                reason=routing.reason,
            )

        resource_type = routing.resource_type or "unknown"
        resource_id = _extract_resource_id(event, resource_type)
        verdict: Verdict = self._engine.evaluate(
            event_id=str(event.event_id),
            signal_id=str(event.event_id),
            resource_id=resource_id,
            resource_type=resource_type,
            resource_props=_extract_props(event.payload),
            signal_type=event.event_type,
        )
        matched = tuple(f.rule_id for f in verdict.findings)
        stage = (
            verdict.audit_hint.pipeline_stage.value
            if verdict.audit_hint is not None
            else PipelineStage.ABSTAIN.value
        )
        reason = verdict.audit_hint.reason if verdict.audit_hint is not None else None
        return ScenarioOutcome(
            scenario_id=scenario_id,
            expected_tier=expected_tier,
            expected_decision=expected_decision,
            actual_tier="t0",
            actual_pipeline_stage=stage,
            matched_rule_ids=matched,
            expected_rule_ids=expected_rule_ids,
            expected_should_execute=bool(guard.get("should_execute", False)),
            expected_should_trigger_policy_violation=bool(
                guard.get("should_trigger_policy_violation", False)
            ),
            reason=reason,
        )


def _require(scenario: Mapping[str, Any], key: str) -> Any:
    value = scenario.get(key)
    if value is None:
        raise ShadowEvalError(f"scenario missing required field {key!r}")
    return value


def _extract_props(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    resource = payload.get("resource")
    if isinstance(resource, dict):
        nested = resource.get("props")
        if isinstance(nested, dict):
            return dict(nested)
    flat = payload.get("props")
    if isinstance(flat, dict):
        return dict(flat)
    return {}


def _extract_resource_id(event: Event, resource_type: str) -> str:
    resource = event.payload.get("resource")
    if isinstance(resource, dict):
        rid = resource.get("resource_id")
        if isinstance(rid, str) and rid:
            return rid
    if event.resource_ref:
        return event.resource_ref
    return f"anonymous:{resource_type}"


__all__ = [
    "ScenarioOutcome",
    "ShadowEvalError",
    "ShadowEvalReport",
    "ShadowEvaluator",
]
