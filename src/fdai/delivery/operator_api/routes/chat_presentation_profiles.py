"""Value-free presentation profiles derived from verified chat evidence shapes."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from fdai.core.conversation.answer_plan import AnswerFormat, AnswerPlan
from fdai.delivery.operator_api.routes.chat_presentation_contract import (
    PresentationComponent,
    PresentationEmphasis,
    PresentationProfile,
    PresentationRationale,
    PresentationSlot,
    record_count_bucket,
)
from fdai.delivery.operator_api.routes.chat_subscription_health import (
    subscription_health_findings,
)

_SPECIAL_INVENTORY_RESULTS = (
    "scope_counts",
    "state_coverage",
    "inventory_coverage",
)


def presentation_profile(
    view_context: Mapping[str, object],
    plan: AnswerPlan,
) -> PresentationProfile | None:
    """Project one supported tool result into a bounded value-free shape."""

    evidence = view_context.get("_tool_evidence")
    if not isinstance(evidence, Mapping):
        return None
    tool = evidence.get("tool")
    if tool == "query_subscription_health":
        return _subscription_health_profile(evidence, plan)
    if tool == "query_inventory":
        return _inventory_profile(evidence, plan)
    return None


def _subscription_health_profile(
    evidence: Mapping[str, object],
    plan: AnswerPlan,
) -> PresentationProfile | None:
    result = evidence.get("result")
    if not isinstance(result, Mapping) or result.get("status") not in {"matched", "partial"}:
        return None
    findings = subscription_health_findings(evidence)
    metrics = _mapping_rows(result.get("metric_observations"))
    metric_checked = _nonnegative_int(result.get("metric_checked"))
    metric_unavailable = _nonnegative_int(result.get("metric_unavailable"))
    unsupported = _nonnegative_int(result.get("unsupported_metric_resources"))
    source_unavailable = (
        _nonnegative_int(result.get("resource_health_unavailable"))
        + _nonnegative_int(result.get("service_health_unavailable"))
        + metric_unavailable
    )
    truncated = result.get("truncated") is True
    limited = (
        result.get("status") == "partial" or truncated or source_unavailable > 0 or unsupported > 0
    )
    coverage_state: Literal["complete", "limited", "unknown"] = "limited" if limited else "complete"
    slots: list[PresentationSlot] = [
        _slot(
            "overview",
            "summary",
            ("summary_band",),
            "summary_band",
            "primary",
            False,
            False,
            1,
            coverage_state,
        )
    ]
    if limited:
        slots.append(
            _slot(
                "limitations",
                "limitation",
                ("callout",),
                "callout",
                "primary",
                False,
                False,
                1,
                coverage_state,
            )
        )
    if findings:
        slots.append(
            _slot(
                "findings",
                "attention",
                ("status_table", "detail_list"),
                "status_table",
                "primary",
                False,
                False,
                len(findings),
                coverage_state,
            )
        )
    metrics_requested = result.get("metrics_requested") is not False
    if metrics_requested and (metric_checked or metric_unavailable or unsupported):
        coverage_components: tuple[PresentationComponent, ...] = (
            ("data_table",) if plan.format is AnswerFormat.TABLE else ("coverage_bar", "data_table")
        )
        slots.append(
            _slot(
                "coverage",
                "coverage",
                coverage_components,
                coverage_components[0],
                "secondary",
                False,
                False,
                3,
                coverage_state,
            )
        )
    if metrics:
        metric_components: tuple[PresentationComponent, ...] = (
            ("data_table",)
            if plan.format is AnswerFormat.TABLE
            else ("threshold_table", "data_table")
        )
        slots.append(
            _slot(
                "metrics",
                "detail",
                metric_components,
                metric_components[0],
                "supporting",
                len(metrics) > 5,
                True,
                len(metrics),
                coverage_state,
            )
        )
    slots.append(
        _slot(
            "evidence",
            "provenance",
            ("evidence_footer",),
            "evidence_footer",
            "supporting",
            False,
            False,
            1,
            coverage_state,
        )
    )
    return PresentationProfile(kind="subscription_health", slots=tuple(slots))


def _inventory_profile(
    evidence: Mapping[str, object],
    plan: AnswerPlan,
) -> PresentationProfile | None:
    result = evidence.get("result")
    if not isinstance(result, Mapping) or result.get("status") not in {"matched", "partial"}:
        return None
    if result.get("query_source") == "activity" or any(
        result.get(key) is True for key in _SPECIAL_INVENTORY_RESULTS
    ):
        return None
    resources = _mapping_rows(result.get("resources"))
    counts = result.get("matched_type_counts")
    category_count = len(counts) if isinstance(counts, Mapping) else 0
    query_kind = str(result.get("query_kind") or "list")
    limited = result.get("status") == "partial" or result.get("truncated") is True
    coverage_state: Literal["complete", "limited", "unknown"] = "limited" if limited else "complete"
    slots: list[PresentationSlot] = [
        _slot(
            "overview",
            "summary",
            ("summary_band",),
            "summary_band",
            "primary",
            False,
            False,
            1,
            coverage_state,
        )
    ]
    if limited:
        slots.append(
            _slot(
                "limitations",
                "limitation",
                ("callout",),
                "callout",
                "primary",
                False,
                False,
                1,
                coverage_state,
            )
        )
    if query_kind == "types" and category_count >= 2:
        slots.append(
            _slot(
                "distribution",
                "distribution",
                ("bar_chart", "data_table"),
                "bar_chart" if plan.format is not AnswerFormat.TABLE else "data_table",
                "primary",
                False,
                False,
                category_count,
                coverage_state,
            )
        )
    elif resources:
        slots.append(
            _slot(
                "records",
                "comparison",
                ("data_table", "detail_list"),
                "data_table",
                "primary",
                False,
                False,
                len(resources),
                coverage_state,
            )
        )
    else:
        return None
    slots.append(
        _slot(
            "evidence",
            "provenance",
            ("evidence_footer",),
            "evidence_footer",
            "supporting",
            False,
            False,
            1,
            coverage_state,
        )
    )
    return PresentationProfile(kind="inventory", slots=tuple(slots))


def _slot(
    slot_id: str,
    role: PresentationRationale,
    allowed_components: tuple[PresentationComponent, ...],
    default_component: PresentationComponent,
    default_emphasis: PresentationEmphasis,
    default_collapsed: bool,
    can_collapse: bool,
    count: int,
    coverage_state: Literal["complete", "limited", "unknown"],
) -> PresentationSlot:
    return PresentationSlot(
        slot_id=slot_id,
        role=role,
        allowed_components=allowed_components,
        default_component=default_component,
        default_emphasis=default_emphasis,
        default_collapsed=default_collapsed,
        can_collapse=can_collapse,
        record_count_bucket=record_count_bucket(count),
        coverage_state=coverage_state,
    )


def _mapping_rows(value: object) -> list[Mapping[str, object]]:
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


def _nonnegative_int(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


__all__ = ["presentation_profile"]
