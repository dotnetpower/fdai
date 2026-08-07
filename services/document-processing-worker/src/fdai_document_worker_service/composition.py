"""Production composition selection for the Document Processing Worker service."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from fdai_document_worker_service.providers import WorkerFactory
from fdai_document_worker_service.runtime import DocumentWorkerRuntime

_ROLE_ENV = "FDAI_INGESTION_DEPLOYMENT_ROLE"
_EXPECTED_ROLE = "worker"


class DocumentWorkerConfigurationError(ValueError):
    """Raised when service-local composition configuration is invalid."""


class DocumentWorkerComposition(Protocol):
    """Build the complete service-owned runtime without starting worker loops."""

    def build_runtime(
        self,
        environ: Mapping[str, str] | None = None,
    ) -> DocumentWorkerRuntime: ...


def run_default_worker(environ: Mapping[str, str]) -> int:
    """Build production providers only when the default factory is invoked."""
    from fdai_document_worker_service.production import run_production_worker

    return run_production_worker(environ)


@dataclass(frozen=True, slots=True)
class ConfiguredDocumentWorkerComposition:
    """Bind the service-owned factory after enforcing the worker process role."""

    worker_factory: WorkerFactory = run_default_worker

    def build_runtime(
        self,
        environ: Mapping[str, str] | None = None,
    ) -> DocumentWorkerRuntime:
        """Validate the role and bind the selected worker factory."""
        env = dict(os.environ if environ is None else environ)
        configured_role = env.get(_ROLE_ENV, "").strip()
        if configured_role != _EXPECTED_ROLE:
            raise DocumentWorkerConfigurationError(
                f"{_ROLE_ENV} does not match the document processing worker role"
            )
        return DocumentWorkerRuntime(
            environ=env,
            worker_factory=self.worker_factory,
        )
