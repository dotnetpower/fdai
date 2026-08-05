"""Compile subscription-health evidence into bounded presentation blocks."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from fdai.delivery.operator_api.routes.chat_presentation_artifact_common import (
    MAX_TABLE_ROWS,
    block,
    chart_item,
    mapping_rows,
    nonnegative_int,
    number_text,
    summary_item,
    text,
    verification_label,
)
from fdai.delivery.operator_api.routes.chat_presentation_contract import PresentationPlacement
from fdai.delivery.operator_api.routes.chat_subscription_health import (
    subscription_health_findings,
)


def subscription_health_blocks(
    evidence: Mapping[str, Any],
    placements: Sequence[PresentationPlacement],
    *,
    refs: tuple[str, ...],
    korean: bool,
    verification_status: str,
) -> list[dict[str, object]]:
    result = evidence.get("result")
    if not isinstance(result, Mapping):
        return []
    findings = subscription_health_findings(evidence)
    observations = mapping_rows(result.get("metric_observations"))
    blocks: list[dict[str, object]] = []
    for placement in placements:
        rendered: dict[str, object] | None
        if placement.slot_id == "overview":
            rendered = _summary(placement, result, findings, refs, korean)
        elif placement.slot_id == "limitations":
            rendered = _limitations(placement, result, refs, korean, verification_status)
        elif placement.slot_id == "findings":
            rendered = _findings(placement, findings, refs, korean)
        elif placement.slot_id == "coverage":
            rendered = _coverage(placement, result, refs, korean)
        elif placement.slot_id == "metrics":
            rendered = _metrics(placement, observations, refs, korean)
        elif placement.slot_id == "evidence":
            rendered = _evidence(placement, result, refs, korean, verification_status)
        else:
            return []
        if rendered is None:
            return []
        blocks.append(rendered)
    return blocks


def _summary(
    placement: PresentationPlacement,
    result: Mapping[str, Any],
    findings: Sequence[Mapping[str, Any]],
    refs: tuple[str, ...],
    korean: bool,
) -> dict[str, object]:
    items = [
        summary_item(
            "확인 리소스" if korean else "Resources checked",
            nonnegative_int(result.get("resource_count")),
            "neutral",
        ),
        summary_item(
            "상태 이상 후보" if korean else "Health candidates",
            len(findings),
            "attention" if findings else "positive",
        ),
    ]
    if result.get("metrics_requested") is not False:
        items.append(
            summary_item(
                "메트릭 확인" if korean else "Metrics checked",
                nonnegative_int(result.get("metric_checked")),
                "neutral",
            )
        )
    return block(
        placement,
        kind="summary",
        title="Azure 범위 상태" if korean else "Azure scope health",
        refs=refs,
        data={"items": items},
    )


def _limitations(
    placement: PresentationPlacement,
    result: Mapping[str, Any],
    refs: tuple[str, ...],
    korean: bool,
    verification_status: str,
) -> dict[str, object] | None:
    lines: list[str] = []
    if result.get("truncated") is True:
        lines.append(
            "조회 한도에 도달해 추가 리소스나 후보가 있을 수 있습니다."
            if korean
            else "The query limit was reached, so additional resources or candidates may exist."
        )
    unavailable = (
        nonnegative_int(result.get("resource_health_unavailable"))
        + nonnegative_int(result.get("service_health_unavailable"))
        + nonnegative_int(result.get("metric_unavailable"))
    )
    unsupported = nonnegative_int(result.get("unsupported_metric_resources"))
    if unavailable or unsupported or result.get("status") == "partial":
        lines.append(
            (
                f"조회 불가 {unavailable}개와 메트릭 미지원 {unsupported}개는 전체 정상 상태를 "
                "확정하지 못하는 범위입니다."
            )
            if korean
            else (
                f"{unavailable} unavailable check(s) and {unsupported} unsupported metric "
                "resource(s) prevent confirmation of complete normal operation."
            )
        )
    if verification_status == "unverified":
        lines.append(
            "확인된 사실은 표시하지만 전체 결론은 검증되지 않았습니다."
            if korean
            else "Available facts are shown, but the overall conclusion is unverified."
        )
    if not lines:
        return None
    return block(
        placement,
        kind="callout",
        title="관측 범위 제한" if korean else "Observation limitations",
        refs=refs,
        data={"tone": "warning", "lines": lines},
    )


def _findings(
    placement: PresentationPlacement,
    findings: Sequence[Mapping[str, Any]],
    refs: tuple[str, ...],
    korean: bool,
) -> dict[str, object] | None:
    if not findings:
        return None
    rows = [
        {
            "resource": text(item.get("resource_name") or "unknown"),
            "status": text(item.get("status") or "unknown"),
            "type": text(item.get("resource_type") or "unknown"),
            "resource_group": text(item.get("resource_group") or "unknown"),
            "cause": text(item.get("reason") or item.get("title") or "unknown"),
        }
        for item in findings[:MAX_TABLE_ROWS]
    ]
    return block(
        placement,
        kind="table" if placement.component == "status_table" else "list",
        title="상태 이상 후보" if korean else "Health candidates",
        refs=refs,
        data={
            "columns": _finding_columns(korean),
            "rows": rows,
            "status_key": "status",
        },
    )


def _coverage(
    placement: PresentationPlacement,
    result: Mapping[str, Any],
    refs: tuple[str, ...],
    korean: bool,
) -> dict[str, object]:
    items = [
        chart_item(
            "확인됨" if korean else "Checked",
            nonnegative_int(result.get("metric_checked")),
            "positive",
        ),
        chart_item(
            "조회 불가" if korean else "Unavailable",
            nonnegative_int(result.get("metric_unavailable")),
            "warning",
        ),
        chart_item(
            "미지원" if korean else "Unsupported",
            nonnegative_int(result.get("unsupported_metric_resources")),
            "neutral",
        ),
    ]
    title = "메트릭 관측 범위" if korean else "Metric observation coverage"
    if placement.component == "data_table":
        return block(
            placement,
            kind="table",
            title=title,
            refs=refs,
            data={
                "columns": [
                    {"key": "state", "label": "구분" if korean else "State"},
                    {"key": "count", "label": "개수" if korean else "Count"},
                ],
                "rows": [
                    {"state": str(item["label"]), "count": str(item["value"])} for item in items
                ],
                "status_key": "state",
            },
        )
    return block(
        placement,
        kind="coverage",
        title=title,
        refs=refs,
        data={"items": items},
    )


def _metrics(
    placement: PresentationPlacement,
    observations: Sequence[Mapping[str, Any]],
    refs: tuple[str, ...],
    korean: bool,
) -> dict[str, object] | None:
    if not observations:
        return None
    rows = [
        {
            "resource": text(item.get("resource_name") or "unknown"),
            "metric": text(item.get("metric") or "unknown"),
            "value": number_text(item.get("value")),
            "threshold": f"{text(item.get('comparison') or 'unknown')} "
            f"{number_text(item.get('threshold'))}",
            "result": ("임계값 초과" if korean else "Threshold exceeded")
            if item.get("anomalous") is True
            else ("임계값 이내" if korean else "Within threshold"),
        }
        for item in observations[:MAX_TABLE_ROWS]
    ]
    return block(
        placement,
        kind="table" if placement.component == "data_table" else "threshold_table",
        title="메트릭 상세" if korean else "Metric details",
        refs=refs,
        data={
            "columns": _metric_columns(korean),
            "rows": rows,
            "status_key": "result",
        },
    )


def _evidence(
    placement: PresentationPlacement,
    result: Mapping[str, Any],
    refs: tuple[str, ...],
    korean: bool,
    verification_status: str,
) -> dict[str, object]:
    items = [
        {
            "label": "근거" if korean else "Evidence",
            "value": text(result.get("source") or "Azure read providers"),
        },
        {
            "label": "관찰 시각" if korean else "Observed",
            "value": text(result.get("observed_at") or "unknown"),
        },
        {
            "label": "검증" if korean else "Verification",
            "value": verification_label(verification_status, korean=korean),
        },
    ]
    return block(
        placement,
        kind="evidence",
        title="근거 및 관찰 범위" if korean else "Evidence and observation",
        refs=refs,
        data={"items": items},
    )


def _finding_columns(korean: bool) -> list[dict[str, str]]:
    labels = (
        (
            ("resource", "리소스"),
            ("status", "상태"),
            ("type", "형식"),
            ("resource_group", "리소스 그룹"),
            ("cause", "원인 분류"),
        )
        if korean
        else (
            ("resource", "Resource"),
            ("status", "Status"),
            ("type", "Type"),
            ("resource_group", "Resource group"),
            ("cause", "Cause"),
        )
    )
    return [{"key": key, "label": label} for key, label in labels]


def _metric_columns(korean: bool) -> list[dict[str, str]]:
    labels = (
        (
            ("resource", "리소스"),
            ("metric", "메트릭"),
            ("value", "현재 값"),
            ("threshold", "위반 조건"),
            ("result", "판정"),
        )
        if korean
        else (
            ("resource", "Resource"),
            ("metric", "Metric"),
            ("value", "Current value"),
            ("threshold", "Breach condition"),
            ("result", "Result"),
        )
    )
    return [{"key": key, "label": label} for key, label in labels]
