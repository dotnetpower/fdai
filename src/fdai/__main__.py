"""Process entrypoint - headless control plane bootstrap + event loop.

Loads the composition-root container, finalizes the LLM bindings against
Managed Identity when ``llm.mode == "azure"``, boots the P1 control
loop (``event-ingest → trust-router → T0 → executor → audit``) and
subscribes to the configured Kafka topic on the injected event bus.

Fail-fast contract:

- Missing or invalid env aborts before the event loop starts.
- ``llm.mode='azure'`` requires the Managed Identity endpoint envs; the
  ``ManagedIdentityWorkloadIdentity`` adapter raises when they are
  missing so a container that was miswired never masquerades as ready.
- ShadowExecutor + InMemoryStateStore + RecordingRemediationPrPublisher
  are the fake defaults for dev / smoke; setting
  ``FDAI_STATE_STORE_DSN`` switches audit to :class:`PostgresStateStore`,
  setting ``FDAI_GITOPS_TOKEN`` (plus owner/repo) switches
  the executor to the real :class:`GitOpsPrAdapter`, and setting
  ``FDAI_T1_PATTERN_LIBRARY_DSN`` swaps the T1 in-memory library
  for :class:`PgVectorPatternLibrary`. Every autonomous action is
  judged and audited regardless of the backend selection.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

import httpx
import yaml

from .agents.divergence import ShadowDivergenceLedger
from .agents.runtime import PantheonRuntime
from .composition import (
    AzureWireOverrides,
    Container,
    LlmBindings,
    default_container_from_env,
    wire_azure_container,
)
from .core.control_loop import ControlLoop, ControlLoopOutcome, ControlLoopResult
from .core.event_ingest import EventCorrelator, EventIngest
from .core.executor import ShadowExecutor
from .core.executor.action_builder import ActionBuilder
from .core.executor.direct_api import DirectApiShadowExecutor
from .core.executor.lock import ResourceLockManager
from .core.executor.renderer import TemplateRenderer
from .core.executor.tool_call import ToolCallShadowExecutor
from .core.hil_resume import HilResumeCoordinator
from .core.notifications.matrix import load_matrix_from_yaml
from .core.rbac.resolver import GroupMapping
from .core.rca import RcaCoordinator
from .core.tiers.t0_deterministic import T0Engine
from .core.tiers.t0_deterministic.index import RuleIndex
from .core.tiers.t0_deterministic.opa_evaluator import (
    MissingOpaBinaryError,
    OpaRegoEvaluator,
)
from .core.tiers.t1_lightweight.testing import InMemoryPatternLibrary
from .core.tiers.t1_lightweight.tier import PatternLibrary
from .core.trust_router import TrustRouter
from .core.workflow import (
    WorkflowApprovalPlanner,
    WorkflowOrchestrator,
    WorkflowTriggerCoordinator,
    WorkflowTriggerIndex,
)
from .rule_catalog.schema.action_type import load_action_type_catalog
from .rule_catalog.schema.link_type import load_link_type_catalog
from .rule_catalog.schema.object_type import load_object_type_catalog
from .rule_catalog.schema.resource_type import (
    load_resource_type_registry_from_mapping,
)
from .rule_catalog.schema.rule import load_rule_catalog
from .rule_catalog.schema.workflow import load_workflow_catalog
from .shared.config.models import LlmMode
from .shared.providers.event_bus import EventBus
from .shared.providers.idempotency import IdempotencyStore
from .shared.providers.resource_lock import ResourceLock
from .shared.providers.testing.direct_api import RecordingDirectApiExecutor
from .shared.providers.testing.remediation_pr import RecordingRemediationPrPublisher
from .shared.providers.testing.state_store import InMemoryStateStore
from .shared.providers.testing.tool import RecordingToolExecutor
from .shared.providers.workload_identity import WorkloadIdentity

_LOGGER = logging.getLogger("fdai.startup")
_LOOP_LOGGER = logging.getLogger("fdai.control_loop")


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


def _build_audit_store() -> Any:
    """Select the StateStore backend for this process.

    ``FDAI_STATE_STORE_DSN`` (set by the container's KV secret ref)
    switches to :class:`PostgresStateStore`; without it the in-memory
    fake is used. The ``StateStore`` Protocol is the contract, so core
    code neither knows nor cares which backend is active.
    """
    dsn = os.environ.get("FDAI_STATE_STORE_DSN", "").strip()
    if dsn:
        from .delivery.persistence import PostgresStateStore, PostgresStateStoreConfig

        _LOGGER.info("state_store_backend", extra={"backend": "postgres"})
        return PostgresStateStore(config=PostgresStateStoreConfig(dsn=dsn))
    _LOGGER.info("state_store_backend", extra={"backend": "in-memory"})
    return InMemoryStateStore()


def _build_resource_lock() -> ResourceLock:
    """Select the per-resource lock backend for this process.

    ``FDAI_RESOURCE_LOCK_DSN`` (falling back to ``FDAI_STATE_STORE_DSN``)
    switches to the distributed :class:`PostgresAdvisoryResourceLock` so
    per-resource ordering holds across replicas; without a DSN the
    in-process :class:`ResourceLockManager` is used (correct only for a
    single replica). The ``ResourceLock`` Protocol is the contract, so
    the executor neither knows nor cares which backend is active.
    """
    dsn = (
        os.environ.get("FDAI_RESOURCE_LOCK_DSN", "").strip()
        or os.environ.get("FDAI_STATE_STORE_DSN", "").strip()
    )
    if not dsn:
        _LOGGER.info("resource_lock_backend", extra={"backend": "in-memory"})
        return ResourceLockManager()

    from .delivery.persistence import (
        PostgresAdvisoryResourceLock,
        PostgresAdvisoryResourceLockConfig,
    )

    timeout_raw = os.environ.get("FDAI_RESOURCE_LOCK_TIMEOUT_MS", "").strip()
    try:
        timeout_ms = int(timeout_raw) if timeout_raw else 30_000
    except ValueError as exc:
        raise RuntimeError(
            f"FDAI_RESOURCE_LOCK_TIMEOUT_MS={timeout_raw!r} is not an integer"
        ) from exc
    if timeout_ms < 0:
        raise RuntimeError(f"FDAI_RESOURCE_LOCK_TIMEOUT_MS MUST be >= 0; got {timeout_ms}")

    _LOGGER.info("resource_lock_backend", extra={"backend": "postgres-advisory"})
    return PostgresAdvisoryResourceLock(
        config=PostgresAdvisoryResourceLockConfig(dsn=dsn, lock_timeout_ms=timeout_ms)
    )


def _build_operator_memory_store() -> Any:
    """Select the OperatorMemoryStore backend for this process.

    Mirrors :func:`_build_audit_store`. ``FDAI_OPERATOR_MEMORY_DSN``
    (set by the container's KV secret ref) switches to
    :class:`PostgresOperatorMemoryStore`; without it the deterministic
    in-memory fake is used. The ``OperatorMemoryStore`` Protocol is the
    contract, so :class:`DefaultPromptComposer` neither knows nor cares
    which backend is active.

    Upstream ships with the in-memory backend so the composer is fully
    wired end-to-end even without a database - a fork gets the
    operator-memory layer working the moment it seeds an entry, and
    only needs to set the DSN when it wants durability across
    restarts.
    """

    from .core.operator_memory import InMemoryOperatorMemoryStore

    dsn = os.environ.get("FDAI_OPERATOR_MEMORY_DSN", "").strip()
    if dsn:
        from .delivery.persistence import (
            PostgresOperatorMemoryStore,
            PostgresOperatorMemoryStoreConfig,
        )

        _LOGGER.info("operator_memory_store_backend", extra={"backend": "postgres"})
        return PostgresOperatorMemoryStore(config=PostgresOperatorMemoryStoreConfig(dsn=dsn))
    _LOGGER.info("operator_memory_store_backend", extra={"backend": "in-memory"})
    return InMemoryOperatorMemoryStore()


def _build_pattern_library() -> PatternLibrary:
    """Select the :class:`PatternLibrary` backend for this process.

    ``FDAI_T1_PATTERN_LIBRARY_DSN`` (typically the same Postgres
    the state store points at, but broken out so a fork can move the
    T1 store to a dedicated instance) switches to
    :class:`PgVectorPatternLibrary`. Without it the in-memory fake is
    used - the ``PatternLibrary`` Protocol is the contract, so ``core/``
    neither knows nor cares which backend is active.

    Optional tuning envs (fail-fast on unparseable values):

    - ``FDAI_T1_PATTERN_LIBRARY_STATEMENT_TIMEOUT_MS`` - default 15000.
    - ``FDAI_T1_PATTERN_LIBRARY_IVFFLAT_PROBES`` - default 10.

    The T1 tier is not yet wired into the P1 control loop; this builder
    is exposed so the composition root can bind it once T1 lands.
    """
    dsn = os.environ.get("FDAI_T1_PATTERN_LIBRARY_DSN", "").strip()
    if not dsn:
        _LOGGER.info("pattern_library_backend", extra={"backend": "in-memory"})
        return InMemoryPatternLibrary()

    from .delivery.persistence import (
        PgVectorPatternLibrary,
        PgVectorPatternLibraryConfig,
    )

    timeout_raw = os.environ.get("FDAI_T1_PATTERN_LIBRARY_STATEMENT_TIMEOUT_MS", "").strip()
    try:
        timeout_ms = int(timeout_raw) if timeout_raw else 15_000
    except ValueError as exc:
        raise RuntimeError(
            f"FDAI_T1_PATTERN_LIBRARY_STATEMENT_TIMEOUT_MS={timeout_raw!r} is not an integer"
        ) from exc
    if timeout_ms < 1:
        raise RuntimeError(
            f"FDAI_T1_PATTERN_LIBRARY_STATEMENT_TIMEOUT_MS MUST be >= 1; got {timeout_ms}"
        )

    probes_raw = os.environ.get("FDAI_T1_PATTERN_LIBRARY_IVFFLAT_PROBES", "").strip()
    try:
        probes = int(probes_raw) if probes_raw else 10
    except ValueError as exc:
        raise RuntimeError(
            f"FDAI_T1_PATTERN_LIBRARY_IVFFLAT_PROBES={probes_raw!r} is not an integer"
        ) from exc
    if probes < 1:
        raise RuntimeError(f"FDAI_T1_PATTERN_LIBRARY_IVFFLAT_PROBES MUST be >= 1; got {probes}")

    _LOGGER.info("pattern_library_backend", extra={"backend": "pgvector"})
    return PgVectorPatternLibrary(
        config=PgVectorPatternLibraryConfig(
            dsn=dsn,
            statement_timeout_ms=timeout_ms,
            ivfflat_probes=probes,
        )
    )


def _build_publisher(http_client: httpx.AsyncClient | None) -> Any:
    """Select the :class:`RemediationPrPublisher` backend for this process.

    Presence of ``FDAI_GITOPS_TOKEN`` opts into the real
    :class:`GitOpsPrAdapter`; missing token falls back to the in-memory
    :class:`RecordingRemediationPrPublisher` fake. The
    ``RemediationPrPublisher`` Protocol is the contract, so ``core/``
    neither knows nor cares which backend is active.

    Fail-fast contract: opting in requires ``owner`` + ``repo``. A
    partial configuration (token without owner/repo) is a deployment
    bug and raises immediately so the container never masquerades as
    a real GitOps publisher.

    ``http_client`` MUST be non-None when the token is set - the
    adapter never opens its own connection; the composition root owns
    the client lifecycle.
    """
    token = os.environ.get("FDAI_GITOPS_TOKEN", "").strip()
    if not token:
        _LOGGER.info("remediation_pr_backend", extra={"backend": "recording"})
        return RecordingRemediationPrPublisher()

    owner = os.environ.get("FDAI_GITOPS_OWNER", "").strip()
    repo = os.environ.get("FDAI_GITOPS_REPO", "").strip()
    if not owner or not repo:
        raise RuntimeError(
            "FDAI_GITOPS_TOKEN is set but FDAI_GITOPS_OWNER / "
            "FDAI_GITOPS_REPO are missing; both are required to publish "
            "remediation PRs. Unset the token to run in fake mode."
        )
    if http_client is None:
        raise RuntimeError(
            "FDAI_GITOPS_TOKEN is set but no HTTP client is available. "
            "The composition root MUST create an httpx.AsyncClient before "
            "building the publisher."
        )

    from .delivery.gitops_pr.adapter import GitOpsPrAdapter, GitOpsPrConfig

    default_branch = os.environ.get("FDAI_GITOPS_DEFAULT_BRANCH", "main").strip() or "main"
    branch_prefix = (
        os.environ.get("FDAI_GITOPS_BRANCH_PREFIX", "fdai/shadow").strip() or "fdai/shadow"
    )
    api_base = (
        os.environ.get("FDAI_GITOPS_API_BASE", "https://api.github.com").strip()
        or "https://api.github.com"
    )
    timeout_raw = os.environ.get("FDAI_GITOPS_TIMEOUT_SECONDS", "").strip()
    try:
        timeout_seconds = float(timeout_raw) if timeout_raw else 15.0
    except ValueError as exc:
        raise RuntimeError(f"FDAI_GITOPS_TIMEOUT_SECONDS={timeout_raw!r} is not a float") from exc
    if timeout_seconds <= 0:
        raise RuntimeError(f"FDAI_GITOPS_TIMEOUT_SECONDS MUST be > 0; got {timeout_seconds}")

    _LOGGER.info(
        "remediation_pr_backend",
        extra={
            "backend": "gitops",
            "owner": owner,
            "repo": repo,
            "default_branch": default_branch,
            "api_base": api_base,
        },
    )
    return GitOpsPrAdapter(
        config=GitOpsPrConfig(
            owner=owner,
            repo=repo,
            default_branch=default_branch,
            branch_prefix=branch_prefix,
            api_base=api_base,
            timeout_seconds=timeout_seconds,
        ),
        http_client=http_client,
        token=token,
    )


def _build_hil_channel(http_client: httpx.AsyncClient | None) -> Any:
    """Select the :class:`HilChannel` backend for this process.

    Presence of ``FDAI_CHATOPS_WEBHOOK_URL`` opts into the real
    :class:`TeamsHilAdapter`; missing URL returns ``None`` so the caller
    falls back to its persisted HIL queue (existing P1 behavior - see
    ``docs/roadmap/channels-and-notifications.md § 6``). The
    ``HilChannel`` Protocol is the contract, so ``core/`` neither knows
    nor cares which backend is active.

    Env vars (Incoming Webhook mode - P1 default):

    - ``FDAI_CHATOPS_WEBHOOK_URL`` - Teams channel Incoming
      Webhook URL. **Required to opt in.**
    - ``FDAI_CHATOPS_WEBHOOK_SECRET`` - optional HMAC-SHA256
      shared secret; when set the adapter attaches an
      ``X-FDAI-Signature`` header for the receiver to verify.
    - ``FDAI_CHATOPS_APPROVE_CALLBACK_URL`` /
      ``FDAI_CHATOPS_REJECT_CALLBACK_URL`` - optional callback
      URLs rendered as ``Action.Submit`` data on the card buttons.
    - ``FDAI_CHATOPS_TIMEOUT_SECONDS`` - optional per-request
      timeout (default 15s).

    ``http_client`` MUST be non-None when the URL is set - the adapter
    never opens its own connection; the composition root owns the
    client lifecycle.
    """
    webhook_url = os.environ.get("FDAI_CHATOPS_WEBHOOK_URL", "").strip()
    if not webhook_url:
        _LOGGER.info("hil_channel_backend", extra={"backend": "none"})
        return None

    if http_client is None:
        raise RuntimeError(
            "FDAI_CHATOPS_WEBHOOK_URL is set but no HTTP client is "
            "available. The composition root MUST create an httpx.AsyncClient "
            "before building the HIL channel."
        )

    from .delivery.chatops.teams_adapter import TeamsHilAdapter, TeamsHilAdapterConfig

    webhook_secret = os.environ.get("FDAI_CHATOPS_WEBHOOK_SECRET", "").strip() or None
    approve_cb = os.environ.get("FDAI_CHATOPS_APPROVE_CALLBACK_URL", "").strip() or None
    reject_cb = os.environ.get("FDAI_CHATOPS_REJECT_CALLBACK_URL", "").strip() or None

    timeout_raw = os.environ.get("FDAI_CHATOPS_TIMEOUT_SECONDS", "").strip()
    try:
        timeout_seconds = float(timeout_raw) if timeout_raw else 15.0
    except ValueError as exc:
        raise RuntimeError(f"FDAI_CHATOPS_TIMEOUT_SECONDS={timeout_raw!r} is not a float") from exc
    if timeout_seconds <= 0:
        raise RuntimeError(f"FDAI_CHATOPS_TIMEOUT_SECONDS MUST be > 0; got {timeout_seconds}")

    _LOGGER.info(
        "hil_channel_backend",
        extra={
            "backend": "teams-webhook",
            "signed": webhook_secret is not None,
            "approve_callback_configured": approve_cb is not None,
            "reject_callback_configured": reject_cb is not None,
        },
    )
    return TeamsHilAdapter(
        config=TeamsHilAdapterConfig(
            webhook_url=webhook_url,
            webhook_secret=webhook_secret,
            approve_callback_url=approve_cb,
            reject_callback_url=reject_cb,
            timeout_seconds=timeout_seconds,
        ),
        http_client=http_client,
    )


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
            "(e.g. https://oai-fdai-dev-krc.openai.azure.com)"
        )
    return await wire_azure_container(
        container,
        http_client=http_client,
        identity=identity,
        overrides=AzureWireOverrides(
            endpoint=endpoint,
            catalog_root=_resolve_catalog_root(),
            operator_memory_store=_build_operator_memory_store(),
        ),
    )


def _build_direct_api_executor(
    *,
    audit_store: Any,
    resource_lock: ResourceLock,
    idempotency: IdempotencyStore | None = None,
) -> DirectApiShadowExecutor | None:
    """Select the direct-API executor for this process.

    Opt-in via ``FDAI_DIRECT_API_FAKE=1``: composes a
    :class:`RecordingDirectApiExecutor` fake behind the
    :class:`DirectApiShadowExecutor` so an operator can exercise the
    ``execution_path: direct_api`` dispatch path end-to-end without a
    substrate SDK. Absent -> returns ``None`` so :class:`ControlLoop`
    falls back to PR-native routing (the P1 default).

    A real Azure ARM adapter is fork-authored and lands under
    ``delivery/azure/direct_api/``; when it arrives, this helper grows
    an additional env-gated branch mirroring the ``_build_publisher``
    shape.
    """

    if os.environ.get("FDAI_DIRECT_API_FAKE", "").strip() != "1":
        _LOGGER.info("direct_api_backend", extra={"backend": "none"})
        return None

    _LOGGER.info("direct_api_backend", extra={"backend": "recording"})
    return DirectApiShadowExecutor(
        executor=RecordingDirectApiExecutor(),
        audit_store=audit_store,
        resource_lock=resource_lock,
        idempotency=idempotency,
    )


def _build_tool_executor(
    *,
    audit_store: Any,
    resource_lock: ResourceLock,
    idempotency: IdempotencyStore | None = None,
) -> ToolCallShadowExecutor | None:
    """Select the tool-call executor for this process.

    Opt-in via ``FDAI_TOOL_CALL_FAKE=1``: composes a
    :class:`RecordingToolExecutor` fake behind the
    :class:`ToolCallShadowExecutor` so an operator can exercise the
    ``execution_path: tool_call`` dispatch path end-to-end without a real
    tool registry. Absent -> returns ``None`` so :class:`ControlLoop`
    falls back to PR-native routing (the P1 default).

    A real tool adapter (a native Python registry, an MCP client, an HTTP
    callout) is fork-authored and binds here through the same env-gated
    shape.
    """

    if os.environ.get("FDAI_TOOL_CALL_FAKE", "").strip() != "1":
        _LOGGER.info("tool_call_backend", extra={"backend": "none"})
        return None

    _LOGGER.info("tool_call_backend", extra={"backend": "recording"})
    return ToolCallShadowExecutor(
        executor=RecordingToolExecutor(),
        audit_store=audit_store,
        resource_lock=resource_lock,
        idempotency=idempotency,
    )


def _build_idempotency_store() -> IdempotencyStore | None:
    """Select the durable idempotency backend for this process.

    ``FDAI_IDEMPOTENCY_DSN`` (falling back to ``FDAI_STATE_STORE_DSN``)
    switches on the durable :class:`PostgresIdempotencyStore` so a
    post-restart / cross-replica re-delivery of a *mutating* action is
    returned from the store instead of re-executed. Without a DSN the
    executor uses its in-process L1 cache only (existing single-replica
    behavior); ``None`` signals that.
    """
    dsn = (
        os.environ.get("FDAI_IDEMPOTENCY_DSN", "").strip()
        or os.environ.get("FDAI_STATE_STORE_DSN", "").strip()
    )
    if not dsn:
        _LOGGER.info("idempotency_backend", extra={"backend": "in-process-l1-only"})
        return None

    from .delivery.persistence import (
        PostgresIdempotencyStore,
        PostgresIdempotencyStoreConfig,
    )

    _LOGGER.info("idempotency_backend", extra={"backend": "postgres"})
    return PostgresIdempotencyStore(config=PostgresIdempotencyStoreConfig(dsn=dsn))


def _build_workflow_coordinator(
    *,
    catalog_root: Path,
    workflows: tuple[Any, ...],
    action_types_by_name: dict[str, Any],
    audit_store: Any,
) -> WorkflowTriggerCoordinator | None:
    """Assemble the shadow workflow coordinator, opt-in and fail-safe.

    Disabled unless ``FDAI_WORKFLOW_SHADOW`` is truthy AND the catalog ships at
    least one Workflow. Any load error (missing / malformed rbac-groups or
    notifications matrix) logs and returns ``None`` so workflow wiring never
    fails boot or perturbs the control loop; upstream default is off.
    """
    if not workflows:
        return None
    if os.environ.get("FDAI_WORKFLOW_SHADOW", "").lower() not in ("1", "true", "yes", "on"):
        return None
    config_dir = catalog_root.parent / "config"
    rbac_file = config_dir / "rbac-groups.yaml"
    matrix_file = config_dir / "notifications-matrix.yaml"
    try:
        with rbac_file.open("r", encoding="utf-8") as fh:
            group_mapping = GroupMapping.from_config(yaml.safe_load(fh))
        matrix = load_matrix_from_yaml(matrix_file)
    except (OSError, ValueError) as exc:
        _LOGGER.warning("workflow_coordinator_disabled", extra={"error": type(exc).__name__})
        return None
    planner = WorkflowApprovalPlanner(
        action_types=action_types_by_name,
        group_mapping=group_mapping,
        matrix=matrix,
    )
    orchestrator = WorkflowOrchestrator(
        planner=planner,
        action_types=action_types_by_name,
        audit_store=audit_store,
    )
    _LOGGER.info("workflow_coordinator_enabled", extra={"workflows": len(workflows)})
    return WorkflowTriggerCoordinator(
        index=WorkflowTriggerIndex.build(workflows),
        orchestrator=orchestrator,
    )


def _build_control_loop(
    container: Container,
    *,
    http_client: httpx.AsyncClient | None = None,
) -> ControlLoop:
    """Load rule / action / policy catalogs and wire the P1 control loop.

    ``http_client`` - passed to :func:`_build_publisher` when the
    GitOps env vars opt into the real adapter. ``None`` is fine when
    the container runs in fake-publisher mode (dev / unit tests).
    """
    catalog_root = _resolve_catalog_root()
    policies_root = _resolve_policies_root(catalog_root)
    action_types_root = catalog_root / "action-types"
    vocabulary_file = catalog_root / "vocabulary" / "resource-types.yaml"
    object_types_root = catalog_root / "vocabulary" / "object-types"
    link_types_root = catalog_root / "vocabulary" / "link-types"
    remediation_root = catalog_root / "remediation"
    rules_root = catalog_root / "catalog"

    registry = container.schema_registry
    probes_root = catalog_root / "probes"
    action_types = load_action_type_catalog(
        action_types_root,
        schema_registry=registry,
        probes_root=probes_root if probes_root.is_dir() else None,
    )
    with vocabulary_file.open("r", encoding="utf-8") as fh:
        resource_types = load_resource_type_registry_from_mapping(yaml.safe_load(fh))

    # Ontology ObjectType / LinkType catalogs (fail-closed if directories
    # exist but any file is invalid). Missing directories are tolerated
    # so unit tests running against a stub catalog root do not require
    # every fixture to ship the vocabulary tree.
    ontology_object_types = (
        load_object_type_catalog(object_types_root, schema_registry=registry)
        if object_types_root.is_dir()
        else ()
    )
    ontology_link_types = (
        load_link_type_catalog(
            link_types_root,
            schema_registry=registry,
            object_types=ontology_object_types,
        )
        if link_types_root.is_dir() and ontology_object_types
        else ()
    )
    if ontology_object_types or ontology_link_types:
        container = replace(
            container,
            ontology_object_types=ontology_object_types,
            ontology_link_types=ontology_link_types,
        )

    rules = load_rule_catalog(
        rules_root,
        schema_registry=registry,
        action_types=action_types,
        resource_types=resource_types,
        policies_root=policies_root,
        remediation_root=remediation_root,
    )
    index = RuleIndex.build(rules)

    # Workflow catalog (fail-closed if the directory exists but any file is
    # invalid). Cross-references every step's action_type_ref / compensated_by
    # against the ActionType catalog and every guard_rule_ref against the rule
    # catalog, so a malformed workflow blocks boot rather than surfacing at
    # first dispatch (docs/roadmap/process-automation.md 7).
    workflows_root = catalog_root / "workflows"
    workflows = (
        load_workflow_catalog(
            workflows_root,
            schema_registry=registry,
            action_type_names={a.name for a in action_types},
            rule_ids={r.id for r in rules},
        )
        if workflows_root.is_dir()
        else ()
    )
    if workflows:
        container = replace(container, workflows=workflows)

    try:
        evaluator: Any = OpaRegoEvaluator(policies_root=policies_root)
    except MissingOpaBinaryError:
        # opa binary is required for full T0 verdicts; without it, T0
        # abstains on every candidate. Log the fact and continue so the
        # loop still exercises event-ingest + routing paths.
        _LOGGER.warning("opa_binary_missing_fallback_to_abstain")
        evaluator = None

    t0 = T0Engine(index=index, evaluator=evaluator)
    trust_router = TrustRouter(index=index)
    event_ingest = EventIngest(validator=container.event_validator)
    action_types_by_name = {a.name: a for a in action_types}
    action_builder = ActionBuilder(action_types_by_name=action_types_by_name)

    audit_store = _build_audit_store()
    publisher = _build_publisher(http_client)
    renderer = TemplateRenderer(remediation_root=remediation_root)
    resource_lock = _build_resource_lock()
    idempotency_store = _build_idempotency_store()

    executor = ShadowExecutor(
        publisher=publisher,
        audit_store=audit_store,
        renderer=renderer,
        resource_lock=resource_lock,
        idempotency=idempotency_store,
    )
    direct_api_executor = _build_direct_api_executor(
        audit_store=audit_store,
        resource_lock=resource_lock,
        idempotency=idempotency_store,
    )
    tool_executor = _build_tool_executor(
        audit_store=audit_store,
        resource_lock=resource_lock,
        idempotency=idempotency_store,
    )

    # Detection-and-explanation seams (observability-and-detection.md).
    # EventCorrelator groups an event storm into one incident id; the
    # RcaCoordinator adds the deterministic T0 "why" per finding and,
    # when the Azure T2 RCA reasoner is bound (``t2.rca`` capability +
    # prompt), a grounded T2 hypothesis on novel (T0 no-match) cases.
    # Both are read-only explanation surfaces - never a new autonomy
    # path - so they are safe to wire unconditionally.
    event_correlator = EventCorrelator()
    rca_reasoner = (
        container.llm_bindings.rca_reasoner if container.llm_bindings is not None else None
    )
    rca_coordinator = RcaCoordinator(reasoner=rca_reasoner)

    # T1 temporal causal-chain RCA (observability-and-detection.md 4, path
    # b) needs the incident's antecedent changes, which upstream cannot
    # supply without wiring an estate-change source. It is therefore left
    # dark here: the loop keeps ``incident_member_source=None`` so only T0
    # (and, when bound, T2) RCA runs. A fork enables the multi-hop "root
    # change -> ... -> failure" chain by wiring the reference
    # ``DeploymentHistoryMemberSource`` (bridging a real
    # ``DeploymentHistoryProvider`` such as the Azure Resource Graph
    # adapter + ``IncidentRegistry.get`` lookup into ``CorrelatedEvent``s),
    # plus a ``causal_chain_window`` and optional
    # ``resource_dependency_graph``, into the ``ControlLoop`` here.

    # HIL approval round-trip (Notify-on-decision step B). Opt-in: only
    # when a HIL channel is configured (``FDAI_CHATOPS_WEBHOOK_URL``)
    # does the loop park a HIL-routed action and push an A1 approval
    # card. Absent -> ``None`` so the loop records the HIL verdict and
    # stops at the persisted queue (backward-compatible). Parking never
    # turns a HIL verdict into an execution - the coordinator holds the
    # no-self-approval + idempotency invariants.
    hil_channel = _build_hil_channel(http_client)
    hil_resume_coordinator = (
        HilResumeCoordinator(
            state_store=audit_store,
            executor=executor,
            hil_channel=hil_channel,
            rules_by_id={r.id: r for r in rules},
            direct_api_executor=direct_api_executor,
            tool_executor=tool_executor,
            action_types_by_name=action_types_by_name,
        )
        if hil_channel is not None
        else None
    )

    return ControlLoop(
        event_ingest=event_ingest,
        trust_router=trust_router,
        t0_engine=t0,
        action_builder=action_builder,
        executor=executor,
        audit_store=audit_store,
        rules_by_id={r.id: r for r in rules},
        action_types_by_name=action_types_by_name,
        direct_api_executor=direct_api_executor,
        tool_executor=tool_executor,
        event_correlator=event_correlator,
        rca_coordinator=rca_coordinator,
        hil_resume_coordinator=hil_resume_coordinator,
        workflow_coordinator=_build_workflow_coordinator(
            catalog_root=catalog_root,
            workflows=workflows,
            action_types_by_name=action_types_by_name,
            audit_store=audit_store,
        ),
    )


async def _consume(
    *,
    bus: EventBus,
    topic: str,
    group_id: str,
    control_loop: ControlLoop,
    stop: asyncio.Event,
    divergence: ShadowDivergenceLedger | None = None,
) -> None:
    """Feed every Kafka envelope through the P1 control loop.

    :meth:`ControlLoop.process` is idempotent on ``idempotency_key`` and
    never raises for business errors, so a bad event still writes an
    audit entry and the consumer keeps committing offsets to avoid
    poison-message deadlocks.

    When a ``divergence`` ledger is wired, the authoritative P1 decision
    is recorded against the event's correlation id so it can be joined
    with the pantheon's shadow verdict (shadow-before-enforce baseline).
    """
    async for envelope in bus.subscribe(topic, group_id):
        if stop.is_set():
            return
        _LOOP_LOGGER.info(
            "event_received",
            extra={"topic": envelope.topic, "offset": envelope.offset, "key": envelope.key},
        )
        try:
            result = await control_loop.process(envelope.payload)
        except Exception:  # noqa: BLE001 - fail-close: log-and-continue
            _LOOP_LOGGER.exception(
                "control_loop_unhandled_error",
                extra={"key": envelope.key, "offset": envelope.offset},
            )
            continue
        if divergence is not None:
            payload = envelope.payload
            correlation_id = str(
                payload.get("correlation_id")
                or payload.get("event_id")
                or payload.get("id")
                or envelope.key
            )
            divergence.record_authoritative(correlation_id, _authoritative_decision(result))
        _LOOP_LOGGER.info(
            "event_processed",
            extra={
                "outcome": result.outcome.value,
                "tier": result.tier,
                "decision": result.decision,
                "resource_type": result.resource_type,
                "citing_rule_ids": list(result.citing_rule_ids),
            },
        )


def _authoritative_decision(result: ControlLoopResult) -> str:
    """Normalize a P1 :class:`ControlLoopResult` to the shared decision
    vocabulary used by the pantheon (``auto`` / ``hil`` / ``deny`` /
    ``dedupe`` / ``abstain``) so the two sides are directly comparable."""
    outcome = result.outcome
    if outcome == ControlLoopOutcome.EXECUTED:
        return "auto"
    if outcome == ControlLoopOutcome.HIL:
        return "hil"
    if outcome == ControlLoopOutcome.DENIED:
        return "deny"
    if outcome == ControlLoopOutcome.DEDUPED:
        return "dedupe"
    return "abstain"


def _log_pantheon_exit(task: asyncio.Task[None]) -> None:
    """Done-callback for the isolated pantheon task.

    A pantheon crash or early exit is surfaced here without touching the
    P1 wait set, so the shadow overlay can never take the primary control
    plane down with it.
    """
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        _LOGGER.error("pantheon_runtime_failed", exc_info=exc)
    else:
        _LOGGER.warning("pantheon_runtime_exited_early")


async def _run() -> int:
    container = default_container_from_env()
    summary = _summarize_config(container)
    _LOGGER.info("startup_ok", extra={"config": summary})

    http_client: httpx.AsyncClient | None = None
    identity: WorkloadIdentity | None = None
    bus: EventBus | None = None
    pantheon_runtime: PantheonRuntime | None = None
    pantheon_heartbeat: float | None = None
    divergence_ledger: ShadowDivergenceLedger | None = None

    try:
        if container.config.llm.mode == LlmMode.AZURE:
            from .delivery.azure.workload_identity import (
                ManagedIdentityWorkloadIdentity,
            )

            http_client = _new_http_client()
            identity = ManagedIdentityWorkloadIdentity(http_client=http_client)
            container = await _finalize_llm_bindings(
                container, http_client=http_client, identity=identity
            )
            bindings: LlmBindings = container.require_llm_bindings()
            _LOGGER.info(
                "azure_llm_bindings_attached",
                extra={"cross_check_models": len(bindings.cross_check_models)},
            )

        start_consumer = os.environ.get("FDAI_START_CONSUMER", "").lower() in (
            "1",
            "true",
        )
        control_loop: ControlLoop | None = None

        if start_consumer:
            from .delivery.azure.event_bus import (
                EventHubsKafkaBus,
                EventHubsKafkaBusConfig,
            )

            if identity is None:
                from .delivery.azure.workload_identity import (
                    ManagedIdentityWorkloadIdentity,
                )

                if http_client is None:
                    http_client = _new_http_client()
                identity = ManagedIdentityWorkloadIdentity(http_client=http_client)

            bus = EventHubsKafkaBus(
                identity=identity,
                config=EventHubsKafkaBusConfig(
                    bootstrap_servers=container.config.kafka.bootstrap_servers,
                    dlq_suffix=container.config.kafka.topic_dlq_suffix,
                ),
            )
            # A GitOps token opts into the real publisher; ensure an
            # http_client exists before _build_control_loop needs one.
            if os.environ.get("FDAI_GITOPS_TOKEN") and http_client is None:
                http_client = _new_http_client()
            # Same for the HIL channel - an Incoming Webhook URL opts in.
            if os.environ.get("FDAI_CHATOPS_WEBHOOK_URL") and http_client is None:
                http_client = _new_http_client()
            control_loop = _build_control_loop(container, http_client=http_client)
            _LOGGER.info(
                "control_loop_ready",
                extra={
                    "topic": container.config.kafka.topic_events,
                    "group_id": "fdai-core",
                },
            )

            # Optional pantheon: the 15 named agents consume the same
            # ingress topic under distinct consumer groups (fan-out) and
            # react immediately. Opt-in via FDAI_START_PANTHEON and shadow
            # by default - the agents use in-memory audit / issue / admin
            # adapters and Thor's executor stays in shadow, so running it
            # beside the P1 loop adds no autonomous mutation. See
            # docs/roadmap/agent-pantheon-implementation.md.
            start_pantheon = os.environ.get("FDAI_START_PANTHEON", "").lower() in (
                "1",
                "true",
            )
            if start_pantheon:
                pantheon_enforce = os.environ.get("FDAI_PANTHEON_ENFORCE", "").lower() in (
                    "1",
                    "true",
                )
                disabled_raw = os.environ.get("FDAI_PANTHEON_DISABLED_AGENTS", "").strip()
                disabled_agents = (
                    frozenset(n.strip() for n in disabled_raw.split(",") if n.strip())
                    if disabled_raw
                    else None
                )
                # Shared ledger: the pantheon observer records its shadow
                # verdict, the P1 consumer records the authoritative
                # decision; joined by correlation id to measure shadow
                # agreement (the promotion baseline).
                divergence_ledger = ShadowDivergenceLedger()
                pantheon_runtime = PantheonRuntime.build(
                    provider=bus,
                    raw_event_topic=container.config.kafka.topic_events,
                    enforce=pantheon_enforce,
                    disabled_agents=disabled_agents,
                    divergence=divergence_ledger,
                )
                hb_raw = os.environ.get("FDAI_PANTHEON_HEARTBEAT_SECONDS", "").strip()
                if hb_raw:
                    try:
                        pantheon_heartbeat = float(hb_raw)
                    except ValueError as hb_exc:
                        raise RuntimeError(
                            f"FDAI_PANTHEON_HEARTBEAT_SECONDS={hb_raw!r} is not a float"
                        ) from hb_exc
                    if pantheon_heartbeat <= 0:
                        raise RuntimeError(
                            f"FDAI_PANTHEON_HEARTBEAT_SECONDS MUST be > 0; got {pantheon_heartbeat}"
                        )
                _LOGGER.info(
                    "pantheon_ready",
                    extra={
                        "agents": len(pantheon_runtime.agents),
                        "subscriptions": pantheon_runtime.subscription_count,
                        "enforce": pantheon_enforce,
                        "heartbeat_s": pantheon_heartbeat,
                    },
                )
        elif os.environ.get("FDAI_START_PANTHEON", "").lower() in ("1", "true"):
            # Pantheon needs the same Kafka bus the consumer builds; without
            # FDAI_START_CONSUMER there is no bus to bind to. Warn rather
            # than silently no-op so a miswired container is visible.
            _LOGGER.warning("pantheon_requested_without_consumer")

        stop = asyncio.Event()
        loop = asyncio.get_running_loop()

        def _signal_stop(signame: str) -> None:
            _LOGGER.info("shutdown_signal", extra={"signal": signame})
            stop.set()

        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, _signal_stop, sig.name)

        if bus is not None and control_loop is not None:
            consumer_task = asyncio.create_task(
                _consume(
                    bus=bus,
                    topic=container.config.kafka.topic_events,
                    group_id="fdai-core",
                    control_loop=control_loop,
                    stop=stop,
                    divergence=divergence_ledger,
                )
            )
            wait_task = asyncio.create_task(stop.wait())

            # Blast-radius isolation: the pantheon runs OUTSIDE the P1 wait
            # set. A pantheon crash is logged via a done-callback but MUST
            # NOT bring down the P1 control plane; P1 shutdown cancels it
            # in turn. The pantheon is a shadow overlay, never a dependency
            # of the primary pipeline.
            pantheon_task: asyncio.Task[None] | None = None
            if pantheon_runtime is not None:
                pantheon_task = asyncio.create_task(
                    pantheon_runtime.run(heartbeat_interval=pantheon_heartbeat),
                    name="pantheon-runtime",
                )
                pantheon_task.add_done_callback(_log_pantheon_exit)

            done, _pending = await asyncio.wait(
                {consumer_task, wait_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            consumer_task.cancel()
            wait_task.cancel()
            if pantheon_task is not None:
                pantheon_task.cancel()
            # Await the cancels so cleanup can drain the consumer's
            # ``async for`` + finally (which stops the AIOKafkaConsumer)
            # before we tear down the bus / HTTP client in the outer
            # ``finally``. Without this a cancelled consumer can be
            # racing the aiokafka close and log noisy warnings on exit.
            cleanup_tasks: list[asyncio.Task[Any]] = [consumer_task, wait_task]
            if pantheon_task is not None:
                cleanup_tasks.append(pantheon_task)
            await asyncio.gather(*cleanup_tasks, return_exceptions=True)
            for task in done:
                exc = task.exception()
                if exc is not None:
                    _LOGGER.error("consumer_task_failed", exc_info=exc)
        else:
            await stop.wait()

        _LOGGER.info("shutdown_complete")
        return 0
    finally:
        if pantheon_runtime is not None:
            try:
                await pantheon_runtime.stop()
            except Exception:  # noqa: BLE001
                _LOGGER.warning("pantheon_stop_failed", exc_info=True)
        if bus is not None:
            close = getattr(bus, "close", None)
            if callable(close):
                try:
                    await close()
                except Exception:  # noqa: BLE001
                    _LOGGER.warning("bus_close_failed", exc_info=True)
        if http_client is not None:
            try:
                await http_client.aclose()
            except Exception:  # noqa: BLE001
                _LOGGER.warning("http_client_close_failed", exc_info=True)


def main() -> int:
    # Bootstrap the plain-text formatter for the tiny window before
    # `default_container_from_env()` swaps in the marked JSON handler via
    # `configure_telemetry`. `force=True` guarantees that if the caller
    # already installed a root handler (uvicorn, pytest fixtures) we
    # override cleanly instead of stacking - otherwise every log line
    # would emit twice, once as plain text and once as JSON, once the
    # composition root wires the JSON formatter.
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)sZ %(levelname)s %(name)s :: %(message)s",
        force=True,
    )
    try:
        return asyncio.run(_run())
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":  # pragma: no cover - process entrypoint
    sys.exit(main())
