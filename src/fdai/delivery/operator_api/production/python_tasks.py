"""Optional production composition for governed Python tasks."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass

import httpx

from fdai.delivery.operator_api.production import env_contract as _env
from fdai.delivery.operator_api.production.config import ProdOperatorApiConfigError
from fdai.delivery.operator_api.routes.python_tasks import (
    PythonTaskRoutesConfig,
    PythonTaskRunSubmitter,
)
from fdai.delivery.persistence.postgres_scheduler_store import (
    PostgresScheduleStore,
    PostgresScheduleStoreConfig,
)
from fdai.delivery.persistence.postgres_vm_task import (
    PostgresPythonTaskArtifactStore,
    PostgresVmTaskConfig,
    PostgresVmTaskTargetResolver,
)
from fdai.delivery.vm_task import PlanningVmTaskRunner
from fdai.shared.contracts.models import Workflow
from fdai.shared.providers.event_bus import EventBus

ShutdownCallback = Callable[[], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class ProductionPythonTasks:
    routes: PythonTaskRoutesConfig
    shutdown_callbacks: tuple[ShutdownCallback, ...]


def build_production_python_tasks(
    *,
    env: Mapping[str, str],
    dsn: str,
    statement_timeout_ms: int,
    connect_timeout_s: int,
    event_bus: EventBus | None,
    event_topic: str,
    workflows: tuple[Workflow, ...],
    shutdown_callbacks: tuple[ShutdownCallback, ...],
) -> ProductionPythonTasks:
    """Build Python-task persistence, planning, and optional authoring."""
    store_config = PostgresVmTaskConfig(
        dsn=dsn,
        statement_timeout_ms=statement_timeout_ms,
        connect_timeout_s=connect_timeout_s,
    )
    task_author = None
    author_endpoint = env.get(_env.PYTHON_TASK_AUTHOR_ENDPOINT_ENV, "").strip()
    author_deployment = env.get(_env.PYTHON_TASK_AUTHOR_DEPLOYMENT_ENV, "").strip()
    if bool(author_endpoint) != bool(author_deployment):
        raise ProdOperatorApiConfigError(
            f"{_env.PYTHON_TASK_AUTHOR_ENDPOINT_ENV} and "
            f"{_env.PYTHON_TASK_AUTHOR_DEPLOYMENT_ENV} MUST be configured together"
        )
    if author_endpoint:
        from fdai.delivery.azure.llm.python_task_author import (
            AzureOpenAIPythonTaskAuthor,
            AzureOpenAIPythonTaskAuthorConfig,
        )
        from fdai.delivery.azure.workload_identity import ManagedIdentityWorkloadIdentity

        author_http = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=60.0, write=15.0, pool=5.0)
        )
        task_author = AzureOpenAIPythonTaskAuthor(
            identity=ManagedIdentityWorkloadIdentity(http_client=author_http),
            http_client=author_http,
            config=AzureOpenAIPythonTaskAuthorConfig(
                endpoint=author_endpoint,
                deployment=author_deployment,
            ),
        )

        async def _close_task_author_http() -> None:
            await author_http.aclose()

        shutdown_callbacks = (*shutdown_callbacks, _close_task_author_http)

    routes = PythonTaskRoutesConfig(
        artifacts=PostgresPythonTaskArtifactStore(config=store_config),
        targets=PostgresVmTaskTargetResolver(config=store_config),
        runner=PlanningVmTaskRunner(),
        submitter=(
            PythonTaskRunSubmitter(event_bus=event_bus, topic=event_topic)
            if event_bus is not None and event_topic
            else None
        ),
        schedule_store=PostgresScheduleStore(
            config=PostgresScheduleStoreConfig(
                dsn=dsn,
                statement_timeout_ms=statement_timeout_ms,
                connect_timeout_s=connect_timeout_s,
            )
        ),
        workflows=workflows,
        author=task_author,
    )
    return ProductionPythonTasks(routes=routes, shutdown_callbacks=shutdown_callbacks)
