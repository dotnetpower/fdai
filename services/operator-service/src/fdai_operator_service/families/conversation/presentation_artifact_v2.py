"""Compile an accessible v2 artifact from verified semantic rows.

This compiler copies exact values only after the deterministic planner selects
one channel-neutral block. Vendor capability reduction remains downstream.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from fdai_operator_service.families.conversation.contracts import JsonObject
from fdai_operator_service.families.conversation.presentation_artifact_domains import (
    _error_activity_blocks,
    _health_blocks,
    _resource_condition_artifact,
    _service_health_artifact,
    _target_candidates_overview,
)
from fdai_operator_service.families.conversation.presentation_artifact_renderers import (
    _compile_block,
    _limitation_block,
    _metric_series_sampling,
    _metric_series_sampling_description,
    _presentation_semantics,
)
from fdai_operator_service.families.conversation.presentation_artifact_v3 import (
    PresentationLayout,
    assemble_presentation_artifact_v3,
)
from fdai_operator_service.families.conversation.presentation_planner import (
    EvidenceShape,
    PresentationIntent,
    SemanticShape,
    analyze_evidence_shape,
    plan_presentation,
)
from fdai_operator_service.families.conversation.subscription_scope_presentation import (
    subscription_scope_artifact,
)

_MAX_COLUMNS = 6
_MAX_CELL_CHARS = 512
_MAX_REFS = 8
_RESOURCE_STATE_COLUMNS = (
    "name",
    "resource_group",
    "region",
    "observed_state",
    "type",
    "source_observed_at",
)
_RESOURCE_HEALTH_COLUMNS = (
    "name",
    "type",
    "coverage_state",
    "availability_state",
    "provider_observed_at",
    "collection_completed_at",
)
_RESOURCE_METRIC_COLUMNS = (
    "name",
    "type",
    "metric_concept",
    "value",
    "unit",
    "window_end",
)
_RESOURCE_EVENT_COLUMNS = (
    "occurred_at",
    "name",
    "type",
    "event_kind",
    "status",
    "classification",
)
_RESOURCE_INGRESS_COLUMNS = (
    "name",
    "ingress_enabled",
    "external",
    "fqdn",
    "target_port",
    "transport",
)
_SERVICE_HEALTH_COLUMNS = (
    "impact_start_at",
    "event_type",
    "title",
    "level",
    "impacted_resource_count",
    "resource_name",
)
_OPERATIONS = frozenset(
    {"select", "aggregate", "compare", "explain_change", "validate", "action_draft"}
)
_OUTPUT_SHAPES = frozenset(
    {
        "aggregation_table",
        "causal_evidence",
        "evidence_validation",
        "ontology_manifest",
        "ontology_relationships",
        "property_filtered_resources",
        "resource_event_history",
        "resource_condition_sections",
        "resource_health_list",
        "resource_list",
        "resource_metric_list",
        "resource_state_list",
        "resource_state_transitions",
        "resource_target_candidates",
        "subscription_scope_identity",
        "subscription_service_health",
        "target_error_activity_correlation",
        "target_health_assessment",
        "target_ingress_configuration",
        "target_resource_metric",
        "target_resource_metric_series",
        "temporal_comparison",
        "topology_graph",
    }
)


def compile_presentation_artifact_v2(
    *,
    semantic: Mapping[str, object],
    technical_details: Mapping[str, object],
    locale: str,
) -> JsonObject | None:
    """Compile one v2 artifact or fail closed to canonical text."""
    context = technical_details.get("presentation_context")
    outputs = technical_details.get("outputs")
    evidence_refs = semantic.get("evidence_refs")
    if (
        not isinstance(context, Mapping)
        or set(context)
        not in (
            {"operation", "output_shape"},
            {"operation", "output_shape", "measure_concepts"},
            {"operation", "output_shape", "presentation_semantics"},
            {
                "operation",
                "output_shape",
                "measure_concepts",
                "presentation_semantics",
            },
        )
        or not isinstance(outputs, list)
        or not isinstance(evidence_refs, list)
        or not evidence_refs
        or len(evidence_refs) > _MAX_REFS
        or any(not isinstance(item, str) for item in evidence_refs)
    ):
        return None
    operation = context.get("operation")
    output_shape = context.get("output_shape")
    if operation not in _OPERATIONS or output_shape not in _OUTPUT_SHAPES:
        return None
    if output_shape == "resource_condition_sections":
        return _resource_condition_artifact(
            outputs=outputs,
            context=context,
            evidence_refs=cast(list[str], evidence_refs),
            locale=locale,
            verified=_semantic_is_verified(semantic),
        )
    if len(outputs) != 1 or not isinstance(outputs[0], Mapping):
        return None
    if output_shape == "subscription_scope_identity":
        return subscription_scope_artifact(
            output=cast(Mapping[str, object], outputs[0]),
            evidence_refs=cast(list[str], evidence_refs),
            locale=locale,
            verified=_semantic_is_verified(semantic),
        )
    if output_shape == "subscription_service_health":
        return _service_health_artifact(
            output=cast(Mapping[str, object], outputs[0]),
            evidence_refs=cast(list[str], evidence_refs),
            locale=locale,
            verified=_semantic_is_verified(semantic),
        )
    semantics = _presentation_semantics(context.get("presentation_semantics"))
    if context.get("presentation_semantics") is not None and semantics is None:
        return None
    semantic_shape, semantic_fields = semantics or (None, {})
    output = cast(Mapping[str, object], outputs[0])
    if isinstance(output.get("incident_profile"), Mapping):
        return None
    if output_shape == "target_error_activity_correlation":
        blocks = _error_activity_blocks(
            output,
            locale=locale,
            evidence_refs=evidence_refs,
            verified=_semantic_is_verified(semantic),
        )
        if blocks is None:
            return None
        return assemble_presentation_artifact_v3(
            layout="operational_brief",
            blocks=blocks,
            evidence_refs=cast(list[str], evidence_refs[:_MAX_REFS]),
            locale=locale,
            input_kinds=(
                "verified_semantic_result",
                "presentation_context",
                "operator_locale",
            ),
        )

    if output_shape == "target_health_assessment":
        blocks = _health_blocks(
            output,
            locale=locale,
            evidence_refs=evidence_refs,
            verified=_semantic_is_verified(semantic),
        )
        if blocks is None:
            return None
        return assemble_presentation_artifact_v3(
            layout="operational_brief",
            blocks=blocks,
            evidence_refs=cast(list[str], evidence_refs[:_MAX_REFS]),
            locale=locale,
            input_kinds=(
                "verified_semantic_result",
                "presentation_context",
                "operator_locale",
            ),
        )
    shape = analyze_evidence_shape(
        output,
        verified=_semantic_is_verified(semantic),
        semantic_shape=semantic_shape,
        semantic_fields=semantic_fields,
    )
    sampling_description: str | None = None
    if output_shape == "target_resource_metric_series" and shape.records:
        sampling = _metric_series_sampling(shape)
        if sampling is None:
            return None
        source_count, displayed_count, strategy = sampling
        sampling_description = _metric_series_sampling_description(
            source_count=source_count,
            displayed_count=displayed_count,
            strategy=strategy,
            korean=locale.casefold().startswith("ko"),
        )
    intent = _presentation_intent(
        operation=cast(str, operation),
        output_shape=cast(str, output_shape),
        shape=shape,
    )
    decision = plan_presentation(intent=intent, shape=shape)
    block = _compile_block(
        decision.kind,
        reason_code=decision.reason_code,
        shape=shape,
        locale=locale,
        evidence_refs=cast(list[object], evidence_refs),
        preferred_columns=(_preferred_columns(cast(str, output_shape))),
        time_series_description=sampling_description,
        visualization=decision.visualization,
    )
    if block is None:
        return None
    blocks = [block]
    if output_shape == "resource_target_candidates":
        overview = _target_candidates_overview(
            output,
            locale=locale,
            evidence_refs=evidence_refs,
        )
        if overview is None:
            return None
        blocks.insert(0, overview)
    limitation = _limitation_block(output, shape=shape, locale=locale, evidence_refs=evidence_refs)
    if limitation is not None and block["slot_id"] != "limitations":
        blocks.append(limitation)
    layout = _layout_for_output_shape(cast(str, output_shape))
    if layout is None:
        return cast(
            JsonObject,
            {
                "schema_version": 2,
                "layout": "stack",
                "evidence_refs": evidence_refs[:_MAX_REFS],
                "blocks": blocks,
            },
        )
    return assemble_presentation_artifact_v3(
        layout=layout,
        blocks=blocks,
        evidence_refs=cast(list[str], evidence_refs[:_MAX_REFS]),
        locale=locale,
        input_kinds=(
            "verified_semantic_result",
            "presentation_context",
            "operator_locale",
        ),
    )


def _layout_for_output_shape(output_shape: str) -> PresentationLayout | None:
    if output_shape in {"ontology_manifest", "ontology_relationships"}:
        return "markdown_document"
    return None


def _presentation_intent(
    *,
    operation: str,
    output_shape: str,
    shape: EvidenceShape,
) -> PresentationIntent:
    if shape.semantic_shape is SemanticShape.CORRELATION:
        return PresentationIntent.CORRELATION
    if shape.semantic_shape is SemanticShape.CATEGORICAL_MATRIX:
        return PresentationIntent.MATRIX
    if output_shape == "target_resource_metric_series":
        return PresentationIntent.TREND
    if output_shape == "temporal_comparison":
        return (
            PresentationIntent.TREND if len(shape.records) >= 3 else PresentationIntent.COMPARISON
        )
    if operation == "compare":
        return PresentationIntent.COMPARISON
    if output_shape == "aggregation_table":
        if shape.threshold_field is not None:
            return PresentationIntent.THRESHOLD
        if shape.numerator_field is not None and shape.denominator_field is not None:
            return PresentationIntent.COVERAGE
        if shape.category_field is not None and shape.current_field is not None:
            return PresentationIntent.DISTRIBUTION
        return PresentationIntent.SUMMARY if len(shape.records) == 1 else PresentationIntent.EXACT
    if output_shape == "topology_graph" and shape.timestamp_field is not None:
        return PresentationIntent.CHRONOLOGY
    if output_shape == "resource_event_history":
        return PresentationIntent.CHRONOLOGY
    if output_shape == "resource_state_transitions":
        return PresentationIntent.CHRONOLOGY
    if output_shape == "subscription_service_health":
        return PresentationIntent.CHRONOLOGY
    if output_shape in {
        "resource_health_list",
        "resource_list",
        "resource_metric_list",
        "property_filtered_resources",
        "resource_state_list",
        "resource_target_candidates",
    }:
        return PresentationIntent.EXACT
    return PresentationIntent.EXACT


def _preferred_columns(output_shape: str) -> tuple[str, ...]:
    return {
        "resource_event_history": _RESOURCE_EVENT_COLUMNS,
        "resource_health_list": _RESOURCE_HEALTH_COLUMNS,
        "resource_metric_list": _RESOURCE_METRIC_COLUMNS,
        "resource_state_list": _RESOURCE_STATE_COLUMNS,
        "resource_state_transitions": (
            "effective_at",
            "name",
            "state_type",
            "from_state",
            "to_state",
            "source_identity",
        ),
        "resource_target_candidates": ("name", "type"),
        "subscription_service_health": _SERVICE_HEALTH_COLUMNS,
        "target_ingress_configuration": _RESOURCE_INGRESS_COLUMNS,
        "target_resource_metric": _RESOURCE_METRIC_COLUMNS,
        "target_resource_metric_series": ("timestamp", "value", "unit", "metric"),
    }.get(output_shape, ())


def _semantic_is_verified(semantic: Mapping[str, object]) -> bool:
    completed = semantic.get("checks_completed")
    total = semantic.get("checks_total")
    return (
        semantic.get("disposition") == "answered"
        and isinstance(completed, int)
        and not isinstance(completed, bool)
        and isinstance(total, int)
        and not isinstance(total, bool)
        and completed == total
        and total > 0
    )


__all__ = ["compile_presentation_artifact_v2"]
