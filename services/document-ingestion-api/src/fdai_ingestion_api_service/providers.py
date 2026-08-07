"""Injected provider contracts for Document Ingestion API composition."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol


class ApplicationFactory(Protocol):
    """Build one ASGI application from a validated environment snapshot."""

    def __call__(self, environ: Mapping[str, str]) -> object: ...


class ApplicationFactoryResolver(Protocol):
    """Resolve a configured application factory without owning its implementation."""

    def __call__(self, reference: str) -> ApplicationFactory: ...
