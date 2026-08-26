"""Metric semantic registry, aligned window, and causal join tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.detection.series import MetricSample
from fdai.core.ontology_platform import QueryRow, QueryTable
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
    MetricScopeSeriesNodeHandler,
    MetricSeriesNodeHandler,
)
from fdai.core.ontology_platform.topology_history import TopologyDiff
from fdai.core.rca.temporal_causality import TemporalCausalityConfig
from fdai_service_contracts.ontology_query import OntologyQueryNode, QueryNodeKind, canonical_json

START = datetime(2026, 8, 10, tzinfo=UTC)


class _Provider:
    async def read(  # type: ignore[no-untyped-def]
        self, *, definition, resource_id, start, end, query_labels=None
    ):
        del query_labels
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


def _scope_node() -> OntologyQueryNode:
    return OntologyQueryNode(
        node_id="metric",
        kind=QueryNodeKind.METRIC_SCOPE_SERIES,
        depends_on=("scope",),
        arguments_json=canonical_json(
            {
                "concept_id": "request.volume",
                "start": START.isoformat(),
                "end": (START + timedelta(minutes=2)).isoformat(),
            }
        ),
        output_kind="metric.window",
    )


def _scope_handler(
    provider: object | None = None,
    *,
    scope_label_selectors: dict[str, tuple[str, ...]] | None = None,
) -> MetricScopeSeriesNodeHandler:
    definition = MetricSemanticDefinition(
        concept_id="request.volume",
        provider_metric="http.server.request.count",
        canonical_unit="count",
        aggregation=MetricAggregation.SUM,
        description="Completed requests.",
        scope_label_selectors=scope_label_selectors or {},
    )
    return MetricScopeSeriesNodeHandler(
        registry=MetricSemanticRegistry.build((definition,)),
        provider=provider or _Provider(),  # type: ignore[arg-type]
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


async def test_metric_scope_series_reads_one_canonical_resource_and_marks_sampling() -> None:
    handler = _scope_handler()
    scope = QueryTable(
        rows=(
            QueryRow.from_values("service-b", {"id": "service-b"}),
            QueryRow.from_values("service-a", {"id": "service-a"}),
        ),
        complete=True,
    )

    result = await handler(
        _scope_node(),
        {"scope": QueryNodeResult(value=scope, evidence_refs=("objectset:receipt",))},
    )

    assert isinstance(result.value, MetricWindow)
    assert result.value.resource_id == "service-a"
    assert result.value.complete is False
    assert result.value.missing_reason == "object_scope_sampled"
    assert result.value.evidence_refs == ("metric:provider", "objectset:receipt")


async def test_metric_scope_series_retains_empty_and_incomplete_scope_evidence() -> None:
    handler = _scope_handler()
    empty = await handler(
        _scope_node(),
        {
            "scope": QueryNodeResult(
                value=QueryTable(rows=(), complete=True),
                evidence_refs=("objectset:empty",),
            )
        },
    )
    incomplete = await handler(
        _scope_node(),
        {
            "scope": QueryNodeResult(
                value=QueryTable(
                    rows=(QueryRow.from_values("service-a", {"id": "service-a"}),),
                    complete=False,
                    truncation_reason="source_truncated",
                ),
                evidence_refs=("objectset:partial",),
            )
        },
    )

    assert isinstance(empty.value, MetricWindow)
    assert empty.value.resource_id == "scope:none"
    assert empty.value.missing_reason == "no_visible_resource"
    assert empty.evidence_refs == ("objectset:empty",)
    assert isinstance(incomplete.value, MetricWindow)
    assert incomplete.value.complete is False
    assert incomplete.value.missing_reason == "object_scope_incomplete"
    assert incomplete.value.evidence_refs == ("metric:provider", "objectset:partial")


async def test_metric_scope_series_rejects_unproven_scope_and_provider_identity_drift() -> None:
    handler = _scope_handler()
    table = QueryTable(
        rows=(QueryRow.from_values("service-a", {"id": "service-a"}),),
        complete=True,
    )
    with pytest.raises(ValueError, match="MUST cite scope evidence"):
        await handler(_scope_node(), {"scope": QueryNodeResult(value=table)})
    with pytest.raises(TypeError, match="MUST be a QueryTable"):
        await handler(
            _scope_node(),
            {"scope": QueryNodeResult(value="service-a", evidence_refs=("scope:bad",))},
        )

    class _DriftProvider(_Provider):
        async def read(self, *, definition, resource_id, start, end):  # type: ignore[no-untyped-def]
            result = await super().read(
                definition=definition,
                resource_id=resource_id,
                start=start,
                end=end,
            )
            return replace(result, resource_id="service-b")

    with pytest.raises(ValueError, match="does not match the verified scope request"):
        await _scope_handler(_DriftProvider())(
            _scope_node(),
            {"scope": QueryNodeResult(value=table, evidence_refs=("objectset:receipt",))},
        )


async def test_metric_scope_series_preserves_provider_and_sampling_gaps() -> None:
    class _GapProvider(_Provider):
        async def read(self, *, definition, resource_id, start, end):  # type: ignore[no-untyped-def]
            result = await super().read(
                definition=definition,
                resource_id=resource_id,
                start=start,
                end=end,
            )
            return replace(result, complete=False, missing_reason="provider_gap")

    scope = QueryTable(
        rows=(
            QueryRow.from_values("service-a", {"id": "service-a"}),
            QueryRow.from_values("service-b", {"id": "service-b"}),
        ),
        complete=True,
    )
    result = await _scope_handler(_GapProvider())(
        _scope_node(),
        {"scope": QueryNodeResult(value=scope, evidence_refs=("objectset:receipt",))},
    )

    assert isinstance(result.value, MetricWindow)
    assert result.value.complete is False
    assert result.value.missing_reason == "object_scope_sampled+provider_gap"


async def test_metric_scope_series_uses_reviewed_exact_identity_labels() -> None:
    class _ScopedProvider(_Provider):
        query_labels: dict[str, str] | None = None

        async def read(  # type: ignore[no-untyped-def]
            self, *, definition, resource_id, start, end, query_labels=None
        ):
            self.query_labels = query_labels
            return await super().read(
                definition=definition,
                resource_id=resource_id,
                start=start,
                end=end,
            )

    provider = _ScopedProvider()
    handler = _scope_handler(
        provider,
        scope_label_selectors={
            "resource_id": ("properties", "properties", "cluster_ref"),
            "pod_uid": ("properties", "properties", "uid"),
        },
    )
    scope = QueryTable(
        rows=(
            QueryRow.from_values(
                "pod-a",
                {
                    "id": "pod-a",
                    "properties": {
                        "properties": {
                            "cluster_ref": "/Subscriptions/EXAMPLE/ManagedClusters/AKS",
                            "uid": "pod-uid-a",
                        }
                    },
                },
            ),
        ),
        complete=True,
    )

    result = await handler(
        _scope_node(),
        {"scope": QueryNodeResult(value=scope, evidence_refs=("objectset:receipt",))},
    )

    assert isinstance(result.value, MetricWindow)
    assert result.value.resource_id == "pod-a"
    assert provider.query_labels == {
        "resource_id": "/subscriptions/example/managedclusters/aks",
        "pod_uid": "pod-uid-a",
    }
