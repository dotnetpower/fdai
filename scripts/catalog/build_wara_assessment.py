#!/usr/bin/env python3
"""Build derived WARA assessment records from the existing pinned catalog."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path
from typing import Any

import yaml
from fdai.rule_catalog.schema.wara_assessment import canonical_digest, classify_wara_query

_EXPECTED = {
    "active_recommendations": 393,
    "disabled_recommendations": 63,
    "resource_types": 80,
    "automated_recommendations": 143,
    "manual_recommendations": 250,
}
_MANUAL_KIND = {
    "BusinessContinuity": ("business_continuity_plan", 7_776_000),
    "DisasterRecovery": ("recovery_drill", 7_776_000),
    "HighAvailability": ("architecture_review", 7_776_000),
    "MonitoringAndAlerting": ("monitoring_configuration", 2_592_000),
    "OtherBestPractices": ("expert_assessment", 7_776_000),
    "Personalized": ("expert_assessment", 2_592_000),
    "Scalability": ("capacity_evidence", 2_592_000),
    "Security": ("security_review", 2_592_000),
    "ServiceUpgradeAndRetirement": ("service_lifecycle_review", 2_592_000),
}


def _load_object(path: Path) -> dict[str, Any]:
    value: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected JSON object")
    return value


def _load_array(path: Path) -> list[dict[str, Any]]:
    value: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ValueError(f"{path}: expected JSON object array")
    return value


def _sha256_text(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"


def _parent_provider_type(normalized: str) -> str | None:
    segments = normalized.split("/")
    return "/".join(segments[:-1]) if len(segments) > 2 else None


def _resource_mappings(path: Path) -> dict[str, tuple[str, ...]]:
    raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not isinstance(raw.get("types"), list):
        raise ValueError("resource type registry is malformed")
    collected: dict[str, set[str]] = {}
    for item in raw["types"]:
        if not isinstance(item, dict):
            raise ValueError("resource type entry MUST be an object")
        provider_type = item.get("azure_arm_type")
        if isinstance(provider_type, str):
            normalized = provider_type.casefold()
            collected.setdefault(normalized, set()).add(str(item["id"]))
    return {key: tuple(sorted(values)) for key, values in collected.items()}


def _validate_source_registry(path: Path) -> None:
    raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not isinstance(raw.get("sources"), list):
        raise ValueError("source registry is malformed")
    by_id = {str(item.get("id")): item for item in raw["sources"] if isinstance(item, dict)}
    for source_id in ("aprl", "wara"):
        source = by_id.get(source_id)
        if source is None:
            raise ValueError(f"source registry is missing {source_id}")
        if source.get("license") != "MIT" or source.get("redistribution") != "embeddable":
            raise ValueError(f"{source_id} source license is not admitted for embedding")


def build_catalog(
    framework_path: Path,
    published_path: Path,
    resource_types_path: Path,
    source_registry_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build conservative reviewed assessment and external query catalogs."""

    _validate_source_registry(source_registry_path)
    framework = _load_object(framework_path)
    inventory = framework.get("inventory")
    if not isinstance(inventory, dict):
        raise ValueError("WARA framework inventory is required")
    actual_counts = {
        "active_recommendations": inventory.get("active_controls"),
        "disabled_recommendations": inventory.get("disabled_controls"),
        "resource_types": inventory.get("resource_type_count"),
        "automated_recommendations": inventory.get("automated_active_controls"),
        "manual_recommendations": int(inventory.get("active_controls", 0))
        - int(inventory.get("automated_active_controls", 0)),
    }
    if actual_counts != _EXPECTED:
        raise ValueError(f"pinned WARA inventory changed: {actual_counts!r}")
    published_body = published_path.read_bytes()
    published_digest = f"sha256:{hashlib.sha256(published_body).hexdigest()}"
    if published_digest != inventory.get("published_active_digest"):
        raise ValueError("published WARA object digest does not match pinned catalog")
    published = _load_array(published_path)
    published_by_id = {str(item.get("aprlGuid")): item for item in published}
    if len(published) != _EXPECTED["active_recommendations"] or len(published_by_id) != len(
        published
    ):
        raise ValueError("published WARA GUIDs are incomplete or duplicated")

    active: list[dict[str, Any]] = []
    disabled = 0
    areas = framework.get("areas")
    if not isinstance(areas, list):
        raise ValueError("WARA framework areas are malformed")
    for area in areas:
        if not isinstance(area, dict) or not isinstance(area.get("controls"), list):
            raise ValueError("WARA framework area is malformed")
        for control in area["controls"]:
            if not isinstance(control, dict) or not isinstance(control.get("wara"), dict):
                raise ValueError("WARA framework control is malformed")
            if control["wara"].get("state") == "Disabled":
                disabled += 1
                continue
            active.append(control)
    if (
        len(active) != _EXPECTED["active_recommendations"]
        or disabled != _EXPECTED["disabled_recommendations"]
    ):
        raise ValueError("WARA framework lifecycle counts changed")

    canonical_types = _resource_mappings(resource_types_path)
    resource_mappings: dict[str, dict[str, Any]] = {}
    recommendations: list[dict[str, Any]] = []
    queries: list[dict[str, Any]] = []
    umbrella_relations: list[dict[str, Any]] = []

    for control in sorted(active, key=lambda item: str(item["id"])):
        guid = str(control["id"])
        metadata = control["wara"]
        published_item = published_by_id.get(guid)
        if published_item is None:
            raise ValueError(f"active WARA GUID {guid!r} missing from published object")
        provider_type = str(metadata["resource_type"])
        normalized_type = provider_type.casefold()
        canonical_candidates = canonical_types.get(normalized_type, ())
        canonical_type = canonical_candidates[0] if len(canonical_candidates) == 1 else None
        resource_disposition = (
            "canonical"
            if canonical_type is not None
            else "ambiguous"
            if canonical_candidates
            else "unsupported"
        )
        parent_type = _parent_provider_type(normalized_type)
        mapping = {
            "normalized_provider_type": normalized_type,
            "disposition": resource_disposition,
            "canonical_resource_type": canonical_type,
            "parent_provider_type": parent_type,
            "requires_exact_child_scope": parent_type is not None,
        }
        resource_mappings.setdefault(
            normalized_type,
            {**mapping, "reviewer": "fdai-maintainers"},
        )
        automated = bool(metadata["automation_available"])
        query_review: dict[str, Any] | None = None
        manual_evidence: dict[str, Any] | None = None
        if automated:
            query = published_item.get("query")
            if not isinstance(query, str) or not query.strip():
                raise ValueError(f"automated WARA GUID {guid!r} has no query body")
            body_digest = _sha256_text(query)
            if body_digest != metadata.get("query_digest"):
                raise ValueError(f"WARA query digest drift for {guid}")
            classification, safety_reasons, tables, query_resource_types = classify_wara_query(
                query,
                declared_provider_type=normalized_type,
            )
            query_review = {
                "query_ref": f"queries.json#{guid}",
                "body_digest": body_digest,
                "safety_classification": classification.value,
                "declared_tables": list(tables),
                "query_resource_types": list(query_resource_types),
                "maximum_rows": 500,
                "timeout_seconds": 30,
                "evidence_freshness_ceiling_seconds": 86_400,
                "evaluator_ref": None,
                "blocked_reasons": sorted({*safety_reasons, "missing_exact_evaluator"}),
            }
            queries.append(
                {
                    "aprl_guid": guid,
                    "body_digest": body_digest,
                    "body_base64": base64.b64encode(query.encode("utf-8")).decode("ascii"),
                }
            )
        else:
            control_name = str(metadata["control"])
            kind, freshness = _MANUAL_KIND.get(
                control_name,
                ("expert_assessment", 2_592_000),
            )
            manual_evidence = {
                "kind": kind,
                "authoritative_producer": "workload-evidence-owner",
                "scope_contract": "exact-workload-and-resource-scope",
                "freshness_ceiling_seconds": freshness,
                "digest_required": True,
                "failure_behavior": "unknown",
                "accountable_owner_slot": "workload-reliability-owner",
                "blocked_reason": None,
            }
        tags = sorted(str(item) for item in metadata.get("tags", []))
        recommendation = {
            "aprl_guid": guid,
            "title": str(control["title"]),
            "recommendation_control": str(metadata["control"]),
            "impact": str(metadata["impact"]),
            "provider_resource_type": provider_type,
            "source_path": str(metadata["source_path"]),
            "source_digest": str(metadata["source_digest"]),
            "workload_tags": tags,
            "automation_available": automated,
            "product_group_verified": bool(metadata["product_group_verified"]),
            "disposition": "ambiguous_or_blocked" if automated else "manual_evidence",
            "mapping_state": "unmapped",
            "rule_refs": [],
            "objective_refs": [],
            "applicability": mapping,
            "query_review": query_review,
            "manual_evidence": manual_evidence,
            "reviewer": "fdai-maintainers",
            "review_state": "reviewed-conservative",
        }
        recommendation["implementation_digest"] = canonical_digest(recommendation)
        recommendations.append(recommendation)

        if str(metadata["source_path"]) == "azure-waf/reliability/recommendations.yaml":
            title = str(control["title"])
            waf_id = title.split(" ", 1)[0]
            if not waf_id.startswith("RE:"):
                raise ValueError(f"WAF umbrella recommendation lacks control id: {guid}")
            umbrella_relations.append(
                {
                    "aprl_guid": guid,
                    "waf_control_ref": f"azure-waf:{waf_id}",
                    "relation": "specializes",
                    "semantic_equivalence": False,
                    "counting": "independent_aprl_guid",
                }
            )

    if len(resource_mappings) != _EXPECTED["resource_types"]:
        raise ValueError("WARA resource mapping count changed")
    query_catalog: dict[str, Any] = {
        "schema_version": "1.0.0",
        "source_revision": str(framework["sources"][0]["resolved_ref"]),
        "published_active_digest": published_digest,
        "queries": sorted(queries, key=lambda item: str(item["aprl_guid"])),
    }
    query_catalog["queries_digest"] = canonical_digest(query_catalog)
    source_catalog_digest = f"sha256:{hashlib.sha256(framework_path.read_bytes()).hexdigest()}"
    crosswalk: dict[str, Any] = {
        "schema_version": "1.0.0",
        "framework_id": str(framework["id"]),
        "framework_version": str(framework["version"]),
        "source_revision": str(framework["sources"][0]["resolved_ref"]),
        "source_license": "MIT",
        "redistribution": "embeddable",
        "source_catalog_digest": source_catalog_digest,
        "published_active_digest": published_digest,
        "queries_digest": query_catalog["queries_digest"],
        "expected_counts": _EXPECTED,
        "resource_type_mappings": [resource_mappings[key] for key in sorted(resource_mappings)],
        "umbrella_relations": sorted(
            umbrella_relations,
            key=lambda item: (str(item["waf_control_ref"]), str(item["aprl_guid"])),
        ),
        "recommendations": recommendations,
    }
    crosswalk["crosswalk_digest"] = canonical_digest(crosswalk)
    return crosswalk, query_catalog


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--framework",
        type=Path,
        default=Path("rule-catalog/collected/wara-aprl/azure-wara.json"),
    )
    parser.add_argument("--published-object", type=Path, required=True)
    parser.add_argument(
        "--resource-types",
        type=Path,
        default=Path("rule-catalog/vocabulary/resource-types.yaml"),
    )
    parser.add_argument(
        "--source-registry",
        type=Path,
        default=Path("rule-catalog/sources/registry.yaml"),
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("rule-catalog/collected/wara-aprl/assessment"),
    )
    args = parser.parse_args()
    crosswalk, queries = build_catalog(
        args.framework,
        args.published_object,
        args.resource_types,
        args.source_registry,
    )
    _write_json(args.output_root / "crosswalk.json", crosswalk)
    _write_json(args.output_root / "queries.json", queries)
    print(
        "built WARA assessment catalog "
        f"({len(crosswalk['recommendations'])} recommendations, "
        f"{len(queries['queries'])} queries)"
    )


if __name__ == "__main__":
    main()
