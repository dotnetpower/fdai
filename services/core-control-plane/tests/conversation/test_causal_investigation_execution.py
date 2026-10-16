"""Compiler-to-handler regressions for bounded causal investigations."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest
from fdai.core.conversation.semantic_investigation_planning import compile_investigation_plan
from fdai.core.detection.series import MetricSample
from fdai.core.ontology_platform.metric_semantics import (
    CausalEvidenceJoin,
    CausalJoinStatus,
    MetricAggregation,
    MetricWindow,
    compare_aligned_windows,
)
from fdai.core.ontology_platform.query_execution import QueryNodeResult
from fdai.core.ontology_platform.query_metric_handlers import EvidenceJoinNodeHandler
from fdai_service_contracts.ontology_query import QueryNodeKind

from tests.conversation.test_semantic_investigation_planning import (
    _manifest,
    _verified_intent,
    _verifier,
    _windows,
)
from tests.core.ontology_platform.test_metric_semantics import _topology_diff


@pytest.mark.parametrize("future_sample", [False, True])
@pytest.mark.parametrize("comparison_mismatch", [False, True])
async def test_compiled_join_uses_the_end_of_its_requested_series(
    future_sample: bool,
    comparison_mismatch: bool,
) -> None:
    windows = _windows()
    plan = compile_investigation_plan(
        _verified_intent(),
        manifest=_manifest(),
        verifier=_verifier(),
        windows=windows,
        purpose="operations-review",
    )
    join = next(node for node in plan.nodes if node.kind is QueryNodeKind.EVIDENCE_JOIN)
    assert join.arguments["feature_cutoff"] == windows.current_end.isoformat()
    values = (3.0, 8.0, 1.0, 7.0, 2.0, 9.0, 4.0, 6.0, 0.0, 5.0)

    def metric(concept: str, samples: tuple[float, ...]) -> MetricWindow:
        return MetricWindow(
            concept_id=concept,
            resource_id="service-a",
            unit="ms",
            start=windows.current_start,
            end=windows.current_end,
            samples=tuple(
                MetricSample(timestamp=windows.current_start + timedelta(minutes=i), value=value)
                for i, value in enumerate(samples)
            ),
            complete=True,
            evidence_refs=("metric:current",),
        )

    cause = metric("dependency.latency", values)
    effect = metric("service.latency", (0.0, *values[:-1]))
    baseline = replace(
        effect,
        start=windows.baseline_start,
        end=windows.baseline_end,
        samples=tuple(
            MetricSample(timestamp=item.timestamp - timedelta(minutes=10), value=0.0)
            for item in effect.samples
        ),
    )
    comparison = compare_aligned_windows(baseline, effect, aggregation=MetricAggregation.AVERAGE)
    if comparison_mismatch:
        comparison = replace(comparison, resource_id="resource:unrelated")
    if future_sample:
        cause = replace(
            cause,
            end=windows.current_end + timedelta(minutes=1),
            samples=(
                *cause.samples,
                MetricSample(timestamp=windows.current_end + timedelta(minutes=1), value=1.0),
            ),
        )
    topology = _topology_diff()
    assert topology.before is not None and topology.after is not None
    topology = replace(
        topology,
        before=replace(topology.before, as_of=windows.baseline_end, known_at=windows.known_at),
        after=replace(topology.after, as_of=windows.current_end, known_at=windows.known_at),
    )
    dependencies = {
        key: QueryNodeResult(value=value)
        for key, value in zip(join.depends_on, (cause, effect, topology, comparison), strict=True)
    }
    if comparison_mismatch:
        with pytest.raises(ValueError, match="comparison MUST match the effect window"):
            await EvidenceJoinNodeHandler()(join, dependencies)
    elif future_sample:
        with pytest.raises(ValueError, match="MUST NOT cross feature_cutoff"):
            await EvidenceJoinNodeHandler()(join, dependencies)
    else:
        result = await EvidenceJoinNodeHandler()(join, dependencies)
        assert isinstance(result.value, CausalEvidenceJoin)
        assert result.value.temporal_claim is not None
        assert result.value.status is CausalJoinStatus.UNRESOLVED
        assert "competing_explanations_unresolved" in result.value.limitations
        assert result.value.execution_authority is False
