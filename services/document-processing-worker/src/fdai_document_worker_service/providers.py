"""Injected provider contracts for Document Processing Worker composition."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol


class WorkerFactory(Protocol):
    """Run one worker process from a validated environment snapshot."""

    def __call__(self, environ: Mapping[str, str]) -> int: ...
