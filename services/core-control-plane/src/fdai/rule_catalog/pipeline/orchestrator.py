"""Continuous rule-update pipeline orchestrator.

Composes the P2-A stages end-to-end:

.. code-block:: text

    candidate rules + scenario set
       ─► ShadowEvaluator ─► RegressionGate ─► RulePromotionController
                              (PASS / FAIL)      (audited)

Each call is one *run*: given a candidate rule set, replay it against
the frozen scenario set, decide promote-vs-rollback, and produce an
audit-worthy result. The pipeline does NOT touch git / the delivery
adapter - the catalog-as-code PR machinery lives one layer up (a
future stage that a fork wires in). This keeps the pipeline itself
pure, so a fork can replace the delivery layer without editing ``core/``.

Phase 2 mapping (docs/roadmap/phases/phase-2-quality-and-t1.md):

- **source watcher** - external, delivers candidate rules; the caller
  hands the loaded catalog to :meth:`ContinuousRulePipeline.run`.
- **collect / normalize** - the rule loader already normalized the
  candidates (`rule_catalog/schema/rule.py`).
- **shadow eval** - :class:`ShadowEvaluator`.
- **regression gate** - :class:`RegressionGate`.
- **promote | rollback** - :class:`RulePromotionController`.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fdai.core.tiers.t0_deterministic.engine import PolicyEvaluator
from fdai.rule_catalog.pipeline.promotion import (
    BaselineState,
    PromotionRecord,
    RulePromotionController,
)
from fdai.rule_catalog.pipeline.regression_gate import (
    RegressionDecision,
    RegressionGate,
)
from fdai.rule_catalog.pipeline.shadow_eval import (
    ShadowEvalReport,
    ShadowEvaluator,
)
from fdai.shared.contracts.models import Rule
from fdai.shared.providers.state_store import StateStore


@dataclass(frozen=True, slots=True)
class PipelineRun:
    """Aggregate result of one :meth:`ContinuousRulePipeline.run` call."""

    candidate_report: ShadowEvalReport
    decision: RegressionDecision
    promotion: PromotionRecord
    baseline: BaselineState | None
    baseline_report: ShadowEvalReport | None = field(default=None)


@dataclass(frozen=True, slots=True)
class ContinuousRulePipeline:
    """Compose ShadowEvaluator + RegressionGate + PromotionController."""

    regression_gate: RegressionGate
    promotion: RulePromotionController
    evaluator: PolicyEvaluator | None = None
    """Optional T0 policy evaluator to use for the replay.

    Defaults to the T0 engine's built-in :class:`AbstainEvaluator` when
    omitted - abstains never count as policy-violation escapes, so a
    pipeline run with no OPA still exercises router + audit paths
    without spuriously failing the regression gate.
    """

    async def run(
        self,
        *,
        candidate_rules: Iterable[Rule],
        scenario_set_id: str,
        scenarios: Iterable[Mapping[str, Any]] | None = None,
        scenarios_dir: Path | None = None,
        baseline_rules: Iterable[Rule] | None = None,
        previous_baseline: BaselineState | None = None,
    ) -> PipelineRun:
        """Run one continuous-update cycle.

        Provide **exactly one** of ``scenarios`` / ``scenarios_dir``.
        ``baseline_rules`` is optional - when supplied, the pipeline
        replays it too so the regression gate has a fresh baseline
        report to compare against. Callers that keep a cached baseline
        report can skip that leg by passing ``baseline_rules=None`` and
        relying on ``previous_baseline`` for the audit trail.
        """
        candidate_rules_tuple = tuple(candidate_rules)
        candidate_report = self._replay(
            candidate_rules_tuple,
            scenario_set_id=scenario_set_id,
            scenarios=scenarios,
            scenarios_dir=scenarios_dir,
        )

        baseline_report: ShadowEvalReport | None = None
        if baseline_rules is not None:
            baseline_report = self._replay(
                tuple(baseline_rules),
                scenario_set_id=f"{scenario_set_id}::baseline",
                scenarios=scenarios,
                scenarios_dir=scenarios_dir,
            )

        decision = self.regression_gate.evaluate(
            candidate=candidate_report, baseline=baseline_report
        )
        record, new_baseline = await self.promotion.apply(
            decision=decision, previous_baseline=previous_baseline
        )
        return PipelineRun(
            candidate_report=candidate_report,
            decision=decision,
            promotion=record,
            baseline=new_baseline,
            baseline_report=baseline_report,
        )

    def _replay(
        self,
        rules: tuple[Rule, ...],
        *,
        scenario_set_id: str,
        scenarios: Iterable[Mapping[str, Any]] | None,
        scenarios_dir: Path | None,
    ) -> ShadowEvalReport:
        if (scenarios is None) == (scenarios_dir is None):
            raise ValueError("provide exactly one of `scenarios` or `scenarios_dir`")
        evaluator = ShadowEvaluator(candidate_rules=rules, evaluator=self.evaluator)
        if scenarios_dir is not None:
            return evaluator.evaluate_scenario_directory(
                scenario_set_id=scenario_set_id, directory=scenarios_dir
            )
        if scenarios is None:  # pragma: no cover - guarded above, kept for narrowing
            raise ValueError("scenarios were None after narrowing")
        return evaluator.evaluate_scenarios(scenario_set_id=scenario_set_id, scenarios=scenarios)


def build_pipeline(
    *,
    audit_store: StateStore,
    evaluator: PolicyEvaluator | None = None,
    regression_gate: RegressionGate | None = None,
) -> ContinuousRulePipeline:
    """Convenience factory the composition root uses in tests + fork bindings."""
    return ContinuousRulePipeline(
        regression_gate=regression_gate or RegressionGate(),
        promotion=RulePromotionController(audit_store=audit_store),
        evaluator=evaluator,
    )


__all__ = [
    "ContinuousRulePipeline",
    "PipelineRun",
    "build_pipeline",
]
