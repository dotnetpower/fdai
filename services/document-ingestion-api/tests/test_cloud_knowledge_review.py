"""Offline review is original-free preparation, never a shortcut to admission or answer quality."""

from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fdai_ingestion_api_service.cloud_knowledge import review
from fdai_ingestion_api_service.cloud_knowledge.review_contracts import (
    ExcerptMetrics,
    ReviewPlan,
    ReviewReport,
    ReviewSource,
    SourceReview,
    WorkerResult,
)
from fdai_ingestion_api_service.cloud_knowledge.review_io import (
    decode_json,
    directory,
    read_file,
)
from fdai_service_contracts.cloud_knowledge import (
    Applicability,
    CloudSourceEvidence,
    RefreshPolicy,
    SourceCheckReceipt,
    canonical_bytes,
    content_digest,
)
from fdai_service_contracts.cloud_knowledge_structure import (
    CloudStructuredDocument,
    structured_excerpts,
)

NOW = datetime(2026, 9, 1, tzinfo=UTC)


def _source(root: Path, name: str = "one", body: str | None = None) -> ReviewSource:
    html = (
        body
        or "<main><h1>Example</h1><details><summary>Scope</summary><p>Body.</p></details></main>"
    )
    original, normalized = html.encode(), b"legacy normalized text"
    (root / f"{name}.html").write_bytes(original)
    (root / f"{name}.txt").write_bytes(normalized)
    url = f"https://example.com/{name}"
    return ReviewSource(
        title="Example",
        original_path=f"{name}.html",
        normalized_path=f"{name}.txt",
        evidence=CloudSourceEvidence(
            source_id=name,
            source_url=url,
            source_sha256=content_digest(original),
            normalized_sha256=content_digest(normalized),
            collected_at=NOW,
            check=SourceCheckReceipt(
                source_id=name,
                source_url=url,
                checked_at=NOW,
                outcome="fetched",
                content_sha256=content_digest(original),
                equivalence="body_hash",
                collector_id="fixture",
            ),
            applicability=Applicability(
                resource_type="Microsoft.Example/widgets", service_generation="reference"
            ),
            policy=RefreshPolicy(),
            license_ref="synthetic-fixture",
        ),
    )


def _plan(root: Path, *sources: ReviewSource) -> Path:
    path = root / "input.json"
    path.write_bytes(canonical_bytes(ReviewPlan(sources=sources)))
    return path


def test_real_worker_creates_original_free_candidate_and_exact_accounting(tmp_path: Path) -> None:
    source = _source(tmp_path)
    plan = _plan(tmp_path, source)
    output = tmp_path / "review"
    result = review.prepare_review(plan, source_root=tmp_path, output=output)
    assert result.requested == result.processable == 1
    assert result.held == result.not_processed == 0
    assert result.production_qualified is result.source_rights_verified is False
    assert result.independent_review_verified is result.execution_authority is False
    assert result.input_sha256 == content_digest(plan.read_bytes())
    assert result.sources[0].collected_at == result.sources[0].checked_at == NOW
    assert result.sources[0].candidate_path is not None
    candidate = (output / result.sources[0].candidate_path).read_bytes()
    doc = CloudStructuredDocument.model_validate_json(candidate)
    assert content_digest(candidate) == result.sources[0].candidate_sha256
    assert doc.normalizer_version == "2.1.0"
    assert b"original_text" not in candidate and b"<details>" not in candidate
    assert doc.evidence.model_dump(exclude={"normalized_sha256"}) == (
        source.evidence.model_dump(exclude={"normalized_sha256"})
    )
    assert ReviewReport.model_validate_json((output / "report.json").read_bytes()) == result
    assert output.stat().st_mode & 0o777 == 0o700
    assert all(path.stat().st_mode & 0o777 == 0o600 for path in output.iterdir())


def test_held_source_does_not_disappear_from_declared_scope(tmp_path: Path) -> None:
    good = _source(tmp_path, "good")
    held = _source(
        tmp_path, "held", '<main><p>Requires a diagram.</p><img src="/required.png"></main>'
    )
    result = review.prepare_review(
        _plan(tmp_path, good, held), source_root=tmp_path, output=tmp_path / "review"
    )
    assert (result.requested, result.processable, result.held) == (2, 1, 1)
    assert result.sources[1].outcome == "held"
    assert "unsupported_media" in result.sources[1].holds
    assert result.sources[1].candidate_path is not None
    assert result.sources[1].excerpts is None
    assert result.review_required and not result.production_qualified


def test_oversized_atomic_context_is_retained_without_excerpt_measurements(tmp_path: Path) -> None:
    source = _source(tmp_path, body="<main><p>" + "x" * 8192 + "</p></main>")
    result = review.prepare_review(
        _plan(tmp_path, source), source_root=tmp_path, output=tmp_path / "review"
    )
    assert result.held == result.requested == 1
    assert result.sources[0].holds == ("excerpt_derivation_rejected",)
    assert result.sources[0].candidate_path is not None
    assert result.sources[0].excerpts is None and result.sources[0].derived_bytes is None


