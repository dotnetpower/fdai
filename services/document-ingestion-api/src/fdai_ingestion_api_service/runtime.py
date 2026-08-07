"""Service-owned runtime record for the Document Ingestion API."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from fdai_ingestion_api_service.providers import ApplicationFactory


@dataclass(frozen=True, slots=True)
class IngestionApiRuntime:
    """Bind one environment snapshot to its resolved application factory."""

    environ: Mapping[str, str]
    application_factory: ApplicationFactory

    def create_app(self) -> object:
        """Create the configured ASGI application exactly once per invocation."""
        return self.application_factory(self.environ)
