"""Verified metric-series and causal evidence-join query handlers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime
from typing import Any

from fdai_service_contracts.ontology_query import (
    EvidenceAuthority,
    OntologyQueryNode,
    QueryNodeKind,
)

from fdai.core.rca.temporal_causality import TemporalCausalityConfig

from .metric_semantics import (
    CausalEvidenceJoin,
    CausalJoinStatus,
    MetricSemanticRegistry,
    MetricWindow,
    MetricWindowComparison,
    MetricWindowProvider,
    compare_aligned_windows,
    join_causal_evidence,
)
from .query_execution import QueryNodeResult
from .query_values import QueryTable
from .topology_history import TopologyDiff

METRIC_ARGUMENT_SCHEMAS: Mapping[QueryNodeKind, Mapping[str, object]] = {
    QueryNodeKind.METRIC_SERIES: {
        "type": "object",
        "additionalProperties": False,
        "required": ["concept_id", "resource_id", "start", "end"],
        "properties": {
            "concept_id": {"type": "string", "minLength": 1, "maxLength": 128},
            "resource_id": {"type": "string", "minLength": 1, "maxLength": 256},
            "start": {"type": "string", "format": "date-time"},
            "end": {"type": "string", "format": "date-time"},
        },
    },
    QueryNodeKind.METRIC_SCOPE_SERIES: {
        "type": "object",
        "additionalProperties": False,
        "required": ["concept_id", "start", "end"],
        "properties": {
            "concept_id": {"type": "string", "minLength": 1, "maxLength": 128},
            "start": {"type": "string", "format": "date-time"},
            "end": {"type": "string", "format": "date-time"},
        },
    },
    QueryNodeKind.METRIC_COMPARISON: {
        "type": "object",
        "additionalProperties": False,
        "required": [],
    },
    QueryNodeKind.EVIDENCE_JOIN: {
        "type": "object",
        "additionalProperties": False,
        "required": ["feature_cutoff"],
        "properties": {
            "feature_cutoff": {"type": "string", "format": "date-time"},
            "effect_direction": {"type": "string", "enum": ["decrease", "increase"]},
            "lag_seconds": {
                "type": "array",
                "minItems": 1,
                "maxItems": 16,
                "items": {"type": "integer", "minimum": 0},
                "uniqueItems": True,
            },
            "min_samples": {"type": "integer", "minimum": 4},
            "min_abs_correlation": {"type": "number", "minimum": 0, "maximum": 1},
            "competing_explanations": {
                "type": "array",
                "maxItems": 16,
                "items": {"type": "string", "minLength": 1, "maxLength": 256},
                "uniqueItems": True,
            },
        },
    },
}


class MetricSeriesNodeHandler:
    """Read one exact metric concept for one exact resource and bounded window."""

    def __init__(
        self,
        *,
        registry: MetricSemanticRegistry,
        provider: MetricWindowProvider,
    ) -> None:
        self._registry = registry
        self._provider = provider

    async def __call__(
        self,
        node: OntologyQueryNode,
        dependencies: Mapping[str, QueryNodeResult],
    ) -> QueryNodeResult:
        if node.kind is not QueryNodeKind.METRIC_SERIES or dependencies:
            raise ValueError("metric_series node MUST be a dependency-free metric source")
        if set(node.arguments) != {"concept_id", "resource_id", "start", "end"}:
            raise ValueError("metric_series arguments do not match the closed schema")
        concept_id = _text(node.arguments["concept_id"], "concept_id")
        resource_id = _text(node.arguments["resource_id"], "resource_id")
        start = _timestamp(node.arguments["start"], "start")
        end = _timestamp(node.arguments["end"], "end")
        definition = self._registry.resolve(concept_id)
        result = await self._provider.read(
            definition=definition,
            resource_id=resource_id,
            start=start,
            end=end,
        )
        if (
            result.concept_id != concept_id
            or result.resource_id != resource_id
            or result.unit != definition.canonical_unit
            or result.start != start
            or result.end != end
        ):
            raise ValueError("metric provider result does not match the verified request")
        return QueryNodeResult(
            value=result,
            evidence_refs=result.evidence_refs,
            authority=EvidenceAuthority.SERVER_OPERATIONAL_METRICS,
        )


class MetricScopeSeriesNodeHandler:
    """Read one canonical resource while retaining visible-scope incompleteness."""

    def __init__(
        self,
        *,
        registry: MetricSemanticRegistry,
        provider: MetricWindowProvider,
    ) -> None:
        self._registry = registry
        self._provider = provider

    async def __call__(
        self,
        node: OntologyQueryNode,
        dependencies: Mapping[str, QueryNodeResult],
    ) -> QueryNodeResult:
        if node.kind is not QueryNodeKind.METRIC_SCOPE_SERIES:
            raise ValueError("metric scope handler is bound to the wrong node kind")
        if len(node.depends_on) != 1 or set(dependencies) != set(node.depends_on):
            raise ValueError("metric_scope_series requires one table dependency")
        if set(node.arguments) != {"concept_id", "start", "end"}:
            raise ValueError("metric_scope_series arguments do not match the closed schema")
        dependency = dependencies[node.depends_on[0]]
        if not isinstance(dependency.value, QueryTable):
            raise TypeError("metric_scope_series dependency MUST be a QueryTable")
        if not dependency.evidence_refs:
            raise ValueError("metric_scope_series dependency MUST cite scope evidence")
        table = dependency.value
        resource_ids = tuple(
            sorted({_text(row.values.get("id"), "resource_id") for row in table.rows})
        )
        concept_id = _text(node.arguments["concept_id"], "concept_id")
        start = _timestamp(node.arguments["start"], "start")
        end = _timestamp(node.arguments["end"], "end")
        definition = self._registry.resolve(concept_id)
        if not resource_ids:
            result = MetricWindow(
                concept_id=concept_id,
                resource_id="scope:none",
                unit=definition.canonical_unit,
                start=start,
                end=end,
                samples=(),
                complete=False,
                evidence_refs=dependency.evidence_refs,
                missing_reason="no_visible_resource",
            )
            return QueryNodeResult(
                value=result,
                evidence_refs=result.evidence_refs,
                authority=EvidenceAuthority.SERVER_OPERATIONAL_METRICS,
            )
        resource_id = resource_ids[0]
        query_labels = None
        if definition.scope_label_selectors:
            if not table.complete or len(resource_ids) != 1:
                reason = (
                    "object_scope_incomplete" if not table.complete else "object_scope_ambiguous"
                )
                result = MetricWindow(
                    concept_id=concept_id,
                    resource_id=resource_id,
                    unit=definition.canonical_unit,
                    start=start,
                    end=end,
                    samples=(),
                    complete=False,
                    evidence_refs=dependency.evidence_refs,
                    missing_reason=reason,
                )
                return QueryNodeResult(
                    value=result,
                    evidence_refs=result.evidence_refs,
                    authority=EvidenceAuthority.SERVER_OPERATIONAL_METRICS,
                )
            row = next(row for row in table.rows if row.values.get("id") == resource_id)
            query_labels = _scope_query_labels(
                row.values,
                definition.scope_label_selectors,
            )
        if query_labels is None:
            result = await self._provider.read(
                definition=definition,
                resource_id=resource_id,
                start=start,
                end=end,
            )
        else:
            result = await self._provider.read(
                definition=definition,
                resource_id=resource_id,
                start=start,
                end=end,
                query_labels=query_labels,
            )
        if (
            result.concept_id != concept_id
            or result.resource_id != resource_id
            or result.unit != definition.canonical_unit
            or result.start != start
            or result.end != end
        ):
            raise ValueError("metric provider result does not match the verified scope request")
        evidence_refs = tuple(dict.fromkeys((*result.evidence_refs, *dependency.evidence_refs)))
        scope_reason = (
            "object_scope_incomplete"
            if not table.complete
            else "object_scope_sampled"
            if len(resource_ids) > 1
            else None
        )
        if scope_reason is not None:
            missing_reason = "+".join(
                sorted({reason for reason in (result.missing_reason, scope_reason) if reason})
            )
            result = replace(
                result,
                complete=False,
                missing_reason=missing_reason,
                evidence_refs=evidence_refs,
            )
        elif result.evidence_refs != evidence_refs:
            result = replace(result, evidence_refs=evidence_refs)
        return QueryNodeResult(
            value=result,
            evidence_refs=result.evidence_refs,
            authority=EvidenceAuthority.SERVER_OPERATIONAL_METRICS,
        )


def _scope_query_labels(
    values: Mapping[str, Any],
    selectors: Mapping[str, tuple[str, ...]],
) -> Mapping[str, str]:
    labels: dict[str, str] = {}
    for label, path in selectors.items():
        selected: object = values
        for segment in path:
            if not isinstance(selected, Mapping) or segment not in selected:
                raise ValueError("metric scope selector is absent from the verified Resource")
            selected = selected[segment]
        value = _text(selected, f"scope_label.{label}")
        labels[label] = value.casefold() if label == "resource_id" else value
    return labels


class EvidenceJoinNodeHandler:
    """Join cause, effect, and optional topology diff into one bounded disposition."""

    async def __call__(
        self,
        node: OntologyQueryNode,
        dependencies: Mapping[str, QueryNodeResult],
    ) -> QueryNodeResult:
        if node.kind is not QueryNodeKind.EVIDENCE_JOIN:
            raise ValueError("evidence join handler is bound to the wrong node kind")
        if len(node.depends_on) not in {2, 3, 4} or set(dependencies) != set(node.depends_on):
            raise ValueError(
                "evidence_join requires cause, effect, optional topology, and comparison"
            )
        allowed = {
            "feature_cutoff",
            "effect_direction",
            "lag_seconds",
            "min_samples",
            "min_abs_correlation",
            "competing_explanations",
        }
        if set(node.arguments) - allowed or "feature_cutoff" not in node.arguments:
            raise ValueError("evidence_join arguments do not match the closed schema")
        cause = dependencies[node.depends_on[0]].value
        effect = dependencies[node.depends_on[1]].value
        if not isinstance(cause, MetricWindow) or not isinstance(effect, MetricWindow):
            raise TypeError("evidence_join cause and effect MUST be MetricWindow values")
        topology: TopologyDiff | None = None
        if len(node.depends_on) >= 3:
            topology_value = dependencies[node.depends_on[2]].value
            if not isinstance(topology_value, TopologyDiff):
                raise TypeError("evidence_join topology dependency MUST be TopologyDiff")
            topology = topology_value
        comparison: MetricWindowComparison | None = None
        if len(node.depends_on) == 4:
            comparison_value = dependencies[node.depends_on[3]].value
            if not isinstance(comparison_value, MetricWindowComparison):
                raise TypeError(
                    "evidence_join comparison dependency MUST be MetricWindowComparison"
                )
            comparison = comparison_value
            effect_direction = node.arguments.get("effect_direction")
            if effect_direction not in {"decrease", "increase"}:
                raise ValueError("evidence_join comparison requires a bounded effect_direction")
            limitation = _symptom_comparison_limitation(
                comparison,
                direction=effect_direction,
            )
            if limitation is not None:
                evidence_refs = tuple(
                    dict.fromkeys(
                        (
                            *cause.evidence_refs,
                            *effect.evidence_refs,
                            *comparison.evidence_refs,
                        )
                    )
                )
                return QueryNodeResult(
                    value=CausalEvidenceJoin(
                        status=CausalJoinStatus.UNRESOLVED,
                        temporal_claim=None,
                        topology_diff_digest=topology.digest if topology else None,
                        competing_explanations=(),
                        limitations=(limitation,),
                        evidence_refs=evidence_refs,
                    ),
                    evidence_refs=evidence_refs,
                )
        lags = node.arguments.get("lag_seconds", [0])
        if not isinstance(lags, list) or not lags or len(lags) > 16:
            raise ValueError("evidence_join lag_seconds MUST be a bounded array")
        if any(isinstance(item, bool) or not isinstance(item, int) for item in lags):
            raise ValueError("evidence_join lag_seconds MUST contain integers")
        competing = node.arguments.get("competing_explanations", [])
        if not isinstance(competing, list) or len(competing) > 16:
            raise ValueError("evidence_join competing explanations exceed bounds")
        competing_text = tuple(_text(item, "competing_explanation") for item in competing)
        min_samples = node.arguments.get("min_samples", 12)
        min_correlation = node.arguments.get("min_abs_correlation", 0.5)
        if isinstance(min_samples, bool) or not isinstance(min_samples, int):
            raise ValueError("evidence_join min_samples MUST be an integer")
        if isinstance(min_correlation, bool) or not isinstance(min_correlation, int | float):
            raise ValueError("evidence_join min_abs_correlation MUST be numeric")
        result = join_causal_evidence(
            cause=cause,
            effect=effect,
            topology_change=topology,
            feature_cutoff=_timestamp(node.arguments["feature_cutoff"], "feature_cutoff"),
            config=TemporalCausalityConfig(
                lag_seconds=tuple(lags),
                min_samples=min_samples,
                min_abs_correlation=float(min_correlation),
            ),
            competing_explanations=competing_text,
        )
        if comparison is not None:
            result = replace(
                result,
                evidence_refs=tuple(
                    dict.fromkeys((*result.evidence_refs, *comparison.evidence_refs))
                ),
            )
        return QueryNodeResult(value=result, evidence_refs=result.evidence_refs)


def _symptom_comparison_limitation(
    comparison: MetricWindowComparison,
    *,
    direction: object,
) -> str | None:
    if not comparison.complete or comparison.absolute_change is None:
        return "symptom_change_incomplete"
    if direction == "increase" and comparison.absolute_change <= 0:
        return "symptom_increase_not_observed"
    if direction == "decrease" and comparison.absolute_change >= 0:
        return "symptom_decrease_not_observed"
    return None


class MetricComparisonNodeHandler:
    """Compare equal baseline and current windows using reviewed aggregation."""

    def __init__(self, *, registry: MetricSemanticRegistry) -> None:
        self._registry = registry

    async def __call__(
        self,
        node: OntologyQueryNode,
        dependencies: Mapping[str, QueryNodeResult],
    ) -> QueryNodeResult:
        if node.kind is not QueryNodeKind.METRIC_COMPARISON or node.arguments:
            raise ValueError("metric comparison accepts no model arguments")
        if len(node.depends_on) != 2 or set(dependencies) != set(node.depends_on):
            raise ValueError("metric comparison requires baseline and current windows")
        baseline = dependencies[node.depends_on[0]].value
        current = dependencies[node.depends_on[1]].value
        if not isinstance(baseline, MetricWindow) or not isinstance(current, MetricWindow):
            raise TypeError("metric comparison dependencies MUST be MetricWindow values")
        definition = self._registry.resolve(baseline.concept_id)
        if current.concept_id != definition.concept_id:
            raise ValueError("metric comparison concept does not match the registry")
        result = compare_aligned_windows(
            baseline,
            current,
            aggregation=definition.aggregation,
        )
        return QueryNodeResult(value=result, evidence_refs=result.evidence_refs)


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 256:
        raise ValueError(f"metric query {name} MUST be bounded and non-empty")
    return value


def _timestamp(value: object, name: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"metric query {name} MUST be an RFC 3339 string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"metric query {name} MUST be an RFC 3339 string") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"metric query {name} MUST be timezone-aware")
    return parsed


__all__ = [
    "EvidenceJoinNodeHandler",
    "METRIC_ARGUMENT_SCHEMAS",
    "MetricComparisonNodeHandler",
    "MetricScopeSeriesNodeHandler",
    "MetricSeriesNodeHandler",
]
