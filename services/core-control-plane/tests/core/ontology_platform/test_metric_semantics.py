"""Metric semantic registry, aligned window, and causal join tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.detection.series import MetricSample
from fdai.core.ontology_platform.metric_semantics import (
    CausalEvidenceJoin,
    CausalJoinStatus,
    MetricAggregation,
    MetricSemanticDefinition,
    MetricSemanticRegistry,
    MetricWindow,
    compare_aligned_windows,
    join_causal_evidence,
)
from fdai.core.ontology_platform.query_execution import QueryNodeResult
from fdai.core.ontology_platform.query_metric_handlers import (
    EvidenceJoinNodeHandler,
    MetricSeriesNodeHandler,
)
from fdai.core.ontology_platform.topology_history import TopologyDiff
from fdai.core.rca.temporal_causality import TemporalCausalityConfig
from fdai_service_contracts.ontology_query import OntologyQueryNode, QueryNodeKind, canonical_json

START = datetime(2026, 8, 10, tzinfo=UTC)


class _Provider:
    async def read(self, *, definition, resource_id, start, end):  # type: ignore[no-untyped-def]
        return MetricWindow(
            concept_id=definition.concept_id,
            resource_id=resource_id,
            unit=definition.canonical_unit,
            start=start,
            end=end,
            samples=(MetricSample(timestamp=start, value=1.0),),
            complete=True,
            evidence_refs=("metric:provider",),
        )


def _window(
    *,
    concept_id: str = "request.volume",
    start: datetime = START,
    values: tuple[float, ...] = (0.0, 0.0),
    complete: bool = True,
    reason: str | None = None,
) -> MetricWindow:
    return MetricWindow(
        concept_id=concept_id,
        resource_id="service-a",
        unit="count",
        start=start,
        end=start + timedelta(minutes=max(2, len(values))),
        samples=tuple(
            MetricSample(timestamp=start + timedelta(minutes=index), value=value)
            for index, value in enumerate(values)
        ),
        complete=complete,
        missing_reason=reason,
        evidence_refs=(f"metric:{concept_id}:{start.hour}",),
    )


def _topology_diff(*, complete: bool = True) -> TopologyDiff:
    return TopologyDiff(
        before_digest="sha256:" + ("a" * 64),
        after_digest="sha256:" + ("b" * 64),
        added_object_ids=(),
        removed_object_ids=(),
        changed_object_ids=(),
        added_link_keys=(),
        removed_link_keys=("vnet-a|peered_with|vnet-b",),
        changed_link_keys=(),
        complete=complete,
        evidence_refs=("topology:change",),
        digest="sha256:" + ("c" * 64),
    )


def test_metric_registry_resolves_exact_reviewed_concepts_without_alias_routing() -> None:
    definition = MetricSemanticDefinition(
        concept_id="request.volume",
        provider_metric="http.server.request.count",
        canonical_unit="count",
        aggregation=MetricAggregation.SUM,
        description="Completed server requests in the bounded window.",
        monotonic=True,
    )
    registry = MetricSemanticRegistry.build((definition,))

    assert registry.resolve("request.volume") is definition
    assert registry.digest.startswith("sha256:")
    with pytest.raises(KeyError, match="unknown metric concept"):
        registry.resolve("requests")


def test_aligned_windows_distinguish_observed_zero_from_missing_data() -> None:
    baseline = _window(start=START, values=(0.0, 0.0))
    current = _window(start=START + timedelta(hours=1), values=(0.0, 0.0))

    zero = compare_aligned_windows(baseline, current, aggregation=MetricAggregation.SUM)
    missing = compare_aligned_windows(
        baseline,
        _window(
            start=START + timedelta(hours=1),
            values=(),
            complete=False,
            reason="provider_gap",
        ),
        aggregation=MetricAggregation.SUM,
    )

    assert zero.complete is True
    assert zero.current_value == 0.0
    assert zero.relative_change is None
    assert missing.complete is False
    assert missing.current_value is None
    assert missing.reason == "provider_gap"


def test_causal_join_never_treats_chronology_without_topology_as_cause() -> None:
    cause = _window(concept_id="deployment.change", values=(1.0, 0.0, 0.0, 0.0))
    effect = _window(concept_id="request.errors", values=(0.0, 1.0, 1.0, 1.0))

    result = join_causal_evidence(
        cause=cause,
        effect=effect,
        topology_change=None,
        feature_cutoff=START + timedelta(minutes=4),
        config=TemporalCausalityConfig(lag_seconds=(0,), min_samples=4),
        competing_explanations=("credential_change", "application_release"),
    )

    assert result.status is CausalJoinStatus.UNRESOLVED
    assert "topology_change_unavailable" in result.limitations
    assert result.competing_explanations == ("credential_change", "application_release")


def test_complete_join_retains_refutation_and_competing_explanations() -> None:
    cause = _window(
        concept_id="network.change",
        values=(1.0, 1.0, 1.0, 1.0, 1.0, 1.0),
    )
    effect = _window(
        concept_id="storage.write.success",
        values=(1.0, 0.0, 1.0, 0.0, 1.0, 0.0),
    )

    result = join_causal_evidence(
        cause=cause,
        effect=effect,
        topology_change=_topology_diff(),
        feature_cutoff=START + timedelta(minutes=6),
        config=TemporalCausalityConfig(
            lag_seconds=(0,),
            min_samples=4,
            difference_period=0,
        ),
        competing_explanations=("dns", "firewall", "credential"),
    )

    assert result.status is CausalJoinStatus.REFUTED
    assert result.temporal_claim is not None
    assert "association_below_threshold" in result.limitations
    assert result.topology_diff_digest == _topology_diff().digest
    assert result.evidence_refs[-1] == "topology:change"


async def test_metric_and_evidence_join_query_handlers_use_exact_typed_dependencies() -> None:
    definition = MetricSemanticDefinition(
        concept_id="request.volume",
        provider_metric="http.server.request.count",
        canonical_unit="count",
        aggregation=MetricAggregation.SUM,
        description="Completed requests.",
    )
    metric_handler = MetricSeriesNodeHandler(
        registry=MetricSemanticRegistry.build((definition,)),
        provider=_Provider(),
    )
    metric = await metric_handler(
        OntologyQueryNode(
            node_id="metric",
            kind=QueryNodeKind.METRIC_SERIES,
            arguments_json=canonical_json(
                {
                    "concept_id": "request.volume",
                    "resource_id": "service-a",
                    "start": START.isoformat(),
                    "end": (START + timedelta(minutes=2)).isoformat(),
                }
            ),
            output_kind="metric.window",
        ),
        {},
    )
    join = await EvidenceJoinNodeHandler()(
        OntologyQueryNode(
            node_id="join",
            kind=QueryNodeKind.EVIDENCE_JOIN,
            depends_on=("cause", "effect"),
            arguments_json=canonical_json(
                {
                    "feature_cutoff": (START + timedelta(minutes=2)).isoformat(),
                    "min_samples": 4,
                    "competing_explanations": ["deployment"],
                }
            ),
            output_kind="causal.join",
        ),
        {"cause": metric, "effect": QueryNodeResult(value=metric.value)},
    )

    assert isinstance(join.value, CausalEvidenceJoin)
    assert join.value.status is CausalJoinStatus.UNRESOLVED
    assert "topology_change_unavailable" in join.value.limitations