@pytest.mark.parametrize("field", ["source_sha256", "normalized_sha256"])
def test_tampered_source_bytes_are_held_not_copied(tmp_path: Path, field: str) -> None:
    source = _source(tmp_path)
    plan = _plan(tmp_path, source)
    path = source.original_path if field == "source_sha256" else source.normalized_path
    (tmp_path / path).write_bytes(b"changed")
    output = tmp_path / "review"
    result = review.prepare_review(plan, source_root=tmp_path, output=output)
    assert result.held == 1 and result.sources[0].candidate_path is None
    assert [p.name for p in output.iterdir()] == ["report.json"]


@pytest.mark.parametrize(
    "path", ["../escape", "/absolute", "folder/../escape", "a//b", "a\\b", "a%2fb", "file:thing"]
)
def test_manifest_paths_cannot_escape_or_be_reinterpreted(tmp_path: Path, path: str) -> None:
    source = _source(tmp_path)
    with pytest.raises(ValueError):
        ReviewSource.model_validate(source.model_dump() | {"original_path": path})


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "fifo", "directory"])
def test_local_input_rejects_links_and_special_files_without_waiting(
    tmp_path: Path, kind: str
) -> None:
    original = tmp_path / "original"
    original.write_bytes(b"input")
    target = tmp_path / "target"
    if kind == "symlink":
        target.symlink_to(original)
    elif kind == "hardlink":
        os.link(original, target)
    elif kind == "fifo":
        os.mkfifo(target)
    else:
        target.mkdir()
    with directory(tmp_path) as root, pytest.raises((OSError, ValueError)):
        read_file(root, "target", 100)


def test_intermediate_symlink_and_existing_output_are_not_followed_or_replaced(
    tmp_path: Path,
) -> None:
    source = _source(tmp_path)
    plan = _plan(tmp_path, source)
    linked = tmp_path / "linked"
    linked.symlink_to(tmp_path, target_is_directory=True)
    assert (
        review.main(
            ["--input", str(plan), "--source-root", str(linked), "--output", str(tmp_path / "new")]
        )
        == 2
    )
    assert not (tmp_path / "new").exists()
    output = tmp_path / "existing"
    output.mkdir()
    sentinel = output / "retained"
    sentinel.write_bytes(b"never replace")
    assert (
        review.main(["--input", str(plan), "--source-root", str(tmp_path), "--output", str(output)])
        == 2
    )
    assert sentinel.read_bytes() == b"never replace"


@pytest.mark.parametrize(
    "content",
    [
        b'{"sources":[],"sources":[]}',
        b'{"x":NaN}',
        b'{"x":1e10000}',
        b'{"x":1e-10000}',
        b"[" * 33 + b"]" * 33,
    ],
)
def test_json_rejects_duplicates_nonfinite_and_deep_input(content: bytes) -> None:
    with pytest.raises(ValueError):
        decode_json(content, 4096)


