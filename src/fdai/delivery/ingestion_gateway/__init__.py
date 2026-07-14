"""Dedicated document-ingestion ASGI gateway."""

from .main import IngestionGatewayConfig, build_app

__all__ = ["IngestionGatewayConfig", "build_app"]
