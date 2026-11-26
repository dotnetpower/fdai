"""Governed execution-backend adapters bound at the composition root."""

from __future__ import annotations

from fdai.delivery.execution_backend.adapters import (
    BubblewrapExecutionBackend,
    VmTaskExecutionBackend,
)
from fdai.delivery.execution_backend.container_apps_job import (
    AzureContainerAppsJobExecutionBackend,
    ContainerAppsJobConfig,
    ContainerAppsJobTemplate,
)

__all__ = [
    "AzureContainerAppsJobExecutionBackend",
    "BubblewrapExecutionBackend",
    "ContainerAppsJobConfig",
    "ContainerAppsJobTemplate",
    "VmTaskExecutionBackend",
]
