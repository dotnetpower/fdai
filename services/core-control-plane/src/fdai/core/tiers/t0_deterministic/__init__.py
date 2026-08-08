"""T0 deterministic tier - policy evaluation, what-if, drift detection.

Public exports:

- :class:`~fdai.core.tiers.t0_deterministic.engine.T0Engine` - orchestrator.
- :class:`~fdai.core.tiers.t0_deterministic.engine.PolicyEvaluator` - DI seam
  for the check_logic runner (default: :class:`AbstainEvaluator`; the OPA/Rego
  runner :class:`OpaRegoEvaluator` binds at the composition root once ``opa`` is
  installed).
- :class:`~fdai.core.tiers.t0_deterministic.opa_evaluator.OpaRegoEvaluator`
  - subprocess-backed evaluator; raises
  :class:`~fdai.core.tiers.t0_deterministic.opa_evaluator.MissingOpaBinaryError`
  when ``opa`` is not on ``PATH`` so the composition root can bind
  :class:`AbstainEvaluator` explicitly (auditable degraded posture).
- :class:`~fdai.core.tiers.t0_deterministic.index.RuleIndex` - O(indexed) rule lookup.
- :class:`~fdai.core.tiers.t0_deterministic.models.Finding` /
  :class:`~fdai.core.tiers.t0_deterministic.models.Verdict` /
  :class:`~fdai.core.tiers.t0_deterministic.models.AuditHint` /
  :class:`~fdai.core.tiers.t0_deterministic.models.PipelineStage` - data types.

See ``docs/roadmap/phases/phase-1-rule-catalog-t0.md`` for the phase-1 T0 spec.
"""

from fdai.core.tiers.t0_deterministic.engine import (
    AbstainEvaluator,
    PolicyEvaluator,
    PolicyResult,
    T0Engine,
)
from fdai.core.tiers.t0_deterministic.index import RuleIndex
from fdai.core.tiers.t0_deterministic.models import (
    AuditHint,
    Finding,
    PipelineStage,
    Verdict,
)
from fdai.core.tiers.t0_deterministic.opa_evaluator import (
    MissingOpaBinaryError,
    OpaEvaluatorError,
    OpaRegoEvaluator,
)

__all__ = [
    "AbstainEvaluator",
    "AuditHint",
    "Finding",
    "MissingOpaBinaryError",
    "OpaEvaluatorError",
    "OpaRegoEvaluator",
    "PipelineStage",
    "PolicyEvaluator",
    "PolicyResult",
    "RuleIndex",
    "T0Engine",
    "Verdict",
]
