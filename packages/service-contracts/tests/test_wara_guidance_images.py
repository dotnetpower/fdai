"""The reviewed image inventory makes bounded, non-absence claims for every guide."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from urllib.error import HTTPError

import pytest
from scripts.catalog import wara_guidance_image_discovery as discovery
from scripts.catalog.wara_guidance_image_manifest import (
    compact_manifest,
    expand_compact_manifest,
    recompute_summary,
)
from scripts.catalog.wara_guidance_images import (
    apply_reference_image,
    image_authoring_inputs,
    image_review_summary,
    load_image_review_manifest,
)


def test_image_manifest_covers_all_recommendations_and_exact_learn_groups() -> None:
    manifest = load_image_review_manifest()
    assert manifest["recommendation_count"] == 456
    assert len(manifest["recommendation_records"]) == 456
    assert manifest["document_group_count"] == len(manifest["document_groups"])
    assert len(manifest["document_groups"]) == 408
    assert manifest["learn_citation_count"] == 459
    assert sum(manifest["summary"]["recommendation_review_status_counts"].values()) == 456
    assert sum(manifest["summary"]["document_inspection_status_counts"].values()) == 408
    assert manifest["summary"]["selected_reference_image_count"] == 0
    assert all(
        group["candidate_suitability"] != "no_embedded_candidate_found_in_cited_document"
        or "does not establish" in group["inspection_reason"]
        for group in manifest["document_groups"]
    )


def test_apply_reference_image_only_attaches_an_approved_asset() -> None:
    entry = {
        "recommendation_id": "1981f704-97b9-b645-9c57-33f8ded9261a",
        "reference_image": {"asset_id": "unreviewed"},
    }
    result = apply_reference_image(entry)
    assert result is entry
    assert "reference_image" not in entry


def test_apply_reference_image_rejects_an_identity_without_a_review_record() -> None:
    with pytest.raises(ValueError, match="no decision"):
        apply_reference_image({"recommendation_id": "unrecognized"})


def test_image_evidence_inputs_and_summary_are_explicit() -> None:
    root = Path(__file__).resolve().parents[3]
    assert image_authoring_inputs(root) == [
        root / "rule-catalog/guidance/azure-wara/reference-images.json"
    ]
    summary = image_review_summary()
    assert summary["recommendation_count"] == 456
    assert summary["document_group_count"] == 408
    assert summary["document_inspection_status_counts"] == {"inspected": 407, "fetch_failed": 1}
    assert summary["candidate_image_count"] == 1179
    assert summary["selected_reference_image_count"] == 0
    assert summary["rights_blocked_candidate_count"] == 1


def test_split_manifest_codec_preserves_review_summary_and_dispositions() -> None:
    manifest = load_image_review_manifest()
    restored = expand_compact_manifest(compact_manifest(manifest))
    recompute_summary(restored)
    assert restored["summary"] == manifest["summary"]
    assert restored["recommendations"] == manifest["recommendations"]
    assert restored["document_groups"] == manifest["document_groups"]


def test_candidate_alt_typography_is_normalized_without_changing_asset_urls() -> None:
    manifest = deepcopy(load_image_review_manifest())
    group = next(group for group in manifest["document_groups"] if group["candidates"])
    candidate = group["candidates"][0]
    candidate["alt"] = "Volume\u2019s snapshots"
    restored = expand_compact_manifest(compact_manifest(manifest))
    restored_group = next(
        item
        for item in restored["document_groups"]
        if item["source_document_url"] == group["source_document_url"]
    )
    restored_candidate = next(
        item for item in restored_group["candidates"] if item["image_url"] == candidate["image_url"]
    )
    assert "Volume's snapshots" in restored_candidate["alt"]


def test_discovery_only_admits_same_origin_learn_media_candidates() -> None:
    parser = discovery._PageImages()
    parser.feed(
        '<h1>Overview</h1><img src="media/overview/chart.png" alt="Architecture">'
        '<img src="https://example.com/media/chart.png">'
        '<img src="http://learn.microsoft.com/media/chart.png">'
        '<img src="/tracking.png">'
    )
    candidates = discovery._image_candidates(
        parser, "https://learn.microsoft.com/en-us/azure/backup/overview"
    )
    assert parser.heading == "Overview"
    assert candidates == [
        {
            "image_url": (
                "https://learn.microsoft.com/en-us/azure/backup/media/overview/chart.png"
            ),
            "alt": "Architecture",
            "title": "",
            "suitability": "requires_visual_and_rights_review",
        }
    ]


@pytest.mark.parametrize("status", [429, 503])
def test_split_discovery_stops_without_retry_on_provider_limit(monkeypatch, status) -> None:
    calls = []

    class LimitedOpener:
        def open(self, request, *, timeout):
            calls.append((request.full_url, timeout))
            raise HTTPError(request.full_url, status, "stop", None, None)

    monkeypatch.setattr(discovery, "build_opener", lambda _: LimitedOpener())
    with pytest.raises(discovery.LearnRateLimitError, match=str(status)):
        discovery._fetch_document("https://learn.microsoft.com/en-us/azure/backup/overview")
    assert len(calls) == 1


@pytest.mark.parametrize("maximum_requests", [0, 21])
def test_split_discovery_rejects_unbounded_batches(maximum_requests) -> None:
    with pytest.raises(ValueError, match="between 1 and 20"):
        discovery.inspect_next_documents(maximum_requests)