def test_timeout_is_an_explicit_source_hold(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _source(tmp_path)

    def timeout(*args: object, **kwargs: object) -> WorkerResult:
        raise subprocess.TimeoutExpired("synthetic-worker", 1)

    monkeypatch.setattr(review, "_process", timeout)
    report = review.prepare_review(
        _plan(tmp_path, source), source_root=tmp_path, output=tmp_path / "review"
    )
    assert report.sources[0].holds == ("source_processing_deadline",)
    assert report.held == 1


def test_total_deadline_preserves_every_unprocessed_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first, second = _source(tmp_path, "one"), _source(tmp_path, "two")
    ticks = iter([0.0, 2.0, 2.0])
    monkeypatch.setattr(review.time, "monotonic", lambda: next(ticks))
    report = review.prepare_review(
        _plan(tmp_path, first, second),
        source_root=tmp_path,
        output=tmp_path / "review",
        total_seconds=1,
    )
    assert report.not_processed == report.requested == 2
    assert all(source.holds == ("review_deadline",) for source in report.sources)


def test_candidates_cannot_exceed_aggregate_output_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _source(tmp_path)
    monkeypatch.setattr(review, "MAX_TOTAL_OUTPUT_BYTES", 1)
    report = review.prepare_review(
        _plan(tmp_path, source), source_root=tmp_path, output=tmp_path / "review"
    )
    assert report.held == 1 and report.sources[0].holds == ("candidate_byte_budget",)
    assert report.candidate_bytes_written == 0


def test_deadline_is_rechecked_after_input_loading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _source(tmp_path)
    ticks = iter([0.0, 0.0, 2.0])
    monkeypatch.setattr(review.time, "monotonic", lambda: next(ticks))

    def forbidden(*args: object, **kwargs: object) -> WorkerResult:
        pytest.fail("expired total deadline reached the normalizer")

    monkeypatch.setattr(review, "_process", forbidden)
    report = review.prepare_review(
        _plan(tmp_path, source), source_root=tmp_path, output=tmp_path / "review", total_seconds=1
    )
    assert report.not_processed == 1


def test_expired_total_deadline_cannot_publish_a_successful_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _source(tmp_path)
    ticks = iter([0.0, 0.0, 0.0, 2.0])
    monkeypatch.setattr(review.time, "monotonic", lambda: next(ticks))
    output = tmp_path / "review"
    report = review.prepare_review(
        _plan(tmp_path, source), source_root=tmp_path, output=output, total_seconds=1
    )
    assert report.held == 1 and report.sources[0].holds == ("review_deadline",)
    assert [path.name for path in output.iterdir()] == ["report.json"]


def test_excerpt_derivation_runs_only_in_the_budgeted_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fdai_service_contracts import cloud_knowledge_structure

    def unbounded_parent(*args: object, **kwargs: object) -> None:
        pytest.fail("excerpt derivation escaped the timed child process")

    monkeypatch.setattr(review, "structured_excerpts", unbounded_parent, raising=False)
    monkeypatch.setattr(cloud_knowledge_structure, "structured_excerpts", unbounded_parent)
    source = _source(tmp_path)
    report = review.prepare_review(
        _plan(tmp_path, source), source_root=tmp_path, output=tmp_path / "review"
    )
    assert report.processable == 1 and report.sources[0].excerpts == report.sources[0].blocks


@pytest.mark.parametrize("outcome", ["held", "not_processed"])
def test_non_processable_receipt_cannot_claim_excerpt_measurements(outcome: str) -> None:
    with pytest.raises(ValueError):
        SourceReview.model_validate(
            {
                "source_id": "synthetic",
                "source_sha256": "a" * 64,
                "collected_at": NOW,
                "checked_at": NOW,
                "outcome": outcome,
                "holds": ("review_deadline",),
                "maximum_excerpt_bytes": 1,
                "derived_bytes": 1,
            }
        )


def test_worker_parent_lineage_is_rechecked_before_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fdai_ingestion_api_service.cloud_knowledge.structured_normalization import (
        reprocess_document,
    )
    from fdai_service_contracts.cloud_knowledge_release import CloudKnowledgeDocument

    source = _source(tmp_path)
    snapshot = CloudKnowledgeDocument(
        evidence=source.evidence,
        title=source.title,
        original_text=(tmp_path / source.original_path).read_text(),
        text=(tmp_path / source.normalized_path).read_text(),
    )
    doc = reprocess_document(snapshot, now=NOW, normalizer_version="2.1.0")
    forged = doc.model_copy(update={"parent_normalized_sha256": "f" * 64})
    sizes = tuple(len(excerpt.text.encode()) for excerpt in structured_excerpts(doc))
    result = WorkerResult(
        document=forged,
        metrics=ExcerptMetrics(
            excerpts=len(sizes), maximum_excerpt_bytes=max(sizes), derived_bytes=sum(sizes)
        ),
    )
    monkeypatch.setattr(review, "_process", lambda *args, **kwargs: result)
    report = review.prepare_review(
        _plan(tmp_path, source), source_root=tmp_path, output=tmp_path / "review"
    )
    assert report.held == 1 and report.sources[0].candidate_path is None


def test_duplicate_source_ids_cannot_inflate_denominator(tmp_path: Path) -> None:
    source = _source(tmp_path)
    with pytest.raises(ValueError, match="unique"):
        ReviewPlan(sources=(source, source))


def test_report_cannot_upgrade_itself_to_production(tmp_path: Path) -> None:
    source = _source(tmp_path)
    report = review.prepare_review(
        _plan(tmp_path, source), source_root=tmp_path, output=tmp_path / "review"
    )
    for field in (
        "production_qualified",
        "execution_authority",
        "independent_review_verified",
        "source_rights_verified",
    ):
        with pytest.raises(ValueError):
            ReviewReport.model_validate(report.model_dump() | {field: True})
    with pytest.raises(ValueError, match="counts"):
        ReviewReport.model_validate(report.model_dump() | {"held": 1})


def test_cli_holds_have_a_report_and_nonzero_exit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = _source(tmp_path, body='<main><p>Image evidence.</p><img src="/required.png"></main>')
    code = review.main(
        [
            "--input",
            str(_plan(tmp_path, source)),
            "--source-root",
            str(tmp_path),
            "--output",
            str(tmp_path / "review"),
        ]
    )
    assert code == 1
    assert "production_qualified=false" in capsys.readouterr().out
    assert json.loads((tmp_path / "review/report.json").read_bytes())["held"] == 1
