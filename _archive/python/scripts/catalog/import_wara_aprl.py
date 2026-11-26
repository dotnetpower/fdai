#!/usr/bin/env python3
"""Import a pinned APRL checkout into the non-authoritative WARA framework catalog."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

_SOURCE_BASES = ("azure-resources", "azure-specialized-workloads", "azure-waf")
_PINNED_APRL_COMMIT = "1f421a90c157bc8894b3a47b05ba08b8650a0bd5"
_PINNED_WARA_COMMIT = "86832273f857b7298b625b26d18e2e0dbb06714c"
_PINNED_WARA_VERSION = "v1.0.6"
_SOURCE_VERSION = "2026-08-24"
_RETRIEVED_AT = "2026-08-31T00:00:00Z"


def _sha256_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _area_id(path: Path) -> str:
    stem = str(path.parent).casefold().replace("\\", "/")
    return re.sub(r"[^a-z0-9._-]+", "-", stem.replace("/", ".")).strip("-")


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} MUST be a mapping")
    return value


def _published_by_guid(path: Path) -> tuple[dict[str, dict[str, Any]], str]:
    body = path.read_bytes()
    raw = json.loads(body)
    if not isinstance(raw, list):
        raise ValueError("published WARA object MUST be an array")
    by_guid: dict[str, dict[str, Any]] = {}
    for index, value in enumerate(raw):
        item = _mapping(value, f"published[{index}]")
        guid = str(item.get("aprlGuid"))
        if guid in by_guid:
            raise ValueError(f"duplicate published WARA GUID {guid!r}")
        by_guid[guid] = item
    return by_guid, _sha256_bytes(body)


def _recommendation(
    raw: dict[str, Any],
    *,
    source_path: str,
    source_digest: str,
    published: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    guid = str(raw["aprlGuid"])
    state = str(raw["recommendationMetadataState"])
    published_item = published.get(guid)
    if state == "Active" and published_item is None:
        raise ValueError(f"active WARA recommendation {guid!r} missing from published object")
    if state == "Disabled" and published_item is not None:
        raise ValueError(f"disabled WARA recommendation {guid!r} appears in published object")
    for field in (
        "description",
        "recommendationTypeId",
        "recommendationControl",
        "recommendationImpact",
        "recommendationResourceType",
        "recommendationMetadataState",
        "pgVerified",
        "automationAvailable",
        "tags",
        "longDescription",
        "potentialBenefits",
        "learnMoreLink",
    ):
        if published_item is not None and published_item.get(field) != raw.get(field):
            raise ValueError(f"published WARA field drift for {guid}:{field}")
    links = raw.get("learnMoreLink") or []
    if len(links) > 1:
        raise ValueError(f"WARA recommendation {guid!r} has multiple learn-more links")
    link = _mapping(links[0], f"{guid}.learnMoreLink") if links else None
    query = published_item.get("query") if published_item is not None else None
    query_digest = _sha256_text(query) if isinstance(query, str) else None
    return {
        "id": guid,
        "title": str(raw["description"]).strip(),
        "description": str(raw["longDescription"]).strip(),
        "best_practice_ref": None,
        "objective_refs": [],
        "mapping_status": "reference_only",
        "applicability": "resource_type_and_workload_review_required",
        "wara": {
            "recommendation_type_id": raw.get("recommendationTypeId"),
            "control": str(raw["recommendationControl"]),
            "impact": str(raw["recommendationImpact"]),
            "resource_type": str(raw["recommendationResourceType"]),
            "state": state,
            "product_group_verified": bool(raw["pgVerified"]),
            "automation_available": bool(raw["automationAvailable"]),
            "tags": sorted(str(item) for item in raw.get("tags", [])),
            "potential_benefits": str(raw["potentialBenefits"]).strip(),
            "learn_more_name": str(link["name"]) if link is not None else None,
            "learn_more_url": str(link["url"]) if link is not None else None,
            "source_path": source_path,
            "source_digest": source_digest,
            "query_digest": query_digest,
        },
    }


def import_catalog(source_root: Path, published_object: Path) -> dict[str, Any]:
    """Return a complete WARA framework snapshot from exact pinned inputs."""

    published, published_digest = _published_by_guid(published_object)
    areas: list[dict[str, Any]] = []
    all_controls: list[dict[str, Any]] = []
    for base in _SOURCE_BASES:
        for path in sorted((source_root / base).rglob("recommendations.yaml")):
            relative = str(path.relative_to(source_root))
            body = path.read_bytes()
            raw = yaml.safe_load(body) or []
            if not isinstance(raw, list):
                raise ValueError(f"{relative} MUST contain a recommendation array")
            if not raw:
                raise ValueError(f"{relative} MUST contain at least one recommendation")
            controls = [
                _recommendation(
                    _mapping(item, f"{relative}[{index}]"),
                    source_path=relative,
                    source_digest=_sha256_bytes(body),
                    published=published,
                )
                for index, item in enumerate(raw)
            ]
            controls.sort(key=lambda item: str(item["id"]))
            all_controls.extend(controls)
            areas.append(
                {
                    "id": _area_id(path.relative_to(source_root)),
                    "source_url": (
                        "https://raw.githubusercontent.com/Azure/"
                        "Azure-Proactive-Resiliency-Library-v2/"
                        f"{_PINNED_APRL_COMMIT}/{relative}"
                    ),
                    "source_version": _SOURCE_VERSION,
                    "resolved_ref": _PINNED_APRL_COMMIT,
                    "retrieved_at": _RETRIEVED_AT,
                    "source_path": relative,
                    "source_digest": _sha256_bytes(body),
                    "controls": controls,
                }
            )
    guids = [str(item["id"]) for item in all_controls]
    if len(guids) != len(set(guids)):
        duplicates = sorted(guid for guid, count in Counter(guids).items() if count > 1)
        raise ValueError(f"duplicate APRL GUIDs: {duplicates}")
    active = [item for item in all_controls if item["wara"]["state"] == "Active"]
    disabled_count = len(all_controls) - len(active)
    active_guids = {str(item["id"]) for item in active}
    if active_guids != set(published):
        raise ValueError("pinned APRL active GUIDs do not match the published WARA object")
    source_set = sorted((str(area["source_path"]), str(area["source_digest"])) for area in areas)
    source_set_digest = _sha256_text(json.dumps(source_set, separators=(",", ":")))
    return {
        "schema_version": "1.0.0",
        "kind": "framework-definition",
        "id": "azure-wara",
        "version": "2026-08-31",
        "name": "Azure Well-Architected Reliability Assessment",
        "scope": "workload-and-resource",
        "advisory": True,
        "completeness_scope": (
            f"All {len(all_controls)} APRL recommendations from {len(areas)} source "
            f"files at the pinned commit. The {len(active)} active recommendations "
            "exactly match the object consumed by "
            f"WARA {_PINNED_WARA_VERSION}; {disabled_count} disabled recommendations "
            "are retained for lifecycle completeness."
        ),
        "inventory": {
            "total_controls": len(all_controls),
            "active_controls": len(active),
            "disabled_controls": disabled_count,
            "area_count": len(areas),
            "resource_type_count": len(
                {str(item["wara"]["resource_type"]).casefold() for item in active}
            ),
            "automated_active_controls": sum(
                bool(item["wara"]["automation_available"]) for item in active
            ),
            "product_group_verified_active_controls": sum(
                bool(item["wara"]["product_group_verified"]) for item in active
            ),
            "published_active_digest": published_digest,
            "source_set_digest": source_set_digest,
        },
        "sources": [
            {
                "id": "aprl",
                "source_url": ("https://github.com/Azure/Azure-Proactive-Resiliency-Library-v2"),
                "source_version": _SOURCE_VERSION,
                "resolved_ref": _PINNED_APRL_COMMIT,
                "retrieved_at": _RETRIEVED_AT,
            },
            {
                "id": "wara",
                "source_url": ("https://github.com/Azure/Well-Architected-Reliability-Assessment"),
                "source_version": "2025-05-22",
                "resolved_ref": _PINNED_WARA_COMMIT,
                "retrieved_at": _RETRIEVED_AT,
            },
            {
                "id": "wara-published-object",
                "source_url": ("https://azure.github.io/WARA-Build/objects/recommendations.json"),
                "source_version": _SOURCE_VERSION,
                "resolved_ref": _PINNED_APRL_COMMIT,
                "retrieved_at": _RETRIEVED_AT,
            },
        ],
        "areas": sorted(areas, key=lambda item: str(item["id"])),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--published-object", type=Path, required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("rule-catalog/collected/wara-aprl/azure-wara.json"),
    )
    args = parser.parse_args()
    catalog = import_catalog(args.source_root, args.published_object)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.suffix == ".json":
        rendered = json.dumps(catalog, ensure_ascii=False, indent=2) + "\n"
    else:
        rendered = yaml.safe_dump(
            catalog,
            sort_keys=False,
            allow_unicode=True,
            width=120,
        )
    args.output.write_text(rendered, encoding="utf-8")
    inventory = catalog["inventory"]
    print(
        "imported "
        f"{inventory['total_controls']} WARA/APRL recommendations "
        f"({inventory['active_controls']} active, "
        f"{inventory['disabled_controls']} disabled)"
    )


if __name__ == "__main__":
    main()
