"""Production composition selection for the Document Processing Worker service."""

from __future__ import annotations

import importlib
import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol, cast

from fdai_document_worker_service.providers import WorkerFactory, WorkerFactoryResolver
from fdai_document_worker_service.runtime import DocumentWorkerRuntime

FACTORY_ENV = "FDAI_DOCUMENT_WORKER_FACTORY"
DEFAULT_FACTORY = "fdai_document_worker_service.adapters.legacy_fdai:run_worker"
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


def resolve_worker_factory(reference: str) -> WorkerFactory:
    """Resolve a ``module:attribute`` worker factory reference."""
    module_name, separator, attribute_name = reference.strip().partition(":")
    if not separator or not module_name or not attribute_name:
        raise DocumentWorkerConfigurationError(
            f"{FACTORY_ENV} MUST use a module:attribute reference"
        )
    try:
        candidate = getattr(importlib.import_module(module_name), attribute_name)
    except (AttributeError, ImportError) as exc:
        raise DocumentWorkerConfigurationError(f"{FACTORY_ENV} could not be resolved") from exc
    if not callable(candidate):
        raise DocumentWorkerConfigurationError(f"{FACTORY_ENV} MUST resolve to a callable")
    return cast(WorkerFactory, candidate)


@dataclass(frozen=True, slots=True)
class ConfiguredDocumentWorkerComposition:
    """Resolve the configured factory after enforcing the worker process role."""

    resolver: WorkerFactoryResolver = resolve_worker_factory

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
        reference = env.get(FACTORY_ENV, DEFAULT_FACTORY).strip()
        if not reference:
            raise DocumentWorkerConfigurationError(f"{FACTORY_ENV} MUST be non-empty")
        return DocumentWorkerRuntime(
            environ=env,
            worker_factory=self.resolver(reference),
        )
