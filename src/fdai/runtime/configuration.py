"""Runtime path, HTTP, configuration summary, and container attachment helpers."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import httpx

from fdai.composition import (
    AzureWireOverrides,
    Container,
    wire_azure_container,
)
from fdai.runtime.providers import (
    _build_metering_store,
    _build_model_health_sink,
    _build_operator_memory_store,
)
from fdai.shared.config.models import LlmMode
from fdai.shared.providers.workload_identity import WorkloadIdentity

_LOGGER = logging.getLogger("fdai.startup")


def _new_http_client() -> httpx.AsyncClient:
    """Build the shared :class:`httpx.AsyncClient` with sensible timeouts.

    httpx's default is a global 5-second timeout on every phase, which is
    too aggressive for LLM completions (T2 reasoners can legitimately
    stream for tens of seconds) and for the GitOps + Chatops adapters that
    hit third-party APIs behind rate limiters. The per-phase budget below
    keeps the connect phase snappy (fail fast on DNS / TCP) while giving
    the read phase enough headroom for realistic responses.

    Every adapter that needs one MUST use this helper instead of
    ``httpx.AsyncClient()`` so timeouts stay uniform and diff-reviewable.
    """
    return httpx.AsyncClient(
        timeout=httpx.Timeout(connect=5.0, read=60.0, write=15.0, pool=5.0),
        follow_redirects=False,
    )


def _resolve_catalog_root() -> Path:
    """Locate the rule-catalog/ tree across dev + container layouts.

    - Dev / editable install: ``<repo>/rule-catalog/`` next to ``src/``.
    - Docker runtime: ``/app/rule-catalog/`` (see Dockerfile).
    - Explicit override via ``FDAI_CATALOG_ROOT`` env.

    A missing tree is a fail-fast error - the control loop can't start
    without at least one rule.
    """
    override = os.environ.get("FDAI_CATALOG_ROOT")
    if override:
        candidate = Path(override)
        if candidate.is_dir():
            return candidate
        raise FileNotFoundError(f"FDAI_CATALOG_ROOT={override!r} is not a directory")

    # Walk up from this module looking for a rule-catalog/ sibling.
    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        cand = parent / "rule-catalog"
        if (cand / "catalog").is_dir():
            return cand

    # Container image default (Dockerfile copies to /app/rule-catalog).
    for absolute in (Path("/app/rule-catalog"), Path.cwd() / "rule-catalog"):
        if (absolute / "catalog").is_dir():
            return absolute

    raise FileNotFoundError("Could not locate the rule-catalog tree. Set FDAI_CATALOG_ROOT.")


def _resolve_policies_root(catalog_root: Path) -> Path:
    """Sibling policies/ tree; same override + walk-up as catalog."""
    override = os.environ.get("FDAI_POLICIES_ROOT")
    if override:
        candidate = Path(override)
        if candidate.is_dir():
            return candidate
        raise FileNotFoundError(f"FDAI_POLICIES_ROOT={override!r} is not a directory")
    sibling = catalog_root.parent / "policies"
    if sibling.is_dir():
        return sibling
    for absolute in (Path("/app/policies"), Path.cwd() / "policies"):
        if absolute.is_dir():
            return absolute
    raise FileNotFoundError("Could not locate the policies/ tree. Set FDAI_POLICIES_ROOT.")


def _summarize_config(container: Container) -> dict[str, Any]:
    """Return a secret-free view of the loaded config for the startup log."""
    cfg = container.config
    return {
        "env": cfg.runtime.env,
        "autonomy_mode_default": cfg.runtime.autonomy_mode_default.value,
        "azure_region": cfg.azure.region,
        "kafka_bootstrap": cfg.kafka.bootstrap_servers,
        "kafka_topic_events": cfg.kafka.topic_events,
        "postgres_host": cfg.postgres.host,
        "postgres_db": cfg.postgres.database,
        "llm_mode": cfg.llm.mode,
        "llm_capabilities": list(cfg.llm.capabilities),
        "llm_bindings_available": container.llm_bindings is not None,
        # Adapter parity: log whether telemetry seams resolved to their
        # live Azure adapters or fell back to the upstream no-op defaults,
        # so an operator can tell at a glance whether detection sees real
        # metrics or nothing at all.
        "metric_provider": type(container.metric_provider).__name__,
        "inventory": type(container.inventory).__name__,
    }


async def _finalize_llm_bindings(
    container: Container,
    *,
    http_client: httpx.AsyncClient,
    identity: WorkloadIdentity,
) -> Container:
    """When mode=azure, attach the real AOAI adapters. Otherwise no-op.

    Backwards-compat wrapper around the public
    :func:`fdai.composition.wire_azure_container`. This helper's
    only remaining job is env-var resolution:

    - ``FDAI_LLM_ENDPOINT`` -> ``AzureWireOverrides.endpoint``
    - :func:`_resolve_catalog_root` -> ``AzureWireOverrides.catalog_root``
    - :func:`_build_operator_memory_store` -> ``.operator_memory_store``
    - ``FDAI_MONITOR_WORKSPACE_ID`` (optional) ->
      ``AzureWireOverrides.monitor_workspace_id``. When set,
      :func:`wire_azure_container` auto-binds the Azure Monitor Logs
      metric adapter using the shipped
      :func:`~fdai.delivery.azure.demo_queries.default_metric_queries`
      catalog in place of :class:`NoopMetricProvider`, so the detection
      pipeline sees real telemetry without every fork rewriring it.
    - ``FDAI_PROMETHEUS_ENDPOINT`` (optional) ->
      ``AzureWireOverrides.prometheus_base_url``. When set (typically
      AKS Managed Prometheus), Prom becomes the primary route for its
      supported metrics; AML (when also set) covers the rest via a
      routed composite so AKS metrics get sub-minute detection while
      non-AKS resources still resolve on the AML KQL floor.
    - ``FDAI_PROMETHEUS_AUDIENCE`` (optional) - OIDC audience used to
      mint the Prometheus bearer token (required for AAD-guarded
      Managed Prometheus).

    A fork that needs different resolution SHOULD call
    :func:`wire_azure_container` directly with its own
    :class:`AzureWireOverrides` and skip this wrapper entirely.
    """
    if container.config.llm.mode != LlmMode.AZURE:
        return container
    endpoint = os.environ.get("FDAI_LLM_ENDPOINT")
    if not endpoint:
        raise RuntimeError(
            "llm.mode='azure' requires FDAI_LLM_ENDPOINT env "
            "(e.g. https://<caf-openai-endpoint>.openai.azure.com)"
        )
    # Optional: bind the Azure Monitor Logs metric adapter when the
    # deploy exposes a Log Analytics workspace. Empty / unset -> upstream
    # default ``NoopMetricProvider`` stays, matching dev-mode parity.
    monitor_workspace_id = os.environ.get("FDAI_MONITOR_WORKSPACE_ID", "").strip() or None
    # Optional: bind the Prometheus adapter (AKS Managed Prometheus is
    # the common case) as the primary route for AKS-scoped metrics.
    prometheus_base_url = os.environ.get("FDAI_PROMETHEUS_ENDPOINT", "").strip() or None
    prometheus_audience = os.environ.get("FDAI_PROMETHEUS_AUDIENCE", "").strip() or None
    return await wire_azure_container(
        container,
        http_client=http_client,
        identity=identity,
        overrides=AzureWireOverrides(
            endpoint=endpoint,
            catalog_root=_resolve_catalog_root(),
            operator_memory_store=_build_operator_memory_store(),
            metering_sink=_build_metering_store(),
            model_health_sink=_build_model_health_sink(),
            monitor_workspace_id=monitor_workspace_id,
            prometheus_base_url=prometheus_base_url,
            prometheus_audience=prometheus_audience,
        ),
    )


def _attach_runtime_metric_provider(
    container: Container,
    *,
    http_client: httpx.AsyncClient,
    identity: WorkloadIdentity,
) -> Container:
    """Attach live telemetry independently of the configured LLM mode."""
    from fdai.composition import attach_metric_provider

    monitor_workspace_id = os.environ.get("FDAI_MONITOR_WORKSPACE_ID", "").strip() or None
    prometheus_base_url = os.environ.get("FDAI_PROMETHEUS_ENDPOINT", "").strip() or None
    prometheus_audience = os.environ.get("FDAI_PROMETHEUS_AUDIENCE", "").strip() or None
    return attach_metric_provider(
        container,
        identity=identity,
        http_client=http_client,
        monitor_workspace_id=monitor_workspace_id,
        monitor_queries=None,
        metrics_api_queries=None,
        prometheus_base_url=prometheus_base_url,
        prometheus_queries=None,
        prometheus_audience=prometheus_audience,
    )


def _attach_runtime_knowledge_source(container: Container) -> Container:
    """Bind the durable pgvector knowledge source when Postgres is available."""
    if container.llm_bindings is None:
        return container
    dsn = (
        os.environ.get("FDAI_KNOWLEDGE_DSN", "").strip()
        or os.environ.get("FDAI_STATE_STORE_DSN", "").strip()
    )
    if not dsn:
        return container
    from fdai.composition import bind_pgvector_knowledge_source
    from fdai.delivery.pgvector.knowledge import PgvectorKnowledgeConfig
    from fdai.shared.providers.local import EnvSecretProvider

    secret_name = (
        "FDAI_KNOWLEDGE_DSN" if os.environ.get("FDAI_KNOWLEDGE_DSN") else "FDAI_STATE_STORE_DSN"
    )
    _LOGGER.info("knowledge_source_backend", extra={"backend": "pgvector"})
    return bind_pgvector_knowledge_source(
        container,
        config=PgvectorKnowledgeConfig(dsn_secret=secret_name),
        secrets=EnvSecretProvider(),
    )


def _attach_runtime_github_change_feed(
    container: Container, *, http_client: httpx.AsyncClient
) -> Container:
    """Bind the configured GitOps repository as the RCA change feed."""
    token = os.environ.get("FDAI_GITOPS_TOKEN", "").strip()
    owner = os.environ.get("FDAI_GITOPS_OWNER", "").strip()
    repo = os.environ.get("FDAI_GITOPS_REPO", "").strip()
    if not token or not owner or not repo:
        return container
    from fdai.composition import bind_github_change_feed
    from fdai.delivery.github import GitHubChangeFeedConfig

    async def _token_provider() -> str:
        return token

    _LOGGER.info("change_feed_backend", extra={"backend": "github"})
    return bind_github_change_feed(
        container,
        config=GitHubChangeFeedConfig(
            repository=f"{owner}/{repo}",
            api_base=os.environ.get("FDAI_GITOPS_API_BASE", "https://api.github.com").strip(),
        ),
        http_client=http_client,
        token_provider=_token_provider,
    )
