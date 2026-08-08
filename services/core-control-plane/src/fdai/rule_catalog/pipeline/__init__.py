"""Watch → collect → shadow-eval → regression → promote / rollback.

Phase 2 continuous rule-update pipeline. Every stage writes an audit
entry; a rule change is delivered as a catalog-as-code PR, defaulting to
shadow-only per
[`docs/roadmap/phases/phase-2-quality-and-t1.md`].

Public exports:

- :class:`~fdai.rule_catalog.pipeline.shadow_eval.ShadowEvaluator` -
  replay a candidate rule set against a scenario set in judge-and-log mode.
- :class:`~fdai.rule_catalog.pipeline.shadow_eval.ShadowEvalReport` /
  :class:`~fdai.rule_catalog.pipeline.shadow_eval.ScenarioOutcome` -
  measurement types consumed by the regression gate.
"""

from fdai.rule_catalog.pipeline.orchestrator import (
    ContinuousRulePipeline,
    PipelineRun,
    build_pipeline,
)
from fdai.rule_catalog.pipeline.promotion import (
    BaselineState,
    PromotionOutcome,
    PromotionRecord,
    RulePromotionController,
)
from fdai.rule_catalog.pipeline.regression_gate import (
    RegressionDecision,
    RegressionGate,
    RegressionGateConfig,
    RegressionOutcome,
)
from fdai.rule_catalog.pipeline.shadow_eval import (
    ScenarioOutcome,
    ShadowEvalError,
    ShadowEvalReport,
    ShadowEvaluator,
)

__all__ = [
    "BaselineState",
    "ContinuousRulePipeline",
    "PipelineRun",
    "PromotionOutcome",
    "PromotionRecord",
    "RegressionDecision",
    "RegressionGate",
    "RegressionGateConfig",
    "RegressionOutcome",
    "RulePromotionController",
    "ScenarioOutcome",
    "ShadowEvalError",
    "ShadowEvalReport",
    "ShadowEvaluator",
    "build_pipeline",
]
