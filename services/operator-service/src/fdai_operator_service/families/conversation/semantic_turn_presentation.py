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
# Scalar leaves lifted out of an open-shape property bag so the answer table
# stays readable. The exact untouched row still travels in technical details.
_LIFTED_ROW_FIELDS = ("name", "type", "status", "location")
# Categorical fields worth charting once a result is complete, most specific
# first. A single-value field yields no chart; the table already says it.
_DISTRIBUTION_FIELDS = ("type", "status", "location", "object_type")
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


def _readable_gap(gap: str, *, korean: bool) -> str:
    """Never surface a raw gap key: Markdown reads its underscores as emphasis."""
    readable = gap.replace("_", " ").strip() or gap
    return f"근거 공백: {readable}" if korean else f"Evidence gap: {readable}"


_INCIDENT_PROFILE_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("title", "제목", "Title"),
    ("severity", "심각도", "Severity"),
    ("status", "상태", "Status"),
    ("vertical", "버티컬", "Vertical"),
    ("opened_at", "최초 기록", "First recorded"),
    ("last_updated_at", "최종 기록", "Last recorded"),
    ("actors", "관여 주체", "Actors"),
)
_INCIDENT_GAP_NEXT_STEPS: tuple[tuple[str, str, str], ...] = (
    (
        "incident_profile_missing",
        "이 상관관계에 인시던트 레코드가 존재하는지 확인하세요.",
        "Confirm an incident record exists for this correlation.",
    ),
    (
        "root_cause_missing",
        "근거 인용이 포함된 RCA 가설이 기록되었는지 확인하세요.",
        "Confirm that an RCA hypothesis with grounded citations has been recorded.",
    ),
    (
        "impact_evidence_missing",
        "영향받은 리소스의 영향 근거를 수집하세요.",
        "Collect impact evidence for the affected resources.",
    ),
    (
        "grounded_citations_missing",
        "각 주장을 감사 기록에 연결하는 근거 인용을 수집하세요.",
        "Collect grounded citations that link each claim to an audit record.",
    ),
    (
        "correlated_audit_truncated",
        "더 높은 레코드 한도로 이 조회를 다시 실행하세요.",
        "Re-run this query with a higher record limit.",
    ),
)
_INCIDENT_TIMELINE_ROWS = 10


def _incident_cell(value: object) -> str | None:
    """Render one incident cell without inventing a value for a missing field."""
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return str(value)
    if isinstance(value, list | tuple):
        parts = [item for item in (_incident_cell(entry) for entry in value) if item]
        return ", ".join(parts) or None
    return None


def _incident_profile_items(profile: Mapping[str, object], *, korean: bool) -> list[JsonObject]:
    """Show every populated profile field, and say so when the status is not one of them."""
    items: list[JsonObject] = []
    for key, korean_label, english_label in _INCIDENT_PROFILE_FIELDS:
        rendered = _incident_cell(profile.get(key))
        if rendered is None:
            continue
        items.append(
            cast(
                JsonObject,
                {
                    "label": korean_label if korean else english_label,
                    "value": rendered,
                    "tone": "attention" if key in ("severity", "status") else "neutral",
                },
            )
        )
    if _incident_cell(profile.get("status")) is None:
        items.append(
            cast(
                JsonObject,
                {
                    "label": "인시던트 상태" if korean else "Incident status",
                    "value": "미기록" if korean else "not recorded",
                    "tone": "attention",
                },
            )
        )
    return items


