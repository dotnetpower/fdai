"""Reviewed notices that say why a question's reading was held or unsupported.

A read held on its reading, such as a stated constraint the reading left out, used to show
the generic evidence hold, which told the operator that evidence was unavailable when the
question itself was not read as asked. These notices name the typed reason and the closed
constraint role or atom category from the planner. They restate the reading, never an
operational fact, and unknown codes are never shown raw.
"""

from __future__ import annotations

from collections.abc import Iterable

READING_HOLD_REASONS = frozenset(
    {
        "semantic_constraint_uncovered",
        "semantic_judgment_review_conflict",
        "semantic_judgment_review_unavailable",
        "semantic_plan_constraint_uncovered",
        "semantic_reading_ambiguous",
        "semantic_reading_continuation_required",
        "semantic_reading_limited",
        "semantic_reading_unavailable",
        "semantic_reading_unverified",
    }
)
READING_UNSUPPORTED_REASONS = frozenset({"semantic_stated_constraint_unsupported"})
_MAX_NAMED = 3
# The code families whose labels each reason's notice may name, so a clarification kind
# never reads as an unsupported atom.
_FAMILIES: dict[str, frozenset[str]] = {
    "semantic_constraint_uncovered": frozenset({"role"}),
    "semantic_plan_constraint_uncovered": frozenset({"role"}),
    "semantic_reading_ambiguous": frozenset({"kind"}),
    "semantic_reading_unavailable": frozenset({"kind"}),
    "semantic_reading_unverified": frozenset({"role", "kind"}),
    "semantic_stated_constraint_unsupported": frozenset({"atom"}),
}

