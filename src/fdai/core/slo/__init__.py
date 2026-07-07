"""Workload SLO subsystem - SLI / Objective / ErrorBudget / BurnRate.

Design contract: ``docs/roadmap/sre-agent-scope.md § 3.3``.

**Distinct from control-plane SLOs** documented in
[deployment.md](../../../../docs/roadmap/deployment.md), which measure
FDAI itself (event-processing latency per tier, action success rate,
console availability). This subsystem measures the **workloads** FDAI
operates on so incident priority and change-freeze decisions can be
ranked by real user impact.

Public surface:

- :class:`SLO` - the dataclass form of the JSON schema shipped at
  ``shared/contracts/slo/schema.json``.
- :class:`SloRegistry` - loads SLOs from YAML files under
  ``rule-catalog/slo/`` (fork-hosted; upstream ships zero definitions).
- :class:`BurnRateEvaluator` - Google-SRE Ch. 5 multi-window
  multi-burn-rate alert evaluator. A breach emits an
  :class:`~fdai.shared.contracts.models.Event` on the internal bus
  (``event_type="slo.error_budget_burn"``) so the standard
  trust-router / risk-gate / executor path handles the response - no
  side channel.
- :class:`ErrorBudget` / :class:`BurnRate` - value objects.
"""

from __future__ import annotations

from .burn_rate import BurnRate, BurnRateAlert, BurnRateBreach, BurnRateEvaluator
from .models import SLI, SLO, ErrorBudget, SLIKind
from .registry import SloRegistry, SloRegistryError

__all__ = [
    "SLI",
    "SLO",
    "BurnRate",
    "BurnRateAlert",
    "BurnRateBreach",
    "BurnRateEvaluator",
    "ErrorBudget",
    "SLIKind",
    "SloRegistry",
    "SloRegistryError",
]
