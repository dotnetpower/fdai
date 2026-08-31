"""On-demand cross-resource investigation (SRE-agent-parity).

Turns a set of resources into one grounded, read-only investigation:
per-resource analyzers emit findings, the coordinator correlates them into
a timeline + root-cause hypothesis, ranks P1..P3 recommendations, and
measures latency against a budget. Nothing here executes a change - the
risk gate stays the sole authority over "execute".

Maps the Azure SRE Agent demo (session notes slides 10-14):

- slide 10 - on-demand investigation across resources -> RCA + recommendations
  (:class:`InvestigationCoordinator`).
- slides 11-12 - per-resource analyzers (AppGW, MySQL, Azure OpenAI, AKS,
  API Management) (:mod:`fdai.core.investigation.analyzers`).
- slide 13 - the report: timeline + correlation + prioritized recommendations
  (:class:`InvestigationReport`).
- slide 14 - a latency budget + measured KPI (:meth:`InvestigationReport.kpi`).
"""

from __future__ import annotations

from fdai.core.investigation.analyzer import (
    Aggregation,
    Comparison,
    ResourceAnalyzer,
    Threshold,
    ThresholdAnalyzer,
    reduce_values,
)
from fdai.core.investigation.analyzers import (
    KIND_AKS,
    KIND_API_MANAGEMENT,
    KIND_APP_GATEWAY,
    KIND_AZURE_OPENAI,
    KIND_MYSQL,
    aks_analyzer,
    api_management_analyzer,
    app_gateway_analyzer,
    azure_openai_analyzer,
    default_analyzers,
    mysql_analyzer,
)
from fdai.core.investigation.contract import (
    AnalyzerFinding,
    FindingAssessment,
    InvestigationOutcome,
    InvestigationReport,
    Priority,
    Recommendation,
    TimelineEntry,
    priority_for,
)
from fdai.core.investigation.coordinator import (
    InvestigationCoordinator,
    InvestigationRequest,
    correlate,
)
from fdai.core.investigation.kubernetes_pod import (
    KIND_KUBERNETES_POD,
    POD_LIFECYCLE_ASSESSOR,
    KubernetesPodLifecycleAnalyzer,
    PodLifecycleEvidence,
    PodLifecycleEvidenceSource,
    StaticPodLifecycleEvidenceSource,
    pod_lifecycle_assessment,
)
from fdai.core.investigation.recommendations import (
    build_recommendations,
    build_timeline,
    summarize_priorities,
)
from fdai.shared.providers.metric import (
    MetricPoint,
    MetricProvider,
    MetricQuery,
    StaticMetricProvider,
)

__all__ = [
    "KIND_AKS",
    "KIND_API_MANAGEMENT",
    "KIND_APP_GATEWAY",
    "KIND_AZURE_OPENAI",
    "KIND_KUBERNETES_POD",
    "KIND_MYSQL",
    "POD_LIFECYCLE_ASSESSOR",
    "Aggregation",
    "AnalyzerFinding",
    "Comparison",
    "FindingAssessment",
    "InvestigationCoordinator",
    "InvestigationOutcome",
    "InvestigationReport",
    "InvestigationRequest",
    "KubernetesPodLifecycleAnalyzer",
    "MetricPoint",
    "MetricProvider",
    "MetricQuery",
    "PodLifecycleEvidence",
    "PodLifecycleEvidenceSource",
    "Priority",
    "Recommendation",
    "ResourceAnalyzer",
    "StaticMetricProvider",
    "StaticPodLifecycleEvidenceSource",
    "Threshold",
    "ThresholdAnalyzer",
    "TimelineEntry",
    "aks_analyzer",
    "api_management_analyzer",
    "app_gateway_analyzer",
    "azure_openai_analyzer",
    "build_recommendations",
    "build_timeline",
    "correlate",
    "default_analyzers",
    "mysql_analyzer",
    "pod_lifecycle_assessment",
    "priority_for",
    "reduce_values",
    "summarize_priorities",
]
