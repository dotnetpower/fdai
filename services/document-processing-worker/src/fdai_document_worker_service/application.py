"""Application lifecycle boundary for the Document Processing Worker service."""

from __future__ import annotations

from collections.abc import Mapping

from fdai_document_worker_service.composition import (
    ConfiguredDocumentWorkerComposition,
    DocumentWorkerComposition,
)
from fdai_document_worker_service.supervisor import configure_worker_logging


def run_worker(
    environ: Mapping[str, str] | None = None,
    *,
    composition: DocumentWorkerComposition | None = None,
) -> int:
    """Run the configured worker without importing an implementation package."""
    configure_worker_logging()
    selected = composition or ConfiguredDocumentWorkerComposition()
    return selected.build_runtime(environ).run()
