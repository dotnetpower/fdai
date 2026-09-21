"""CAF, MCSB, and WARA workflow catalog projections."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from typing import cast

from starlette.exceptions import HTTPException

from fdai_operator_service.families.workflow.contracts import (
    WorkflowOperation,
    WorkflowReadRequest,
)
from fdai_operator_service.workflow_rule_projection import _rule_counts


def _wara_counts(controls: list[dict[str, object]], field: str) -> dict[str, int]:
    values = []
    for item in controls:
        value = item.get(field)
        if isinstance(value, bool):
            values.append(str(value).lower())
        elif isinstance(value, str):
            values.append(value)
    counts = Counter(values)
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def _caf_catalog_payload(
    stored: Mapping[str, object],
    request: WorkflowReadRequest,
) -> dict[str, object]:
    controls_value = stored.get("controls")
    evaluation_source = stored.get("evaluation_source")
    if not isinstance(controls_value, list) or not isinstance(evaluation_source, str):
        raise HTTPException(status_code=503, detail="authoritative CAF catalog is malformed")
    controls = [item for item in controls_value if isinstance(item, dict)]
    if len(controls) != len(controls_value):
        raise HTTPException(status_code=503, detail="authoritative CAF catalog is malformed")

    if request.operation is WorkflowOperation.CAF_DETAIL:
        control_id = request.path_parameters.get("control_id", "")
        selected = next((item for item in controls if item.get("control_id") == control_id), None)
        if selected is None:
            raise HTTPException(status_code=404, detail=f"unknown CAF control {control_id!r}")
        return dict(selected)

    filter_fields = (
        "area",
        "mapping_state",
        "applicability",
        "evaluation_status",
        "satisfaction",
        "owner_slot",
    )
    filters = {field: request.query.get(field, "").strip().lower() for field in filter_fields}
    needle = request.query.get("q", "").strip().lower()
    matched = [
        item
        for item in controls
        if all(
            not expected or str(item.get(field, "")).lower() == expected
            for field, expected in filters.items()
        )
        and (
            not needle
            or needle
            in "\n".join(
                str(item.get(field, "")) for field in ("control_id", "title", "description", "area")
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
            "by_area": _wara_counts(controls, "area"),
            "by_mapping": _wara_counts(controls, "mapping_state"),
            "by_applicability": _wara_counts(controls, "applicability"),
            "by_evaluation": _wara_counts(controls, "evaluation_status"),
            "by_satisfaction": _wara_counts(controls, "satisfaction"),
            "by_owner": _wara_counts(controls, "owner_slot"),
        },
        "controls": [
            {
                key: value
                for key, value in item.items()
                if key not in {"evidence_specifications", "crosswalk"}
            }
            for item in matched[offset : offset + limit]
        ],
        "evaluation_source": evaluation_source,
        "framework_id": stored.get("framework_id"),
        "framework_version": stored.get("framework_version"),
        "catalog_digest": stored.get("catalog_digest"),
        "source_revision_digest": stored.get("source_revision_digest"),
        "last_profile_id": stored.get("last_profile_id"),
        "last_evaluated_at": stored.get("last_evaluated_at"),
    }


def _mcsb_catalog_payload(
    stored: Mapping[str, object],
    request: WorkflowReadRequest,
) -> dict[str, object]:
    catalogs_value = stored.get("catalogs")
    evaluation_source = stored.get("evaluation_source")
    if not isinstance(catalogs_value, list) or not isinstance(evaluation_source, str):
        raise HTTPException(status_code=503, detail="authoritative MCSB catalog is malformed")
    catalogs = [item for item in catalogs_value if isinstance(item, dict)]
    if len(catalogs) != len(catalogs_value):
        raise HTTPException(status_code=503, detail="authoritative MCSB catalog is malformed")

    version = (
        request.path_parameters.get("benchmark_version")
        if request.operation is WorkflowOperation.MCSB_DETAIL
        else request.query.get("version", "v1")
    )
    selected_catalog = next(
        (
            item
            for item in catalogs
            if isinstance(item.get("benchmark"), dict)
            and item["benchmark"].get("benchmark_version") == version
        ),
        None,
    )
    if selected_catalog is None:
        raise HTTPException(status_code=404, detail=f"unknown MCSB version {version!r}")
    controls_value = selected_catalog.get("controls")
    if not isinstance(controls_value, list) or not all(
        isinstance(item, dict) for item in controls_value
    ):
        raise HTTPException(status_code=503, detail="authoritative MCSB catalog is malformed")
    controls = cast(list[dict[str, object]], controls_value)

    if request.operation is WorkflowOperation.MCSB_DETAIL:
        control_id = request.path_parameters.get("control_id", "")
        selected = next((item for item in controls if item.get("control_id") == control_id), None)
        if selected is None:
            raise HTTPException(status_code=404, detail=f"unknown MCSB control {control_id!r}")
        return dict(selected)

    domain = request.query.get("domain", "").strip().lower()
    coverage = request.query.get("coverage", "").strip().lower()
    needle = request.query.get("q", "").strip().lower()
    matched = [
        item
        for item in controls
        if (not domain or str(item.get("domain", "")).lower() == domain)
        and (not coverage or str(item.get("coverage", "")).lower() == coverage)
        and (
            not needle or needle in f"{item.get('control_id', '')}\n{item.get('title', '')}".lower()
        )
    ]
    offset = request.offset or 0
    limit = request.limit or 100
    return {
        "benchmark": selected_catalog["benchmark"],
        "versions": [
            item["benchmark"] for item in catalogs if isinstance(item.get("benchmark"), dict)
        ],
        "total": len(controls),
        "filtered_total": len(matched),
        "offset": offset,
        "limit": limit,
        "facets": {
            "by_domain": _rule_counts(controls, "domain"),
            "by_coverage": _rule_counts(controls, "coverage"),
        },
        "controls": [
            {
                key: value
                for key, value in item.items()
                if key
                not in {
                    "benchmark_version",
                    "rule_ids",
                    "runtime_observation_ids",
                    "manual_evidence_refs",
                    "source",
                    "evaluation_source",
                }
            }
            for item in matched[offset : offset + limit]
        ],
        "evaluation_source": evaluation_source,
    }


def _wara_catalog_payload(
    stored: Mapping[str, object],
    request: WorkflowReadRequest,
) -> dict[str, object]:
    controls_value = stored.get("controls")
    inventory_value = stored.get("inventory")
    evaluation_source = stored.get("evaluation_source")
    if (
        not isinstance(controls_value, list)
        or not isinstance(inventory_value, dict)
        or not isinstance(evaluation_source, str)
    ):
        raise HTTPException(status_code=503, detail="authoritative WARA catalog is malformed")
    controls = [item for item in controls_value if isinstance(item, dict)]
    if len(controls) != len(controls_value):
        raise HTTPException(status_code=503, detail="authoritative WARA catalog is malformed")

    if request.operation is WorkflowOperation.WARA_DETAIL:
        recommendation_id = request.path_parameters.get("recommendation_id", "")
        selected = next((item for item in controls if item.get("id") == recommendation_id), None)
        if selected is None:
            raise HTTPException(
                status_code=404,
                detail=f"unknown WARA recommendation {recommendation_id!r}",
            )
        return dict(selected)

    filter_fields = (
        "resource_type",
        "recommendation_control",
        "impact",
        "lifecycle",
        "product_group_verified",
        "automation_available",
        "mapping_disposition",
        "applicability",
        "evaluation_status",
        "satisfaction",
    )
    filters = {field: request.query.get(field, "").strip().lower() for field in filter_fields}
    needle = request.query.get("q", "").strip().lower()
    matched = [
        item
        for item in controls
        if all(
            not expected or str(item.get(field, "")).lower() == expected
            for field, expected in filters.items()
        )
        and (
            not needle
            or needle
            in "\n".join(
                str(item.get(field, ""))
                for field in ("id", "title", "resource_type", "recommendation_control")
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
            "by_resource_type": _wara_counts(controls, "resource_type"),
            "by_recommendation_control": _wara_counts(
                controls,
                "recommendation_control",
            ),
            "by_impact": _wara_counts(controls, "impact"),
            "by_lifecycle": _wara_counts(controls, "lifecycle"),
            "by_product_group_verified": _wara_counts(
                controls,
                "product_group_verified",
            ),
            "by_automation_available": _wara_counts(
                controls,
                "automation_available",
            ),
            "by_mapping_disposition": _wara_counts(
                controls,
                "mapping_disposition",
            ),
            "by_applicability": _wara_counts(controls, "applicability"),
            "by_evaluation": _wara_counts(controls, "evaluation_status"),
            "by_satisfaction": _wara_counts(controls, "satisfaction"),
        },
        "controls": matched[offset : offset + limit],
        "inventory": dict(inventory_value),
        "evaluation_source": evaluation_source,
        "source_revision": stored.get("source_revision"),
        "crosswalk_digest": stored.get("crosswalk_digest"),
    }
