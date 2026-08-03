"""Tests for the content-free public document ontology corpus harness."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import NoReturn

import pytest
from scripts.evaluation.document_ontology_public_corpus import (
    FetchResult,
    evaluate_manifest,
    load_manifest,
)

_ROOT = Path(__file__).resolve().parents[2]
_MANIFEST = _ROOT / "tests/evaluation/document_ontology_public_corpus.v1.json"
_URL = "https://raw.githubusercontent.com/example/docs/main/manual.md"
_LINES = (
    "Service must keep latency below 250 ms.",
    "Service depends on workload.",
)
_CONTENT = ("\n".join(_LINES) + "\n").encode()


class FakeFetcher:
    def __init__(self, content: bytes = _CONTENT, *, final_url: str = _URL) -> None:
        self.content = content
        self.final_url = final_url
        self.calls: list[str] = []

    def fetch(self, url: str, *, timeout_seconds: float, max_bytes: int) -> FetchResult:
        assert timeout_seconds > 0.0
        assert len(self.content) <= max_bytes
        self.calls.append(url)
        return FetchResult(content=self.content, final_url=self.final_url)


class FailingFetcher:
    def fetch(self, url: str, *, timeout_seconds: float, max_bytes: int) -> NoReturn:
        raise AssertionError(f"unexpected fetch for {url}")


def _annotation(line: int, *signals: str) -> dict[str, object]:
    return {
        "locator": f"line:{line}",
        "text_sha256": hashlib.sha256(_LINES[line - 1].encode()).hexdigest(),
        "expected_claim_signals": list(signals),
    }


def _manifest_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "sources": [
            {
                "id": "example-manual",
                "url": _URL,
                "sha256": hashlib.sha256(_CONTENT).hexdigest(),
                "license_id": "CC-BY-4.0",
                "license_source": "https://example.com/license",
                "format": "markdown",
                "language": "en",
                "source_line_count": 2,
                "source_bytes": len(_CONTENT),
                "critical_claims": [
                    _annotation(1, "normative", "threshold"),
                    _annotation(2, "relationship"),
                ],
            }
        ],
    }


def _write_manifest(tmp_path: Path, payload: dict[str, object]) -> Path:
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_checked_in_manifest_pins_eleven_sources_without_bodies() -> None:
    manifest = load_manifest(_MANIFEST)

    assert len(manifest.sources) == 11
    assert all(len(source.critical_claims) >= 2 for source in manifest.sources)
    assert {source.source_format for source in manifest.sources} == {"markdown", "sgml"}
    assert {source.language for source in manifest.sources} == {"en"}
    assert not any(_MANIFEST.parent.glob("*.md"))
    assert not any(_MANIFEST.parent.glob("*.sgml"))


@pytest.mark.parametrize(("field", "value"), [("sha256", "bad"), ("license_id", "")])
def test_manifest_rejects_bad_hashes_and_missing_licenses(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    payload = _manifest_payload()
    source = payload["sources"][0]  # type: ignore[index]
    source[field] = value  # type: ignore[index]

    with pytest.raises(ValueError, match="manifest source"):
        load_manifest(_write_manifest(tmp_path, payload))


@pytest.mark.parametrize("duplicate_field", ["id", "url"])
def test_manifest_rejects_duplicate_ids_and_urls(
    tmp_path: Path,
    duplicate_field: str,
) -> None:
    payload = _manifest_payload()
    first = payload["sources"][0]  # type: ignore[index]
    second = dict(first)  # type: ignore[arg-type]
    second["id"] = "second-manual"
    second["url"] = "https://raw.githubusercontent.com/example/docs/main/second.md"
    second[duplicate_field] = first[duplicate_field]  # type: ignore[index]
    payload["sources"] = [first, second]

    with pytest.raises(ValueError, match=f"duplicate source {duplicate_field}"):
        load_manifest(_write_manifest(tmp_path, payload))


def test_fake_fetch_runs_inventory_and_reports_unbound_provider(tmp_path: Path) -> None:
    manifest = load_manifest(_write_manifest(tmp_path, _manifest_payload()))
    fetcher = FakeFetcher()

    report = evaluate_manifest(
        manifest,
        cache_dir=tmp_path / "cache",
        fetcher=fetcher,
    )

    assert fetcher.calls == [_URL]
    assert report["summary"] == {
        "annotation_count": 2,
        "annotation_detected_count": 2,
        "candidate_count": 0,
        "extraction_success_count": 0,
        "manual_count": 1,
        "parser_rejection_count": 0,
        "provider_abstention_count": 1,
        "replay_mismatch_count": 0,
    }
    result = report["manuals"][0]
    assert result["provider"] == {
        "abstained": True,
        "candidate_count": 0,
        "extraction_success": False,
        "status": "unbound",
    }
    assert result["replay_match"] is True
    assert "text" not in json.dumps(report)


def test_valid_cache_replays_without_network_and_is_deterministic(tmp_path: Path) -> None:
    manifest = load_manifest(_write_manifest(tmp_path, _manifest_payload()))
    cache = tmp_path / "cache"
    first = evaluate_manifest(manifest, cache_dir=cache, fetcher=FakeFetcher())
    replay = evaluate_manifest(manifest, cache_dir=cache, fetcher=FailingFetcher())

    assert first == replay


def test_bad_source_hash_fails_without_exposing_source_text(tmp_path: Path) -> None:
    manifest = load_manifest(_write_manifest(tmp_path, _manifest_payload()))
    source_body = b"x" * len(_CONTENT)
    fetcher = FakeFetcher(source_body)

    with pytest.raises(ValueError, match="example-manual source SHA-256 mismatch") as error:
        evaluate_manifest(manifest, cache_dir=tmp_path / "cache", fetcher=fetcher)

    assert source_body.decode() not in str(error.value)


def test_redirected_final_url_is_rejected(tmp_path: Path) -> None:
    manifest = load_manifest(_write_manifest(tmp_path, _manifest_payload()))
    fetcher = FakeFetcher(final_url="https://raw.githubusercontent.com/example/other/manual.md")

    with pytest.raises(ValueError, match="final URL mismatch"):
        evaluate_manifest(manifest, cache_dir=tmp_path / "cache", fetcher=fetcher)


def test_annotation_hash_fails_closed_and_signal_miss_is_accounted(tmp_path: Path) -> None:
    manifest = load_manifest(_write_manifest(tmp_path, _manifest_payload()))
    source = manifest.sources[0]
    bad_hash = replace(
        source.critical_claims[0],
        text_sha256="f" * 64,
    )
    hash_manifest = replace(
        manifest,
        sources=(replace(source, critical_claims=(bad_hash, source.critical_claims[1])),),
    )
    with pytest.raises(ValueError, match="critical claim hash mismatch"):
        evaluate_manifest(hash_manifest, cache_dir=tmp_path / "hash", fetcher=FakeFetcher())

    bad_signal = replace(
        source.critical_claims[0],
        expected_claim_signals=("history",),
    )
    signal_manifest = replace(
        manifest,
        sources=(replace(source, critical_claims=(bad_signal, source.critical_claims[1])),),
    )
    report = evaluate_manifest(
        signal_manifest,
        cache_dir=tmp_path / "signal",
        fetcher=FakeFetcher(),
    )
    assert report["summary"]["annotation_count"] == 2
    assert report["summary"]["annotation_detected_count"] == 1
