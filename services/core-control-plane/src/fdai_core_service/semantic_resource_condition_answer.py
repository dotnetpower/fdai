"""Render multi-source Resource condition answers without merging authority."""

from __future__ import annotations

from collections.abc import Mapping

from .semantic_answer_presentation import condition_rows


def render_resource_condition_answer(
    outputs: list[dict[str, object]],
    *,
    korean: bool,
    output_shape: str | None,
    measure_concepts: tuple[str, ...],
) -> str | None:
    """Render each requested condition under its own evidence family."""

    if output_shape != "resource_condition_sections" or len(outputs) != 2:
        return None
    by_node = {
        output.get("node_id"): output
        for output in outputs
        if isinstance(output.get("node_id"), str)
    }
    state_output = by_node.get("resource-condition-power")
    health_output = by_node.get("resource-condition-health")
    if not isinstance(state_output, Mapping) or not isinstance(health_output, Mapping):
        return None
    state_concepts = tuple(item for item in measure_concepts if item.startswith("resource_state."))
    health_concepts = tuple(
        item for item in measure_concepts if item.startswith("resource_health.")
    )
    if not state_concepts or not health_concepts:
        return None
    state_rows = condition_rows(state_output)
    health_rows = condition_rows(health_output)
    if state_rows is None or health_rows is None:
        return None
    sections = (
        (
            "inventory power state",
            "inventory 전원 상태",
            state_concepts,
            state_rows,
            state_output,
            "state_concept",
        ),
        (
            "Resource Health",
            "Resource Health",
            health_concepts,
            health_rows,
            health_output,
            "health_concept",
        ),
    )
    if korean:
        lines = [
            "## 리소스 상태 확인 결과",
            "",
            "요청한 상태를 서로 다른 두 authoritative source에서 독립적으로 확인했습니다.",
            "",
        ]
    else:
        lines = [
            "## Resource condition results",
            "",
            "The requested conditions were checked independently against two "
            "authoritative sources.",
            "",
        ]
    for english_source, korean_source, concepts, rows, output, concept_field in sections:
        complete = output.get("source_complete") is True
        display_complete = complete and output.get("display_truncated") is not True
        limitation = output.get("source_truncation_reason")
        source = korean_source if korean else english_source
        lines.extend([f"### {source}", ""])
        for concept in concepts:
            matches = tuple(
                row
                for row in rows
                if row.get(concept_field) == concept
                or (
                    concept_field == "health_concept"
                    and isinstance(
                        (matching_concepts := row.get("matching_health_concepts")),
                        list,
                    )
                    and concept in matching_concepts
                )
            )
            status = (
                "matched" if matches else "verified_empty" if display_complete else "unresolved"
            )
            names = tuple(
                str(name) for row in matches if isinstance((name := row.get("name")), str) and name
            )
            label = concept.rsplit(".", 1)[-1].replace("_", " ")
            lines.append(
                f"- `{label}`: `{status}`"
                + (f" - {', '.join(f'`{name}`' for name in names[:8])}" if names else "")
            )
        lines.append(
            f"- source completeness: `{'complete' if complete else 'incomplete'}`"
            if not korean
            else f"- 원본 완전성: `{'complete' if complete else 'incomplete'}`"
        )
        if isinstance(limitation, str) and limitation:
            lines.append(f"- {'제한 사항' if korean else 'limitation'}: `{limitation}`")
        if output.get("display_truncated") is True:
            lines.append(
                "- 표시 범위가 잘려 있어 보이지 않는 일치 항목을 배제할 수 없습니다."
                if korean
                else "- Display rows are truncated; unseen matches cannot be excluded."
            )
        lines.append("")
    lines.append(
        "`execution_authority=false`"
        if korean
        else "This result is read-only and has `execution_authority=false`."
    )
    return "\n".join(lines)


__all__ = ["render_resource_condition_answer"]
