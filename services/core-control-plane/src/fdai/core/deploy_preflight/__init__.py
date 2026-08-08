"""deploy-preflight - collect deployment blockers before an apply.

Before the executor emits a remediation PR (and as a standalone check for
human-authored deploys), the preflight pass runs a set of deterministic
:class:`~fdai.shared.providers.feasibility_probe.FeasibilityProbe`
implementations over a :class:`PreflightTarget` and assembles a single
grounded :class:`DeploymentReadinessReport`. It is the ``what-if`` verifier
generalized from per-action to per-deployment.

Full design: ``docs/roadmap/deployment/deployment-preflight.md``.
"""

from __future__ import annotations

from fdai.core.deploy_preflight.analyzer import PreflightAnalyzer
from fdai.core.deploy_preflight.check_publish import (
    PreflightCheckOutcome,
    PreflightCheckResult,
    publish_preflight_check,
)
from fdai.core.deploy_preflight.environment_profile import (
    DeploymentEnvironmentProfile,
    DeploymentEnvironmentProfileCache,
    apply_inventory_delta,
    build_profile,
)
from fdai.core.deploy_preflight.reassemble import (
    AppliedToggle,
    ReanalyzeFn,
    ReassemblyOutcome,
    ReassemblyReason,
    ReassemblyStatus,
    reassemble,
)
from fdai.core.deploy_preflight.reassembly_proposals import (
    ACTION_TYPE,
    ProposalSink,
    ToggleActionProposal,
    build_toggle_proposals,
    submit_toggle_proposals,
)
from fdai.core.deploy_preflight.report import (
    DeploymentReadinessReport,
    ReadinessVerdict,
)

__all__ = [
    "ACTION_TYPE",
    "AppliedToggle",
    "DeploymentEnvironmentProfile",
    "DeploymentEnvironmentProfileCache",
    "DeploymentReadinessReport",
    "PreflightAnalyzer",
    "PreflightCheckOutcome",
    "PreflightCheckResult",
    "ProposalSink",
    "ReadinessVerdict",
    "ReanalyzeFn",
    "ReassemblyOutcome",
    "ReassemblyReason",
    "ReassemblyStatus",
    "ToggleActionProposal",
    "apply_inventory_delta",
    "build_profile",
    "build_toggle_proposals",
    "publish_preflight_check",
    "reassemble",
    "submit_toggle_proposals",
]
