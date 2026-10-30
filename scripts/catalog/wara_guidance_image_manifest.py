"""Compact storage codec and stable review reasons for WARA image authoring."""

from __future__ import annotations

import hashlib
from typing import Any

_COMPACT_FORMAT = "compact-v1"
_VM_BACKUP_ID = "1981f704-97b9-b645-9c57-33f8ded9261a"
REVIEW_REASONS = {
    "document_pending": (
        "At least one exact cited Learn document has not been inspected. This is not evidence "
        "that a suitable official image does not exist."
    ),
    "no_learn_document": (
        "This recommendation cites no Microsoft Learn URL. No image-absence conclusion is "
        "inferred for other cited source types or related documents."
    ),
    "rights_verification_blocked": (
        "The cited backup overview page is a separate document from this related image source. "
        "The Learn article and its media reference were inspected, and the diagram appears "
        "technically relevant to VM backup. Redistribution was not approved: exact asset "
        "inclusion in the licensed source and any asset-specific third-party notice could not be "
        "independently verified after the MicrosoftDocs API returned SAML 403. Microsoft Learn "
        "Terms of Use restrict image reuse unless expressly permitted. Do not vendor this "
        "candidate until an authorized source confirms the applicable license and notices."
    ),
    "partial_document_review": "Some, but not all, exact cited Learn documents were inspected.",
    "document_fetch_failed": (
        "No cited document completed inspection; a bounded fetch failed. No image absence or "
        "suitability conclusion is inferred."
    ),
    "candidate_review_required": (
        "Cited Learn document(s) were fetched. Candidate media remain subject to visual and "
        "rights review."
    ),
    "no_candidate_in_cited_documents": (
        "No embedded candidate was found in the cited documents; this is not evidence that no "
        "suitable image exists elsewhere."
    ),
    "no_embedded_candidate": (
        "No Learn media image was found in the inspected exact document. This does not establish "
        "that no suitable image exists in another document."
    ),
    "page_candidates_pending": (
        "The inspected cited document embeds media images listed below. Automated page metadata "
        "does not establish visual suitability or redistribution rights."
    ),
    "page_uninspected": "This exact cited Learn URL has not yet been fetched and inspected.",
    "page_http_error": (
        "The exact cited Learn URL returned the HTTP status recorded with this group."
    ),
    "fetch_unavailable": (
        "The cited Learn page could not be inspected with the bounded same-origin request. "
        "No alternate transport was attempted."
    ),
    "approved_asset": (
        "This recommendation uses a rights-reviewed, digest-verified local reference image."
    ),
}


def recompute_summary(manifest: dict[str, Any]) -> None:
    groups = manifest["document_groups"]
    recommendations = manifest["recommendations"]
    grouped = {item["source_document_url"]: item for item in groups}
    for recommendation in recommendations:
        urls = recommendation["learn_document_urls"]
        states = [grouped[url]["inspection_status"] for url in urls]
        candidates = [candidate for url in urls for candidate in grouped[url]["candidates"]]
        if not urls:
            recommendation["review_status"] = "no_cited_learn_document"
            recommendation["decision"] = "no_learn_document_to_inspect"
            recommendation["reason"] = (
                "This recommendation cites no Microsoft Learn URL. No image-absence conclusion "
                "is inferred for other cited source types or related documents."
            )
        elif recommendation["recommendation_id"] == _VM_BACKUP_ID:
            recommendation["review_status"] = (
                "partially_reviewed"
                if any(state == "inspected" for state in states)
                else "unreviewed"
            )
            recommendation["decision"] = "review_required"
            recommendation["reason"] = REVIEW_REASONS["rights_verification_blocked"]
        elif states and all(state == "inspected" for state in states):
            recommendation["review_status"] = "document_inspected"
            recommendation["decision"] = (
                "candidate_review_required" if candidates else "no_candidate_in_cited_documents"
            )
            recommendation["reason"] = "Cited Learn document(s) were fetched. " + (
                "Candidate media remain subject to visual and rights review."
                if candidates
                else "No embedded candidate was found in the cited documents; this is not "
                "evidence that no suitable image exists elsewhere."
            )
        elif any(state == "inspected" for state in states):
            recommendation["review_status"] = "partially_reviewed"
            recommendation["decision"] = "document_review_incomplete"
            recommendation["reason"] = (
                "Some, but not all, exact cited Learn documents were inspected."
            )
        elif any(state == "fetch_failed" for state in states):
            recommendation["review_status"] = "unreviewed"
            recommendation["decision"] = "document_fetch_failed"
            recommendation["reason"] = (
                "No cited document completed inspection; a bounded fetch failed. No image "
                "absence or suitability conclusion is inferred."
            )
        else:
            recommendation["review_status"] = "unreviewed"
            recommendation["decision"] = "document_review_pending"
            recommendation["reason"] = (
                "At least one exact cited Learn document has not been inspected. This is not "
                "evidence that a suitable official image does not exist."
            )
    status_counts: dict[str, int] = {}
    decision_counts: dict[str, int] = {}
    for item in recommendations:
        status_counts[item["review_status"]] = status_counts.get(item["review_status"], 0) + 1
        decision_counts[item["decision"]] = decision_counts.get(item["decision"], 0) + 1
    group_counts: dict[str, int] = {}
    for item in groups:
        group_counts[item["inspection_status"]] = group_counts.get(item["inspection_status"], 0) + 1
    manifest["summary"] = {
        "recommendation_review_status_counts": status_counts,
        "recommendation_decision_counts": decision_counts,
        "document_inspection_status_counts": group_counts,
        "groups_with_candidate_images": sum(bool(item["candidates"]) for item in groups),
        "candidate_image_count": sum(len(item["candidates"]) for item in groups),
        "selected_reference_image_count": sum(
            item["decision"] == "selected" for item in recommendations
        ),
    }


