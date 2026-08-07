"""Production composition selection for the Document Ingestion API service."""

from __future__ import annotations

import importlib
import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol, cast

from fdai_ingestion_api_service.providers import (
    ApplicationFactory,
    ApplicationFactoryResolver,
)
from fdai_ingestion_api_service.runtime import IngestionApiRuntime

FACTORY_ENV = "FDAI_INGESTION_API_FACTORY"
DEFAULT_FACTORY = "fdai_ingestion_api_service.adapters.legacy_fdai:create_app"
_ROLE_ENV = "FDAI_INGESTION_DEPLOYMENT_ROLE"
_EXPECTED_ROLE = "api"


class IngestionApiConfigurationError(ValueError):
    """Raised when service-local composition configuration is invalid."""


class IngestionApiComposition(Protocol):
    """Build the complete service-owned runtime without starting the server."""

    def build_runtime(
        self,
        environ: Mapping[str, str] | None = None,
    ) -> IngestionApiRuntime: ...


def resolve_application_factory(reference: str) -> ApplicationFactory:
    """Resolve a ``module:attribute`` application factory reference."""
    module_name, separator, attribute_name = reference.strip().partition(":")
    if not separator or not module_name or not attribute_name:
        raise IngestionApiConfigurationError(f"{FACTORY_ENV} MUST use a module:attribute reference")
    try:
        candidate = getattr(importlib.import_module(module_name), attribute_name)
    except (AttributeError, ImportError) as exc:
        raise IngestionApiConfigurationError(f"{FACTORY_ENV} could not be resolved") from exc
    if not callable(candidate):
        raise IngestionApiConfigurationError(f"{FACTORY_ENV} MUST resolve to a callable")
    return cast(ApplicationFactory, candidate)


@dataclass(frozen=True, slots=True)
class ConfiguredIngestionApiComposition:
    """Resolve the configured factory after enforcing the API process role."""

    resolver: ApplicationFactoryResolver = resolve_application_factory

    def build_runtime(
        self,
        environ: Mapping[str, str] | None = None,
    ) -> IngestionApiRuntime:
        """Validate the role and bind the selected application factory."""
        env = dict(os.environ if environ is None else environ)
        configured_role = env.get(_ROLE_ENV, "").strip()
        if configured_role != _EXPECTED_ROLE:
            raise IngestionApiConfigurationError(
                f"{_ROLE_ENV} does not match the document ingestion API role"
            )
        reference = env.get(FACTORY_ENV, DEFAULT_FACTORY).strip()
        if not reference:
            raise IngestionApiConfigurationError(f"{FACTORY_ENV} MUST be non-empty")
        return IngestionApiRuntime(
            environ=env,
            application_factory=self.resolver(reference),
        )
