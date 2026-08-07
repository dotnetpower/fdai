"""Deprecated compatibility entry point for the isolated Executor service."""

from fdai_executor_service.cli import (
    IsolatedExecutorRuntimeConfig,
    build_isolated_executor_supervisor,
    main,
)

__all__ = [
    "IsolatedExecutorRuntimeConfig",
    "build_isolated_executor_supervisor",
    "main",
]