def _reason_code_for_decision(decision: str) -> str:
    return {
        "review_required": "rights_verification_blocked",
        "no_learn_document_to_inspect": "no_learn_document",
        "document_review_pending": "document_pending",
        "document_review_incomplete": "partial_document_review",
        "document_fetch_failed": "document_fetch_failed",
        "candidate_review_required": "candidate_review_required",
        "no_candidate_in_cited_documents": "no_candidate_in_cited_documents",
        "selected": "approved_asset",
    }[decision]


def compact_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    groups: dict[str, dict[str, Any]] = {}
    candidate_registry: dict[str, dict[str, Any]] = {}
    for group in manifest["document_groups"]:
        candidate_ids = []
        for candidate in group["candidates"]:
            image_url = candidate["image_url"]
            candidate_id = hashlib.sha256(image_url.encode("utf-8")).hexdigest()[:16]
            record = candidate_registry.setdefault(
                candidate_id,
                {"image_url": image_url, "alt_texts": []},
            )
            if record["image_url"] != image_url:
                raise ValueError("WARA image candidate identifier collision")
            text = (
                candidate.get("alt", "")
                .strip()
                .translate(
                    {
                        0x2013: "-",
                        0x2014: "-",
                        0x2018: "'",
                        0x2019: "'",
                        0x201C: '"',
                        0x201D: '"',
                        0x2026: "...",
                        0xA0: " ",
                    }
                )
            )
            if text and text not in record["alt_texts"]:
                record["alt_texts"].append(text)
            candidate_ids.append(candidate_id)

        status = group["inspection_status"]
        suitability = {
            "not_assessed": "not_assessed",
            "potential_candidates_require_visual_and_rights_review": "candidate_review_required",
            "no_embedded_candidate_found_in_cited_document": "no_candidate_in_document",
        }.get(group["candidate_suitability"], "not_assessed")
        if status == "unreviewed":
            reason_code = "page_uninspected"
        elif status == "fetch_failed":
            reason_code = (
                "page_http_error"
                if group.get("inspection", {}).get("http_status") is not None
                else "fetch_unavailable"
            )
        elif candidate_ids:
            reason_code = "page_candidates_pending"
        else:
            reason_code = "no_embedded_candidate"
        inspection = group.get("inspection")
        if isinstance(inspection, dict):
            inspection = {
                key: inspection[key]
                for key in (
                    "http_status",
                    "final_url",
                    "page_digest",
                    "candidate_count",
                )
                if inspection.get(key) is not None
            }
        groups[group["source_document_url"]] = {
            "inspection_status": status,
            "candidate_suitability": suitability,
            "reason_code": reason_code,
            "inspection": inspection,
            "candidate_ids": sorted(set(candidate_ids)),
            "related_candidate_research": group.get("related_candidate_research", []),
        }

    ordered_urls = sorted(groups)
    group_index = {url: index for index, url in enumerate(ordered_urls)}
    recommendations: dict[str, dict[str, Any]] = {}
    for item in manifest["recommendations"]:
        record: dict[str, Any] = {
            "groups": sorted(group_index[url] for url in item["learn_document_urls"]),
            "review_status": item["review_status"],
            "decision": item["decision"],
            "reason_code": _reason_code_for_decision(item["decision"]),
        }
        if item.get("reference_image") is not None:
            record["reference_image"] = item["reference_image"]
        recommendations[item["recommendation_id"]] = record
    return {
        "storage_format": _COMPACT_FORMAT,
        "schema_version": manifest["schema_version"],
        "framework_revision": manifest["framework_revision"],
        "catalog_digest": manifest["catalog_digest"],
        "recommendation_count": manifest["recommendation_count"],
        "learn_citation_count": manifest["learn_citation_count"],
        "document_group_count": manifest["document_group_count"],
        "review_reasons": REVIEW_REASONS,
        "document_groups": groups,
        "candidates": candidate_registry,
        "recommendations": recommendations,
        "summary": manifest["summary"],
    }