# Each notice: (Korean, English). ``{detail}`` receives the reviewed labels of the codes.
_NOTICES: dict[str, tuple[str, str]] = {
    "semantic_constraint_uncovered": (
        "질문에 밝힌 조건({detail})이 해석에 반영되지 않아 요청을 보류했습니다. "
        "질문보다 넓은 범위로 답하지 않았습니다.",
        "The request was held because the reading of the question left out a stated "
        "{detail}. FDAI did not answer a broader question than the one asked.",
    ),
    "semantic_plan_constraint_uncovered": (
        "검증된 조회 계획이 질문에 밝힌 조건({detail})을 읽지 않아 요청을 보류했습니다. "
        "질문보다 넓은 범위로 답하지 않았습니다.",
        "The request was held because the verified read plan does not read the stated "
        "{detail}. FDAI did not answer a broader question than the one asked.",
    ),
    "semantic_judgment_review_conflict": (
        "질문을 독립적으로 읽은 두 결과가 서로 달라 요청을 보류했습니다.",
        "The request was held because two independent readings of the question disagreed.",
    ),
    "semantic_judgment_review_unavailable": (
        "질문 해석을 독립적으로 검토할 수 없어 요청을 보류했습니다.",
        "The request was held because the independent review of its reading was unavailable.",
    ),
    "semantic_reading_ambiguous": (
        "질문을 한 가지 뜻으로 확정할 수 없어 요청을 보류했습니다({detail}).",
        "The request was held because the question could not be settled to one reading ({detail}).",
    ),
    "semantic_reading_continuation_required": (
        "질문에 답하려면 검증된 조회가 둘 이상 필요해 요청을 보류했습니다. "
        "한 번에 한 가지씩 질문해 주세요.",
        "The request was held because answering it needs more than one verified read. "
        "Ask one part at a time.",
    ),
    "semantic_reading_limited": (
        "질문 해석에 검토된 안내로 밝힐 수 없는 제한이 있어 요청을 보류했습니다.",
        "The request was held because its reading carries a limitation that no reviewed "
        "notice can state.",
    ),
    "semantic_reading_unavailable": (
        "질문의 검증된 해석을 끝내지 못해 요청을 보류했습니다({detail}).",
        "The request was held because a verified reading of the question could not be "
        "completed ({detail}).",
    ),
    "semantic_reading_unverified": (
        "독립적인 검토에서 질문 해석이 질문과 일치하지 않아 요청을 보류했습니다({detail}).",
        "The request was held because an independent review found that the reading did not "
        "match the question ({detail}).",
    ),
    "semantic_stated_constraint_unsupported": (
        "질문에 밝힌 조건({detail})을 읽을 수 있는 검증된 조회가 아직 없어 답하지 않았습니다. "
        "더 좁은 질문에 대한 답을 대신 보여 주지 않았습니다.",
        "FDAI did not answer because no verified reader supports the stated {detail} yet, "
        "and an answer to a narrower question would not be the question asked.",
    ),
}
# Shown instead when a reason carries no code with a reviewed label.
_PLAIN_NOTICES: dict[str, tuple[str, str]] = {
    "semantic_plan_constraint_uncovered": (
        "검증된 조회 계획이 질문에 밝힌 조건을 읽지 않아 요청을 보류했습니다. "
        "질문보다 넓은 범위로 답하지 않았습니다.",
        "The request was held because the verified read plan does not read a stated "
        "condition. FDAI did not answer a broader question than the one asked.",
    ),
    "semantic_constraint_uncovered": (
        "질문에 밝힌 조건이 해석에 반영되지 않아 요청을 보류했습니다. "
        "질문보다 넓은 범위로 답하지 않았습니다.",
        "The request was held because the reading of the question left out a stated "
        "condition. FDAI did not answer a broader question than the one asked.",
    ),
    "semantic_reading_ambiguous": (
        "질문을 한 가지 뜻으로 확정할 수 없어 요청을 보류했습니다.",
        "The request was held because the question could not be settled to one reading.",
    ),
    "semantic_reading_unavailable": (
        "질문의 검증된 해석을 끝내지 못해 요청을 보류했습니다.",
        "The request was held because a verified reading of the question could not be completed.",
    ),
    "semantic_reading_unverified": (
        "독립적인 검토에서 질문 해석이 질문과 일치하지 않아 요청을 보류했습니다.",
        "The request was held because an independent review found that the reading did not "
        "match the question.",
    ),
    "semantic_stated_constraint_unsupported": (
        "질문에 밝힌 조건을 읽을 수 있는 검증된 조회가 아직 없어 답하지 않았습니다. "
        "더 좁은 질문에 대한 답을 대신 보여 주지 않았습니다.",
        "FDAI did not answer because no verified reader supports a stated condition yet, "
        "and an answer to a narrower question would not be the question asked.",
    ),
}
_ROLE_LABELS: dict[str, tuple[str, str]] = {
    "names": ("이름으로 지정한 대상", "named thing"),
    "restricts": ("제한 조건", "restriction"),
    "relates": ("관계", "relation"),
    "times": ("기간", "time period"),
    "groups": ("그룹 기준", "grouping"),
    "measures": ("측정 항목", "measure"),
    "orders": ("순서 기준", "ordering"),
    "compares": ("비교", "comparison"),
    "negates": ("부정 조건", "negation"),
    "supposes": ("가정", "hypothetical premise"),
    "quantifies": ("수량 조건", "quantity"),
}
# Clarification and data codes, keyed by the code's kind before any value.
_KIND_LABELS: dict[str, tuple[str, str]] = {
    "competing_reading": ("해석이 둘 이상입니다", "the question has competing readings"),
    "unused_mention": (
        "질문에 나온 대상이 해석에 쓰이지 않았습니다",
        "a named thing has no place in the reading",
    ),
    "anchor_not_found": (
        "이름으로 지정한 리소스를 찾지 못했습니다",
        "a named resource was not found",
    ),
    "anchor_ambiguous": (
        "이름이 둘 이상의 리소스와 일치합니다",
        "a name matches more than one resource",
    ),
    "concept_disagreement": (
        "두 독립 판독이 개념을 서로 다르게 연결했습니다",
        "two independent readers grounded a named concept differently",
    ),
    "anchor_resolution_incomplete": (
        "이름으로 지정한 리소스를 완전히 읽지 못했습니다",
        "a named resource could not be read completely",
    ),
    "anchor_binding_unavailable": (
        "이름으로 지정한 리소스를 읽을 수 없습니다",
        "a named resource could not be read",
    ),
    "review_merged": (
        "하나의 표현에 여러 조건이 합쳐져 있습니다",
        "one phrase merged more than one condition",
    ),
    "review_literal_differs": (
        "값의 범위를 두 판독이 다르게 읽었습니다",
        "two readers read a stated value differently",
    ),
}
for _code in (
    "prior_result_unavailable",
    "prior_result_foreign",
    "prior_result_changed",
    "prior_result_expired",
    "prior_result_empty",
    "prior_result_out_of_range",
    "prior_result_ambiguous",
):
    _KIND_LABELS[_code] = (
        "가리킨 이전 답변을 사용할 수 없습니다",
        "the earlier answer it refers to is not available",
    )
