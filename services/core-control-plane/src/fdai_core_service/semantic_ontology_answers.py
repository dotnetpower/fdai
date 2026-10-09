"""Render verified schema answers and compact scalar data views.

Manifest answers are exclusive for their output shapes: a result that cannot be
verified renders a bounded unavailable answer instead of a generic row count.
"""

from __future__ import annotations

from collections.abc import Mapping

from fdai.shared.contracts.models import OntologyDeclarationKind

from .semantic_source_limitations import source_limitation_text
from .semantic_verified_rows import verified_scalar_count

_SOURCE_KO = (
    "- 읽기 전용 출처: 활성 온톨로지 release에 대해 역할과 목적으로 범위가 제한된 `query.manifest`."
)
_SOURCE_EN = (
    "- Read-only source: role- and purpose-scoped `query.manifest` for the active ontology release."
)


def render_ontology_schema_answer(
    outputs: list[dict[str, object]],
    *,
    korean: bool,
    output_shape: str | None,
    subject_constraints: tuple[str, ...],
) -> str | None:
    """Render one manifest declaration list or declaration count, or return ``None``."""

    if output_shape == "ontology_manifest":
        return _render_declaration_list(
            outputs,
            korean=korean,
            subject_constraints=subject_constraints,
        )
    declaration_count = _render_declaration_count(
        outputs,
        korean=korean,
        output_shape=output_shape,
        subject_constraints=subject_constraints,
    )
    if declaration_count is not None:
        return declaration_count
    return _render_scalar_count(outputs, korean=korean, output_shape=output_shape)


def _render_scalar_count(
    outputs: list[dict[str, object]],
    *,
    korean: bool,
    output_shape: str | None,
) -> str | None:
    """Render one complete ungrouped count without exposing its transport row."""

    if output_shape != "aggregation_table" or len(outputs) != 1:
        return None
    count = verified_scalar_count(outputs[0])
    if count is None:
        return None
    return "\n".join(
        (
            "## 검증된 개수" if korean else "## Verified count",
            "",
            f"**{count}개**" if korean else f"**{count}**",
            "",
            (
                "이 결과는 실행 권한을 부여하지 않습니다."
                if korean
                else "This result grants no execution authority."
            ),
        )
    )


def _render_declaration_list(
    outputs: list[dict[str, object]],
    *,
    korean: bool,
    subject_constraints: tuple[str, ...],
) -> str:
    declaration_kind = (
        _declaration_kind(subject_constraints[0]) if len(subject_constraints) == 1 else None
    )
    output = outputs[0] if len(outputs) == 1 else None
    rows = output.get("rows") if output is not None else None
    total = output.get("total_rows") if output is not None else None
    if (
        output is None
        or declaration_kind is None
        or not isinstance(rows, list)
        or not rows
        or not isinstance(total, int)
        or isinstance(total, bool)
        or total < len(rows)
        or output.get("returned_rows") != len(rows)
    ):
        return _list_unavailable(korean=korean)
    entries: list[str] = []
    for row in rows:
        values = row.get("values") if isinstance(row, Mapping) else None
        name = values.get("name") if isinstance(values, Mapping) else None
        if (
            not isinstance(values, Mapping)
            or values.get("kind") != declaration_kind.value
            or values.get("available") is not True
            or values.get("execution_authority") is not False
            or not isinstance(name, str)
            or not name.strip()
        ):
            return _list_unavailable(korean=korean)
        version = values.get("version")
        suffix = f" (v{_inline(version)})" if isinstance(version, str) and version else ""
        entries.append(f"- `{_inline(name)}`{suffix}")
    label = _declaration_label(declaration_kind)
    source_complete = output.get("source_complete") is True
    if korean:
        heading = (
            f"## 읽을 수 있는 {label} {total}개"
            if source_complete
            else f"## 확인 범위에서 읽을 수 있는 {label} {total}개"
        )
    else:
        heading = (
            f"## {total} readable {label}"
            if source_complete
            else f"## {total} readable {label} in the checked scope"
        )
    lines = [heading, "", *entries]
    if output.get("display_truncated") is True:
        lines.extend(
            [
                "",
                (
                    f"표시 한도에 따라 {len(rows)}개만 표시했습니다. "
                    "전체 목록은 기술 상세에서 확인하세요."
                    if korean
                    else (
                        f"Displayed {len(rows)} of {total} declarations within the presentation "
                        "limit. Technical details retain the bounded rows."
                    )
                ),
            ]
        )
    if not source_complete:
        limitation = output.get("source_truncation_reason")
        reason = limitation if isinstance(limitation, str) and limitation else "source_incomplete"
        lines.extend(
            [
                "",
                (
                    "일부 선언을 확인할 수 없어 전체 목록으로 해석할 수 없습니다. "
                    f"제한: {source_limitation_text(reason, korean=True)}"
                    if korean
                    else (
                        "Some declarations could not be verified, so this is not the complete "
                        f"list. Limitation: {source_limitation_text(reason, korean=False)}"
                    )
                ),
            ]
        )
    lines.extend(
        [
            "",
            _SOURCE_KO if korean else _SOURCE_EN,
            "",
            (
                "이 결과는 실행 권한을 부여하지 않습니다."
                if korean
                else "This result grants no execution authority."
            ),
        ]
    )
    return "\n".join(lines)