def expand_compact_manifest(value: dict[str, Any]) -> dict[str, Any]:
    if value.get("storage_format") != _COMPACT_FORMAT:
        return value
    if value.get("review_reasons") != REVIEW_REASONS:
        raise ValueError("WARA image review reason definitions are stale")
    compact_groups = value.get("document_groups")
    candidate_registry = value.get("candidates")
    compact_recommendations = value.get("recommendations")
    if not isinstance(compact_groups, dict) or not isinstance(candidate_registry, dict):
        raise ValueError("compact WARA image review manifest is malformed")
    if not isinstance(compact_recommendations, dict):
        raise ValueError("compact WARA recommendation review is malformed")

    ordered_urls = sorted(compact_groups)
    url_by_index = {index: url for index, url in enumerate(ordered_urls)}
    identities_by_group: dict[int, list[str]] = {index: [] for index in url_by_index}
    for identity, record in compact_recommendations.items():
        if not isinstance(record, dict):
            raise ValueError("compact WARA recommendation is malformed")
        indexes = record.get("groups", [])
        if not isinstance(indexes, list) or any(index not in url_by_index for index in indexes):
            raise ValueError("compact WARA recommendation group index is invalid")
        for index in indexes:
            identities_by_group[index].append(identity)

    groups = []
    for index, url in enumerate(ordered_urls):
        record = compact_groups[url]
        if not isinstance(record, dict):
            raise ValueError("compact WARA Learn group is malformed")
        candidate_ids = record.get("candidate_ids", [])
        candidates = []
        for candidate_id in candidate_ids:
            candidate = candidate_registry.get(candidate_id)
            if not isinstance(candidate, dict):
                raise ValueError("compact WARA image candidate is missing")
            candidates.append(
                {
                    "image_url": candidate.get("image_url"),
                    "alt": "; ".join(candidate.get("alt_texts", [])),
                    "title": "",
                    "suitability": "requires_visual_and_rights_review",
                }
            )
        suitability = {
            "not_assessed": "not_assessed",
            "candidate_review_required": ("potential_candidates_require_visual_and_rights_review"),
            "no_candidate_in_document": "no_embedded_candidate_found_in_cited_document",
        }.get(record.get("candidate_suitability"))
        if suitability is None:
            raise ValueError("compact WARA candidate suitability is invalid")
        reason_code = record.get("reason_code")
        if reason_code not in REVIEW_REASONS:
            raise ValueError("compact WARA Learn group reason is unknown")
        group: dict[str, Any] = {
            "source_document_url": url,
            "recommendation_ids": sorted(identities_by_group[index]),
            "inspection_status": record.get("inspection_status"),
            "candidate_suitability": suitability,
            "inspection_reason": REVIEW_REASONS[reason_code],
            "inspection": record.get("inspection"),
            "candidates": candidates,
        }
        if record.get("related_candidate_research"):
            group["related_candidate_research"] = record["related_candidate_research"]
        groups.append(group)

    recommendations = []
    for identity in sorted(compact_recommendations):
        record = compact_recommendations[identity]
        if not isinstance(record, dict):
            raise ValueError("compact WARA recommendation is malformed")
        indexes = record.get("groups", [])
        reason_code = record.get("reason_code")
        if reason_code not in REVIEW_REASONS:
            raise ValueError("compact WARA recommendation reason is unknown")
        item: dict[str, Any] = {
            "recommendation_id": identity,
            "learn_document_urls": [url_by_index[index] for index in indexes],
            "review_status": record.get("review_status"),
            "decision": record.get("decision"),
            "reason": REVIEW_REASONS[reason_code],
        }
        if record.get("reference_image") is not None:
            item["reference_image"] = record["reference_image"]
        recommendations.append(item)
    return {
        "schema_version": value.get("schema_version"),
        "framework_revision": value.get("framework_revision"),
        "catalog_digest": value.get("catalog_digest"),
        "recommendation_count": value.get("recommendation_count"),
        "learn_citation_count": value.get("learn_citation_count"),
        "document_group_count": value.get("document_group_count"),
        "recommendations": recommendations,
        "document_groups": groups,
        "summary": value.get("summary"),
    }
