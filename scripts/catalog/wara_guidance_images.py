"""Review cited Learn documents and apply only approved local WARA image decisions."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

if __package__:
    from .wara_guidance_image_manifest import (
        REVIEW_REASONS as _REVIEW_REASONS,
    )
    from .wara_guidance_image_manifest import (
        compact_manifest as _compact_manifest,
    )
    from .wara_guidance_image_manifest import (
        expand_compact_manifest as _expand_compact_manifest,
    )
    from .wara_guidance_image_manifest import recompute_summary as _recompute_summary
else:
    from wara_guidance_image_manifest import (
        REVIEW_REASONS as _REVIEW_REASONS,
    )
    from wara_guidance_image_manifest import (
        compact_manifest as _compact_manifest,
    )
    from wara_guidance_image_manifest import (
        expand_compact_manifest as _expand_compact_manifest,
    )
    from wara_guidance_image_manifest import recompute_summary as _recompute_summary

_ROOT = Path(__file__).resolve().parents[2]
_FRAMEWORK_PATH = _ROOT / "rule-catalog/collected/wara-aprl/azure-wara.json"
_DATA_PATH = _ROOT / "packages/service-contracts/src/fdai_service_contracts/data"
_MANIFEST_PATH = _ROOT / "rule-catalog/guidance/azure-wara/reference-images.json"
_LEARN_COMMIT = "6e232e43ce97e38e61c9a265b3148485e5414892"
_VM_BACKUP_DOCUMENT = "https://learn.microsoft.com/en-us/azure/backup/backup-azure-vms-introduction"
_VM_BACKUP_IMAGE = (
    "https://learn.microsoft.com/en-us/azure/backup/media/"
    "backup-azure-vms-introduction/vmbackup-architecture.png"
)
_VM_BACKUP_CITATION = "https://learn.microsoft.com/azure/backup/backup-overview"
_GUID = re.compile(r"^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$")
_REVISION = re.compile(r"^[a-f0-9]{40}$")
_MAXIMUM_MANIFEST_BYTES = 8_388_608


def _framework_identities() -> tuple[str, ...]:
    try:
        framework = json.loads(_FRAMEWORK_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("the pinned WARA framework cannot be read") from exc
    identities = tuple(
        control["id"]
        for area in framework["areas"]
        for control in area["controls"]
        if isinstance(control.get("id"), str)
    )
    if len(identities) != 456 or len(set(identities)) != 456:
        raise ValueError("the pinned WARA framework does not contain 456 unique recommendations")
    if any(_GUID.fullmatch(identity) is None for identity in identities):
        raise ValueError("the pinned WARA framework contains an invalid recommendation identity")
    return tuple(sorted(identities))


def _learn_inventory() -> tuple[dict[str, list[str]], dict[str, list[str]], str, str]:
    try:
        manifest = json.loads((_DATA_PATH / "wara-guidance.json").read_text(encoding="utf-8"))
        groups: dict[str, set[str]] = {}
        recommendation_urls: dict[str, set[str]] = {
            identity: set() for identity in _framework_identities()
        }
        for reference in manifest["shards"]:
            shard = json.loads((_DATA_PATH / reference["path"]).read_text(encoding="utf-8"))
            for entry in shard["entries"]:
                identity = entry["recommendation_id"]
                for source in entry["sources"]:
                    if source["kind"] == "learn":
                        url = source["url"]
                        groups.setdefault(url, set()).add(identity)
                        recommendation_urls.setdefault(identity, set()).add(url)
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("the generated WARA guidance citations cannot be read") from exc
    if set(recommendation_urls) != set(_framework_identities()):
        raise ValueError("Learn citation inventory does not match the pinned WARA framework")
    return (
        {url: sorted(identities) for url, identities in sorted(groups.items())},
        {identity: sorted(urls) for identity, urls in recommendation_urls.items()},
        str(manifest["framework_revision"]),
        str(manifest["catalog_digest"]),
    )


def _related_backup_candidate() -> dict[str, object]:
    return {
        "source_document_url": _VM_BACKUP_DOCUMENT,
        "image_url": _VM_BACKUP_IMAGE,
        "source_revision": _LEARN_COMMIT,
        "candidate_suitability": "technically_relevant_rights_blocked",
        "reason": _REVIEW_REASONS["rights_verification_blocked"],
    }


def _initial_manifest() -> dict[str, object]:
    groups, recommendation_urls, framework_revision, catalog_digest = _learn_inventory()
    document_groups = []
    for url, identities in groups.items():
        document_groups.append(
            {
                "source_document_url": url,
                "recommendation_ids": identities,
                "inspection_status": "unreviewed",
                "candidate_suitability": "not_assessed",
                "inspection_reason": (
                    "This exact cited Learn URL has not yet been fetched and inspected."
                ),
                "inspection": None,
                "candidates": [],
            }
        )
    if _VM_BACKUP_CITATION in groups:
        backup_group = next(
            group
            for group in document_groups
            if group["source_document_url"] == _VM_BACKUP_CITATION
        )
        backup_group["related_candidate_research"] = [_related_backup_candidate()]
    recommendations = [
        {
            "recommendation_id": identity,
            "learn_document_urls": recommendation_urls[identity],
            "review_status": "unreviewed",
            "decision": "document_review_pending",
            "reason": (
                "At least one exact cited Learn document has not been inspected. This is not "
                "evidence that a suitable official image does not exist."
            ),
        }
        for identity in _framework_identities()
    ]
    return {
        "schema_version": "1.0.0",
        "framework_revision": framework_revision,
        "catalog_digest": catalog_digest,
        "recommendation_count": len(recommendations),
        "learn_citation_count": sum(len(urls) for urls in recommendation_urls.values()),
        "document_group_count": len(document_groups),
        "recommendations": recommendations,
        "document_groups": document_groups,
        "summary": {},
    }


def _validate_manifest(value: Any) -> dict[str, Any]:
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != "1.0.0"
        or value.get("recommendation_count") != 456
        or not isinstance(value.get("recommendations"), list)
        or not isinstance(value.get("document_groups"), list)
    ):
        raise ValueError("WARA image review manifest has an invalid envelope")
    source_groups, recommendation_urls, framework_revision, catalog_digest = _learn_inventory()
    if (
        value.get("framework_revision") != framework_revision
        or value.get("catalog_digest") != catalog_digest
        or value.get("document_group_count") != len(source_groups)
        or value.get("learn_citation_count")
        != sum(len(urls) for urls in recommendation_urls.values())
    ):
        raise ValueError("WARA image review manifest does not match the generated WARA catalog")
    if set(item.get("source_document_url") for item in value["document_groups"]) != set(
        source_groups
    ):
        raise ValueError("WARA image review manifest does not cover every exact Learn URL")
    groups: dict[str, dict[str, Any]] = {}
    for item in value["document_groups"]:
        url = item.get("source_document_url")
        if (
            not isinstance(url, str)
            or url in groups
            or item.get("recommendation_ids") != source_groups[url]
            or item.get("inspection_status") not in {"unreviewed", "inspected", "fetch_failed"}
            or not isinstance(item.get("candidate_suitability"), str)
            or not isinstance(item.get("candidates"), list)
        ):
            raise ValueError("WARA Learn document review group is invalid")
        for candidate in item["candidates"]:
            if (
                not isinstance(candidate, dict)
                or not isinstance(candidate.get("image_url"), str)
                or candidate.get("suitability") != "requires_visual_and_rights_review"
            ):
                raise ValueError("WARA Learn image candidate metadata is invalid")
        groups[url] = item
    records: dict[str, dict[str, Any]] = {}
    for item in value["recommendations"]:
        if not isinstance(item, dict):
            raise ValueError("WARA image recommendation review is invalid")
        identity = item.get("recommendation_id")
        if (
            not isinstance(identity, str)
            or _GUID.fullmatch(identity) is None
            or identity in records
            or item.get("learn_document_urls") != recommendation_urls.get(identity)
            or not isinstance(item.get("reason"), str)
        ):
            raise ValueError("WARA image recommendation review is incomplete")
        reference = item.get("reference_image")
        if item.get("decision") == "selected":
            if not isinstance(reference, dict):
                raise ValueError("a selected WARA image requires complete provenance")
            from fdai_service_contracts.reference_image_assets import load_packaged_reference_image
            from fdai_service_contracts.wara_guidance import ReferenceImage

            model = ReferenceImage.model_validate(reference)
            load_packaged_reference_image(model)
        elif reference is not None:
            raise ValueError("an unselected WARA image must not carry a renderable asset")
        records[identity] = item
    if set(records) != set(_framework_identities()):
        raise ValueError("WARA image review manifest does not cover all 456 recommendations")
    result = dict(value)
    result["recommendation_records"] = records
    _recompute_summary(result)
    if value.get("summary") != result["summary"]:
        raise ValueError("WARA image review manifest summary is stale")
    return result


def _save_manifest(value: dict[str, Any]) -> None:
    _recompute_summary(value)
    compact = _compact_manifest(value)
    body = json.dumps(compact, ensure_ascii=False, sort_keys=True, indent=1) + "\n"
    if len(body.encode("utf-8")) > _MAXIMUM_MANIFEST_BYTES:
        raise ValueError("compact WARA image review manifest exceeds its byte limit")
    _MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    _MANIFEST_PATH.write_text(body, encoding="utf-8")
    load_image_review_manifest.cache_clear()


def refresh_inventory() -> None:
    try:
        existing = json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        existing = {}
    existing = _expand_compact_manifest(existing)
    old_groups = {
        item["source_document_url"]: item
        for item in existing.get("document_groups", [])
        if isinstance(item, dict) and isinstance(item.get("source_document_url"), str)
    }
    manifest = _initial_manifest()
    for group in manifest["document_groups"]:
        previous = old_groups.get(group["source_document_url"])
        if previous is not None:
            group.update(previous)
            group["recommendation_ids"] = _learn_inventory()[0][group["source_document_url"]]
    _save_manifest(manifest)


@lru_cache(maxsize=1)
def load_image_review_manifest() -> dict[str, Any]:
    try:
        body = _MANIFEST_PATH.read_bytes()
    except OSError as exc:
        raise ValueError("WARA image review manifest is unavailable") from exc
    if len(body) > _MAXIMUM_MANIFEST_BYTES:
        raise ValueError("WARA image review manifest exceeds its byte limit")
    try:
        value = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ValueError("WARA image review manifest is invalid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("WARA image review manifest must be a JSON object")
    return _validate_manifest(_expand_compact_manifest(value))


def image_authoring_inputs(root: Path) -> list[Path]:
    """Return the reviewed manifest and both shipped copies of every approved PNG."""

    manifest_path = root / "rule-catalog/guidance/azure-wara/reference-images.json"
    if manifest_path.resolve() != _MANIFEST_PATH.resolve():
        raise ValueError("WARA image authoring inputs require the active repository root")
    manifest = load_image_review_manifest()
    filenames = sorted(
        {
            f"{item['reference_image']['asset_id']}.png"
            for item in manifest["recommendations"]
            if item["decision"] == "selected"
        }
    )
    return [manifest_path] + [
        root / directory / filename
        for directory in (
            "packages/service-contracts/src/fdai_service_contracts/data/wara-guidance-assets",
            "console/public/wara-guidance-assets",
        )
        for filename in filenames
    ]


def image_review_summary() -> dict[str, Any]:
    """Expose document inspection separately from visual and redistribution review."""

    manifest = load_image_review_manifest()
    summary = json.loads(json.dumps(manifest["summary"]))
    summary.update(
        recommendation_count=manifest["recommendation_count"],
        document_group_count=manifest["document_group_count"],
        rights_blocked_candidate_count=sum(
            candidate.get("candidate_suitability") == "technically_relevant_rights_blocked"
            for group in manifest["document_groups"]
            for candidate in group.get("related_candidate_research", [])
        ),
    )
    return summary


def apply_reference_image(entry: dict[str, Any]) -> dict[str, Any]:
    """Apply only an approved image decision, preserving explicit absence for other states."""

    identity = entry.get("recommendation_id", entry.get("id"))
    if not isinstance(identity, str):
        raise ValueError("WARA image application requires a recommendation identity")
    try:
        decision = load_image_review_manifest()["recommendation_records"][identity]
    except KeyError as exc:
        raise ValueError(
            "WARA image review manifest has no decision for this recommendation"
        ) from exc
    entry.pop("reference_image", None)
    if decision.get("decision") == "selected":
        entry["reference_image"] = decision["reference_image"]
    return entry


def main() -> None:
    if __package__:
        from .wara_guidance_image_discovery import main as discovery_main
    else:
        from wara_guidance_image_discovery import main as discovery_main

    discovery_main()


if __name__ == "__main__":
    main()
