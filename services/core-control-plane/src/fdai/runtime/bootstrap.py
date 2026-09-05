"""Headless control-plane process lifecycle and shutdown coordination."""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import httpx

from fdai.composition import (
    Container,
    LlmBindings,
    bind_resolved_models_revision,
    default_container_from_env,
)
from fdai.delivery.github.model_lifecycle_observations import (
    GitHubModelLifecycleObservationConfig,
    GitHubModelLifecycleObservationSource,
)
from fdai.delivery.runtime_settings import runtime_settings_service_from_env
from fdai.runtime.bootstrap_bindings import (
    build_runtime_workload_identity as _build_runtime_workload_identity,
)
from fdai.runtime.bootstrap_bindings import (
    case_history_identity_client_id as _case_history_identity_client_id,
)
from fdai.runtime.bootstrap_core import (
    CoreRuntime,
    build_core_runtime,
)
from fdai.runtime.bootstrap_lifecycle import (
    bind_health_readiness,
    install_shutdown_signals,
    open_health_port,
)
from fdai.runtime.bootstrap_lifecycle import (
    run_main as _run_main,
)
from fdai.runtime.bootstrap_plan import build_bootstrap_plan
from fdai.runtime.bootstrap_resources import RuntimeResources
from fdai.runtime.bootstrap_task_hooks import default_runtime_task_hooks
from fdai.runtime.bootstrap_tasks import (
    run_runtime_tasks,
)
from fdai.runtime.bootstrap_tasks import (
    schedule_semantic_turn_consumer as _schedule_semantic_turn_consumer,
)
from fdai.runtime.bootstrap_topics import RUNTIME_LOGICAL_TOPICS as _RUNTIME_LOGICAL_TOPICS
from fdai.runtime.configuration import (
    _attach_runtime_configuration_drift,
    _attach_runtime_knowledge_source,
    _attach_runtime_metric_provider,
    _finalize_llm_bindings,
    _new_http_client,
    _summarize_config,
)
from fdai.runtime.model_lifecycle_startup import (
    FileResolvedModelsSource,
    resolve_models_startup_revision,
)
from fdai.runtime.providers import _build_audit_store
from fdai.shared.config.models import LlmMode
from fdai.shared.config.runtime_flags import pantheon_start_enabled
from fdai.shared.providers.state_store import StateStore

_LOGGER = logging.getLogger("fdai.startup")
__all__ = [
    "_RUNTIME_LOGICAL_TOPICS",
    "_run",
    "_schedule_semantic_turn_consumer",
    "main",
]


