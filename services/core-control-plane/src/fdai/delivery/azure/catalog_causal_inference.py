"""100%-coverage catalog-driven causal inference and multi-hop root-cause engine (Rounds D001-D010).

Connects all 50 public Azure Resource Graph (ARG) tables, 1,908 ARG resource types,
420 ARG relationship mappings, 12 Azure Monitor Log Analytics categories (867 tables),
156 canonical ResourceTypes (312 platform metrics, 156 KQL recipes), 24 causal
telemetry mechanisms, and 50 diagnostic probes to FDAI's deterministic T1/T2 causal
inference primitives (:class:`~fdai.core.rca.causal_chain.CausalChainAnalyzer`,
:class:`~fdai.core.rca.temporal_causality.TemporalCausalityAnalyzer`, and
:class:`~fdai.core.rca.hypothesis.CausalEvidenceAssessment`).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import MappingProxyType
from typing import Final

from fdai.core.detection.series import MetricSample
from fdai.core.rca.causal_chain import (
    CausalChain,
    CausalChainAnalyzer,
    CausalChainConfig,
    CorrelatedEvent,
)
from fdai.core.rca.contract import CauseDomain, Citation, CitationKind
from fdai.core.rca.hypothesis import (
    CausalClosure,
    CausalEvidenceAssessment,
    CausalHypothesisRecord,
    CausalHypothesisStatus,
)
from fdai.core.rca.temporal_causality import (
    TemporalCausalClaim,
    TemporalCausalityAnalyzer,
    TemporalCausalityConfig,
    TemporalSeries,
)
from fdai.delivery.azure.arg_catalog_relationships import (
    ArgRelationshipMappingCatalog,
    load_arg_relationship_mapping_catalog,
)
from fdai.delivery.azure.arg_public_catalog import ArgPublicCatalog, load_arg_public_catalog
from fdai.delivery.azure.catalog_telemetry_mechanisms import (
    CatalogTelemetryMechanism,
    CausalMechanismAndProbeCatalog,
    load_causal_mechanism_and_probe_catalog,
)
from fdai.delivery.azure.monitor_log_catalog import (
    MonitorLogPublicCatalog,
    load_monitor_log_catalog,
)
from fdai.delivery.azure.resource_type_recipes import (
    ResourceTypeRecipeCatalog,
    load_resource_type_recipe_catalog,
)
from fdai.shared.contracts.models import CausalEvidenceGrade

ARG_CHANGE_BEARING_TABLES: Final[frozenset[str]] = frozenset(
    {
        "resourcechanges",
        "resourcecontainerchanges",
        "extensibilityresourcechanges",
        "healthresourcechanges",
        "maintenanceresourcechanges",
        "networkresourcechanges",
        "quotaresourcechanges",
        "deploymentresources",
        "patchinstallationresources",
        "chaosresources",
        "policyresources",
        "aksresources",
    }
)

ARG_CAUSE_DOMAIN_BY_TABLE: Final[Mapping[str, CauseDomain]] = MappingProxyType(
    {
        "advisorresources": CauseDomain.INFRASTRUCTURE,
        "aksresources": CauseDomain.INFRASTRUCTURE,
        "alertsmanagementresources": CauseDomain.MIXED,
        "appserviceresources": CauseDomain.APPLICATION,
        "authorizationresources": CauseDomain.SHARED_DEPENDENCY,
        "awsresources": CauseDomain.EXTERNAL_PROVIDER,
        "azurebusinesscontinuityresources": CauseDomain.INFRASTRUCTURE,
        "azuredevopsplatformresources": CauseDomain.APPLICATION,
        "batchresources": CauseDomain.INFRASTRUCTURE,
        "capabilityresources": CauseDomain.EXTERNAL_PROVIDER,
        "chaosresources": CauseDomain.INFRASTRUCTURE,
        "communitygalleryresources": CauseDomain.INFRASTRUCTURE,
        "computeresources": CauseDomain.INFRASTRUCTURE,
        "deploymentresources": CauseDomain.APPLICATION,
        "desktopvirtualizationresources": CauseDomain.INFRASTRUCTURE,
        "dnsresources": CauseDomain.SHARED_DEPENDENCY,
        "edgeorderresources": CauseDomain.EXTERNAL_PROVIDER,
        "elasticsanresources": CauseDomain.INFRASTRUCTURE,
        "extendedlocationresources": CauseDomain.INFRASTRUCTURE,
        "extensibilityresourcechanges": CauseDomain.APPLICATION,
        "featureresources": CauseDomain.EXTERNAL_PROVIDER,
        "guestconfigurationresources": CauseDomain.INFRASTRUCTURE,
        "healthresourcechanges": CauseDomain.EXTERNAL_PROVIDER,
        "healthresources": CauseDomain.EXTERNAL_PROVIDER,
        "impactreportresources": CauseDomain.INFRASTRUCTURE,
        "insightresources": CauseDomain.APPLICATION,
        "iotsecurityresources": CauseDomain.INFRASTRUCTURE,
        "kubernetesconfigurationresources": CauseDomain.APPLICATION,
        "kustoresources": CauseDomain.SHARED_DEPENDENCY,
        "maintenanceresourcechanges": CauseDomain.EXTERNAL_PROVIDER,
        "maintenanceresources": CauseDomain.EXTERNAL_PROVIDER,
        "managedserviceresources": CauseDomain.SHARED_DEPENDENCY,
        "mirgateresources": CauseDomain.INFRASTRUCTURE,
        "networkresourcechanges": CauseDomain.SHARED_DEPENDENCY,
        "networkresources": CauseDomain.SHARED_DEPENDENCY,
        "orbitalresources": CauseDomain.EXTERNAL_PROVIDER,
        "patchassessmentresources": CauseDomain.INFRASTRUCTURE,
        "patchinstallationresources": CauseDomain.INFRASTRUCTURE,
        "policyresources": CauseDomain.SHARED_DEPENDENCY,
        "quotaresourcechanges": CauseDomain.INFRASTRUCTURE,
        "recoveryservicesresources": CauseDomain.INFRASTRUCTURE,
        "resourcechanges": CauseDomain.INFRASTRUCTURE,
        "resourcecontainerchanges": CauseDomain.SHARED_DEPENDENCY,
        "resourcecontainers": CauseDomain.SHARED_DEPENDENCY,
        "resources": CauseDomain.INFRASTRUCTURE,
        "securityresources": CauseDomain.SHARED_DEPENDENCY,
        "servicefabricresources": CauseDomain.APPLICATION,
        "servicehealthresources": CauseDomain.EXTERNAL_PROVIDER,
        "sportresources": CauseDomain.EXTERNAL_PROVIDER,
        "tagresources": CauseDomain.SHARED_DEPENDENCY,
    }
)

MONITOR_CAUSE_DOMAIN_BY_CATEGORY: Final[Mapping[str, CauseDomain]] = MappingProxyType(
    {
        "Applications": CauseDomain.APPLICATION,
        "Audit": CauseDomain.SHARED_DEPENDENCY,
        "Azure Monitor": CauseDomain.MIXED,
        "Azure Resources": CauseDomain.INFRASTRUCTURE,
        "Azure Virtual Desktop": CauseDomain.INFRASTRUCTURE,
        "Containers": CauseDomain.INFRASTRUCTURE,
        "Desktop Analytics": CauseDomain.APPLICATION,
        "IT & Management Tools": CauseDomain.INFRASTRUCTURE,
        "Network": CauseDomain.SHARED_DEPENDENCY,
        "Security": CauseDomain.SHARED_DEPENDENCY,
        "Virtual Machines": CauseDomain.INFRASTRUCTURE,
        "Workloads": CauseDomain.SHARED_DEPENDENCY,
    }
)


@dataclass(frozen=True, slots=True)
class CatalogCausalObservation:
    """One observed event from an ARG table, Monitor Log table, or diagnostic probe."""

    event_id: str
    occurred_at: datetime
    resource_ref: str
    resource_type: str
    arg_table: str
    monitor_table: str
    mechanism: CatalogTelemetryMechanism
    probe_id: str
    is_change: bool
    change_kind: str | None = None

    def __post_init__(self) -> None:
        if (
            not self.event_id.strip()
            or not self.resource_ref.strip()
            or not self.resource_type.strip()
            or not self.arg_table.strip()
            or not self.monitor_table.strip()
            or not self.probe_id.strip()
        ):
            raise ValueError("CatalogCausalObservation identifiers MUST be non-empty")
        if self.occurred_at.tzinfo is None:
            raise ValueError("CatalogCausalObservation.occurred_at MUST be timezone-aware")
        if type(self.is_change) is not bool:
            raise ValueError("CatalogCausalObservation.is_change MUST be boolean")

    def to_correlated_event(self) -> CorrelatedEvent:
        domain = ARG_CAUSE_DOMAIN_BY_TABLE.get(
            self.arg_table.strip().lower(), CauseDomain.INFRASTRUCTURE
        )
        return CorrelatedEvent(
            event_id=self.event_id,
            at=self.occurred_at,
            resource_ref=self.resource_ref,
            is_change=self.is_change,
            change_kind=self.change_kind,
            cause_domain=domain,
        )


@dataclass(frozen=True, slots=True)
class CatalogCausalInferenceResult:
    """Complete deterministic causal inference output over catalog-grounded observations."""

    incident_id: str
    causal_chain: CausalChain | None
    temporal_claim: TemporalCausalClaim | None
    assessment: CausalEvidenceAssessment
    hypothesis_record: CausalHypothesisRecord
    citations: tuple[Citation, ...]
    active_relationship_mappings: tuple[str, ...]
    execution_authority: bool = False

    def __post_init__(self) -> None:
        if type(self.execution_authority) is not bool or self.execution_authority:
            raise ValueError("CatalogCausalInferenceResult MUST have execution_authority=False")


class CatalogCausalInferenceEngine:
    """Run multi-hop topological and temporal causal inference over all catalog assets."""

    def __init__(self, *, repo_root: Path | None = None) -> None:
        self._arg: ArgPublicCatalog = load_arg_public_catalog(repo_root)
        self._mon: MonitorLogPublicCatalog = load_monitor_log_catalog(repo_root)
        self._recipes: ResourceTypeRecipeCatalog = load_resource_type_recipe_catalog(repo_root)
        self._mechs: CausalMechanismAndProbeCatalog = load_causal_mechanism_and_probe_catalog(
            repo_root
        )
        self._rels: ArgRelationshipMappingCatalog = load_arg_relationship_mapping_catalog(repo_root)

    def infer_causality(
        self,
        *,
        incident_id: str,
        failure: CatalogCausalObservation,
        antecedents: Sequence[CatalogCausalObservation],
        depends_on: Mapping[str, frozenset[str]],
        relationship_mapping_ids: Sequence[str],
        cause_series: Sequence[MetricSample] = (),
        effect_series: Sequence[MetricSample] = (),
        cause_metric_id: str = "",
        effect_metric_id: str = "",
        cutoff: datetime | None = None,
    ) -> CatalogCausalInferenceResult:
        """Reconstruct the multi-hop causal chain, lagged correlation, and hypothesis."""
        if not incident_id.strip():
            raise ValueError("incident_id MUST be non-empty")
        for obs in (failure, *antecedents):
            self._arg.get_table(obs.arg_table)
            self._mon.get_table(obs.monitor_table)
            self._recipes.get_profile(obs.resource_type)
            self._mechs.get_mechanism(obs.mechanism)
            self._mechs.get_probe(obs.probe_id)
        for mid in relationship_mapping_ids:
            if mid not in self._rels.mappings:
                raise KeyError(f"Unknown ARG relationship mapping_id: {mid!r}")

        chain_analyzer = CausalChainAnalyzer(
            CausalChainConfig(
                window=timedelta(minutes=60),
                depends_on=depends_on,
                max_hops=4,
                transitive_depth=3,
            )
        )
        correlated = [item.to_correlated_event() for item in antecedents]
        chain = chain_analyzer.reconstruct(
            failure_event_id=failure.event_id,
            failure_at=failure.occurred_at,
            failure_resource_ref=failure.resource_ref,
            correlated_events=correlated,
        )

        effective_cutoff = (cutoff or failure.occurred_at).astimezone(UTC)
        temporal_claim: TemporalCausalClaim | None = None
        if (
            len(cause_series) >= 6
            and len(effect_series) >= 6
            and cause_metric_id
            and effect_metric_id
        ):
            tc_analyzer = TemporalCausalityAnalyzer(
                TemporalCausalityConfig(
                    lag_seconds=(60, 120),
                    min_samples=4,
                    min_abs_correlation=0.5,
                    difference_period=1,
                )
            )
            temporal_claim = tc_analyzer.analyze(
                cause=TemporalSeries(metric=cause_metric_id, samples=tuple(cause_series)),
                effect=TemporalSeries(metric=effect_metric_id, samples=tuple(effect_series)),
                feature_cutoff=effective_cutoff,
                evidence_refs=(f"metric:{cause_metric_id}", f"metric:{effect_metric_id}"),
            )

        has_chain = chain is not None and len(chain.hops) > 0
        has_temporal = (
            temporal_claim is not None
            and temporal_claim.evidence_grade is CausalEvidenceGrade.PREDICTIVE_PRECEDENCE
        )
        grade = (
            CausalEvidenceGrade.QUASI_EXPERIMENTAL
            if (has_chain and has_temporal)
            else CausalEvidenceGrade.PREDICTIVE_PRECEDENCE
            if (has_chain or has_temporal)
            else CausalEvidenceGrade.ASSOCIATION
        )
        supporting_refs = tuple(
            sorted(
                {
                    f"arg:{failure.arg_table}",
                    f"monitor:{failure.monitor_table}",
                    f"probe:{failure.probe_id}",
                    *(f"event:{obs.event_id}" for obs in antecedents),
                    *(f"rel:{mid}" for mid in relationship_mapping_ids),
                }
            )
        )
        assessment = CausalEvidenceAssessment(
            temporal_precedence=0.92 if has_chain else 0.65,
            topological_reachability=0.95 if relationship_mapping_ids else 0.70,
            mechanism_fit=0.90,
            intervention_consistency=0.88 if has_temporal else 0.75,
            evidence_completeness=1.0,
            ambiguity=chain.ambiguity if chain is not None else 1,
            supporting_refs=supporting_refs,
        )
        root_ref = (
            chain.resource_path[0]
            if (chain is not None and chain.resource_path)
            else failure.resource_ref
        )
        hypothesis = CausalHypothesisRecord(
            hypothesis_id=f"hyp:{incident_id}",
            incident_id=incident_id,
            status=(
                CausalHypothesisStatus.SUPPORTED if has_chain else CausalHypothesisStatus.CANDIDATE
            ),
            cause_ref=root_ref,
            effect_ref=failure.resource_ref,
            mechanism=failure.mechanism.value,
            evidence_grade=grade,
            confidence=assessment.confidence,
            ambiguity=assessment.ambiguity,
            graph_revision="sha256:" + "0" * 64,
            evidence_cutoff=effective_cutoff,
            method_version="catalog-causal-inference.v1",
            created_at=effective_cutoff,
            supporting_refs=supporting_refs,
            closure=CausalClosure.CONFIRMED if (has_chain and has_temporal) else None,
        )
        citations = (
            Citation(
                kind=CitationKind.CHANGE,
                ref=chain.root_event_id if chain is not None else failure.event_id,
                facts=("tier:t1", f"mechanism:{failure.mechanism.value}"),
            ),
            Citation(
                kind=CitationKind.TELEMETRY,
                ref=failure.monitor_table,
                facts=(f"probe:{failure.probe_id}",),
            ),
        )
        return CatalogCausalInferenceResult(
            incident_id=incident_id,
            causal_chain=chain,
            temporal_claim=temporal_claim,
            assessment=assessment,
            hypothesis_record=hypothesis,
            citations=citations,
            active_relationship_mappings=tuple(relationship_mapping_ids),
        )


__all__ = [
    "ARG_CAUSE_DOMAIN_BY_TABLE",
    "ARG_CHANGE_BEARING_TABLES",
    "MONITOR_CAUSE_DOMAIN_BY_CATEGORY",
    "CatalogCausalInferenceEngine",
    "CatalogCausalInferenceResult",
    "CatalogCausalObservation",
]
