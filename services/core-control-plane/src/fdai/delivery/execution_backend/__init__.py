"""Governed execution-backend adapters bound at the composition root."""

from __future__ import annotations

from fdai.delivery.execution_backend.adapters import (
    BubblewrapExecutionBackend,
    VmTaskExecutionBackend,
)

__all__ = ["BubblewrapExecutionBackend", "VmTaskExecutionBackend"]
