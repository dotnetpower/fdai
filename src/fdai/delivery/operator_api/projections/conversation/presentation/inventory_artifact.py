"""Compile inventory evidence into bounded presentation blocks."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from fdai.delivery.operator_api.projections.conversation.presentation.artifact_common import (
    MAX_TABLE_ROWS,
    block,
    chart_item,
    mapping_rows,
    nonnegative_int,
    nonnegative_int_or_none,
    summary_item,
    text,
    verification_label,
)
from fdai.delivery.operator_api.projections.conversation.presentation.contract import (
    PresentationPlacement,
)

_MAX_DISTRIBUTION_ITEMS = 16


def inventory_blocks(
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
    resources = mapping_rows(result.get("resources"))
    raw_counts = result.get("matched_type_counts")
    counts = raw_counts if isinstance(raw_counts, Mapping) else {}
    blocks: list[dict[str, object]] = []
    for placement in placements:
        rendered: dict[str, object] | None
        if placement.slot_id == "overview":
            rendered = _summary(placement, result, resources, counts, refs, korean)
        elif placement.slot_id == "limitations":
            rendered = _limitations(placement, result, refs, korean, verification_status)
        elif placement.slot_id == "records":
            rendered = _records(placement, resources, refs, korean)
        elif placement.slot_id == "distribution":
            rendered = _distribution(placement, counts, refs, korean)
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
    resources: Sequence[Mapping[str, Any]],
    counts: Mapping[object, object],
    refs: tuple[str, ...],
    korean: bool,
) -> dict[str, object]:
    matched_count = nonnegative_int(result.get("matched_count")) or len(resources)
    return block(
        placement,
        kind="summary",
        title="Azure 인벤토리" if korean else "Azure inventory",
        refs=refs,
        data={
            "items": [
                summary_item(
                    "일치 리소스" if korean else "Matched resources",
                    matched_count,
                    "neutral",
                ),
                summary_item(
                    "리소스 형식" if korean else "Resource types",
                    len(counts),
                    "neutral",
                ),
            ]
        },
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
            "인벤토리 snapshot이 잘려 추가 리소스가 있을 수 있습니다."
            if korean
            else "The inventory snapshot is truncated, so additional resources may exist."
        )
    if result.get("status") == "partial":
        lines.append(
            "확인된 리소스는 표시하지만 전체 범위는 확정되지 않았습니다."
            if korean
            else "Observed resources are shown, but complete scope coverage is unconfirmed."
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
        title="인벤토리 범위 제한" if korean else "Inventory limitations",
        refs=refs,
        data={"tone": "warning", "lines": lines},
    )


def _records(
    placement: PresentationPlacement,
    resources: Sequence[Mapping[str, Any]],
    refs: tuple[str, ...],
    korean: bool,
) -> dict[str, object] | None:
    if not resources:
        return None
    rows = [
        {
            "name": text(item.get("name") or "unknown"),
            "type": text(item.get("type") or "unknown"),
            "status": text(item.get("status") or "unknown"),
            "location": text(item.get("location") or "unknown"),
            "resource_group": text(item.get("resource_group") or "unknown"),
        }
        for item in resources[:MAX_TABLE_ROWS]
    ]
    labels = (
        (
            ("name", "이름"),
            ("type", "형식"),
            ("status", "상태"),
            ("location", "위치"),
            ("resource_group", "리소스 그룹"),
        )
        if korean
        else (
            ("name", "Name"),
            ("type", "Type"),
            ("status", "Status"),
            ("location", "Location"),
            ("resource_group", "Resource group"),
        )
    )
    return block(
        placement,
        kind="table" if placement.component == "data_table" else "list",
        title="리소스" if korean else "Resources",
        refs=refs,
        data={
            "columns": [{"key": key, "label": label} for key, label in labels],
            "rows": rows,
            "status_key": "status",
        },
    )


def _distribution(
    placement: PresentationPlacement,
    counts: Mapping[object, object],
    refs: tuple[str, ...],
    korean: bool,
) -> dict[str, object] | None:
    items = []
    for label, raw_value in counts.items():
        value = nonnegative_int_or_none(raw_value)
        if value is not None:
            items.append(chart_item(text(label), value, "neutral"))
        if len(items) == _MAX_DISTRIBUTION_ITEMS:
            break
    if not items:
        return None
    title = "리소스 형식별 분포" if korean else "Resources by type"
    if placement.component == "data_table":
        return block(
            placement,
            kind="table",
            title=title,
            refs=refs,
            data={
                "columns": [
                    {"key": "type", "label": "형식" if korean else "Type"},
                    {"key": "count", "label": "개수" if korean else "Count"},
                ],
                "rows": [
                    {"type": str(item["label"]), "count": str(item["value"])} for item in items
                ],
                "status_key": None,
            },
        )
    return block(
        placement,
        kind="bar",
        title=title,
        refs=refs,
        data={"items": items},
    )


def _evidence(
    placement: PresentationPlacement,
    result: Mapping[str, Any],
    refs: tuple[str, ...],
    korean: bool,
    verification_status: str,
) -> dict[str, object]:
    return block(
        placement,
        kind="evidence",
        title="근거 및 snapshot" if korean else "Evidence and snapshot",
        refs=refs,
        data={
            "items": [
                {
                    "label": "근거" if korean else "Evidence",
                    "value": text(result.get("source") or "inventory"),
                },
                {
                    "label": "스냅샷" if korean else "Snapshot",
                    "value": text(result.get("snapshot_at") or "unknown"),
                },
                {
                    "label": "최신성" if korean else "Freshness",
                    "value": text(result.get("freshness") or "unknown"),
                },
                {
                    "label": "검증" if korean else "Verification",
                    "value": verification_label(verification_status, korean=korean),
                },
            ]
        },
    )
