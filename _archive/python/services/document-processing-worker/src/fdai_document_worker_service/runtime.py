"""Service-owned runtime record for the Document Processing Worker."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from fdai_document_worker_service.providers import WorkerFactory


@dataclass(frozen=True, slots=True)
class DocumentWorkerRuntime:
    """Bind one environment snapshot to its resolved worker factory."""

    environ: Mapping[str, str]
    worker_factory: WorkerFactory

    def run(self) -> int:
        """Run the selected worker factory exactly once."""
        return self.worker_factory(self.environ)