async def _run() -> int:
    container = default_container_from_env()
    plan = build_bootstrap_plan(
        llm_mode=container.config.llm.mode,
        environment=os.environ,
    )
    summary = _summarize_config(container)
    _LOGGER.info("startup_ok", extra={"config": summary})

    resources = RuntimeResources()
    identity: Any = None
    runtime_values: Mapping[str, object] | None = None
    state_store: StateStore | None = None

    try:
        resources.health_server = await open_health_port()
        if container.config.llm.mode == LlmMode.AZURE or plan.start_consumer:
            runtime_values = await runtime_settings_service_from_env(os.environ).effective_values()
        identity_requests = plan.identity_requests
        if identity_requests.case_history:
            _case_history_identity_client_id(os.environ)
        if plan.requires_initial_identity:
            resources.http_client = _new_http_client()
            identity = _build_runtime_workload_identity(resources.http_client)

        if container.config.llm.mode == LlmMode.AZURE:
            if resources.http_client is None or identity is None:
                raise RuntimeError("Azure LLM mode requires HTTP and workload identity bindings")
            if runtime_values is None:  # pragma: no cover - startup branch invariant
                raise RuntimeError("Azure LLM mode requires a runtime settings snapshot")
            state_store = _build_audit_store()
            container = await _attach_model_lifecycle_startup_revision(
                container,
                http_client=resources.http_client,
                environment=os.environ,
                state_store=state_store,
            )
            container = await _finalize_llm_bindings(
                container,
                http_client=resources.http_client,
                identity=identity,
                runtime_values=runtime_values,
            )
            bindings: LlmBindings = container.require_llm_bindings()
            _LOGGER.info(
                "azure_llm_bindings_attached",
                extra={"cross_check_models": len(bindings.cross_check_models)},
            )
        elif identity_requests.telemetry:
            if resources.http_client is None or identity is None:
                raise RuntimeError("Azure telemetry requires HTTP and workload identity bindings")
            container = _attach_runtime_metric_provider(
                container,
                http_client=resources.http_client,
                identity=identity,
            )

        if container.llm_bindings is not None:
            container = _attach_runtime_knowledge_source(container)

        if identity_requests.configuration_drift:
            if resources.http_client is None or identity is None:
                raise RuntimeError(
                    "Azure configuration drift requires HTTP and workload identity bindings"
                )
            container = _attach_runtime_configuration_drift(
                container,
                http_client=resources.http_client,
                identity=identity,
                environment=os.environ,
            )

        core_runtime: CoreRuntime | None = None
        if plan.start_consumer:
            if runtime_values is None:  # pragma: no cover - startup branch invariant
                raise RuntimeError("Core runtime requires a runtime settings snapshot")
            if identity is None and plan.consumer_requires_workload_identity:
                if resources.http_client is None:
                    resources.http_client = _new_http_client()
                identity = _build_runtime_workload_identity(resources.http_client)
            core_runtime = await build_core_runtime(
                container=container,
                plan=plan,
                resources=resources,
                identity=identity,
                environment=os.environ,
                runtime_values_snapshot=runtime_values,
                state_store=state_store,
            )
        elif pantheon_start_enabled(os.environ):
            # Pantheon needs the same Kafka bus the consumer builds; without
            # FDAI_START_CONSUMER there is no bus to bind to. Warn rather
            # than silently no-op so a miswired container is visible.
            _LOGGER.warning("pantheon_requested_without_consumer")

        bind_health_readiness(
            resources.health_server,
            control_loop=(core_runtime.control_loop if core_runtime is not None else None),
            startup_readiness=(core_runtime.readiness if core_runtime is not None else None),
        )
        stop = install_shutdown_signals()
        if core_runtime is not None:
            await run_runtime_tasks(
                core_runtime.task_configuration(stop),
                default_runtime_task_hooks(),
            )
        else:
            await stop.wait()

        _LOGGER.info("shutdown_complete")
        return 0
    finally:
        await resources.close()


async def _attach_model_lifecycle_startup_revision(
    container: Container,
    *,
    http_client: httpx.AsyncClient,
    environment: Mapping[str, str],
    state_store: StateStore,
    evaluated_at: datetime | None = None,
) -> Container:
    path = container.config.llm.resolved_models_path
    expected_digest = container.config.llm.resolved_models_sha256
    if path is None or expected_digest is None:
        raise RuntimeError("Azure LLM startup requires one resolved-model revision")
    observations: tuple[Mapping[str, object], ...] = ()
    token = environment.get("FDAI_GITOPS_TOKEN", "").strip()
    runtime_env = environment.get("RUNTIME_ENV", "").strip().lower()
    if not token and runtime_env in {"staging", "prod"}:
        raise RuntimeError("staging and prod require FDAI_GITOPS_TOKEN for lifecycle observations")
    if token:
        owner = environment.get("FDAI_GITOPS_OWNER", "").strip()
        repo = environment.get("FDAI_GITOPS_REPO", "").strip()
        if not owner or not repo:
            raise RuntimeError("FDAI_GITOPS_TOKEN requires FDAI_GITOPS_OWNER and FDAI_GITOPS_REPO")
        ttl_raw = environment.get("FDAI_MODEL_LIFECYCLE_REVIEW_TTL_HOURS", "168")
        try:
            ttl_hours = int(ttl_raw)
        except ValueError as exc:
            raise RuntimeError("FDAI_MODEL_LIFECYCLE_REVIEW_TTL_HOURS MUST be an integer") from exc
        observations = await GitHubModelLifecycleObservationSource(
            config=GitHubModelLifecycleObservationConfig(
                owner=owner,
                repo=repo,
                api_base=environment.get(
                    "FDAI_GITHUB_API_BASE",
                    "https://api.github.com",
                ).strip(),
                review_ttl_hours=ttl_hours,
            ),
            http_client=http_client,
            token=token,
        ).load()
    revision = await resolve_models_startup_revision(
        FileResolvedModelsSource(path),
        expected_artifact_digest=expected_digest,
        observations=observations,
        decision_store=state_store,
        evaluated_at=evaluated_at or datetime.now(UTC),
    )
    return bind_resolved_models_revision(
        container,
        models=revision.models,
        artifact_digest=revision.artifact_digest,
        held_capabilities=revision.held_capabilities,
    )


def main() -> int:
    return _run_main(_run)
