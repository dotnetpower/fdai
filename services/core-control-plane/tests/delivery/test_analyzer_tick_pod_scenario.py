"""Bounded Pod restart and replacement scenario through the analyzer path."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from fdai.core.investigation import AnalyzerFinding, InvestigationCoordinator
from fdai.core.ontology_platform.kubernetes_pod_replacement_evidence import (
    DeploymentReplicaObservation,
    KubernetesPodReplacementEvidenceResult,
    KubernetesPodReplacementStatus,
    PodLifecycleObservation,
    PodReplacementDeploymentObservation,
    PodTerminationObservation,
    evaluate_kubernetes_pod_replacement,
)
from fdai.delivery.analyzer_tick import (
    AnalyzerPublicationClaim,
    AnalyzerPublicationClaimStatus,
    AnalyzerTarget,
    AnalyzerTickRunner,
)
from fdai.shared.contracts.models import Severity
from fdai.shared.providers.event_bus import PublishReceipt
from fdai.shared.providers.state_evidence import (
    LinkObservationMetadata,
    StateFactAuthority,
    StateFactLane,
    StateFactMetadata,
)

_CUTOFF = datetime(2026, 8, 27, 8, 0, tzinfo=UTC)
_WINDOW_START = _CUTOFF - timedelta(minutes=30)


def _metadata(at: datetime) -> StateFactMetadata:
    return StateFactMetadata(
        lane=StateFactLane.OBSERVED,
        authority=StateFactAuthority.PROVIDER,
        source_identity="kubernetes-api-inventory",
        source_revision="resource-version-10",
        effective_at=at,
        recorded_at=at,
        evidence_cutoff=at,
        freshness_ceiling_seconds=300,
        completeness=1.0,
        synthetic=False,
        evidence_refs=(f"kubernetes:{at.isoformat()}",),
    )


def _link(at: datetime, suffix: str) -> LinkObservationMetadata:
    return LinkObservationMetadata(
        state_fact=_metadata(at),
        verification_method="independent-source",
        verified=True,
        verifier_identity="kubernetes-link-verifier",
        verifier_revision="verifier-v1",
        verification_receipt_ref=f"link-verification:{suffix}",
    )


def _old_pod() -> PodLifecycleObservation:
    observed_at = _CUTOFF - timedelta(minutes=10)
    return PodLifecycleObservation(
        pod_id="pod/old",
        pod_uid="pod-uid-old",
        cluster_id="cluster-a",
        namespace="default",
        owner_uid="replicaset-uid-a",
        root_controller_uid="deployment-uid-a",
        root_controller_kind="Deployment",
        owner_link=_link(observed_at, "old-owner"),
        root_controller_link=_link(observed_at, "old-root"),
        created_at=_WINDOW_START - timedelta(hours=1),
        phase="Failed",
        ready=False,
        container_count=1,
        ready_container_count=0,
        restart_count=0,
        waiting_reasons=(),
        workload_revision="revision-a",
        metadata=_metadata(observed_at),
        evidence_refs=("pod-old",),
    )


def _new_pod() -> PodLifecycleObservation:
    return PodLifecycleObservation(
        pod_id="pod/new",
        pod_uid="pod-uid-new",
        cluster_id="cluster-a",
        namespace="default",
        owner_uid="replicaset-uid-a",
        root_controller_uid="deployment-uid-a",
        root_controller_kind="Deployment",
        owner_link=_link(_CUTOFF, "new-owner"),
        root_controller_link=_link(_CUTOFF, "new-root"),
        created_at=_CUTOFF - timedelta(minutes=4),
        phase="Running",
        ready=True,
        container_count=1,
        ready_container_count=1,
        restart_count=0,
        waiting_reasons=(),
        workload_revision="revision-a",
        metadata=_metadata(_CUTOFF),
        evidence_refs=("pod-new",),
    )


def _termination() -> PodTerminationObservation:
    return PodTerminationObservation(
        pod_uid="pod-uid-old",
        cluster_id="cluster-a",
        namespace="default",
        event_type="Failed",
        reason="OOMKilled",
        exit_code=137,
        event_time=_CUTOFF - timedelta(minutes=5),
        recorded_at=_CUTOFF - timedelta(minutes=5),
        source_identity="kubernetes-event-watch",
        source_revision="resource-version-20",
        evidence_refs=("termination-old",),
    )


def _deployment() -> PodReplacementDeploymentObservation:
    return PodReplacementDeploymentObservation(
        deployment_id="deployment/orders",
        deployment_uid="deployment-uid-a",
        cluster_id="cluster-a",
        namespace="default",
        desired_replicas_before=1,
        desired_replicas_after=1,
        desired_replica_history=(
            DeploymentReplicaObservation(observed_at=_WINDOW_START, desired_replicas=1),
            DeploymentReplicaObservation(observed_at=_CUTOFF, desired_replicas=1),
        ),
        replica_history_complete=True,
        ready_replicas=1,
        available_replicas=1,
        unavailable_replicas=0,
        metadata=_metadata(_CUTOFF),
        evidence_refs=("deployment-current",),
    )


def _evaluate(
    old_pod: PodLifecycleObservation,
    candidate: PodLifecycleObservation,
) -> KubernetesPodReplacementEvidenceResult:
    return evaluate_kubernetes_pod_replacement(
        old_pod=old_pod,
        candidates=(candidate,),
        termination=_termination(),
        deployment=_deployment(),
        correlation_window_start=_WINDOW_START,
        cutoff=_CUTOFF,
    )


class _PodScenarioAnalyzer:
    resource_kind = "kubernetes_pod"

    def __init__(self, findings: dict[str, AnalyzerFinding]) -> None:
        self._findings = findings

    async def analyze(
        self,
        *,
        resource_ref: str,
        window_seconds: float,
    ) -> tuple[AnalyzerFinding, ...]:
        assert window_seconds == 300
        return (self._findings[resource_ref],)


class _ScenarioBus:
    def __init__(self) -> None:
        self.published: list[dict[str, object]] = []

    async def publish(
        self,
        topic: str,
        key: str,
        payload: dict[str, object],
    ) -> PublishReceipt:
        self.published.append(payload)
        return PublishReceipt(topic=topic, partition=0, offset=len(self.published) - 1)


class _ScenarioPublicationLedger:
    def __init__(self) -> None:
        self.receipts: dict[str, PublishReceipt] = {}

    async def claim(self, idempotency_key: str) -> AnalyzerPublicationClaim:
        receipt = self.receipts.get(idempotency_key)
        if receipt is not None:
            return AnalyzerPublicationClaim(
                status=AnalyzerPublicationClaimStatus.COMPLETED,
                receipt=receipt,
            )
        return AnalyzerPublicationClaim(
            status=AnalyzerPublicationClaimStatus.NEW,
            token=idempotency_key,
            claimed_at=_CUTOFF,
        )

    async def complete(
        self,
        idempotency_key: str,
        claim: AnalyzerPublicationClaim,
        receipt: PublishReceipt,
    ) -> None:
        assert claim.status is AnalyzerPublicationClaimStatus.NEW
        self.receipts[idempotency_key] = receipt

    async def release(
        self,
        idempotency_key: str,
        claim: AnalyzerPublicationClaim,
    ) -> None:
        raise AssertionError(f"unexpected release for {idempotency_key}:{claim.token}")


def _finding(
    resource_ref: str,
    result: KubernetesPodReplacementEvidenceResult,
    *,
    latency_seconds: int,
) -> AnalyzerFinding:
    return AnalyzerFinding(
        resource_ref=resource_ref,
        resource_kind="kubernetes_pod",
        signal=result.status.value,
        observation=f"Bounded pod lifecycle assessment: {result.status.value}.",
        severity=Severity.HIGH,
        occurred_at=_CUTOFF - timedelta(seconds=latency_seconds),
        evidence_refs=tuple(
            sorted({*result.historical_evidence_refs, *result.current_evidence_refs})
        ),
        metadata={
            "evidence_complete": str(result.complete).lower(),
            "recovery_closed": str(result.recovery_verified).lower(),
        },
    )


async def test_analyzer_path_joins_restart_replacement_and_recovery_receipts() -> None:
    old_pod = _old_pod()
    same_uid = _evaluate(
        old_pod,
        replace(
            _new_pod(),
            pod_id=old_pod.pod_id,
            pod_uid=old_pod.pod_uid,
            created_at=old_pod.created_at,
            restart_count=1,
        ),
    )
    distinct_uid = _evaluate(old_pod, _new_pod())
    assert same_uid.status is KubernetesPodReplacementStatus.CONTAINER_RESTART
    assert distinct_uid.status is KubernetesPodReplacementStatus.POD_REPLACEMENT
    assert same_uid.complete and same_uid.recovery_verified
    assert distinct_uid.complete and distinct_uid.recovery_verified

    same_ref = "scenario/same-uid"
    replacement_ref = "scenario/distinct-uid"
    bus = _ScenarioBus()
    runner = AnalyzerTickRunner(
        coordinator=InvestigationCoordinator(
            analyzers=(
                _PodScenarioAnalyzer(
                    {
                        same_ref: _finding(same_ref, same_uid, latency_seconds=12),
                        replacement_ref: _finding(
                            replacement_ref,
                            distinct_uid,
                            latency_seconds=7,
                        ),
                    }
                ),
            )
        ),
        event_bus=bus,  # type: ignore[arg-type]
        publication_ledger=_ScenarioPublicationLedger(),
        window_seconds=300,
        clock=lambda: _CUTOFF,
    )
    targets = (
        AnalyzerTarget(resource_ref=same_ref, resource_kind="kubernetes_pod"),
        AnalyzerTarget(resource_ref=replacement_ref, resource_kind="kubernetes_pod"),
    )

    first = await runner.run_once(targets)
    duplicate = await runner.run_once(targets)

    assert first.published == 2
    assert duplicate.published == 0
    assert duplicate.duplicates_suppressed == 2
    assert len(bus.published) == 2
    replacement_receipt = next(item for item in first.receipts if item.signal == "pod_replacement")
    assert replacement_receipt.to_dict() == {
        "idempotency_key": replacement_receipt.idempotency_key,
        "signal": "pod_replacement",
        "detection_latency_seconds": 7.0,
        "evidence_complete": True,
        "publication": "published",
        "recovery_closed": True,
        "evidence_refs": [
            "deployment-current",
            "pod-new",
            "pod-old",
            "termination-old",
        ],
    }
