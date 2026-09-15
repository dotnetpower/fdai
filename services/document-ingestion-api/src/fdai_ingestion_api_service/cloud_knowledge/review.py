"""Prepare retained snapshots for review without network, signatures, approvals or index writes."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from fdai_service_contracts.cloud_knowledge import canonical_bytes, content_digest
from fdai_service_contracts.cloud_knowledge_release import CloudKnowledgeDocument
from fdai_service_contracts.cloud_knowledge_structure import (
    StructuredNormalizerVersion,
)
from pydantic import TypeAdapter

from .review_contracts import (
    MAX_CANDIDATE_BYTES,
    MAX_MANIFEST_BYTES,
    MAX_SOURCE_BYTES,
    MAX_TOTAL_OUTPUT_BYTES,
    MAX_TOTAL_SOURCE_BYTES,
    MAX_WORKER_BYTES,
    ReviewError,
    ReviewPlan,
    ReviewReport,
    ReviewSource,
    SourceReview,
    WorkerResult,
)
from .review_io import decode_json, directory, new_directory, read_file, write_file

_NORMALIZER: TypeAdapter[StructuredNormalizerVersion] = TypeAdapter(StructuredNormalizerVersion)


def _process(
    snapshot: CloudKnowledgeDocument,
    *,
    version: StructuredNormalizerVersion,
    now: datetime,
    timeout: float,
) -> WorkerResult:
    content = canonical_bytes(snapshot)
    if len(content) > MAX_WORKER_BYTES:
        return WorkerResult(reason="normalization_rejected")
    command = [
        sys.executable,
        "-m",
        "fdai_ingestion_api_service.cloud_knowledge.review_worker",
        "--normalizer",
        version,
        "--derived-at",
        now.isoformat(),
    ]
    # Do not inherit cloud identity, proxy, signing, credentials or user-site settings.
    environment = {
        "PYTHONPATH": str(Path(__file__).resolve().parents[2]),
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "LANG": "C.UTF-8",
    }
    completed = subprocess.run(  # noqa: S603 - fixed module and validated arguments
        command,
        input=content,
        capture_output=True,
        check=False,
        timeout=timeout,
        env=environment,
    )
    if completed.returncode != 0 or len(completed.stdout) > MAX_WORKER_BYTES:
        raise ReviewError("review worker did not produce a bounded result")
    return WorkerResult.model_validate(decode_json(completed.stdout, MAX_WORKER_BYTES))


def _record(source: ReviewSource, **values: object) -> SourceReview:
    return SourceReview.model_validate(
        {
            "source_id": source.evidence.source_id,
            "source_sha256": source.evidence.source_sha256,
            "collected_at": source.evidence.collected_at,
            "checked_at": source.evidence.check.checked_at,
            **values,
        }
    )


def _candidate_record(source: ReviewSource, result: WorkerResult) -> SourceReview:
    doc = result.document
    if doc is None:
        raise ReviewError("review candidate requires a worker document")
    if (
        doc.title != source.title
        or doc.parent_normalized_sha256 != source.evidence.normalized_sha256
        or doc.evidence.model_dump(exclude={"normalized_sha256"})
        != source.evidence.model_dump(exclude={"normalized_sha256"})
    ):
        raise ReviewError("review worker changed source provenance")
    values: dict[str, object] = {
        "processing_digest": doc.processing_digest,
        "blocks": len(doc.blocks),
        "outcome": "held",
        "holds": doc.unresolved_dependencies or ((result.reason,) if result.reason else ()),
    }
    if result.metrics is not None:
        values.update(outcome="processable", **result.metrics.model_dump())
    content = canonical_bytes(doc)
    values.update(
        candidate_path=content_digest(source.evidence.source_id.encode()) + ".json",
        candidate_sha256=content_digest(content),
    )
    return _record(source, **values)


def prepare_review(
    plan_path: Path,
    *,
    source_root: Path,
    output: Path,
    normalizer_version: str = "2.1.0",
    per_source_seconds: int = 30,
    total_seconds: int = 900,
) -> ReviewReport:
    """Read a frozen local scope and publish every source outcome with original dates.

    No successful subset is emitted as an approved release. The output directory must
    be new; partial files survive a failed write for diagnosis, never as a successful run.
    """
    if not 1 <= per_source_seconds <= 30 or not 1 <= total_seconds <= 900:
        raise ReviewError("review deadlines exceed their bounds")
    version = _NORMALIZER.validate_python(normalizer_version, strict=True)
    with directory(plan_path.parent) as parent:
        content = read_file(parent, plan_path.name, MAX_MANIFEST_BYTES)
    plan = ReviewPlan.model_validate(decode_json(content, MAX_MANIFEST_BYTES))
    started = datetime.now(UTC)
    deadline = time.monotonic() + total_seconds
    results: list[SourceReview] = []
    source_bytes = candidate_bytes = 0
    with directory(source_root) as root, new_directory(output) as destination:
        for source in plan.sources:
            print(
                f"review-progress: started={len(results) + 1} requested={len(plan.sources)}",
                file=sys.stderr,
            )
            remaining = deadline - time.monotonic()
            if remaining <= 0 or source_bytes >= MAX_TOTAL_SOURCE_BYTES:
                reason = "review_deadline" if remaining <= 0 else "source_byte_budget"
                results.append(_record(source, outcome="not_processed", holds=(reason,)))
                continue
            try:
                original = read_file(
                    root,
                    source.original_path,
                    min(MAX_SOURCE_BYTES, MAX_TOTAL_SOURCE_BYTES - source_bytes),
                )
                source_bytes += len(original)
                normalized = read_file(
                    root,
                    source.normalized_path,
                    min(MAX_SOURCE_BYTES, MAX_TOTAL_SOURCE_BYTES - source_bytes),
                )
                source_bytes += len(normalized)
                snapshot = CloudKnowledgeDocument(
                    evidence=source.evidence,
                    title=source.title,
                    original_text=original.decode("utf-8"),
                    text=normalized.decode("utf-8"),
                )
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    results.append(
                        _record(source, outcome="not_processed", holds=("review_deadline",))
                    )
                    continue
                result = _process(
                    snapshot,
                    version=version,
                    now=datetime.now(UTC),
                    timeout=min(per_source_seconds, remaining),
                )
                if result.document is None:
                    results.append(
                        _record(source, outcome="held", holds=("normalization_rejected",))
                    )
                    continue
                doc = result.document
                if doc.normalizer_version != version:
                    raise ReviewError("review worker returned the wrong normalizer")
                record = _candidate_record(source, result)
                candidate = canonical_bytes(doc)
                if time.monotonic() >= deadline:
                    results.append(_record(source, outcome="held", holds=("review_deadline",)))
                    continue
                if (
                    len(candidate) > MAX_CANDIDATE_BYTES
                    or candidate_bytes + len(candidate) > MAX_TOTAL_OUTPUT_BYTES
                ):
                    results.append(
                        _record(source, outcome="held", holds=("candidate_byte_budget",))
                    )
                    continue
            except subprocess.TimeoutExpired:
                results.append(
                    _record(source, outcome="held", holds=("source_processing_deadline",))
                )
                continue
            except (OSError, ValueError, TypeError, RecursionError):
                results.append(
                    _record(source, outcome="held", holds=("source_input_or_processing_rejected",))
                )
                continue
            if record.candidate_path is None:
                raise ReviewError("review candidate path is missing")
            write_file(destination, record.candidate_path, candidate)
            candidate_bytes += len(candidate)
            results.append(record)
            print(
                f"review-progress: completed={len(results)} requested={len(plan.sources)}",
                file=sys.stderr,
            )
        report = ReviewReport(
            input_sha256=content_digest(content),
            normalizer_version=version,
            started_at=started,
            completed_at=datetime.now(UTC),
            sources=tuple(results),
            requested=len(plan.sources),
            processable=sum(r.outcome == "processable" for r in results),
            held=sum(r.outcome == "held" for r in results),
            not_processed=sum(r.outcome == "not_processed" for r in results),
            source_bytes_read=source_bytes,
            candidate_bytes_written=candidate_bytes,
        )
        write_file(destination, "report.json", canonical_bytes(report))
        os.fsync(destination)
    return report


def main(argv: list[str] | None = None) -> int:
    """Return 0 for all-source processing, 1 for explicit holds, 2 for invalid input/I/O.

    Every return path is review-only; even 0 is not source-rights or answer qualification.
    """
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--normalizer-version", choices=("2.0.0", "2.1.0"), default="2.1.0")
    parser.add_argument("--per-source-seconds", type=int, default=30)
    parser.add_argument("--total-seconds", type=int, default=900)
    args = parser.parse_args(argv)
    try:
        report = prepare_review(
            args.input,
            source_root=args.source_root,
            output=args.output,
            normalizer_version=args.normalizer_version,
            per_source_seconds=args.per_source_seconds,
            total_seconds=args.total_seconds,
        )
    except (OSError, ValueError, TypeError, RecursionError):
        print("cloud-knowledge-review: rejected local input or output", file=sys.stderr)
        return 2
    print(
        f"cloud-knowledge-review: requested={report.requested} processable={report.processable} "
        f"held={report.held} not_processed={report.not_processed} production_qualified=false"
    )
    return 0 if report.processable == report.requested else 1


if __name__ == "__main__":
    raise SystemExit(main())
