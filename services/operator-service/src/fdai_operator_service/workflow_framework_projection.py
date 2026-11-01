"""CAF, MCSB, and WARA workflow catalog projections."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from typing import cast

from fdai_service_contracts.framework_guidance import localized_framework_titles
from fdai_service_contracts.wara_guidance import localized_wara_titles, wara_guidance_detail
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
    korean_titles = localized_framework_titles(controls, framework_id="azure-caf")
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
                [
                    *(
                        str(item.get(field, ""))
                        for field in ("control_id", "title", "description", "area")
                    ),
                    korean_titles.get(str(item.get("control_id", "")), ""),
                ]
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
                **(
                    {
                        key: value
                        for key, value in item.items()
                        if key not in {"evidence_specifications", "crosswalk"}
                    }
                ),
                **(
                    {"title_ko": korean_titles[str(item.get("control_id"))]}
                    if str(item.get("control_id")) in korean_titles
                    else {}
                ),
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
    korean_titles = (
        localized_framework_titles(controls, framework_id="azure-mcsb") if version == "v1" else {}
    )
    matched = [
        item
        for item in controls
        if (not domain or str(item.get("domain", "")).lower() == domain)
        and (not coverage or str(item.get("coverage", "")).lower() == coverage)
        and (
            not needle
            or needle
            in "\n".join(
                (
                    str(item.get("control_id", "")),
                    str(item.get("title", "")),
                    korean_titles.get(str(item.get("control_id", "")), ""),
                )
            ).lower()
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
                **{
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
                        "guidance_source_revision",
                        "guidance_source_digest",
                    }
                },
                **(
                    {"title_ko": korean_titles[str(item.get("control_id"))]}
                    if str(item.get("control_id")) in korean_titles
                    else {}
                ),
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
        try:
            return wara_guidance_detail(dict(selected))
        except ValueError as exc:
            raise HTTPException(
                status_code=503,
                detail="WARA guidance source validation failed",
            ) from exc

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
    korean_titles = localized_wara_titles(controls)
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
                [
                    *(
                        str(item.get(field, ""))
                        for field in ("id", "title", "resource_type", "recommendation_control")
                    ),
                    korean_titles.get(str(item.get("id", "")), ""),
                ]
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
        "controls": [
            {**item, "title_ko": korean_titles[str(item.get("id"))]}
            if str(item.get("id")) in korean_titles
            else item
            for item in matched[offset : offset + limit]
        ],
        "inventory": dict(inventory_value),
        "evaluation_source": evaluation_source,
        "source_revision": stored.get("source_revision"),
        "crosswalk_digest": stored.get("crosswalk_digest"),
    }


def _msrc_csaf_catalog_payload(
    stored: Mapping[str, object],
    request: WorkflowReadRequest,
) -> dict[str, object]:
    controls_value = stored.get("controls")
    evaluation_source = stored.get("evaluation_source")
    source_revision = stored.get("source_revision")
    advisories_digest = stored.get("advisories_digest")
    crosswalk_digest = stored.get("crosswalk_digest")
    if (
        not isinstance(controls_value, list)
        or not isinstance(evaluation_source, str)
        or not isinstance(source_revision, str)
        or not isinstance(advisories_digest, str)
        or not isinstance(crosswalk_digest, str)
    ):
        raise HTTPException(
            status_code=503,
            detail="authoritative MSRC CSAF catalog is malformed",
        )
    controls = [item for item in controls_value if isinstance(item, dict)]
    if len(controls) != len(controls_value) or any(
        item.get("execution_authority") is not False for item in controls
    ):
        raise HTTPException(
            status_code=503,
            detail="authoritative MSRC CSAF catalog is malformed",
        )

    if request.operation is WorkflowOperation.MSRC_CSAF_DETAIL:
        cve_id = request.path_parameters.get("cve_id", "").strip()
        # C29: Validate CVE/ADV identifier format on detail lookup and return 404 when unknown
        selected = next((item for item in controls if item.get("cve_id") == cve_id), None)
        if not cve_id or selected is None:
            raise HTTPException(
                status_code=404,
                detail=f"unknown MSRC CSAF vulnerability {cve_id!r}",
            )
        return dict(selected)

    # C26 & V22: Support evaluation_status, exposure, kev_sla_tier, and vex_justification filters
    filter_fields = (
        "year",
        "severity",
        "exploit_status",
        "disposition",
        "mapping_state",
        "primary_resource_type",
        "evaluation_status",
        "exposure",
        "kev_sla_tier",
        "vex_justification",
    )
    filters = {
        field: request.query.get(
            "resource_type" if field == "primary_resource_type" else field,
            "",
        )
        .strip()
        .lower()
        for field in filter_fields
    }
    # V23: Support attack_surface query filter (zero_click, pre_auth_network, wormable)
    attack_surface = request.query.get("attack_surface", "").strip().lower()
    surface_flag_map = {
        "zero_click": "is_zero_click",
        "pre_auth_network": "is_pre_auth_network",
        "wormable": "is_wormable_candidate",
    }
    needle_tokens = [tok for tok in request.query.get("q", "").strip().lower().split() if tok]

    def _matches_control(item: dict[str, object]) -> bool:
        if not all(
            not expected or str(item.get(field, "")).lower() == expected
            for field, expected in filters.items()
        ):
            return False
        if (
            attack_surface in surface_flag_map
            and item.get(surface_flag_map[attack_surface]) is not True
        ):
            return False
        if not needle_tokens:
            return True
        # C28, V26, V27: Multi-token AND search across all identifying and crosswalk fields
        haystack = "\n".join(
            [
                *(
                    str(item.get(field, ""))
                    for field in (
                        "cve_id",
                        "title",
                        "advisory_tracking_id",
                        "advisory_title",
                        "primary_resource_type",
                        "existing_rule_id",
                        "candidate_action_type",
                        "kev_sla_tier",
                        "vex_justification",
                    )
                ),
                *(
                    str(pid)
                    for pid in (
                        cast(list[object], item["product_ids"])
                        if isinstance(item.get("product_ids"), list)
                        else []
                    )
                ),
            ]
        ).lower()
        return all(tok in haystack for tok in needle_tokens)

    matched = [item for item in controls if _matches_control(item)]
    # C27 & V25: Sort matched controls by requested sort mode (threat/cvss/recent/cve/risk_score)
    sort_mode = request.query.get("sort", "threat").strip().lower() or "threat"
    exploit_rank = {
        "exploited": 5,
        "exploitation_more_likely": 4,
        "publicly_disclosed": 3,
        "exploitation_less_likely": 2,
        "exploitation_unlikely": 1,
        "unproven": 0,
    }
    if sort_mode == "cvss":
        matched.sort(
            key=lambda item: (
                -float(item.get("cvss_base_score", 0.0))
                if isinstance(item.get("cvss_base_score"), (int, float))
                else 0.0,
                str(item.get("cve_id", "")),
            )
        )
    elif sort_mode == "risk_score":
        matched.sort(
            key=lambda item: (
                -float(item.get("risk_score", 0.0))
                if isinstance(item.get("risk_score"), (int, float))
                else 0.0,
                -float(item.get("cvss_base_score", 0.0))
                if isinstance(item.get("cvss_base_score"), (int, float))
                else 0.0,
                str(item.get("cve_id", "")),
            )
        )
    elif sort_mode == "recent":
        matched.sort(
            key=lambda item: (
                str(item.get("current_release_date", "")),
                str(item.get("cve_id", "")),
            ),
            reverse=True,
        )
    elif sort_mode == "cve":
        matched.sort(key=lambda item: str(item.get("cve_id", "")))
    else:
        matched.sort(
            key=lambda item: (
                -exploit_rank.get(str(item.get("exploit_status", "")), 0),
                -float(item.get("cvss_base_score", 0.0))
                if isinstance(item.get("cvss_base_score"), (int, float))
                else 0.0,
                str(item.get("cve_id", "")),
            )
        )
    # V28, V29, V30: Clamp offset/limit bounds and include active_filters + VEX/SLA facets
    offset = max(0, request.offset or 0)
    limit = max(1, min(500, request.limit or 100))
    active_filters = {
        k: v
        for k, v in {
            **filters,
            "attack_surface": attack_surface,
            "q": " ".join(needle_tokens),
            "sort": sort_mode if sort_mode != "threat" else "",
        }.items()
        if v
    }
    response: dict[str, object] = {
        "schema_version": str(stored.get("schema_version") or "1.0.0"),
        "source_id": "msrc_csaf",
        "source_revision": source_revision,
        "advisories_digest": advisories_digest,
        "crosswalk_digest": crosswalk_digest,
        "evaluation_source": evaluation_source,
        "total": len(controls),
        "filtered_total": len(matched),
        "offset": offset,
        "limit": limit,
        "active_filters": active_filters,
        "facets": {
            "by_year": _wara_counts(controls, "year"),
            "by_severity": _wara_counts(controls, "severity"),
            "by_exploit_status": _wara_counts(controls, "exploit_status"),
            "by_disposition": _wara_counts(controls, "disposition"),
            "by_mapping_state": _wara_counts(controls, "mapping_state"),
            "by_resource_type": _wara_counts(controls, "primary_resource_type"),
            "by_evaluation_status": _wara_counts(controls, "evaluation_status"),
            "by_exposure": _wara_counts(controls, "exposure"),
            "by_kev_sla_tier": _wara_counts(controls, "kev_sla_tier"),
            "by_vex_justification": _wara_counts(controls, "vex_justification"),
        },
        "controls": [dict(item) for item in matched[offset : offset + limit]],
    }
    # C30: Preserve optional summary, last_workload_id, and last_evaluated_at metadata
    if isinstance(stored.get("summary"), Mapping):
        response["summary"] = dict(cast(Mapping[str, object], stored["summary"]))
    if isinstance(stored.get("last_workload_id"), str):
        response["last_workload_id"] = stored["last_workload_id"]
    if isinstance(stored.get("last_evaluated_at"), str):
        response["last_evaluated_at"] = stored["last_evaluated_at"]
    return response
