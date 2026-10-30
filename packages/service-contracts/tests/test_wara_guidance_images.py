"""The reviewed image inventory makes bounded, non-absence claims for every guide."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from urllib.error import HTTPError

import pytest
from scripts.catalog import wara_guidance_image_discovery as discovery
from scripts.catalog import wara_guidance_images as images
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
    assert manifest["summary"]["selected_reference_image_count"] == 1
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
    assert entry["reference_image"]["source_document_url"].endswith("backup-azure-vms-introduction")
    unselected = next(
        item
        for item in load_image_review_manifest()["recommendations"]
        if item["decision"] != "selected"
    )
    entry = {
        "recommendation_id": unselected["recommendation_id"],
        "reference_image": {"asset_id": "unreviewed"},
    }
    apply_reference_image(entry)
    assert "reference_image" not in entry


def test_apply_reference_image_rejects_an_identity_without_a_review_record() -> None:
    with pytest.raises(ValueError, match="no decision"):
        apply_reference_image({"recommendation_id": "unrecognized"})


def test_image_evidence_inputs_and_summary_are_explicit() -> None:
    root = Path(__file__).resolve().parents[3]
    inputs = image_authoring_inputs(root)
    assert inputs[0] == root / "rule-catalog/guidance/azure-wara/reference-images.json"
    assert len(inputs) == 3
    assert inputs[1].read_bytes() == inputs[2].read_bytes()
    summary = image_review_summary()
    assert summary["recommendation_count"] == 456
    assert summary["document_group_count"] == 408
    assert summary["document_inspection_status_counts"] == {"inspected": 407, "fetch_failed": 1}
    assert summary["candidate_image_count"] == 1179
    assert summary["selected_reference_image_count"] == 1
    assert summary["rights_blocked_candidate_count"] == 0


def test_split_manifest_codec_preserves_review_summary_and_dispositions() -> None:
    manifest = load_image_review_manifest()
    restored = expand_compact_manifest(compact_manifest(manifest))
    recompute_summary(restored)
    assert restored["summary"] == manifest["summary"]
    assert restored["recommendations"] == manifest["recommendations"]
    assert restored["citation_digest"] == manifest["citation_digest"]
    assert restored["document_groups"] == manifest["document_groups"]


@pytest.mark.parametrize("key", ["license_evidence_url", "source_repository_url", "reviewed_scope"])
def test_selected_asset_without_license_evidence_is_rejected(key) -> None:
    manifest = deepcopy(load_image_review_manifest())
    selected = next(item for item in manifest["recommendations"] if item["decision"] == "selected")
    selected["rights_review"].pop(key)
    with pytest.raises(ValueError, match="recorded license and scope evidence"):
        images._validate_manifest(manifest)


@pytest.mark.parametrize("drift", ["framework_revision", "learn_document_urls"])
def test_inventory_refresh_rejects_stale_selected_asset(tmp_path, monkeypatch, drift) -> None:
    manifest = deepcopy(load_image_review_manifest())
    selected = next(item for item in manifest["recommendations"] if item["decision"] == "selected")
    if drift == "framework_revision":
        manifest[drift] = "changed"
    else:
        selected[drift] = [
            next(
                group["source_document_url"]
                for group in manifest["document_groups"]
                if group["source_document_url"] not in selected[drift]
            )
        ]
    path = tmp_path / "reference-images.json"
    path.write_text(json.dumps(compact_manifest(manifest)))
    monkeypatch.setattr(images, "_MANIFEST_PATH", path)
    before = path.read_bytes()
    with pytest.raises(ValueError, match="source changed"):
        images.refresh_inventory()
    assert path.read_bytes() == before


def test_image_review_binding_tracks_citations_not_its_own_generated_output(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(images, "_DATA_PATH", tmp_path)
    monkeypatch.setattr(images, "_framework_identities", lambda: ("example",))
    index = {
        "framework_revision": "revision",
        "catalog_digest": "old",
        "shards": [{"path": "part.json"}],
    }
    part = {
        "entries": [
            {
                "recommendation_id": "example",
                "sources": [{"kind": "learn", "url": "https://learn.microsoft.com/a"}],
            }
        ]
    }
    (tmp_path / "wara-guidance.json").write_text(json.dumps(index))
    (tmp_path / "part.json").write_text(json.dumps(part))
    before = images._learn_inventory()[3]
    index["catalog_digest"] = "new image and prose output"
    (tmp_path / "wara-guidance.json").write_text(json.dumps(index))
    assert images._learn_inventory()[3] == before
    part["entries"][0]["sources"][0]["url"] = "https://learn.microsoft.com/b"
    (tmp_path / "part.json").write_text(json.dumps(part))
    assert images._learn_inventory()[3] != before


def test_inventory_refresh_preserves_reviewed_asset_and_license_evidence(
    tmp_path, monkeypatch
) -> None:
    path = tmp_path / "reference-images.json"
    path.write_bytes(images._MANIFEST_PATH.read_bytes())
    monkeypatch.setattr(images, "_MANIFEST_PATH", path)
    images.load_image_review_manifest.cache_clear()
    try:
        before = images.load_image_review_manifest()
        selected = next(
            item for item in before["recommendations"] if item["decision"] == "selected"
        )
        images.refresh_inventory()
        after = images.load_image_review_manifest()
        assert after["recommendation_records"][selected["recommendation_id"]] == selected
        assert after["summary"]["selected_reference_image_count"] == 1
    finally:
        images.load_image_review_manifest.cache_clear()


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
