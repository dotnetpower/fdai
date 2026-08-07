"""Compatibility adapter for the existing FDAI ingestion implementation."""

from __future__ import annotations

from collections.abc import Mapping


def create_app(environ: Mapping[str, str]) -> object:
    """Delegate application construction to the legacy implementation package."""
    from fdai.delivery.ingestion_gateway.prod import build_prod_app

    return build_prod_app(environ)
