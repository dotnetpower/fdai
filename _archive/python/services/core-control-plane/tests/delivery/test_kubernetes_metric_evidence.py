"""Kubernetes metric evidence tests."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from fdai.delivery.kubernetes_metric_evidence import (
    KubernetesMetricEvidenceCollector,
    KubernetesMetricTarget,
)
from fdai.shared.providers.kubernetes_metric import KubernetesMetricWindowEvidence
from fdai.shared.providers.metric import MetricPoint, MetricQuery, StaticMetricProvider

START = datetime(2026, 9, 10, 0, 0, tzinfo=UTC)
END = datetime(2026, 9, 10, 0, 5, tzinfo=UTC)
TARGET = KubernetesMetricTarget(cluster_ref="cluster-ref", namespace="default", uid="uid-pod")
METRIC = "kubernetes.container.memory.working_set_bytes"


class _UnscopedProvider:
    async def query(self, _query: MetricQuery) -> AsyncIterator[MetricPoint]:
        yield _point(uid="uid-other")


def _point(*, uid: str = "uid-pod") -> MetricPoint:
    return MetricPoint(
        metric_name=METRIC,
        at=START,
        value=1024,
        labels={"cluster_ref": "cluster-ref", "namespace": "default", "uid": uid},
    )


async def test_point_only_provider_never_claims_complete_window() -> None:
    evidence = await KubernetesMetricEvidenceCollector(
        provider=StaticMetricProvider([_point()]),
        source_identity="metric-source",
        source_revision="v1",
    ).collect(metric_name=METRIC, target=TARGET, start=START, end=END)

    assert len(evidence.points) == 1
    assert evidence.complete is False
    assert evidence.limitation == "provider_coverage_unverified"


async def test_coverage_receipt_can_complete_exact_metric_window() -> None:
    evidence = await KubernetesMetricEvidenceCollector(
        provider=StaticMetricProvider([_point()]),
        source_identity="metric-source",
        source_revision="v1",
        coverage_receipt_ref="metric-coverage:example",
        provider_cutoff=END,
    ).collect(metric_name=METRIC, target=TARGET, start=START, end=END)

    assert evidence.complete is True
    assert evidence.limitation is None


async def test_stale_provider_cutoff_cannot_complete_metric_window() -> None:
    evidence = await KubernetesMetricEvidenceCollector(
        provider=StaticMetricProvider([_point()]),
        source_identity="metric-source",
        source_revision="v1",
        coverage_receipt_ref="metric-coverage:example",
        provider_cutoff=START,
    ).collect(metric_name=METRIC, target=TARGET, start=START, end=END)

    assert evidence.complete is False
    assert evidence.limitation == "provider_cutoff_before_window_end"


def test_typed_evidence_rejects_complete_window_with_stale_cutoff() -> None:
    with pytest.raises(ValueError, match="cutoff through the window end"):
        KubernetesMetricWindowEvidence(
            metric_name=METRIC,
            target=TARGET,
            start=START,
            end=END,
            points=(_point(),),
            source_identity="metric-source",
            source_revision="v1",
            provider_cutoff=START,
            coverage_receipt_ref="metric-coverage:example",
            complete=True,
            limitation=None,
        )


async def test_mismatched_uid_discards_candidate_and_fails_closed() -> None:
    evidence = await KubernetesMetricEvidenceCollector(
        provider=_UnscopedProvider(),
        source_identity="metric-source",
        source_revision="v1",
    ).collect(metric_name=METRIC, target=TARGET, start=START, end=END)

    assert evidence.points == ()
    assert evidence.complete is False
    assert evidence.limitation == "point_scope_invalid"


async def test_empty_metric_window_does_not_prove_zero() -> None:
    evidence = await KubernetesMetricEvidenceCollector(
        provider=StaticMetricProvider([]),
        source_identity="metric-source",
        source_revision="v1",
    ).collect(metric_name=METRIC, target=TARGET, start=START, end=END)

    assert evidence.points == ()
    assert evidence.limitation == "zero_points_unverified"