def _incident_timeline_block(
    correlated: list[object],
    *,
    verified_records: int,
    bounded_refs: list[str],
    korean: bool,
) -> JsonObject | None:
    rows: list[JsonObject] = []
    for entry in correlated[-_INCIDENT_TIMELINE_ROWS:]:
        if not isinstance(entry, Mapping):
            continue
        recorded_at = _incident_cell(entry.get("recorded_at"))
        audit_ref = _incident_cell(entry.get("audit_ref"))
        if recorded_at is None or audit_ref is None:
            continue
        rows.append(
            cast(
                JsonObject,
                {
                    "recorded_at": recorded_at,
                    "actor": _incident_cell(entry.get("actor")) or "-",
                    "action_kind": _incident_cell(entry.get("action_kind")) or "-",
                    "mode": _incident_cell(entry.get("mode")) or "-",
                    "audit_ref": audit_ref,
                },
            )
        )
    if not rows:
        return None
    # `correlated` is already capped upstream, so only the verified count states the whole.
    shown, total = len(rows), max(verified_records, len(correlated))
    title = "기록된 활동" if korean else "Recorded activity"
    if total > shown:
        title += f" (최근 {shown}/{total}건)" if korean else f" (latest {shown} of {total})"
    return cast(
        JsonObject,
        {
            "slot_id": "records",
            "kind": "table",
            "title": title,
            "emphasis": "secondary",
            "collapsed": False,
            "evidence_refs": bounded_refs,
            "data": {
                "columns": [
                    {"key": "recorded_at", "label": "기록 시각" if korean else "Recorded"},
                    {"key": "actor", "label": "주체" if korean else "Actor"},
                    {"key": "action_kind", "label": "활동" if korean else "Activity"},
                    {"key": "mode", "label": "모드" if korean else "Mode"},
                    {"key": "audit_ref", "label": "감사 참조" if korean else "Audit ref"},
                ],
                "rows": rows,
                "status_key": None,
            },
        },
    )


def _incident_root_cause_block(
    root_cause: object,
    *,
    bounded_refs: list[str],
    korean: bool,
) -> JsonObject | None:
    if not isinstance(root_cause, Mapping):
        return None
    fields = (
        ("cause", "원인", "Cause"),
        ("tier", "티어", "Tier"),
        ("confidence", "신뢰도", "Confidence"),
        ("reason", "근거", "Reason"),
        ("recorded_at", "기록 시각", "Recorded"),
    )
    items = [
        cast(
            JsonObject,
            {
                "label": korean_label if korean else english_label,
                "value": rendered,
                "tone": "neutral",
            },
        )
        for key, korean_label, english_label in fields
        if (rendered := _incident_cell(root_cause.get(key))) is not None
    ]
    if not items:
        return None
    return cast(
        JsonObject,
        {
            "slot_id": "root_cause",
            "kind": "summary",
            "title": "근본 원인" if korean else "Root cause",
            "emphasis": "primary",
            "collapsed": False,
            "evidence_refs": bounded_refs,
            "data": {"items": items},
        },
    )


def _incident_impact_block(
    impacts: object,
    *,
    bounded_refs: list[str],
    korean: bool,
) -> JsonObject | None:
    if not isinstance(impacts, list) or not impacts:
        return None
    rows: list[JsonObject] = []
    for impact in impacts[:_MAX_TABLE_ROWS]:
        if not isinstance(impact, Mapping):
            continue
        unit = _incident_cell(impact.get("unit"))
        rows.append(
            cast(
                JsonObject,
                {
                    "metric": _incident_cell(impact.get("metric")) or "-",
                    "baseline": _incident_measure(impact.get("baseline"), unit),
                    "observed": _incident_measure(impact.get("observed"), unit),
                    "threshold": _incident_measure(impact.get("threshold"), unit),
                    "impact": _incident_cell(impact.get("impact")) or "-",
                    "evidence_ref": _incident_cell(impact.get("evidence_ref")) or "-",
                },
            )
        )
    if not rows:
        return None
    return cast(
        JsonObject,
        {
            "slot_id": "impact",
            "kind": "table",
            "title": "영향 근거" if korean else "Impact evidence",
            "emphasis": "secondary",
            "collapsed": False,
            "evidence_refs": bounded_refs,
            "data": {
                "columns": [
                    {"key": "metric", "label": "메트릭" if korean else "Metric"},
                    {"key": "baseline", "label": "기준" if korean else "Baseline"},
                    {"key": "observed", "label": "관측" if korean else "Observed"},
                    {"key": "threshold", "label": "임계값" if korean else "Threshold"},
                    {"key": "impact", "label": "영향" if korean else "Impact"},
                    {"key": "evidence_ref", "label": "근거" if korean else "Evidence"},
                ],
                "rows": rows,
                "status_key": None,
            },
        },
    )


