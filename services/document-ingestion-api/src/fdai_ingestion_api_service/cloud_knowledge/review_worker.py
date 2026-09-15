"""One bounded stdin/stdout normalization process; no credentials, transport or activation."""

from __future__ import annotations

import argparse
import resource
import sys
from datetime import datetime

from fdai_service_contracts.cloud_knowledge import canonical_bytes
from fdai_service_contracts.cloud_knowledge_release import CloudKnowledgeDocument
from fdai_service_contracts.cloud_knowledge_structure import (
    CloudStructuredDocument,
    structured_excerpts,
)

from .review_contracts import MAX_WORKER_BYTES, ExcerptMetrics, WorkerResult
from .review_io import decode_json
from .structured_normalization import reprocess_document


def _measure(document: CloudStructuredDocument) -> WorkerResult:
    if document.unresolved_dependencies:
        return WorkerResult(document=document)
    try:
        excerpts = structured_excerpts(document)
    except ValueError:
        return WorkerResult(document=document, reason="excerpt_derivation_rejected")
    sizes = tuple(len(excerpt.text.encode("utf-8")) for excerpt in excerpts)
    return WorkerResult(
        document=document,
        metrics=ExcerptMetrics(
            excerpts=len(sizes), maximum_excerpt_bytes=max(sizes), derived_bytes=sum(sizes)
        ),
    )


def main() -> int:
    """Bound parsing and complete excerpt derivation, returning original-free candidates only."""
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--normalizer", choices=("2.0.0", "2.1.0"), required=True)
    parser.add_argument("--derived-at", required=True)
    args = parser.parse_args()
    resource.setrlimit(resource.RLIMIT_AS, (768 * 1024 * 1024, 768 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_CPU, (30, 30))
    try:
        snapshot = CloudKnowledgeDocument.model_validate(
            decode_json(sys.stdin.buffer.read(MAX_WORKER_BYTES + 1), MAX_WORKER_BYTES)
        )
        result = _measure(
            reprocess_document(
                snapshot,
                now=datetime.fromisoformat(args.derived_at),
                normalizer_version=args.normalizer,
            )
        )
        content = canonical_bytes(result)
        if len(content) > MAX_WORKER_BYTES:
            raise ValueError("review worker output exceeds its bound")
    except (ValueError, TypeError, RecursionError, MemoryError):
        content = canonical_bytes(WorkerResult(reason="normalization_rejected"))
    sys.stdout.buffer.write(content)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
