"""Forseti-owned deterministic AKS diagnostic evidence tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.ontology_platform.kubernetes_diagnostic_assessment import (
    AksDiagnosticContext,
    AksDiagnosticStatus,
    assess_aks_diagnostic,
)
from fdai.shared.providers.inventory import ResourceRecord
from fdai.shared.providers.kubernetes_metric import (
    KubernetesMetricTarget,
    KubernetesMetricWindowEvidence,
)
from fdai.shared.providers.metric import MetricPoint

CUTOFF = datetime(2026, 9, 10, 0, 5, tzinfo=UTC)


def _target(resource_type: str, **props: object) -> ResourceRecord:
    return ResourceRecord(
        resource_id=f"cluster/kubernetes/{resource_type}/uid",
        type=resource_type,
        props={
            "cluster_ref": "cluster",
            "name": "target",
            "resource_version": "20",
            "uid": "uid-target",
            **props,
        },
    )


def _context(target: ResourceRecord, **changes: object) -> AksDiagnosticContext:
    values: dict[str, object] = {
        "target": target,
        "related": (),
        "event_reasons": (),
        "metrics": (),
        "api_reachable": True,
        "azure_availability": "Available",
        "cutoff": CUTOFF,
        "source_cutoffs": {"kubernetes-api": CUTOFF},
        "source_revisions": {"kubernetes-api": "rv-20"},
        "evidence_refs": ("inventory:example",),
        "evidence_complete": True,
        "ontology_release": "sha256:" + "a" * 64,
        "principal_class": "reader",
        "audit_correlation_id": "correlation-example",
    }
    values.update(changes)
    return AksDiagnosticContext(**values)  # type: ignore[arg-type]


def _metric(
    target: KubernetesMetricTarget,
    *,
    end: datetime = CUTOFF,
) -> KubernetesMetricWindowEvidence:
    start = end - timedelta(minutes=5)
    labels = {"cluster_ref": target.cluster_ref, "uid": target.uid}
    if target.namespace is not None:
        labels["namespace"] = target.namespace
    return KubernetesMetricWindowEvidence(
        metric_name="kubernetes.container.oom_events",
        target=target,
        start=start,
        end=end,
        points=(
            MetricPoint(
                metric_name="kubernetes.container.oom_events",
                at=end,
                value=1,
                labels=labels,
            ),
        ),
        source_identity="metrics",
        source_revision="revision-1",
        provider_cutoff=end,
        coverage_receipt_ref="metric-coverage:example",
        complete=True,
        limitation=None,
    )


@pytest.mark.parametrize(
    ("target", "events", "expected"),
    (
        (
            _target("kubernetes.pod", container_waiting_reasons=("ImagePullBackOff",)),
            (),
            AksDiagnosticStatus.IMAGE_PULL_FAILED,
        ),
        (
            _target("kubernetes.pod", container_waiting_reasons=("CrashLoopBackOff",)),
            (),
            AksDiagnosticStatus.CRASH_LOOP,
        ),
        (
            _target(
                "kubernetes.pod",
                diagnostic_conditions=({"type": "PodScheduled", "status": "False"},),
            ),
            (),
            AksDiagnosticStatus.SCHEDULING_BLOCKED,
        ),
        (
            _target(
                "kubernetes.node",
                diagnostic_conditions=({"type": "MemoryPressure", "status": "True"},),
            ),
            (),
            AksDiagnosticStatus.NODE_PRESSURE,
        ),
        (
            _target(
                "kubernetes.node",
                diagnostic_conditions=({"type": "NetworkUnavailable", "status": "True"},),
            ),
            (),
            AksDiagnosticStatus.NETWORKING_UNAVAILABLE,
        ),
        (
            _target("kubernetes.pod"),
            ("FailedCreatePodSandBox",),
            AksDiagnosticStatus.NETWORKING_UNAVAILABLE,
        ),
        (
            _target("kubernetes.endpoint-slice", endpoint_count=2, ready=0),
            (),
            AksDiagnosticStatus.ENDPOINT_UNREADY,
        ),
        (
            _target("kubernetes.persistent-volume-claim", phase="Pending"),
            (),
            AksDiagnosticStatus.STORAGE_BLOCKED,
        ),
        (
            _target(
                "kubernetes.resource-quota",
                quota_hard={"requests.cpu": "4"},
                quota_used={"requests.cpu": "4"},
            ),
            (),
            AksDiagnosticStatus.QUOTA_CONSTRAINED,
        ),
        (
            _target("kubernetes.pod"),
            ("Unhealthy",),
            AksDiagnosticStatus.PROBE_FAILURE_EVIDENCE,
        ),
    ),
)
def test_classifies_reviewed_failure_signals_without_causal_authority(
    target: ResourceRecord,
    events: tuple[str, ...],
    expected: AksDiagnosticStatus,
) -> None:
    result = assess_aks_diagnostic(_context(target, event_reasons=events))

    assert result.status is expected
    assert result.owner_agent == "Forseti"
    assert result.cause_claim_supported is False
    assert result.execution_authority is False


def test_incomplete_evidence_holds_when_no_positive_signal_exists() -> None:
    result = assess_aks_diagnostic(_context(_target("kubernetes.pod"), evidence_complete=False))

    assert result.status is AksDiagnosticStatus.HELD
    assert result.complete is False
    assert result.evidence_gaps == ("required_evidence_incomplete",)


def test_endpoint_with_nil_readiness_does_not_become_a_false_failure() -> None:
    result = assess_aks_diagnostic(
        _context(
            _target(
                "kubernetes.endpoint-slice",
                endpoint_count=1,
                ready=0,
                ready_unknown=1,
            )
        )
    )

    assert result.status is AksDiagnosticStatus.NO_FAILURE_SIGNAL
    assert AksDiagnosticStatus.ENDPOINT_UNREADY not in result.signals


def test_conflicting_source_identity_holds_even_with_positive_signal() -> None:
    result = assess_aks_diagnostic(
        _context(
            _target("kubernetes.pod", container_waiting_reasons=("ImagePullBackOff",)),
            source_revisions={"other-source": "v1"},
        )
    )

    assert result.status is AksDiagnosticStatus.HELD
    assert result.conflicts == ("source_identity_mismatch",)


def test_exact_target_metric_can_add_a_diagnostic_signal() -> None:
    target = _target("kubernetes.pod", namespace="default")
    result = assess_aks_diagnostic(
        _context(
            target,
            metrics=(
                _metric(
                    KubernetesMetricTarget(
                        cluster_ref="cluster",
                        uid="uid-target",
                        namespace="default",
                    )
                ),
            ),
            source_cutoffs={"kubernetes-api": CUTOFF, "metrics": CUTOFF},
            source_revisions={"kubernetes-api": "rv-20", "metrics": "revision-1"},
        )
    )

    assert result.status is AksDiagnosticStatus.OOM_KILLED
    assert result.conflicts == ()


@pytest.mark.parametrize(
    "target",
    (
        KubernetesMetricTarget(cluster_ref="other-cluster", uid="uid-target", namespace="default"),
        KubernetesMetricTarget(cluster_ref="cluster", uid="other-uid", namespace="default"),
        KubernetesMetricTarget(cluster_ref="cluster", uid="uid-target", namespace="other"),
    ),
)
def test_foreign_metric_target_holds_without_importing_its_signal(
    target: KubernetesMetricTarget,
) -> None:
    result = assess_aks_diagnostic(
        _context(
            _target("kubernetes.pod", namespace="default"),
            metrics=(_metric(target),),
            source_cutoffs={"kubernetes-api": CUTOFF, "metrics": CUTOFF},
            source_revisions={"kubernetes-api": "rv-20", "metrics": "revision-1"},
        )
    )

    assert result.status is AksDiagnosticStatus.HELD
    assert result.signals == ()
    assert result.conflicts == ("metric_target_mismatch",)


def test_future_metric_window_holds_without_importing_its_signal() -> None:
    future = CUTOFF + timedelta(minutes=1)
    result = assess_aks_diagnostic(
        _context(
            _target("kubernetes.pod", namespace="default"),
            metrics=(
                _metric(
                    KubernetesMetricTarget(
                        cluster_ref="cluster",
                        uid="uid-target",
                        namespace="default",
                    ),
                    end=future,
                ),
            ),
            source_cutoffs={"kubernetes-api": CUTOFF, "metrics": CUTOFF},
            source_revisions={"kubernetes-api": "rv-20", "metrics": "revision-1"},
        )
    )

    assert result.status is AksDiagnosticStatus.HELD
    assert result.signals == ()
    assert result.conflicts == ("metric_window_mismatch",)