def _incident_measure(value: object, unit: str | None) -> str:
    rendered = _incident_cell(value)
    if rendered is None:
        return "-"
    return f"{rendered} {unit}" if unit else rendered


def _incident_citations_block(
    citations: object,
    *,
    bounded_refs: list[str],
    korean: bool,
) -> JsonObject | None:
    if not isinstance(citations, list) or not citations:
        return None
    rows: list[JsonObject] = []
    for citation in citations[:_MAX_TABLE_ROWS]:
        if not isinstance(citation, Mapping):
            continue
        rows.append(
            cast(
                JsonObject,
                {
                    "tier": _incident_cell(citation.get("tier")) or "-",
                    "kind": _incident_cell(citation.get("kind")) or "-",
                    "ref": _incident_cell(citation.get("ref")) or "-",
                    "summary": _incident_cell(citation.get("summary")) or "-",
                    "recorded_at": _incident_cell(citation.get("recorded_at")) or "-",
                },
            )
        )
    if not rows:
        return None
    return cast(
        JsonObject,
        {
            "slot_id": "citations",
            "kind": "table",
            "title": "근거 인용" if korean else "Grounded citations",
            "emphasis": "supporting",
            "collapsed": False,
            "evidence_refs": bounded_refs,
            "data": {
                "columns": [
                    {"key": "tier", "label": "티어" if korean else "Tier"},
                    {"key": "kind", "label": "종류" if korean else "Kind"},
                    {"key": "ref", "label": "참조" if korean else "Reference"},
                    {"key": "summary", "label": "요약" if korean else "Summary"},
                    {"key": "recorded_at", "label": "기록 시각" if korean else "Recorded"},
                ],
                "rows": rows,
                "status_key": None,
            },
        },
    )


