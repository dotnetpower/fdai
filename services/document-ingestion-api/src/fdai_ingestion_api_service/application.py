"""Application lifecycle boundary for the Document Ingestion API service."""

from __future__ import annotations

from collections.abc import Mapping

from fdai_ingestion_api_service.composition import (
    ConfiguredIngestionApiComposition,
    IngestionApiComposition,
)


def create_app(
    environ: Mapping[str, str] | None = None,
    *,
    composition: IngestionApiComposition | None = None,
) -> object:
    """Build the configured production application without importing an implementation."""
    selected = composition or ConfiguredIngestionApiComposition()
    return selected.build_runtime(environ).create_app()
