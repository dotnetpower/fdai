"""The reviewed image inventory makes bounded, non-absence claims for every guide."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from urllib.error import HTTPError

import pytest
from scripts.catalog import wara_guidance_image_discovery as discovery
from scripts.catalog import wara_guidance_image_selection as selection
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
    assert manifest["summary"]["selected_reference_image_count"] == 16
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
    selected = [
        item
        for item in load_image_review_manifest()["recommendations"]
        if item["decision"] == "selected"
    ]
    assert len(inputs) == 1 + 2 * len(selected) == 33
    shipped = inputs[1 : 1 + len(selected)]
    console = inputs[1 + len(selected) :]
    assert [path.name for path in shipped] == [path.name for path in console]
    assert all(left.read_bytes() == right.read_bytes() for left, right in zip(shipped, console))
    summary = image_review_summary()
    assert summary["recommendation_count"] == 456
    assert summary["document_group_count"] == 408
    assert summary["document_inspection_status_counts"] == {"inspected": 407, "fetch_failed": 1}
    assert summary["candidate_image_count"] == 1179
    assert summary["selected_reference_image_count"] == 16
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
        assert after["summary"]["selected_reference_image_count"] == 16
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


def test_reviewed_official_images_match_the_recorded_manifest_and_both_shipped_copies() -> None:
    assert selection.reviews_match_manifest() == []
    notice, reviews = selection.load_reviews()
    manifest = load_image_review_manifest()
    assert len(reviews) == 15
    assert notice["en"] and notice["ko"]
    for review in reviews:
        record = manifest["recommendation_records"][review["recommendation_id"]]
        image = record["reference_image"]
        assert record["review_status"] == "asset_reviewed"
        assert image["license"] == "CC-BY-4.0"
        assert image["source_document_url"].startswith("https://learn.microsoft.com/en-us/")
        scope = record["rights_review"]
        assert scope["license_evidence_url"].endswith("/ThirdPartyNotices.md")
        assert scope["source_repository_url"].startswith("https://github.com/MicrosoftDocs/")
        assert image["digest"].removeprefix("sha256:") in scope["reviewed_scope"]
        assert "does not imply Microsoft endorsement or trademark rights" in scope["reviewed_scope"]
        for text in (image["alt"], image["caption"]):
            assert text["en"].strip() and text["ko"].strip()
        for root in selection._ASSET_DIRECTORIES:
            path = selection._asset_path(root, image["asset_id"])
            assert hashlib.sha256(path.read_bytes()).hexdigest() == image["asset_id"][7:]


def test_review_for_an_uncited_image_or_unknown_recommendation_is_rejected(
    tmp_path, monkeypatch
) -> None:
    notice, reviews = selection.load_reviews()
    for change in ({"image_url": reviews[0]["image_url"] + "x"}, {"recommendation_id": "unknown"}):
        path = tmp_path / "reviews.json"
        path.write_text(
            json.dumps(
                {
                    "schema_version": "1.0.0",
                    "english_in_image_notice": notice,
                    "reviews": [{**reviews[0], **change}],
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(selection, "_REVIEWS_PATH", path)
        with pytest.raises(ValueError, match="candidate of its|unknown recommendation"):
            selection.apply_reviews(fetch=False)


def test_duplicate_reviews_are_rejected(tmp_path, monkeypatch) -> None:
    notice, reviews = selection.load_reviews()
    path = tmp_path / "reviews.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "english_in_image_notice": notice,
                "reviews": [reviews[0], reviews[0]],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(selection, "_REVIEWS_PATH", path)
    with pytest.raises(ValueError, match="duplicate"):
        selection.load_reviews()


def _article(feedback: str, revision: str = "a" * 40) -> bytes:
    return (
        "<html><head>"
        f'<meta name="github_feedback_content_git_url" content="{feedback}" />'
        f'<meta name="git_commit_id" content="{revision}" /></head>'
        "<body><h1>Example article</h1></body></html>"
    ).encode()


def _fake_network(monkeypatch, *, article: bytes, learn_image: bytes, repository_image: bytes):
    def get(url: str, maximum: int) -> tuple[str, bytes]:
        if url.endswith("/page"):
            return url, article
        if url.startswith("https://learn.microsoft.com/") and url.endswith(".png"):
            return url, learn_image
        if url.endswith("LICENSE"):
            return url, b"Attribution 4.0 International"
        if url.endswith("ThirdPartyNotices.md"):
            return url, b"under the Creative Commons Attribution 4.0 International Public License"
        return url, repository_image

    monkeypatch.setattr(selection, "_get", get)


_REVIEW = {
    "source_document_url": "https://learn.microsoft.com/en-us/azure/example/page",
    "image_url": "https://learn.microsoft.com/en-us/azure/example/media/page/figure.png",
}
_FEEDBACK = "https://github.com/MicrosoftDocs/azure-docs/blob/main/articles/example/page.md"


def test_evidence_requires_a_byte_identical_public_repository_copy(monkeypatch) -> None:
    _fake_network(
        monkeypatch, article=_article(_FEEDBACK), learn_image=b"one", repository_image=b"one"
    )
    evidence = selection.collect_evidence(_REVIEW, set())
    assert (evidence.repository, evidence.raw_path) == (
        "azure-docs",
        "articles/example/media/page/figure.png",
    )
    _fake_network(
        monkeypatch, article=_article(_FEEDBACK), learn_image=b"one", repository_image=b"two"
    )
    with pytest.raises(ValueError, match="byte-identical"):
        selection.collect_evidence(_REVIEW, set())


@pytest.mark.parametrize(
    "feedback",
    [
        "https://github.com/Example/azure-docs/blob/main/articles/example/page.md",
        "https://github.com/MicrosoftDocs/azure-docs/blob/live/articles/example/page.md",
        "https://example.com/MicrosoftDocs/azure-docs/blob/main/articles/example/page.md",
    ],
)
def test_evidence_requires_a_public_microsoft_docs_source(monkeypatch, feedback) -> None:
    _fake_network(monkeypatch, article=_article(feedback), learn_image=b"x", repository_image=b"x")
    with pytest.raises(ValueError, match="source and revision"):
        selection.collect_evidence(_REVIEW, set())


def test_evidence_requires_a_published_revision_and_cc_by_license(monkeypatch) -> None:
    _fake_network(
        monkeypatch,
        article=_article(_FEEDBACK, "not-a-revision"),
        learn_image=b"x",
        repository_image=b"x",
    )
    with pytest.raises(ValueError, match="source and revision"):
        selection.collect_evidence(_REVIEW, set())

    def unlicensed(url: str, maximum: int) -> tuple[str, bytes]:
        if url.endswith("/page"):
            return url, _article(_FEEDBACK)
        return url, b"All rights reserved"

    monkeypatch.setattr(selection, "_get", unlicensed)
    with pytest.raises(ValueError, match="not Creative Commons Attribution 4.0"):
        selection.collect_evidence(_REVIEW, set())


def test_evidence_requests_are_limited_to_public_learn_and_repository_hosts() -> None:
    with pytest.raises(ValueError, match="limited to public"):
        selection._get("https://example.com/image.png", 10)
    with pytest.raises(ValueError, match="limited to public"):
        selection._get("http://learn.microsoft.com/en-us/azure/x", 10)