def _incident_next_step_rows(
    gaps: list[object],
    *,
    korean: bool,
    root_cause: object,
) -> list[JsonObject]:
    """Name the steps the measured gaps call for, not one sentence for every answer."""
    present = {gap for gap in gaps if isinstance(gap, str)}
    authority = "읽기 전용" if korean else "Read-only"
    rows = [
        cast(
            JsonObject,
            {"action": korean_step if korean else english_step, "authority": authority},
        )
        for key, korean_step, english_step in _INCIDENT_GAP_NEXT_STEPS
        if key in present
    ]
    if rows:
        return rows
    if (
        isinstance(root_cause, Mapping)
        and root_cause.get("next_safe_step") == "configure_notification_route"
    ):
        return [
            cast(
                JsonObject,
                {
                    "action": (
                        "notification registry에 운영 알림 채널을 하나 이상 구성한 뒤 전달을 "
                        "다시 시도하세요."
                        if korean
                        else (
                            "Configure at least one operational-alert channel in the notification "
                            "registry, then retry delivery."
                        )
                    ),
                    "authority": authority,
                },
            )
        ]
    return [
        cast(
            JsonObject,
            {
                "action": (
                    "상관된 감사 근거가 완전합니다. 기록된 활동을 검토하세요."
                    if korean
                    else "The correlated audit evidence is complete. Review the recorded activity."
                ),
                "authority": authority,
            },
        )
    ]


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
    root_cause = first.get("root_cause")
    impacts = first.get("impact_evidence")
    citations = first.get("grounded_citations")
    korean = locale.casefold().startswith("ko")
    current_contract = (
        (root_cause is None or isinstance(root_cause, Mapping))
        and isinstance(impacts, list)
        and isinstance(citations, list)
    )
    if (
        isinstance(profile, Mapping)
        and isinstance(correlated, list)
        and isinstance(gaps, list)
        and (current_contract or isinstance(causal, Mapping))
    ):
        verified = first.get("verified_records")
        verified_records = (
            verified
            if isinstance(verified, int) and not isinstance(verified, bool)
            else len(correlated)
        )
        overview_items: list[JsonObject] = [
            cast(
                JsonObject,
                {
                    "label": "감사 기록" if korean else "Audit records",
                    "value": str(verified_records),
                    "tone": "neutral",
                },
            ),
            *_incident_profile_items(profile, korean=korean),
        ]
        timeline_block = _incident_timeline_block(
            correlated,
            verified_records=verified_records,
            bounded_refs=bounded_refs,
            korean=korean,
        )
        root_cause_block = _incident_root_cause_block(
            root_cause,
            bounded_refs=bounded_refs,
            korean=korean,
        )
        impact_block = _incident_impact_block(
            impacts,
            bounded_refs=bounded_refs,
            korean=korean,
        )
        citations_block = _incident_citations_block(
            citations,
            bounded_refs=bounded_refs,
            korean=korean,
        )
        limitations = []
        if not current_contract:
            limitations.append(
                "인과 분석이 구현되지 않아 근본 원인을 확인할 수 없습니다."
                if korean
                else "Root cause isn't available because causal analysis hasn't been implemented."
            )
        if len(correlated) < verified_records:
            limitations.append(
                f"아래 목록에는 가장 최근 {len(correlated)}건만 담겨 있습니다."
                if korean
                else f"Only the most recent {len(correlated)} records are listed."
            )
        gap_labels = (
            {
                "root_cause_missing": "근거에 기반한 근본 원인 가설이 기록되지 않았습니다.",
                "impact_evidence_missing": "영향 근거가 누락되었습니다.",
                "grounded_citations_missing": "근거 인용이 누락되었습니다.",
                "incident_profile_missing": "인시던트 프로파일이 누락되었습니다.",
                "correlated_audit_truncated": "감사 기록이 잘렸습니다.",
            }
            if korean
            else {
                "root_cause_missing": "No grounded root-cause hypothesis is recorded.",
                "impact_evidence_missing": "Impact evidence is missing.",
                "grounded_citations_missing": "Grounded citations are missing.",
                "incident_profile_missing": "The incident profile is missing.",
                "correlated_audit_truncated": "Audit records were truncated.",
            }
        )
        limitations.extend(
            gap_labels.get(gap, _readable_gap(gap, korean=korean))
            for gap in gaps
            if isinstance(gap, str)
        )
        if not limitations:
            limitations.append(
                "기록된 근거 공백이 없습니다." if korean else "No recorded evidence gaps."
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
                        "data": {"items": overview_items},
                    },
                    *([timeline_block] if timeline_block is not None else []),
                    *([root_cause_block] if root_cause_block is not None else []),
                    *([impact_block] if impact_block is not None else []),
                    *([citations_block] if citations_block is not None else []),
                    {
                        "slot_id": "limitations",
                        "kind": "callout",
                        "title": "제한 사항" if korean else "Limitations",
                        "emphasis": "supporting",
                        "collapsed": False,
                        "evidence_refs": bounded_refs,
                        "data": {
                            "tone": "neutral" if not gaps and current_contract else "warning",
                            "lines": list(dict.fromkeys(limitations)),
                        },
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
                            "rows": _incident_next_step_rows(
                                gaps,
                                korean=korean,
                                root_cause=root_cause,
                            ),
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
            distribution = _distribution_block(output, bounded_refs=bounded_refs, korean=korean)
            if distribution is not None:
                blocks.append(distribution)
            limitation = _row_limitation_block(output, bounded_refs=bounded_refs, korean=korean)
            if limitation is not None:
                blocks.append(limitation)
            break
    return blocks


def _readable_rows(output: object) -> list[Mapping[str, object]] | None:
    """Return every verified row of ``output`` in its readable projection."""
    if not isinstance(output, Mapping):
        return None
    rows = output.get("rows")
    if not isinstance(rows, list) or not rows:
        return None
    readable: list[Mapping[str, object]] = []
    for row in rows:
        values = row.get("values") if isinstance(row, Mapping) else None
        if not isinstance(values, Mapping):
            return None
        readable.append(_readable_row(values))
    return readable


def _distribution_block(
    output: object,
    *,
    bounded_refs: list[str],
    korean: bool,
) -> JsonObject | None:
    """Chart one categorical field, but only over a complete verified result.

    A truncated result would make the counts read as the whole population, so
    an incomplete or capped output yields no chart at all.
    """
    if not isinstance(output, Mapping):
        return None
    returned = output.get("returned_rows")
    total = output.get("total_rows")
    readable = _readable_rows(output)
    if readable is None or not isinstance(returned, int) or not isinstance(total, int):
        return None
    if returned != total or len(readable) != total:
        return None
    for field in _DISTRIBUTION_FIELDS:
        counts: dict[str, int] = {}
        complete = True
        for values in readable:
            candidate = values.get(field)
            if not isinstance(candidate, str) or not candidate.strip():
                complete = False
                break
            counts[candidate.strip()[:_MAX_CELL_CHARS]] = (
                counts.get(candidate.strip()[:_MAX_CELL_CHARS], 0) + 1
            )
        if not complete or not 2 <= len(counts) <= _MAX_SUMMARY_ITEMS:
            continue
        ordered = sorted(counts.items(), key=lambda entry: (-entry[1], entry[0]))
        return cast(
            JsonObject,
            {
                "slot_id": "distribution",
                "kind": "bar",
                "title": f"{field} 분포" if korean else f"Distribution by {field}",
                "emphasis": "secondary",
                "collapsed": False,
                "evidence_refs": bounded_refs,
                "data": {
                    "items": [
                        {"label": label, "value": count, "tone": "neutral"}
                        for label, count in ordered
                    ]
                },
            },
        )
    return None


def _row_limitation_block(
    output: object,
    *,
    bounded_refs: list[str],
    korean: bool,
) -> JsonObject | None:
    """State that the listed rows are a bounded slice of the verified total."""
    readable = _readable_rows(output)
    if readable is None or not isinstance(output, Mapping):
        return None
    total = output.get("total_rows")
    if not isinstance(total, int):
        return None
    shown = min(len(readable), _MAX_TABLE_ROWS)
    if shown >= total:
        return None
    line = (
        f"검증된 {total}개 행 중 {shown}개를 표시합니다. 나머지 행은 기술 세부에 있습니다."
        if korean
        else (
            f"{shown} of {total} verified rows are listed. "
            "The remaining rows stay in technical details."
        )
    )
    return cast(
        JsonObject,
        {
            "slot_id": "limitations",
            "kind": "callout",
            "title": "제한 사항" if korean else "Limitations",
            "emphasis": "supporting",
            "collapsed": False,
            "evidence_refs": bounded_refs,
            "data": {"tone": "neutral", "lines": [line]},
        },
    )


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
        readable = _readable_row(values)
        row_values.append(readable)
        for field in readable:
            if field not in fields:
                fields.append(field)
    selected = _ordered_columns(fields)[:_MAX_TABLE_COLUMNS]
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


def _ordered_columns(fields: list[str]) -> list[str]:
    """Lead with the fields an operator reads, keeping the rest in row order.

    An opaque identifier is the widest column and the least useful one to read
    first, so a named field takes the leading position when the row has one.
    """
    leading = [field for field in _LIFTED_ROW_FIELDS if field in fields]
    return leading + [field for field in fields if field not in leading]


def _readable_row(values: Mapping[str, object]) -> dict[str, object]:
    """Keep scalar fields and lift named scalar leaves out of nested bags.

    A serialized property bag is machine output, not an operator-facing
    answer. Dropping it here keeps the reply legible; the untouched row is
    still reachable through the technical-details trajectory.
    """
    readable: dict[str, object] = {}
    nested: list[Mapping[str, object]] = []
    for field, value in values.items():
        if not isinstance(field, str) or not field:
            continue
        if isinstance(value, Mapping):
            nested.append(value)
            continue
        if isinstance(value, list):
            continue
        readable[field] = value
    for bag in nested:
        for field in _LIFTED_ROW_FIELDS:
            candidate = bag.get(field)
            if candidate is None or isinstance(candidate, Mapping | list):
                continue
            readable.setdefault(field, candidate)
    return readable


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
