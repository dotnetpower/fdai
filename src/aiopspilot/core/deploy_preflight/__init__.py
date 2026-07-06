"""deploy-preflight - collect deployment blockers before an apply.

Before the executor emits a remediation PR (and as a standalone check for
human-authored deploys), the preflight pass runs a set of deterministic
:class:`~aiopspilot.shared.providers.feasibility_probe.FeasibilityProbe`
implementations over a :class:`PreflightTarget` and assembles a single
grounded :class:`DeploymentReadinessReport`. It is the ``what-if`` verifier
generalized from per-action to per-deployment.

Full design: ``docs/roadmap/deployment-preflight.md``.
"""

from __future__ import annotations

from aiopspilot.core.deploy_preflight.analyzer import PreflightAnalyzer
from aiopspilot.core.deploy_preflight.report import (
    DeploymentReadinessReport,
    ReadinessVerdict,
)

__all__ = [
    "DeploymentReadinessReport",
    "PreflightAnalyzer",
    "ReadinessVerdict",
]