def _list_unavailable(*, korean: bool) -> str:
    if korean:
        return (
            "## 온톨로지 선언 목록을 확인할 수 없음\n\n"
            "- 활성 온톨로지 release의 매니페스트 결과를 검증하지 못해 선언 목록을 "
            "보고하지 않습니다.\n"
            "- 읽기 전용 출처: `query.manifest`.\n\n"
            "이 결과는 실행 권한을 부여하지 않습니다."
        )
    return (
        "## Ontology declaration list unavailable\n\n"
        "- The active ontology release manifest result could not be verified, so no "
        "declaration list is reported.\n"
        "- Read-only source: `query.manifest`.\n\n"
        "This result grants no execution authority."
    )


def _render_declaration_count(
    outputs: list[dict[str, object]],
    *,
    korean: bool,
    output_shape: str | None,
    subject_constraints: tuple[str, ...],
) -> str | None:
    """Render only complete declaration counts from the verified aggregate output."""

    if output_shape != "aggregation_table" or len(outputs) != 1 or len(subject_constraints) != 1:
        return None
    declaration_kind = _declaration_kind(subject_constraints[0])
    if declaration_kind is None:
        return None
    output = outputs[0]
    complete = output.get("source_complete") is True and output.get("display_truncated") is not True
    rows = output.get("rows")
    row = rows[0] if isinstance(rows, list) and len(rows) == 1 else None
    values = row.get("values") if isinstance(row, Mapping) else None
    group = values.get("group") if isinstance(values, Mapping) else None
    group_kind = group.get("kind") if isinstance(group, Mapping) else None
    value = values.get("value") if isinstance(values, Mapping) else None
    valid_count = (
        isinstance(values, Mapping)
        and values.get("operation") == "count"
        and group_kind in {None, declaration_kind.value}
        and isinstance(value, int)
        and not isinstance(value, bool)
        and value >= 0
    )
    if not complete or not valid_count:
        if korean:
            return (
                "## 온톨로지 선언 개수를 확인할 수 없음\n\n"
                "- 활성 온톨로지 release의 선언 매니페스트가 완전하지 않아 정확한 개수를 "
                "보고하지 않습니다.\n"
                "- 읽기 전용 출처: `query.manifest`.\n\n"
                "이 결과는 실행 권한을 부여하지 않습니다."
            )
        return (
            "## Ontology declaration count unavailable\n\n"
            "- The active ontology release manifest is incomplete, so an exact count is not "
            "reported.\n"
            "- Read-only source: `query.manifest`.\n\n"
            "This result grants no execution authority."
        )
    heading = "## 검증된 온톨로지 선언 개수" if korean else "## Verified ontology declaration count"
    return "\n".join(
        [
            heading,
            "",
            f"- {_declaration_label(declaration_kind)}: {value}",
            _SOURCE_KO if korean else _SOURCE_EN,
            "",
            (
                "각 값은 매니페스트의 서로 다른 선언 개수입니다. 이 결과는 실행 권한을 부여하지 "
                "않습니다."
                if korean
                else (
                    "Each value is the distinct declaration count from the manifest. "
                    "This result grants no execution authority."
                )
            ),
        ]
    )


def _declaration_label(declaration_kind: OntologyDeclarationKind) -> str:
    return f"{declaration_kind.value[:1].upper()}{declaration_kind.value[1:]}Types"


def _declaration_kind(subject: str) -> OntologyDeclarationKind | None:
    try:
        return OntologyDeclarationKind(subject)
    except ValueError:
        if not subject.endswith("Type"):
            return None
    try:
        return OntologyDeclarationKind(subject.removesuffix("Type").casefold())
    except ValueError:
        return None


def _inline(value: str) -> str:
    return value.replace("`", "'").replace("\r", " ").replace("\n", " ")[:256]


__all__ = ["render_ontology_schema_answer"]
