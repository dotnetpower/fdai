"""Rule, promotion, and best-practice workflow projections."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping

from starlette.exceptions import HTTPException

from fdai_operator_service.families.workflow.contracts import (
    WorkflowOperation,
    WorkflowReadRequest,
)


def _promotion_gate_payload(
    stored: Mapping[str, object],
    modes: Mapping[str, str],
) -> dict[str, object]:
    rows_value = stored.get("rows")
    if not isinstance(rows_value, list):
        raise HTTPException(
            status_code=503,
            detail="authoritative promotion-gate projection is malformed",
        )
    rows: list[dict[str, object]] = []
    action_types: set[str] = set()
    for value in rows_value:
        if not isinstance(value, dict):
            raise HTTPException(
                status_code=503,
                detail="authoritative promotion-gate projection is malformed",
            )
        action_type = value.get("action_type_name")
        if not isinstance(action_type, str) or not action_type or action_type in action_types:
            raise HTTPException(
                status_code=503,
                detail="authoritative promotion-gate projection is malformed",
            )
        action_types.add(action_type)
        rows.append(
            {
                **value,
                "mode": modes.get(action_type, "shadow"),
                "mode_source": (
                    "promotion-registry" if action_type in modes else "catalog-default"
                ),
            }
        )
    return {**stored, "rows": rows}


def _rule_catalog_payload(
    stored: Mapping[str, object],
    request: WorkflowReadRequest,
) -> dict[str, object]:
    rules_value = stored.get("rules")
    details_value = stored.get("details")
    if not isinstance(rules_value, list) or not isinstance(details_value, dict):
        raise HTTPException(status_code=503, detail="authoritative Rule catalog is malformed")
    rules = [item for item in rules_value if isinstance(item, dict)]
    if len(rules) != len(rules_value):
        raise HTTPException(status_code=503, detail="authoritative Rule catalog is malformed")

    if request.operation in {
        WorkflowOperation.RULE_DETAIL,
        WorkflowOperation.RULE_FINDINGS,
    }:
        rule_id = request.path_parameters.get("rule_id", "")
        origin = request.query.get("origin", "").strip().lower()
        detail = details_value.get(f"{origin}:{rule_id}") if origin else None
        if detail is None:
            detail = next(
                (
                    value
                    for key, value in details_value.items()
                    if isinstance(key, str) and key.endswith(f":{rule_id}")
                ),
                None,
            )
        if not isinstance(detail, dict):
            raise HTTPException(status_code=404, detail=f"unknown rule id {rule_id!r}")
        return dict(detail)

    origin = request.query.get("origin", "").strip().lower()
    category = request.query.get("category", "").strip().lower()
    severity = request.query.get("severity", "").strip().lower()
    source = request.query.get("source", "").strip().lower()
    needle = request.query.get("q", "").strip().lower()
    matched = [
        item
        for item in rules
        if (not origin or item.get("origin") == origin)
        and (not category or item.get("category") == category)
        and (not severity or item.get("severity") == severity)
        and (not source or item.get("source") == source)
        and (
            not needle or needle in f"{item.get('id', '')}\n{item.get('resource_type', '')}".lower()
        )
    ]
    offset = request.offset or 0
    limit = request.limit or 100
    return {
        "total": len(rules),
        "filtered_total": len(matched),
        "offset": offset,
        "limit": limit,
        "resource_type_count": len({item.get("resource_type") for item in rules}),
        "facets": {
            "by_origin": _rule_counts(rules, "origin"),
            "by_category": _rule_counts(rules, "category"),
            "by_severity": _rule_counts(rules, "severity"),
            "by_source": _rule_counts(rules, "source"),
        },
        "rules": matched[offset : offset + limit],
    }


def _rule_findings_summary_payload(
    stored: Mapping[str, object],
) -> dict[str, object]:
    evaluated = stored.get("evaluated")
    counts = stored.get("counts")
    if not isinstance(evaluated, bool) or not isinstance(counts, Mapping):
        raise HTTPException(
            status_code=503,
            detail="authoritative Rule findings summary is malformed",
        )
    normalized: dict[str, int] = {}
    for key, value in counts.items():
        if (
            not isinstance(key, str)
            or not key
            or not isinstance(value, int)
            or isinstance(value, bool)
            or value < 0
        ):
            raise HTTPException(
                status_code=503,
                detail="authoritative Rule findings summary is malformed",
            )
        normalized[key] = value
    return {"evaluated": evaluated, "counts": normalized}


def _rule_counts(rules: list[dict[str, object]], field: str) -> dict[str, int]:
    counts = Counter(str(item[field]) for item in rules if isinstance(item.get(field), str))
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def _best_practice_catalog_payload(
    stored: Mapping[str, object],
    request: WorkflowReadRequest,
) -> dict[str, object]:
    controls_value = stored.get("controls")
    evaluation_source = stored.get("evaluation_source")
    if not isinstance(controls_value, list) or not isinstance(evaluation_source, str):
        raise HTTPException(
            status_code=503,
            detail="authoritative best-practice catalog is malformed",
        )
    controls = [item for item in controls_value if isinstance(item, dict)]
    if len(controls) != len(controls_value):
        raise HTTPException(
            status_code=503,
            detail="authoritative best-practice catalog is malformed",
        )

    if request.operation is WorkflowOperation.BEST_PRACTICE_DETAIL:
        selected_id = request.path_parameters.get("best_practice_id", "")
        selected = next((item for item in controls if item.get("id") == selected_id), None)
        if selected is None:
            raise HTTPException(status_code=404, detail=f"unknown best-practice id {selected_id!r}")
        return dict(selected)

    pillar = request.query.get("pillar", "").strip().lower()
    status = request.query.get("status", "").strip().lower()
    needle = request.query.get("q", "").strip().lower()
    matched = [
        item
        for item in controls
        if (not pillar or str(item.get("pillar", "")).lower() == pillar)
        and (not status or str(item.get("status", "")).lower() == status)
        and (
            not needle
            or needle
            in "\n".join(
                str(item.get(field, "")) for field in ("id", "control_id", "title", "rationale")
            ).lower()
        )
    ]
    offset = request.offset or 0
    limit = request.limit or 100
    return {
        "total": len(controls),
        "filtered_total": len(matched),
        "offset": offset,
        "limit": limit,
        "facets": {
            "by_pillar": _rule_counts(controls, "pillar"),
            "by_status": _rule_counts(controls, "status"),
            "by_severity": _rule_counts(controls, "severity"),
        },
        "controls": [
            {key: value for key, value in item.items() if key not in {"requirements", "provenance"}}
            for item in matched[offset : offset + limit]
        ],
        "evaluation_source": evaluation_source,
    }
