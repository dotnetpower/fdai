"""Reviewed non-model axes for FDAI presentation quality assurance."""

from __future__ import annotations

from typing import Any


def _metric(
    name: str,
    definition: str,
    aggregation: str,
    target: float | int,
) -> dict[str, Any]:
    return {
        "name": name,
        "definition": definition,
        "aggregation": aggregation,
        "promotion_target": target,
    }


PRESENTATION_EVALUATION_AXES = {
    "viewport_classes": [
        "desktop_1440x900",
        "constrained_desktop_993x641",
        "mobile_390x844",
    ],
    "evidence_states": [
        "verified_complete",
        "verified_partial",
        "verified_empty",
        "unavailable",
        "unverified",
    ],
    "content_stress": [
        "english",
        "korean",
        "long_identifier",
        "timestamp",
        "mixed_numeric_units",
    ],
}

PRESENTATION_METRICS = (
    _metric(
        "presentation_artifact_schema_validity",
        "Presentation artifacts passing the exact Operator and Console schema contract.",
        "validity",
        1.0,
    ),
    _metric(
        "presentation_kind_accuracy",
        "Renderer-neutral block kind matches verified question intent and evidence shape.",
        "accuracy",
        1.0,
    ),
    _metric(
        "visualization_kind_accuracy",
        "Chart or non-chart visualization is appropriate for the verified semantic shape.",
        "accuracy",
        1.0,
    ),
    _metric(
        "semantic_shape_fidelity",
        "Rendered dimensions, measures, roles, and relationships match presentation semantics.",
        "accuracy",
        1.0,
    ),
    _metric(
        "presentation_exact_value_fidelity",
        "Every displayed value equals the verified source value after allowed formatting.",
        "accuracy",
        1.0,
    ),
    _metric(
        "presentation_invented_value_count",
        "Displayed values or categories absent from the verified artifact.",
        "count",
        0,
    ),
    _metric(
        "exact_table_fallback_coverage",
        "Charts requiring exact-value access include a complete accessible table fallback.",
        "coverage",
        1.0,
    ),
    _metric(
        "presentation_evidence_reference_integrity",
        "Block evidence references are a valid subset of verified answer references.",
        "validity",
        1.0,
    ),
    _metric(
        "unit_and_axis_label_accuracy",
        "Units, axes, series, categories, baselines, and thresholds are correctly labeled.",
        "accuracy",
        1.0,
    ),
    _metric(
        "temporal_visual_order_accuracy",
        "Timelines and time series preserve verified chronological order.",
        "accuracy",
        1.0,
    ),
    _metric(
        "truncation_disclosure_recall",
        "Every sampled, bounded, partial, or truncated view discloses its coverage limitation.",
        "recall",
        1.0,
    ),
    _metric(
        "empty_unavailable_state_accuracy",
        "Verified empty, unavailable, partial, failed, and unverified states remain distinct.",
        "accuracy",
        1.0,
    ),
    _metric(
        "presentation_hierarchy_accuracy",
        "Primary result, supporting evidence, limitations, and metadata occupy "
        "their governed roles.",
        "accuracy",
        1.0,
    ),
    _metric(
        "responsive_policy_coverage",
        "Every presentation block has a tested reflow, scroll, or stack policy.",
        "coverage",
        1.0,
    ),
    _metric(
        "accessibility_fallback_coverage",
        "Every presentation block has a tested semantic accessibility fallback.",
        "coverage",
        1.0,
    ),
    _metric(
        "non_color_status_cue_coverage",
        "Every status encoded by color also has text, shape, or semantic markup.",
        "coverage",
        1.0,
    ),
    _metric(
        "keyboard_focus_coverage",
        "Every interactive visualization and disclosure has a visible keyboard focus path.",
        "coverage",
        1.0,
    ),
    _metric(
        "reduced_motion_compliance",
        "Presentation remains understandable when reduced motion is requested.",
        "validity",
        1.0,
    ),
    _metric(
        "viewport_overflow_failure_rate",
        "Required viewport scenarios with clipped, overlapping, or page-wide overflow.",
        "rate",
        0.0,
    ),
    _metric(
        "presentation_text_fallback_precision",
        "Structured artifacts replace answer text only when they add a non-overview result.",
        "precision",
        1.0,
    ),
    _metric(
        "locale_layout_scenario_pass_rate",
        "English, Korean, long identifiers, and timestamps pass required viewport scenarios.",
        "pass_rate",
        1.0,
    ),
)
