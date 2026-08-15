"""Compile bounded Console presentation from a verified semantic projection."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import cast

from fdai_operator_service.families.conversation.contracts import JsonObject

_SEMANTIC_ROUTE_BY_DISPOSITION = {
    "answered": "verified_query_plan",
    "clarification": "semantic_clarification",
    "unsupported": "semantic_unsupported",
    "action_draft": "semantic_action_draft",
    "cancelled": "semantic_cancellation",
}
_SEMANTIC_UNAVAILABLE_REASONS = {
    "authoritative_evidence_unavailable",
    "historical_evidence_unavailable",
    "semantic_planner_unavailable",
}
_MAX_SUMMARY_ITEMS = 16
_MAX_TABLE_COLUMNS = 6
_MAX_TABLE_ROWS = 40
_MAX_CELL_CHARS = 512
_CONTROL_CHARACTERS = {chr(code) for code in range(32)} | {chr(127)}


def semantic_done_event_data(
    projection: Mapping[str, object],
    *,
    locale: str = "en",
) -> JsonObject:
    """Compile one bounded terminal event from a validated durable projection."""
    semantic = projection.get("semantic_result")
    if not isinstance(semantic, Mapping):
        raise ValueError("stored semantic projection is missing semantic_result")
    semantic_receipt = _semantic_receipt(projection, semantic)
    answer = semantic.get("answer")
    disposition = semantic.get("disposition")
    if not isinstance(disposition, str):
        raise ValueError("stored semantic projection is missing terminal disposition")
    missing_answer = not isinstance(answer, str) or not answer
    if missing_answer:
        answer = (
            "The stored semantic result predates terminal presentation support. "
            "Review its evidence record before relying on it."
        )
    evidence_refs = semantic.get("evidence_refs", [])
    checks_completed = semantic.get("checks_completed", 0)
    checks_total = semantic.get("checks_total", 0)
    if (
        not isinstance(evidence_refs, list)
        or any(not isinstance(item, str) for item in evidence_refs)
        or not isinstance(checks_completed, int)
        or not isinstance(checks_total, int)
    ):
        raise ValueError("stored semantic verification is malformed")
    verified = disposition == "answered" and not missing_answer
    payload = projection.get("payload")
    technical_details = payload.get("technical_details") if isinstance(payload, Mapping) else None
    presentation_artifact = semantic_presentation_artifact(
        semantic=semantic,
        technical_details=technical_details,
        locale=locale,
    )
    trajectory_detail = semantic_technical_trajectory(
        projection=projection,
        technical_details=technical_details,
        checks_completed=checks_completed,
        checks_total=checks_total,
        locale=locale,
    )
    answer_plan = semantic_answer_plan(technical_details)
    conversation_context = semantic_conversation_context(technical_details)
    return cast(
        JsonObject,
        {
            "seq": 1,
            "revision": 0,
            "status": disposition,
            "answer": answer,
            "source": "ontology-query",
            "verification": {
                "status": "verified" if verified else "unverified",
                "authority": "ontology-query",
                "checks_completed": checks_completed,
                "checks_total": checks_total,
                "evidence_refs": evidence_refs,
                "reason_code": (
                    "semantic_answer_missing" if missing_answer else semantic.get("reason_code")
                ),
                "claims": [],
                "failed_claim_ids": [],
            },
            "intent_graph": semantic.get("intent_graph"),
            "intent_graph_evidence": semantic.get("intent_graph_evidence"),
            "semantic_result": dict(semantic),
            **(
                {"conversation_context": conversation_context}
                if conversation_context is not None
                else {}
            ),
            **({"answer_plan": answer_plan} if answer_plan is not None else {}),
            **(
                {"presentation_artifact": presentation_artifact}
                if presentation_artifact is not None
                else {}
            ),
            **({"trajectory_detail": trajectory_detail} if trajectory_detail is not None else {}),
            **({"semantic_receipt": semantic_receipt} if semantic_receipt is not None else {}),
        },
    )


def semantic_presentation_artifact(
    *,
    semantic: Mapping[str, object],
    technical_details: object,
    locale: str,
) -> JsonObject | None:
    """Build a receipt-bound summary without adding facts or authority."""
    evidence_refs = semantic.get("evidence_refs")
    if (
        not isinstance(evidence_refs, list)
        or not evidence_refs
        or any(not isinstance(item, str) for item in evidence_refs)
        or not isinstance(technical_details, Mapping)
    ):
        return None
    outputs = technical_details.get("outputs")
    if not isinstance(outputs, list) or not outputs:
        return None
    bounded_refs = evidence_refs[:8]
    first = outputs[0]
    if not isinstance(first, Mapping):
        return None
    profile = first.get("incident_profile")
    correlated = first.get("correlated_evidence")
    gaps = first.get("evidence_gaps")
    causal = first.get("causal_assessment")
    korean = locale.casefold().startswith("ko")
    if (
        isinstance(profile, Mapping)
        and isinstance(correlated, list)
        and isinstance(gaps, list)
        and isinstance(causal, Mapping)
    ):
        status = profile.get("status")
        status_text = status if isinstance(status, str) and status else "unknown"
        limitations = [
            (
                "인과 분석이 구현되지 않아 근본 원인을 확인할 수 없습니다."
                if korean
                else "Root cause isn't available because causal analysis hasn't been implemented."
            )
        ]
        gap_labels = (
            {
                "impact_evidence_missing": "영향 근거가 누락되었습니다.",
                "grounded_citations_missing": "근거 인용이 누락되었습니다.",
            }
            if korean
            else {
                "impact_evidence_missing": "Impact evidence is missing.",
                "grounded_citations_missing": "Grounded citations are missing.",
            }
        )
        limitations.extend(
            gap_labels.get(gap, f"Evidence gap: {gap}") for gap in gaps if isinstance(gap, str)
        )
        return cast(
            JsonObject,
            {
                "schema_version": 1,
                "layout": "stack",
                "evidence_refs": bounded_refs,
                "blocks": [
                    {
                        "slot_id": "overview",
                        "kind": "summary",
                        "title": "검증된 인시던트 근거" if korean else "Verified incident evidence",
                        "emphasis": "primary",
                        "collapsed": False,
                        "evidence_refs": bounded_refs,
                        "data": {
                            "items": [
                                {
                                    "label": "감사 기록" if korean else "Audit records",
                                    "value": str(len(correlated)),
                                    "tone": "neutral",
                                },
                                {
                                    "label": "인시던트 상태" if korean else "Incident status",
                                    "value": status_text,
                                    "tone": "attention",
                                },
                            ]
                        },
                    },
                    {
                        "slot_id": "limitations",
                        "kind": "callout",
                        "title": "제한 사항" if korean else "Limitations",
                        "emphasis": "supporting",
                        "collapsed": False,
                        "evidence_refs": bounded_refs,
                        "data": {"tone": "warning", "lines": list(dict.fromkeys(limitations))},
                    },
                    {
                        "slot_id": "findings",
                        "kind": "list",
                        "title": "다음 안전 단계" if korean else "Next safe step",
                        "emphasis": "secondary",
                        "collapsed": False,
                        "evidence_refs": bounded_refs,
                        "data": {
                            "columns": [
                                {"key": "action", "label": "조치" if korean else "Action"},
                                {"key": "authority", "label": "권한" if korean else "Authority"},
                            ],
                            "rows": [
                                {
                                    "action": (
                                        "변경을 제안하기 전에 누락된 근거를 수집하세요."
                                        if korean
                                        else "Collect missing evidence before proposing a change."
                                    ),
                                    "authority": "읽기 전용" if korean else "Read-only",
                                }
                            ],
                            "status_key": None,
                        },
                    },
                ],
            },
        )
    return cast(
        JsonObject,
        {
            "schema_version": 1,
            "layout": "stack",
            "evidence_refs": bounded_refs,
            "blocks": _general_query_blocks(outputs, bounded_refs=bounded_refs, korean=korean),
        },
    )


def _general_query_blocks(
    outputs: list[object],
    *,
    bounded_refs: list[str],
    korean: bool,
) -> list[JsonObject]:
    """Project the verified outputs themselves, never only how many there are."""
    items = _overview_items(outputs, korean=korean)
    if not items:
        items = [
            {
                "label": "검증된 출력" if korean else "Verified outputs",
                "value": str(len(outputs)),
                "tone": "neutral",
            }
        ]
    blocks: list[JsonObject] = [
        cast(
            JsonObject,
            {
                "slot_id": "overview",
                "kind": "summary",
                "title": "검증된 온톨로지 쿼리" if korean else "Verified ontology query",
                "emphasis": "primary",
                "collapsed": False,
                "evidence_refs": bounded_refs,
                "data": {"items": items},
            },
        )
    ]
    for output in outputs:
        records = _records_block(output, bounded_refs=bounded_refs, korean=korean)
        if records is not None:
            blocks.append(records)
            break
    return blocks


def _overview_items(outputs: list[object], *, korean: bool) -> list[JsonObject]:
    items: list[JsonObject] = []
    labels: set[str] = set()
    for output in outputs:
        if len(items) >= _MAX_SUMMARY_ITEMS or not isinstance(output, Mapping):
            break
        node_id = output.get("node_id")
        value = _output_summary_value(output, korean=korean)
        if not isinstance(node_id, str) or not node_id or node_id in labels or value is None:
            continue
        labels.add(node_id)
        items.append(cast(JsonObject, {"label": node_id, "value": value, "tone": "neutral"}))
    return items


def _output_summary_value(output: Mapping[str, object], *, korean: bool) -> str | None:
    rule_search = output.get("rule_search")
    if isinstance(rule_search, Mapping):
        candidates = rule_search.get("candidates")
        count = len(candidates) if isinstance(candidates, list) else 0
        return f"규칙 후보 {count}건" if korean else f"{count} rule candidates"
    result_kind = output.get("result_kind")
    if isinstance(result_kind, str) and result_kind:
        return result_kind
    returned = output.get("returned_rows")
    total = output.get("total_rows")
    if isinstance(returned, int) and isinstance(total, int):
        return f"전체 {total}개 행 중 {returned}개" if korean else f"{returned} of {total} rows"
    return None


def _records_block(
    output: object,
    *,
    bounded_refs: list[str],
    korean: bool,
) -> JsonObject | None:
    if not isinstance(output, Mapping):
        return None
    rows = output.get("rows")
    if not isinstance(rows, list) or not rows:
        return None
    row_values: list[Mapping[str, object]] = []
    fields: list[str] = []
    for row in rows[:_MAX_TABLE_ROWS]:
        values = row.get("values") if isinstance(row, Mapping) else None
        if not isinstance(values, Mapping):
            return None
        row_values.append(values)
        for field in values:
            if isinstance(field, str) and field and field not in fields:
                fields.append(field)
    selected = fields[:_MAX_TABLE_COLUMNS]
    if not selected:
        return None
    # Positional keys: an ontology field name is not a valid Console column key.
    return cast(
        JsonObject,
        {
            "slot_id": "records",
            "kind": "table",
            "title": "검증된 행" if korean else "Verified rows",
            "emphasis": "secondary",
            "collapsed": False,
            "evidence_refs": bounded_refs,
            "data": {
                "columns": [
                    {"key": f"c{index}", "label": field} for index, field in enumerate(selected)
                ],
                "rows": [
                    {f"c{index}": _cell(values.get(field)) for index, field in enumerate(selected)}
                    for values in row_values
                ],
                "status_key": None,
            },
        },
    )


def _cell(value: object) -> str:
    """Render one bounded printable cell; the Console rejects empty or control text."""
    if value is None:
        rendered = ""
    elif isinstance(value, str):
        rendered = value
    elif isinstance(value, bool):
        rendered = "true" if value else "false"
    elif isinstance(value, int | float):
        rendered = str(value)
    else:
        rendered = json.dumps(value, allow_nan=False, ensure_ascii=False, sort_keys=True)
    cleaned = "".join(
        " " if character in _CONTROL_CHARACTERS else character for character in rendered
    ).strip()
    return cleaned[:_MAX_CELL_CHARS] if cleaned else "-"


def semantic_technical_trajectory(
    *,
    projection: Mapping[str, object],
    technical_details: object,
    checks_completed: int,
    checks_total: int,
    locale: str,
) -> JsonObject | None:
    """Place exact machine output in a bounded, collapsed trajectory activity."""
    if not isinstance(technical_details, Mapping):
        return None
    encoded = json.dumps(
        technical_details,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    if not encoded or len(encoded) > 64 * 1024:
        return None
    recorded_at = projection.get("recorded_at")
    return cast(
        JsonObject,
        {
            "schema_version": 1,
            "activities": [
                {
                    "activity_id": "semantic-query-evidence",
                    "kind": "query",
                    "status": "completed",
                    "label": (
                        "검증된 의미 쿼리 근거"
                        if locale.casefold().startswith("ko")
                        else "Verified semantic query evidence"
                    ),
                    "completed": checks_completed,
                    "total": checks_total,
                    "authority": "read_only",
                    **(
                        {"observed_at": recorded_at}
                        if isinstance(recorded_at, str) and recorded_at
                        else {}
                    ),
                    "execution": {
                        "tool": "ontology-query",
                        "command": "semantic_query_outputs",
                        "input_kind": "query",
                        "redacted": True,
                        "output": encoded,
                        "output_truncated": False,
                    },
                }
            ],
            "branches": [],
            "milestones": [],
            "omitted": {"activities": 0, "branches": 0, "milestones": 0},
            "truncated_outputs": 0,
        },
    )


def semantic_answer_plan(technical_details: object) -> JsonObject | None:
    """Describe the deterministic terminal layout selected from typed output shape."""
    if not isinstance(technical_details, Mapping):
        return None
    outputs = technical_details.get("outputs")
    if not isinstance(outputs, list) or not outputs:
        return None
    first = outputs[0]
    incident = isinstance(first, Mapping) and isinstance(first.get("incident_profile"), Mapping)
    sections = (
        ["verified_facts", "limitations", "next_safe_step"]
        if incident
        else ["verified_summary", "technical_details"]
    )
    return cast(
        JsonObject,
        {
            "intent": "diagnosis" if incident else "summary",
            "detail_level": "standard",
            "format": "mixed",
            "sections": sections,
            "evidence_requirement": "server_read_model",
            "max_words": 500,
            "discuss": "skip",
            "explicit_overrides": [],
            "preference_applied": False,
        },
    )


def semantic_conversation_context(technical_details: object) -> JsonObject | None:
    """Return only a verified incident identity for subsequent read-only turns."""
    if not isinstance(technical_details, Mapping):
        return None
    outputs = technical_details.get("outputs")
    if not isinstance(outputs, list) or len(outputs) != 1:
        return None
    output = outputs[0]
    if not isinstance(output, Mapping):
        return None
    profile = output.get("incident_profile")
    if not isinstance(profile, Mapping):
        return None
    incident_id = profile.get("incident_id")
    correlation_id = profile.get("correlation_id")
    if (
        not isinstance(incident_id, str)
        or not incident_id
        or len(incident_id) > 256
        or not isinstance(correlation_id, str)
        or not correlation_id
        or len(correlation_id) > 256
    ):
        return None
    return cast(
        JsonObject,
        {
            "kind": "incident",
            "incident_id": incident_id,
            "correlation_id": correlation_id,
        },
    )


def _semantic_receipt(
    projection: Mapping[str, object],
    semantic: Mapping[str, object],
) -> dict[str, object] | None:
    projection_id = projection.get("projection_id")
    request_id = projection.get("request_id")
    if projection_id is None and request_id is None:
        return None
    if not isinstance(projection_id, str) or not projection_id:
        raise ValueError("stored semantic projection_id is malformed")
    if not isinstance(request_id, str) or not request_id:
        raise ValueError("stored semantic request_id is malformed")
    disposition = _mapping_text(semantic, "disposition")
    reason_code = _mapping_text(semantic, "reason_code")
    semantic_route = semantic.get("semantic_route")
    unavailable_reason = semantic.get("unavailable_reason")
    expected_route = _SEMANTIC_ROUTE_BY_DISPOSITION.get(disposition)
    if disposition == "held":
        if semantic_route is not None or unavailable_reason not in _SEMANTIC_UNAVAILABLE_REASONS:
            raise ValueError("stored held semantic projection has invalid typed unavailability")
    elif semantic_route != expected_route or unavailable_reason is not None:
        raise ValueError("stored semantic projection route does not match disposition")
    digest_fields = (
        "ontology_release_digest",
        "principal_manifest_digest",
        "plan_digest",
        "execution_receipt_digest",
    )
    digests: dict[str, object] = {}
    for field in digest_fields:
        value = semantic.get(field)
        if value is not None:
            if not isinstance(value, str) or not value:
                raise ValueError(f"stored semantic {field} is malformed")
            digests[field] = value
    if disposition == "answered" and len(digests) != len(digest_fields):
        raise ValueError("stored answered semantic projection is missing exact evidence digests")
    if semantic.get("execution_authority") is not False:
        raise ValueError("stored semantic projection MUST deny execution authority")
    return {
        "schema_version": "1.0.0",
        "projection_id": projection_id,
        "request_id": request_id,
        "disposition": disposition,
        "reason_code": reason_code,
        **({"semantic_route": semantic_route} if semantic_route is not None else {}),
        **({"unavailable_reason": unavailable_reason} if unavailable_reason is not None else {}),
        **digests,
        "execution_authority": False,
    }


def _mapping_text(value: Mapping[str, object], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise ValueError(f"semantic {key} is malformed")
    return item


__all__ = [
    "semantic_answer_plan",
    "semantic_conversation_context",
    "semantic_done_event_data",
    "semantic_presentation_artifact",
    "semantic_technical_trajectory",
]