_FILTER_VALUES: dict[str, tuple[str, str]] = {
    "type": ("리소스 종류", "resource kind"),
    "state": ("상태", "state"),
    "health": ("건강 상태", "health"),
    "region": ("지역", "region"),
    "name_fragment": ("이름", "name"),
    "scope": ("범위", "scope"),
}
_MEASURE_VALUES: dict[str, tuple[str, str]] = {
    "count": ("개수", "count"),
    "state": ("상태", "state"),
    "health": ("건강 상태", "health"),
    "metric": ("지표", "metric"),
    "change": ("변경", "change"),
    "event": ("이벤트", "event"),
    "forecast": ("예측", "forecast"),
    "cost": ("비용", "cost"),
}
_ATOM_CATEGORIES: dict[str, str] = {
    "filter_unsupported": "filter",
    "type_filter_domain_unsupported": "filter:type",
    "state_filter_domain_unsupported": "filter:state",
    "region_filter_domain_unsupported": "filter:region",
    "scope_filter_on_relation_unsupported": "filter:scope",
    "multiple_scopes_unsupported": "filter:scope",
    "measure_unsupported": "measure",
    "measure_mention_unsupported": "measure",
    "group_by_unsupported": "grouping",
    "group_by_unsupported_for_operation": "grouping",
    "schema_group_by_unsupported": "grouping",
    "time_unsupported": "time",
    "time_calendar_window_unsupported": "time",
    "event_window_unsupported": "time",
    "collection_history_unsupported": "time",
    "recent_change_kind_unsupported": "time",
    "counterpart_unsupported": "relation",
    "relation_unsupported_for_operation": "relation",
    "impact_relation_unsupported": "relation",
    "all_kinds_transitive_unsupported": "relation",
    "schema_relation_unsupported": "relation",
    "schema_relation_sense_unsupported": "relation",
    "schema_relation_roles_unsupported": "relation",
    "schema_relation_reach_unsupported": "relation",
    "schema_relation_counterpart_unsupported": "relation",
    "schema_relation_anchor_unsupported": "relation",
    "operation_unsupported": "operation",
    "schema_operation_unsupported": "operation",
    "want_unsupported": "operation",
    "cause_context_atom_unsupported": "operation",
    "subject_unsupported": "operation",
    "schema_subject_unsupported": "operation",
    "schema_scope_unsupported": "operation",
    "result_instance_unsupported": "operation",
    "qualified_mention_unsupported": "reference",
    "qualified_anchor_unsupported": "reference",
    "prior_result_multiple_anchors_unsupported": "reference",
    "anchor_form_unsupported": "reference",
    "reading_beyond_list": "beyond_list",
}
_CATEGORY_LABELS: dict[str, tuple[str, str]] = {
    "filter": ("조건", "filter"),
    "measure": ("측정 항목", "measure"),
    "grouping": ("그룹 기준", "grouping"),
    "time": ("기간 또는 이력", "time period or history"),
    "relation": ("관계", "relation"),
    "operation": ("요청한 답의 종류", "kind of answer asked"),
    "reference": (
        "리소스 또는 이전 답변에 대한 참조",
        "reference to a resource or an earlier answer",
    ),
    "beyond_list": (
        "하나의 필터 목록으로 답할 수 없는 조건",
        "condition that one filtered list cannot answer",
    ),
}


def reading_hold_answer(
    locale: str,
    disposition: str,
    reason_code: str | None,
    details: Iterable[str],
) -> str | None:
    """Return the reviewed notice for a reading hold, or ``None`` for any other outcome.

    Only a held planner reason in ``READING_HOLD_REASONS`` or an unsupported reason in
    ``READING_UNSUPPORTED_REASONS`` has a notice; every other hold keeps its own answer.
    """

    held = disposition == "held" and reason_code in READING_HOLD_REASONS
    unsupported = disposition == "unsupported" and reason_code in READING_UNSUPPORTED_REASONS
    if not (held or unsupported) or reason_code is None:
        return None
    korean = locale.casefold().startswith("ko")
    template = _NOTICES[reason_code][0 if korean else 1]
    if "{detail}" not in template:
        return template
    labels = _labels(tuple(details), _FAMILIES[reason_code], korean=korean)
    if not labels:
        plain = _PLAIN_NOTICES[reason_code]
        return plain[0] if korean else plain[1]
    return template.format(detail=", ".join(labels))


def _labels(details: tuple[str, ...], families: frozenset[str], *, korean: bool) -> tuple[str, ...]:
    """Return distinct reviewed labels for the closed codes, in first-seen order."""

    labels: dict[str, None] = {}
    for code in details:
        family, label = _label(code)
        if family not in families:
            continue
        if label is not None:
            labels[label[0] if korean else label[1]] = None
        if len(labels) >= _MAX_NAMED:
            break
    return tuple(labels)


def _label(code: str) -> tuple[str | None, tuple[str, str] | None]:
    """Return the code's family and reviewed label, or no label for an unknown code."""

    kind, _, value = code.partition(":")
    value = value.split(":", 1)[0]
    if kind in {"role", "unexpressible"}:
        return "role", _ROLE_LABELS.get(value)
    if kind in _KIND_LABELS:
        return "kind", _KIND_LABELS[kind]
    category = _ATOM_CATEGORIES.get(kind)
    if category is None:
        return None, None
    category, _, fixed_value = category.partition(":")
    value = fixed_value or value
    if category == "filter" and value in _FILTER_VALUES:
        korean_value, english_value = _FILTER_VALUES[value]
        return "atom", (f"{korean_value} 조건", f"{english_value} filter")
    if category == "measure" and value in _MEASURE_VALUES:
        korean_value, english_value = _MEASURE_VALUES[value]
        return "atom", (f"{korean_value} 측정", f"{english_value} measure")
    return "atom", _CATEGORY_LABELS[category]


__all__ = ["READING_HOLD_REASONS", "READING_UNSUPPORTED_REASONS", "reading_hold_answer"]
