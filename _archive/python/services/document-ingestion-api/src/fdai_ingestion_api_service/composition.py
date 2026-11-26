"""Production composition selection for the Document Ingestion API service."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from fdai_ingestion_api_service.providers import (
    ApplicationFactory,
)
from fdai_ingestion_api_service.runtime import IngestionApiRuntime

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


def build_default_application(environ: Mapping[str, str]) -> object:
    """Build production providers only when the default factory is invoked."""
    from fdai_ingestion_api_service.production import build_application

    return build_application(environ)


@dataclass(frozen=True, slots=True)
class ConfiguredIngestionApiComposition:
    """Bind the service-owned factory after enforcing the API process role."""

    application_factory: ApplicationFactory = build_default_application

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
        return IngestionApiRuntime(
            environ=env,
            application_factory=self.application_factory,
        )
