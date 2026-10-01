"""Render recently observed Resource changes from verified rows and reviewed notices.

The answer lists each verified change as it was observed, reports rows it cannot trust as
unresolved evidence, states how many changed Resources a bounded read did not list when the
reader counted them, and restates completeness and limitations; it adds no fact of its own.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from fdai.core.ontology_platform.recent_resource_changes import (
    ACTIVITY_LOG_RESOURCE_CHANGE_SOURCE_IDENTITY,
    ARG_RESOURCE_CHANGE_SOURCE_IDENTITY,
)

from .semantic_answer_presentation import (
    authority_line,
    completeness_text,
    condition_rows,
    inline_code,
    readable_timestamp,
)
from .semantic_source_limitations import source_limitation_text


def render_resource_change_answer(
    outputs: list[dict[str, object]],
    *,
    korean: bool,
    output_shape: str | None,
) -> str | None:
    if output_shape != "resource_changes" or len(outputs) != 1:
        return None
    output = outputs[0]
    rows = condition_rows(output)
    if rows is None:
        verified_rows: list[Mapping[str, object]] = []
        returned_rows = output.get("returned_rows")
        unresolved = returned_rows if isinstance(returned_rows, int) else 1
    else:
        verified_rows = [row for row in rows if verified_resource_change_row(row)]
        unresolved = len(rows) - len(verified_rows)
    complete = output.get("source_complete") is True
    limitation = output.get("source_truncation_reason")
    lines = [
        "## 최근 관측된 리소스 변경" if korean else "## Recently observed resource changes",
        "",
    ]
    for row in verified_rows[:20]:
        subject = row.get("subject_name") or str(row.get("subject_ref") or "").rsplit("/", 1)[-1]
        operation = row.get("operation") or row.get("mutation_kind") or "change"
        status = row.get("operation_status")
        occurred_at = row.get("occurred_at")
        prefix = f"- `{inline_code(str(subject or 'resource unavailable'))}`: "
        lines.append(
            prefix
            + f"`{inline_code(str(operation))}`"
            + (f" / `{inline_code(str(status))}`" if status else "")
            + f" ({readable_timestamp(str(occurred_at)) if occurred_at else 'time unavailable'})"
        )
    if not verified_rows:
        lines.append(
            "- 검증된 전체 범위에서 최근 리소스 변경을 찾지 못했습니다."
            if korean and complete
            else "- 현재 확인 가능한 범위에서는 최근 리소스 변경을 찾지 못했습니다."
            if korean
            else "- No recent Resource changes were found in the complete verified scope."
            if complete
            else "- No recent Resource changes were found in the currently available scope."
        )
    if unresolved:
        lines.append(
            f"- 미확정 변경 근거: {unresolved}건"
            if korean
            else f"- Unresolved change evidence: {unresolved}"
        )
    source_total = output.get("source_total_rows")
    listed = min(len(verified_rows), 20)
    if (
        isinstance(source_total, int)
        and not isinstance(source_total, bool)
        and source_total > listed + unresolved
    ):
        remaining = source_total - listed - unresolved
        continuation_ref = output.get("continuation_ref")
        lines.append(
            f"- 이 기간에 변경된 리소스 {source_total}개 중 {remaining}개는 목록에 없습니다."
            if korean
            else f"- {remaining} of the {source_total} changed resources in this window "
            "are not listed."
        )
        if isinstance(continuation_ref, str) and continuation_ref:
            lines.append(
                f"- 계속하려면 continuation reference "
                f"`{inline_code(continuation_ref)}`를 사용하세요."
                if korean
                else f"- To continue, request the next page with continuation reference "
                f"`{inline_code(continuation_ref)}`."
            )
    lines.append(
        f"- 원본 완전성: {completeness_text(complete, korean=True)}"
        if korean
        else f"- Source completeness: {completeness_text(complete, korean=False)}"
    )
    if isinstance(limitation, str) and limitation:
        lines.append(
            f"- 제한 사항: {source_limitation_text(limitation, korean=korean)}"
            if korean
            else f"- Limitation: {source_limitation_text(limitation, korean=korean)}"
        )
    lines.extend(["", authority_line(korean=korean)])
    return "\n".join(lines)


def verified_resource_change_row(row: Mapping[str, object]) -> bool:
    occurred_at = row.get("occurred_at")
    source_identity = row.get("source_identity")
    observation_kind = row.get("observation_kind")
    operation = row.get("operation")
    provider_change = (
        source_identity == ARG_RESOURCE_CHANGE_SOURCE_IDENTITY
        and observation_kind in {"full", "tombstone"}
    ) or (
        source_identity == ACTIVITY_LOG_RESOURCE_CHANGE_SOURCE_IDENTITY
        and isinstance(operation, str)
        and bool(operation)
        and observation_kind in {"partial", "change_hint", "tombstone"}
    )
    if (
        row.get("execution_authority") is not False
        or row.get("mutation_kind") not in {"upsert", "delete"}
        or not provider_change
        or not isinstance(source_identity, str)
        or not source_identity
        or not isinstance(occurred_at, str)
    ):
        return False
    try:
        parsed = datetime.fromisoformat(occurred_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


__all__ = ["render_resource_change_answer", "verified_resource_change_row"]
