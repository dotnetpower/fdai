"""Tests for the content-free public document ontology corpus harness."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import NoReturn
from urllib.error import URLError

import pytest
from fdai.shared.providers.distiller import (
    CandidateKind,
    DistillationResult,
    DistilledCandidate,
)
from scripts.evaluation import document_ontology_public_corpus as corpus
from scripts.evaluation.document_ontology_public_corpus import (
    FetchResult,
    UrlLibCorpusFetcher,
    evaluate_manifest,
    load_manifest,
)

_ROOT = Path(__file__).resolve().parents[3]
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


class StaticDistiller:
    def __init__(self, candidate_count: int) -> None:
        self._result = DistillationResult(
            candidates=tuple(
                DistilledCandidate(
                    kind=CandidateKind.RULE,
                    candidate_id=f"candidate-{index}",
                    source_ref="doc:example-manual",
                    source_section="Service",
                    source_lines=(1, 1),
                )
                for index in range(candidate_count)
            )
        )

    async def distill(self, document: object) -> DistillationResult:
        return self._result


class FakeResponse:
    def __init__(self, content: bytes, final_url: str) -> None:
        self._content = content
        self._final_url = final_url

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self, size: int) -> bytes:
        return self._content[:size]

    def geturl(self) -> str:
        return self._final_url


class FakeOpener:
    def __init__(self, response: FakeResponse | Exception) -> None:
        self._response = response

    def open(self, request: object, *, timeout: float) -> FakeResponse:
        assert timeout > 0.0
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


class RejectingExtractor:
    async def extract(self, **kwargs: object) -> NoReturn:
        raise ValueError("synthetic parser rejection")


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


def _source(payload: dict[str, object]) -> dict[str, object]:
    return payload["sources"][0]  # type: ignore[index,return-value]


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


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"schema_version": 1},
        {"schema_version": True, "sources": []},
        {"schema_version": 1, "sources": "not-an-array"},
        {"schema_version": 1, "sources": []},
    ],
)
def test_manifest_rejects_invalid_root_types_and_schema(
    tmp_path: Path,
    payload: object,
) -> None:
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="manifest|schema_version|sources"):
        load_manifest(path)


def test_manifest_wraps_unreadable_and_malformed_json(tmp_path: Path) -> None:
    missing = tmp_path / "missing.json"
    malformed = tmp_path / "malformed.json"
    malformed.write_text("{", encoding="utf-8")

    for path in (missing, malformed):
        with pytest.raises(ValueError, match="manifest is unreadable"):
            load_manifest(path)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("id", "UPPER", "bounded lowercase token"),
        ("url", "http://raw.githubusercontent.com/example/manual.md", "HTTPS URL"),
        ("url", "https://example.com/manual.md", "host is not allowlisted"),
        ("url", _URL + "?revision=1", "query or fragment"),
        ("url", "https://raw.githubusercontent.com:444/example/manual.md", "default HTTPS port"),
        ("license_source", "https://user:secret@example.com/license", "without credentials"),
        ("format", "pdf", "format is unsupported"),
        ("language", "", "non-empty string"),
        ("source_line_count", 0, "MUST be positive"),
        ("source_bytes", True, "MUST be an integer"),
        ("critical_claims", "claims", "MUST be an array"),
    ],
)
def test_manifest_rejects_invalid_source_boundaries(
    tmp_path: Path,
    field: str,
    value: object,
    message: str,
) -> None:
    payload = _manifest_payload()
    _source(payload)[field] = value

    with pytest.raises(ValueError, match=message):
        load_manifest(_write_manifest(tmp_path, payload))


def test_manifest_rejects_source_and_annotation_shape_errors(tmp_path: Path) -> None:
    payload = _manifest_payload()
    _source(payload)["unexpected"] = True
    with pytest.raises(ValueError, match="source keys"):
        load_manifest(_write_manifest(tmp_path, payload))

    payload = _manifest_payload()
    _source(payload)["critical_claims"] = [_annotation(1, "normative")]
    with pytest.raises(ValueError, match="at least two"):
        load_manifest(_write_manifest(tmp_path, payload))

    payload = _manifest_payload()
    annotations = _source(payload)["critical_claims"]
    annotations[1] = dict(annotations[0])  # type: ignore[index]
    with pytest.raises(ValueError, match="locators MUST be unique"):
        load_manifest(_write_manifest(tmp_path, payload))


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("locator", "line:0", "positive integer"),
        ("locator", "line:3", "exceeds the source line count"),
        ("text_sha256", "A" * 64, "lowercase SHA-256"),
        ("expected_claim_signals", [], "expected signals are invalid"),
        ("expected_claim_signals", ["unknown"], "expected signals are invalid"),
        ("expected_claim_signals", "normative", "MUST be an array"),
    ],
)
def test_manifest_rejects_invalid_annotation_bounds(
    tmp_path: Path,
    field: str,
    value: object,
    message: str,
) -> None:
    payload = _manifest_payload()
    annotations = _source(payload)["critical_claims"]
    annotations[0][field] = value  # type: ignore[index]

    with pytest.raises(ValueError, match=message):
        load_manifest(_write_manifest(tmp_path, payload))


def test_manifest_rejects_invalid_annotation_keys(tmp_path: Path) -> None:
    payload = _manifest_payload()
    annotations = _source(payload)["critical_claims"]
    annotations[0]["unexpected"] = True  # type: ignore[index]

    with pytest.raises(ValueError, match="critical claim keys"):
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


@pytest.mark.parametrize("candidate_count", [0, 2])
def test_bound_provider_reports_abstention_or_extraction_success(
    tmp_path: Path,
    candidate_count: int,
) -> None:
    manifest = load_manifest(_write_manifest(tmp_path, _manifest_payload()))

    report = evaluate_manifest(
        manifest,
        cache_dir=tmp_path / "cache",
        fetcher=FakeFetcher(),
        distiller=StaticDistiller(candidate_count),  # type: ignore[arg-type]
    )

    provider = report["manuals"][0]["provider"]
    assert provider["candidate_count"] == candidate_count
    assert provider["abstained"] is (candidate_count == 0)
    assert provider["extraction_success"] is (candidate_count > 0)
    assert provider["status"] == ("bound" if candidate_count else "abstained")


def test_parser_rejection_returns_content_free_failure_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = load_manifest(_write_manifest(tmp_path, _manifest_payload()))
    monkeypatch.setattr(corpus, "StandardLibraryDocumentExtractor", RejectingExtractor)

    report = evaluate_manifest(
        manifest,
        cache_dir=tmp_path / "cache",
        fetcher=FakeFetcher(),
    )

    result = report["manuals"][0]
    assert result["parser_rejected"] is True
    assert result["parser_error_code"] == "ValueError"
    assert result["inventory_digest"] is None
    assert result["unit_count"] == 0
    assert report["summary"]["parser_rejection_count"] == 1
    assert report["summary"]["replay_mismatch_count"] == 1
    assert _LINES[0] not in json.dumps(report)


def test_valid_cache_replays_without_network_and_is_deterministic(tmp_path: Path) -> None:
    manifest = load_manifest(_write_manifest(tmp_path, _manifest_payload()))
    cache = tmp_path / "cache"
    first = evaluate_manifest(manifest, cache_dir=cache, fetcher=FakeFetcher())
    replay = evaluate_manifest(manifest, cache_dir=cache, fetcher=FailingFetcher())

    assert first == replay


def test_cache_rejects_symbolic_links_and_wrong_sizes(tmp_path: Path) -> None:
    manifest = load_manifest(_write_manifest(tmp_path, _manifest_payload()))
    cache = tmp_path / "cache"
    cache.mkdir()
    cached = cache / "example-manual.md"
    outside = tmp_path / "outside.md"
    outside.write_bytes(_CONTENT)
    cached.symlink_to(outside)
    with pytest.raises(ValueError, match="symbolic link"):
        evaluate_manifest(manifest, cache_dir=cache, fetcher=FailingFetcher())

    cached.unlink()
    cached.write_bytes(_CONTENT + b"extra")
    with pytest.raises(ValueError, match="cached source byte count"):
        evaluate_manifest(manifest, cache_dir=cache, fetcher=FailingFetcher())


def test_cache_revalidates_same_size_content_identity(tmp_path: Path) -> None:
    manifest = load_manifest(_write_manifest(tmp_path, _manifest_payload()))
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "example-manual.md").write_bytes(b"x" * len(_CONTENT))

    with pytest.raises(ValueError, match="source SHA-256 mismatch"):
        evaluate_manifest(manifest, cache_dir=cache, fetcher=FailingFetcher())


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


@pytest.mark.parametrize("timeout_seconds", [0.0, 301.0, float("nan")])
def test_evaluation_rejects_invalid_timeout(
    tmp_path: Path,
    timeout_seconds: float,
) -> None:
    manifest = load_manifest(_write_manifest(tmp_path, _manifest_payload()))

    with pytest.raises(ValueError, match="timeout"):
        evaluate_manifest(
            manifest,
            cache_dir=tmp_path / "cache",
            fetcher=FailingFetcher(),
            timeout_seconds=timeout_seconds,
        )


@pytest.mark.parametrize("max_bytes", [0, True, 32 * 1024 * 1024 + 1])
def test_evaluation_rejects_invalid_byte_limits(tmp_path: Path, max_bytes: int) -> None:
    manifest = load_manifest(_write_manifest(tmp_path, _manifest_payload()))

    with pytest.raises(ValueError, match="byte limit"):
        evaluate_manifest(
            manifest,
            cache_dir=tmp_path / "cache",
            fetcher=FailingFetcher(),
            max_bytes=max_bytes,
        )


def test_evaluation_rejects_source_larger_than_configured_limit(tmp_path: Path) -> None:
    manifest = load_manifest(_write_manifest(tmp_path, _manifest_payload()))

    with pytest.raises(ValueError, match="source exceeds the configured byte limit"):
        evaluate_manifest(
            manifest,
            cache_dir=tmp_path / "cache",
            fetcher=FailingFetcher(),
            max_bytes=len(_CONTENT) - 1,
        )


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (URLError("offline"), "source fetch failed"),
        (FakeResponse(b"12345", _URL), "exceeds the byte limit"),
        (
            FakeResponse(b"ok", "https://raw.githubusercontent.com/example/other.md"),
            "final URL mismatch",
        ),
    ],
)
def test_url_fetcher_fails_closed_on_transport_redirect_and_oversize(
    monkeypatch: pytest.MonkeyPatch,
    response: FakeResponse | Exception,
    message: str,
) -> None:
    monkeypatch.setattr(corpus, "build_opener", lambda *handlers: FakeOpener(response))

    with pytest.raises(ValueError, match=message):
        UrlLibCorpusFetcher().fetch(_URL, timeout_seconds=1.0, max_bytes=4)


def test_url_fetcher_returns_bounded_content_and_disables_redirects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        corpus,
        "build_opener",
        lambda *handlers: FakeOpener(FakeResponse(b"data", _URL)),
    )

    result = UrlLibCorpusFetcher().fetch(_URL, timeout_seconds=1.0, max_bytes=4)

    assert result == FetchResult(content=b"data", final_url=_URL)
    assert (
        corpus._NoRedirectHandler().redirect_request(  # noqa: SLF001
            object(), object(), 302, "redirect", object(), _URL
        )
        is None
    )


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


def test_cli_writes_stdout_output_file_and_reports_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest_path = _write_manifest(tmp_path, _manifest_payload())
    expected = {"summary": {"manual_count": 1}}
    monkeypatch.setattr(corpus, "evaluate_manifest", lambda *args, **kwargs: expected)

    assert corpus.main(["--manifest", str(manifest_path), "--cache-dir", str(tmp_path)]) == 0
    stdout = capsys.readouterr().out
    assert json.loads(stdout) == expected

    output = tmp_path / "report.json"
    assert (
        corpus.main(
            [
                "--manifest",
                str(manifest_path),
                "--cache-dir",
                str(tmp_path),
                "--output",
                str(output),
                "--timeout-seconds",
                "1.5",
                "--max-bytes",
                "1024",
            ]
        )
        == 0
    )
    assert json.loads(output.read_text(encoding="utf-8")) == expected

    monkeypatch.setattr(
        corpus,
        "load_manifest",
        lambda path: (_ for _ in ()).throw(ValueError("invalid manifest")),
    )
    assert corpus.main(["--manifest", str(manifest_path), "--cache-dir", str(tmp_path)]) == 2
    assert capsys.readouterr().err == ("document-ontology-public-corpus: FAIL: invalid manifest\n")
