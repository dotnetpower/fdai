"""Cost Governance vertical - FinOps guardrails (G-6 scaffolded).

Phase 3 § Cost Governance. Wraps :mod:`.finops` (rightsizing / reserved
capacity / cleanup candidates + guard) in a subpackage so future
sub-modules (spend anomaly, showback, budget alerts) can land here
without touching a monolithic file.

Every symbol below is re-exported at the package facade so callers
continue to write ``from fdai.core.verticals.cost_governance import
FinOpsActionKind`` after G-6 (tracker #14, issue #20).

**Compat note.** Callers that used to import from
``fdai.core.verticals.finops`` are updated in the same commit; the old
module path is not re-exposed - the whole point of the cost_governance
scaffold is to establish the domain name upstream so a future
sub-module (anomaly, showback) has a natural home.
"""

from __future__ import annotations

from fdai.core.verticals.cost_governance.finops import (
    FinOpsActionKind,
    FinOpsCandidate,
    FinOpsEnvironment,
    FinOpsGuard,
    FinOpsGuardConfig,
    FinOpsGuardDecision,
    FinOpsGuardOutcome,
    ResourceContext,
)

__all__ = [
    "FinOpsActionKind",
    "FinOpsCandidate",
    "FinOpsEnvironment",
    "FinOpsGuard",
    "FinOpsGuardConfig",
    "FinOpsGuardDecision",
    "FinOpsGuardOutcome",
    "ResourceContext",
]
