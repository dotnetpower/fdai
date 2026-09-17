"""Typed public facade for the independent FDAI Cost Governance package."""

from fdai_cost_governance.__about__ import __version__
from fdai_cost_governance.advisory import RollingCostAdvisoryProvider
from fdai_cost_governance.azure_focus import (
    AzureFocusObservationAdapter,
    CostHttpResponse,
    CostHttpTransport,
    CostReadCredential,
)
from fdai_cost_governance.coordination import (
    CostCoordinationError,
    CostObservationModeLatch,
    DeterministicCostCoordinator,
)
from fdai_cost_governance.guard import (
    FinOpsActionKind,
    FinOpsCandidate,
    FinOpsEnvironment,
    FinOpsGuard,
    FinOpsGuardConfig,
    FinOpsGuardDecision,
    FinOpsGuardOutcome,
    ResourceContext,
)
from fdai_cost_governance.parity import (
    ApprovedParityDifference,
    CostGovernanceParityHarness,
    CostParityError,
    CostParityOwner,
    CostParityRecord,
    CostParityReport,
    value_digest,
)
from fdai_cost_governance.resource_loader import (
    CostGovernanceResourceError,
    PackageResource,
    build_cost_governance_bundle,
    load_package_resources,
    load_resource_bytes,
    load_resource_manifest,
    materialize_cost_governance_catalog,
    resource_manifest_sha256,
)
from fdai_cost_governance.review_targets import (
    CostReadinessTarget,
    load_cost_readiness_targets,
)
from fdai_cost_governance.scheduled_analytics import (
    AnalyticsSourceError,
    AzureAnalyticsBatch,
    AzureScheduledAnalyticsSource,
    ScheduledAnalyticsResult,
    run_scheduled_analytics,
)
from fdai_cost_governance.service import (
    CostAnalyzerService,
    CostCollectorService,
    CostJobConfig,
    CostJobResult,
)
from fdai_cost_governance.validation import (
    CostObservationCampaignReducer,
    CostPromotionReadinessGate,
    CostReadinessBlock,
    CostReadinessDecision,
    CostReadinessResult,
    CostReadinessTargetKind,
    CostReadinessThresholds,
    build_lifecycle_receipt,
)

__all__ = [
    "ApprovedParityDifference",
    "AnalyticsSourceError",
    "AzureAnalyticsBatch",
    "AzureScheduledAnalyticsSource",
    "CostGovernanceParityHarness",
    "CostGovernanceResourceError",
    "CostCoordinationError",
    "CostObservationModeLatch",
    "CostObservationCampaignReducer",
    "CostPromotionReadinessGate",
    "CostReadinessBlock",
    "CostReadinessDecision",
    "CostReadinessResult",
    "CostReadinessTarget",
    "CostReadinessTargetKind",
    "CostReadinessThresholds",
    "CostAnalyzerService",
    "CostCollectorService",
    "CostHttpResponse",
    "CostHttpTransport",
    "CostJobConfig",
    "CostJobResult",
    "CostParityError",
    "CostParityOwner",
    "CostParityRecord",
    "CostParityReport",
    "CostReadCredential",
    "DeterministicCostCoordinator",
    "AzureFocusObservationAdapter",
    "FinOpsActionKind",
    "FinOpsCandidate",
    "FinOpsEnvironment",
    "FinOpsGuard",
    "FinOpsGuardConfig",
    "FinOpsGuardDecision",
    "FinOpsGuardOutcome",
    "PackageResource",
    "ResourceContext",
    "RollingCostAdvisoryProvider",
    "ScheduledAnalyticsResult",
    "__version__",
    "build_lifecycle_receipt",
    "build_cost_governance_bundle",
    "load_package_resources",
    "load_cost_readiness_targets",
    "load_resource_bytes",
    "load_resource_manifest",
    "materialize_cost_governance_catalog",
    "resource_manifest_sha256",
    "run_scheduled_analytics",
    "value_digest",
]
