"""Opt-in production composition for bounded Core task workers, without parent admission.

The binding owns its PostgreSQL runtime lease and cancellation drain. It creates no worker,
operator endpoint, model probe, detached-session sink or execution authority at startup.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

import httpx

from fdai.composition.adaptive_model_targets import resolve_target
from fdai.core.metering.pricing import PricingTable
from fdai.core.task_worker.planning_executor import AnswerPlanningTaskWorkerExecutor
from fdai.core.task_worker.profiles import BACKGROUND_READ_ONLY_PROFILE
from fdai.core.task_worker.runtime import TaskWorkerRuntime, TaskWorkerRuntimeConfig
from fdai.delivery.azure.llm.task_worker import (
    AzureTaskWorkerPlanningConfig,
    AzureTaskWorkerPlanningProvider,
)
from fdai.delivery.persistence.postgres_task_worker import PostgresTaskWorkerStoreConfig
from fdai.delivery.persistence.postgres_task_worker_runtime import PostgresTaskWorkerRuntimeStore
from fdai.delivery.task_worker_inventory import (
    TaskWorkerReadScope,
    build_task_worker_inventory_tools,
)
from fdai.rule_catalog.schema.llm_resolver import ResolvedModels
from fdai.runtime.configuration import _model_endpoint_resolver
from fdai.shared.providers.workload_identity import WorkloadIdentity

if TYPE_CHECKING:
    from fdai.composition import Container
    from fdai.runtime.bootstrap_resources import RuntimeResources


async def bind_task_workers(
    container: Container,
    resources: RuntimeResources,
    identity: WorkloadIdentity | None,
    environment: Mapping[str, str],
) -> None:
    """Attach the factory result to Core's cleanup owner without duplicating bootstrap policy."""
    llm_bindings = container.llm_bindings
    resources.task_workers = await build_task_worker_runtime_from_env(
        environment=environment,
        resolved_models=container.resolved_models,
        held_capabilities=container.held_model_capabilities,
        identity=identity,
        http_client=resources.http_client,
        pricing=llm_bindings.conversation_pricing if llm_bindings is not None else None,
    )


@dataclass(frozen=True, slots=True)
class TaskWorkerRuntimeBinding:
    """A constructed read-only runtime and its exclusive durable owner."""

    runtime: TaskWorkerRuntime
    store: PostgresTaskWorkerRuntimeStore

    async def aclose(self) -> None:
        """Attempt a bounded drain, release owned resources, and propagate any drain failure."""
        try:
            async with asyncio.timeout(30):
                await self.runtime.aclose()
        finally:
            await self.store.aclose()


async def build_task_worker_runtime_from_env(
    *,
    environment: Mapping[str, str],
    resolved_models: ResolvedModels | None,
    held_capabilities: frozenset[str],
    identity: WorkloadIdentity | None,
    http_client: httpx.AsyncClient | None,
    pricing: PricingTable | None,
) -> TaskWorkerRuntimeBinding | None:
    """Bind enabled production workers or fail startup; absent opt-in makes no provider call."""
    enabled = environment.get("FDAI_TASK_WORKERS_ENABLED", "").strip().casefold()
    if enabled in {"", "0", "false", "no", "off"}:
        return None
    if enabled not in {"1", "true", "yes", "on"}:
        raise RuntimeError("FDAI_TASK_WORKERS_ENABLED MUST be boolean")
    dsn = environment.get("FDAI_STATE_STORE_DSN", "").strip()
    read_scope = environment.get("FDAI_TASK_WORKER_READ_SCOPE_JSON", "").strip()
    if not dsn or not read_scope:
        raise RuntimeError("enabled task workers require a Core DSN and explicit read scope")
    if resolved_models is None or identity is None or http_client is None or pricing is None:
        raise RuntimeError(
            "enabled task workers require resolved models, identity, HTTP and pricing"
        )
    if "t1.narrator" in held_capabilities:
        raise RuntimeError("task-worker presentation capability is held")
    endpoint = environment.get("FDAI_LLM_ENDPOINT", "").strip() or None
    resolver = (
        _model_endpoint_resolver(endpoint, environment.get("FDAI_MODEL_ENDPOINTS_JSON"))
        if endpoint is not None
        else None
    )
    target = resolve_target(
        resolved_models,
        "t1.judge",
        endpoint=endpoint,
        endpoint_resolver=resolver,
        held_capabilities=held_capabilities,
    )
    if target is None or target.publisher.casefold() != "openai" or not target.structured_output:
        raise RuntimeError("task workers require an eligible structured OpenAI presentation target")
    price = pricing.pricing_for(target.family)
    if price is None:
        raise RuntimeError("task-worker model pricing is unavailable")
    scope = TaskWorkerReadScope.from_json(read_scope)
    tools = build_task_worker_inventory_tools(dsn=dsn, scope=scope)
    provider = AzureTaskWorkerPlanningProvider(
        config=AzureTaskWorkerPlanningConfig(
            target=target.target, model_family=target.family, pricing=price
        ),
        identity=identity,
        http_client=http_client,
    )
    store = PostgresTaskWorkerRuntimeStore(config=PostgresTaskWorkerStoreConfig(dsn=dsn))
    runtime = TaskWorkerRuntime(
        store=store,
        executor=AnswerPlanningTaskWorkerExecutor(
            provider=provider, contributor_agent="Bragi", require_prepared=True
        ),
        tools=tools,
        config=TaskWorkerRuntimeConfig(
            profile_allowed_tools=BACKGROUND_READ_ONLY_PROFILE.allowed_tools
        ),
        require_recoverable_store=True,
    )
    try:
        async with asyncio.timeout(30):
            await store.open()
            await store.verify_inventory_source()
            await runtime.recover_interrupted()
    except BaseException:
        await store.aclose()
        raise
    return TaskWorkerRuntimeBinding(runtime, store)
