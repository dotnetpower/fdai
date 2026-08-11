"""Verified metric-series and causal evidence-join query handlers."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from fdai_service_contracts.ontology_query import OntologyQueryNode, QueryNodeKind

from fdai.core.rca.temporal_causality import TemporalCausalityConfig

from .metric_semantics import (
    MetricSemanticRegistry,
    MetricWindow,
    MetricWindowProvider,
    join_causal_evidence,
)
from .query_execution import QueryNodeResult
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
    QueryNodeKind.EVIDENCE_JOIN: {
        "type": "object",
        "additionalProperties": False,
        "required": ["feature_cutoff"],
        "properties": {
            "feature_cutoff": {"type": "string", "format": "date-time"},
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
        return QueryNodeResult(value=result, evidence_refs=result.evidence_refs)


class EvidenceJoinNodeHandler:
    """Join cause, effect, and optional topology diff into one bounded disposition."""

    async def __call__(
        self,
        node: OntologyQueryNode,
        dependencies: Mapping[str, QueryNodeResult],
    ) -> QueryNodeResult:
        if node.kind is not QueryNodeKind.EVIDENCE_JOIN:
            raise ValueError("evidence join handler is bound to the wrong node kind")
        if len(node.depends_on) not in {2, 3} or set(dependencies) != set(node.depends_on):
            raise ValueError("evidence_join requires cause, effect, and optional topology")
        allowed = {
            "feature_cutoff",
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
        if len(node.depends_on) == 3:
            topology_value = dependencies[node.depends_on[2]].value
            if not isinstance(topology_value, TopologyDiff):
                raise TypeError("evidence_join topology dependency MUST be TopologyDiff")
            topology = topology_value
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


__all__ = ["EvidenceJoinNodeHandler", "METRIC_ARGUMENT_SCHEMAS", "MetricSeriesNodeHandler"]
