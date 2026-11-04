"""Bridge the 55-scenario causal prediction engine behind reviewed causal-grade receipts.

Maps every :class:`~fdai.delivery.azure.catalog_telemetry_mechanisms.CatalogTelemetryMechanism`
to one reviewed :class:`~fdai.core.conversation.causal_grade_receipts.CausalMechanismSpec` in
``rule-catalog/vocabulary/causal-mechanisms.yaml`` and enforces E8 refutation-read accounting
before any scenario or inference result can claim ``predictive_precedence`` or ``supported``
hypothesis status. Missing, unaccounted, or refuting reads cap the hypothesis at
``association`` and ``candidate`` with ``closure=None``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import Final

import yaml

from fdai.core.conversation.causal_grade_receipts import (
    CausalGradeReceipt,
    CausalMechanismSpec,
    causal_grade_receipt,
    load_causal_mechanism_catalog,
    supports_causal_hypothesis,
)
from fdai.core.rca.hypothesis import CausalHypothesisRecord, CausalHypothesisStatus
from fdai.core.rca.projection import CausalHypothesisProjector
from fdai.delivery.azure.catalog_causal_inference import CatalogCausalInferenceResult
from fdai.delivery.azure.catalog_causal_prediction_engine import (
    CatalogCausalPredictionOrchestrator,
    CausalPredictionScenarioSpec,
    ScenarioExecutionReport,
)
from fdai.delivery.azure.catalog_telemetry_mechanisms import CatalogTelemetryMechanism
from fdai.delivery.repo_assets import repo_asset_root
from fdai.shared.contracts.models import CausalEvidenceGrade
from fdai.shared.providers.ontology_instance import OntologyInstanceStore, OntologyObjectRecord

_MECHANISMS_REL_PATH: Final[Path] = Path("rule-catalog/vocabulary/causal-mechanisms.yaml")

TELEMETRY_TO_REVIEWED_MECHANISM: Final[Mapping[CatalogTelemetryMechanism, str]] = MappingProxyType(
    {
        CatalogTelemetryMechanism.DEPLOYMENT_OPERATION_FAILURE: "deployment_precedes_state_change",
        CatalogTelemetryMechanism.GUEST_SHUTDOWN: "deployment_precedes_state_change",
        CatalogTelemetryMechanism.CONTAINER_RESTARTS: "deployment_precedes_state_change",
        CatalogTelemetryMechanism.BACKUP_JOB_FAILURE: "deployment_precedes_state_change",
        CatalogTelemetryMechanism.POLICY_NON_COMPLIANCE_EVENT: (
            "identity_change_precedes_authorization_failure"
        ),
        CatalogTelemetryMechanism.SECURITY_ALERT_TRIGGERED: (
            "identity_change_precedes_authorization_failure"
        ),
        CatalogTelemetryMechanism.NETWORK_FLOW_DROP: (
            "network_rule_change_precedes_connectivity_loss"
        ),
        CatalogTelemetryMechanism.FIREWALL_DENY: "network_rule_change_precedes_connectivity_loss",
        CatalogTelemetryMechanism.DNS_RESOLUTION_FAILURE: (
            "network_rule_change_precedes_connectivity_loss"
        ),
        CatalogTelemetryMechanism.THROTTLING: "quota_exhaustion_precedes_provisioning_failure",
        CatalogTelemetryMechanism.RESOURCE_SATURATION: (
            "quota_exhaustion_precedes_provisioning_failure"
        ),
        CatalogTelemetryMechanism.MEMORY_OOM_PRESSURE: (
            "quota_exhaustion_precedes_provisioning_failure"
        ),
        CatalogTelemetryMechanism.AUTOSCALE_FLAPPING: "scale_in_precedes_latency_increase",
        CatalogTelemetryMechanism.SLOW_TRACES: "scale_in_precedes_latency_increase",
        CatalogTelemetryMechanism.FAILED_REQUESTS: "setting_drift_precedes_error_rate_increase",
        CatalogTelemetryMechanism.ERROR_TIMELINE: "setting_drift_precedes_error_rate_increase",
        CatalogTelemetryMechanism.TLS_HANDSHAKE_FAILURE: (
            "tls_certificate_expiry_precedes_handshake_failure"
        ),
        CatalogTelemetryMechanism.CERTIFICATE_EXPIRY: (
            "tls_certificate_expiry_precedes_handshake_failure"
        ),
        CatalogTelemetryMechanism.DEPENDENCY_LATENCY: (
            "upstream_dependency_saturation_precedes_latency"
        ),
        CatalogTelemetryMechanism.SQL_DEADLOCK: "upstream_dependency_saturation_precedes_latency",
        CatalogTelemetryMechanism.SQL_BLOCKING_SESSION: (
            "upstream_dependency_saturation_precedes_latency"
        ),
        CatalogTelemetryMechanism.STORAGE_IOPS_SATURATION: (
            "upstream_dependency_saturation_precedes_latency"
        ),
        CatalogTelemetryMechanism.DISK_QUEUE_SATURATION: (
            "upstream_dependency_saturation_precedes_latency"
        ),
        CatalogTelemetryMechanism.REPLICATION_LAG_BREACH: (
            "upstream_dependency_saturation_precedes_latency"
        ),
    }
)


@dataclass(frozen=True, slots=True)
class GradedScenarioExecutionReport:
    """Scenario execution report gated by a deterministic :class:`CausalGradeReceipt`."""

    report: ScenarioExecutionReport
    reviewed_mechanism: CausalMechanismSpec
    grade_receipt: CausalGradeReceipt
    hypothesis_supported: bool
    execution_authority: bool = False

    def __post_init__(self) -> None:
        if type(self.execution_authority) is not bool or self.execution_authority:
            raise ValueError("GradedScenarioExecutionReport MUST have execution_authority=False")


class CatalogCausalGradeBridge:
    """Gate catalog causal inference and 55-scenario runs behind reviewed E8 receipts."""

    def __init__(
        self,
        *,
        repo_root: Path | None = None,
        orchestrator: CatalogCausalPredictionOrchestrator | None = None,
        projector: CausalHypothesisProjector | None = None,
    ) -> None:
        root = repo_root or repo_asset_root()
        raw = yaml.safe_load((root / _MECHANISMS_REL_PATH).read_text(encoding="utf-8"))
        specs = load_causal_mechanism_catalog(raw)
        self._mechanisms: Mapping[str, CausalMechanismSpec] = MappingProxyType(
            {spec.mechanism_id: spec for spec in specs}
        )
        missing = sorted(set(TELEMETRY_TO_REVIEWED_MECHANISM.values()) - set(self._mechanisms))
        if missing:
            raise ValueError(f"Unmapped reviewed causal mechanisms: {missing}")
        self._orchestrator = orchestrator or CatalogCausalPredictionOrchestrator(repo_root=root)
        self._projector = projector

    @property
    def reviewed_mechanisms(self) -> Mapping[str, CausalMechanismSpec]:
        return self._mechanisms

    def resolve_mechanism(
        self, telemetry_mechanism: CatalogTelemetryMechanism | str
    ) -> CausalMechanismSpec:
        enum_val = (
            telemetry_mechanism
            if isinstance(telemetry_mechanism, CatalogTelemetryMechanism)
            else CatalogTelemetryMechanism(str(telemetry_mechanism).strip())
        )
        reviewed_id = TELEMETRY_TO_REVIEWED_MECHANISM[enum_val]
        return self._mechanisms[reviewed_id]

    def grade_and_gate_causal_result(
        self,
        result: CatalogCausalInferenceResult,
        *,
        repeated_sample_count: int,
        reverse_direction_checked: bool,
        confounder_checked: bool,
        complete_windows: bool,
        refutation_reads_run: tuple[str, ...] | None = None,
        missing_refutation_reads: tuple[str, ...] = (),
        refuted_reads: tuple[str, ...] = (),
        refutation_refs: tuple[str, ...] = ("evidence:refutation:peer-window",),
    ) -> tuple[CatalogCausalInferenceResult, CausalGradeReceipt]:
        """Evaluate refutation accounting and downgrade the hypothesis when unproven."""

        spec = self.resolve_mechanism(result.hypothesis_record.mechanism)
        reads_run = (
            spec.refutation_reads if refutation_reads_run is None else tuple(refutation_reads_run)
        )
        receipt = causal_grade_receipt(
            mechanism=spec,
            repeated_sample_count=repeated_sample_count,
            reverse_direction_checked=reverse_direction_checked,
            confounder_checked=confounder_checked,
            complete_windows=complete_windows,
            mechanism_evidence_refs=result.hypothesis_record.supporting_refs,
            refutation_refs=refutation_refs,
            missing_refutation_reads=missing_refutation_reads,
            refutation_reads_run=reads_run,
            refuted_reads=refuted_reads,
        )
        receipt_ref = f"causal-grade-receipt:{receipt.receipt_digest}"
        updated_refs = tuple(sorted({*result.hypothesis_record.supporting_refs, receipt_ref}))
        if supports_causal_hypothesis(receipt):
            gated_hypothesis = CausalHypothesisRecord(
                hypothesis_id=result.hypothesis_record.hypothesis_id,
                incident_id=result.hypothesis_record.incident_id,
                status=result.hypothesis_record.status,
                cause_ref=result.hypothesis_record.cause_ref,
                effect_ref=result.hypothesis_record.effect_ref,
                mechanism=spec.mechanism_id,
                evidence_grade=receipt.grade,
                confidence=result.hypothesis_record.confidence,
                ambiguity=result.hypothesis_record.ambiguity,
                graph_revision=result.hypothesis_record.graph_revision,
                evidence_cutoff=result.hypothesis_record.evidence_cutoff,
                method_version=result.hypothesis_record.method_version,
                created_at=result.hypothesis_record.created_at,
                supporting_refs=updated_refs,
                refuting_refs=result.hypothesis_record.refuting_refs,
                closure=result.hypothesis_record.closure,
            )
        else:
            refuting = tuple(
                sorted(
                    {
                        *result.hypothesis_record.refuting_refs,
                        *(f"refuted:{r}" for r in receipt.refuted_reads),
                        *(f"missing-refutation:{r}" for r in receipt.missing_refutation_reads),
                        *(
                            f"unaccounted-refutation:{r}"
                            for r in receipt.unaccounted_refutation_reads
                        ),
                    }
                )
            )
            gated_hypothesis = CausalHypothesisRecord(
                hypothesis_id=result.hypothesis_record.hypothesis_id,
                incident_id=result.hypothesis_record.incident_id,
                status=CausalHypothesisStatus.CANDIDATE,
                cause_ref=result.hypothesis_record.cause_ref,
                effect_ref=result.hypothesis_record.effect_ref,
                mechanism=spec.mechanism_id,
                evidence_grade=CausalEvidenceGrade.ASSOCIATION,
                confidence=result.hypothesis_record.confidence,
                ambiguity=result.hypothesis_record.ambiguity,
                graph_revision=result.hypothesis_record.graph_revision,
                evidence_cutoff=result.hypothesis_record.evidence_cutoff,
                method_version=result.hypothesis_record.method_version,
                created_at=result.hypothesis_record.created_at,
                supporting_refs=updated_refs,
                refuting_refs=refuting,
                closure=None,
            )
        gated_result = replace(result, hypothesis_record=gated_hypothesis)
        return gated_result, receipt

    def execute_and_grade_scenario(
        self,
        spec: CausalPredictionScenarioSpec,
        *,
        base_time: datetime | None = None,
        repeated_sample_count: int = 3,
        reverse_direction_checked: bool = True,
        confounder_checked: bool = True,
        complete_windows: bool = True,
        refutation_reads_run: tuple[str, ...] | None = None,
        missing_refutation_reads: tuple[str, ...] = (),
        refuted_reads: tuple[str, ...] = (),
    ) -> GradedScenarioExecutionReport:
        """Execute one scenario and enforce E8 causal-grade accounting on its output."""

        raw_report = self._orchestrator.execute_scenario(spec, base_time=base_time)
        reviewed_spec = self.resolve_mechanism(spec.causal_mechanisms[0])
        gated_causal, receipt = self.grade_and_gate_causal_result(
            raw_report.causal_result,
            repeated_sample_count=repeated_sample_count,
            reverse_direction_checked=reverse_direction_checked,
            confounder_checked=confounder_checked,
            complete_windows=complete_windows,
            refutation_reads_run=refutation_reads_run,
            missing_refutation_reads=missing_refutation_reads,
            refuted_reads=refuted_reads,
        )
        gated_report = replace(raw_report, causal_result=gated_causal)
        return GradedScenarioExecutionReport(
            report=gated_report,
            reviewed_mechanism=reviewed_spec,
            grade_receipt=receipt,
            hypothesis_supported=supports_causal_hypothesis(receipt),
        )

    async def project_graded_scenario(
        self,
        graded: GradedScenarioExecutionReport,
        *,
        finding_id: str,
        endpoint_objects: tuple[OntologyObjectRecord, ...] = (),
    ) -> bool:
        """Project the graded hypothesis into the runtime ontology store when bound."""

        if self._projector is None:
            return False
        await self._projector.project(
            graded.report.causal_result.hypothesis_record,
            finding_id=finding_id,
            endpoint_objects=endpoint_objects,
        )
        return True


def build_catalog_causal_grade_bridge(
    *,
    repo_root: Path | None = None,
    ontology_instance_store: OntologyInstanceStore | None = None,
) -> CatalogCausalGradeBridge:
    """Compose the runtime causal-grade bridge with optional Forseti projection."""

    projector = (
        CausalHypothesisProjector(store=ontology_instance_store)
        if ontology_instance_store is not None
        else None
    )
    return CatalogCausalGradeBridge(repo_root=repo_root, projector=projector)


__all__ = [
    "TELEMETRY_TO_REVIEWED_MECHANISM",
    "CatalogCausalGradeBridge",
    "GradedScenarioExecutionReport",
    "build_catalog_causal_grade_bridge",
]
