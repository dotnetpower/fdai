"""Exact-version DOCX ingestion for frozen configuration baselines."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Final

from fdai.core.detection.configuration_drift import FrozenConfigurationBaseline
from fdai.shared.providers.knowledge import KnowledgeDocument, KnowledgeSource
from fdai.shared.providers.local.document_structure import extract_ooxml

_MAX_DOCUMENT_BYTES: Final[int] = 16 * 1024 * 1024


def configuration_baseline_document(
    baseline: FrozenConfigurationBaseline,
    *,
    document_path: Path,
) -> KnowledgeDocument:
    """Build one host-path-free Knowledge document pinned to baseline metadata."""

    content = document_path.read_bytes()
    if not content or len(content) > _MAX_DOCUMENT_BYTES:
        raise ValueError("configuration baseline DOCX size is outside the allowed range")
    digest = hashlib.sha256(content).hexdigest()
    if digest != baseline.document_sha256:
        raise ValueError("configuration baseline DOCX digest does not match the baseline")
    units = extract_ooxml(content)
    text = "\n\n".join(unit.text for unit in units if unit.text.strip())
    if not text:
        raise ValueError("configuration baseline DOCX contains no readable content")
    source_ref = document_path.name
    return KnowledgeDocument(
        doc_id=f"configuration-baseline:{baseline.version}",
        text=text,
        source_ref=source_ref,
        metadata={
            "baseline_version": baseline.version,
            "baseline_sha256": baseline.sha256,
            "document_sha256": baseline.document_sha256,
            "scope": baseline.scope,
            "suffix": ".docx",
        },
    )


async def ingest_configuration_baseline(
    source: KnowledgeSource,
    baseline: FrozenConfigurationBaseline,
    *,
    document_path: Path,
) -> int:
    """Ingest one exact baseline and fail when no chunk is accepted."""

    document = configuration_baseline_document(baseline, document_path=document_path)
    added = await source.ingest((document,))
    if added < 1:
        raise RuntimeError("configuration baseline Knowledge ingestion added no chunks")
    return added


__all__ = ["configuration_baseline_document", "ingest_configuration_baseline"]
