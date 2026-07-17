"""Environment-selected remediation, HIL, tool, and incident delivery adapters."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import httpx

from fdai.core.executor.direct_api import DirectApiShadowExecutor
from fdai.core.executor.tool_call import ToolCallShadowExecutor, ToolReceiptObserver
from fdai.core.notifications.matrix import load_matrix_from_yaml
from fdai.runtime.configuration import _resolve_catalog_root
from fdai.shared.providers.idempotency import IdempotencyStore
from fdai.shared.providers.resource_lock import ResourceLock
from fdai.shared.providers.testing.direct_api import RecordingDirectApiExecutor
from fdai.shared.providers.testing.remediation_pr import RecordingRemediationPrPublisher
from fdai.shared.providers.testing.tool import RecordingToolExecutor

_LOGGER = logging.getLogger("fdai.startup")


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

    from fdai.delivery.gitops_pr.adapter import GitOpsPrAdapter, GitOpsPrConfig

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
    ``docs/roadmap/interfaces/channels-and-notifications.md § 6``). The
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

    from fdai.delivery.chatops.teams_adapter import TeamsHilAdapter, TeamsHilAdapterConfig

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
    receipt_observer: ToolReceiptObserver | None = None,
    http_client: httpx.AsyncClient | None = None,
    metric_provider: Any = None,
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

    routes: dict[str, Any] = {}
    enforce_actions: set[str] = set()
    fallback: Any = None
    gitops_token = os.environ.get("FDAI_GITOPS_TOKEN", "").strip()
    if gitops_token:
        if http_client is None:
            raise RuntimeError("FDAI_GITOPS_TOKEN requires a shared HTTP client")
        owner = os.environ.get("FDAI_GITOPS_OWNER", "").strip()
        repo = os.environ.get("FDAI_GITOPS_REPO", "").strip()
        if not owner or not repo:
            raise RuntimeError("FDAI_GITOPS_TOKEN requires FDAI_GITOPS_OWNER and FDAI_GITOPS_REPO")
        from fdai.delivery.github import GitHubWorkflowToolConfig, GitHubWorkflowToolExecutor

        workflow_tool = GitHubWorkflowToolExecutor(
            config=GitHubWorkflowToolConfig(
                owner=owner,
                repo=repo,
                api_base=os.environ.get("FDAI_GITOPS_API_BASE", "https://api.github.com").strip(),
            ),
            publisher=_build_publisher(http_client=http_client),
            http_client=http_client,
            token=gitops_token,
        )
        github_workflow_actions = {
            "tool.open-fix-pr",
            "tool.request-release",
            "tool.file-security-followup",
            "tool.file-irp-followup",
            "tool.open-incident-ticket",
        }
        routes.update({name: workflow_tool for name in github_workflow_actions})
        github_workflow_enforce = (
            os.environ.get("FDAI_GITHUB_WORKFLOW_TOOLS_ENFORCE", "").strip() == "1"
        )
        if github_workflow_enforce:
            enforce_actions.update(github_workflow_actions)
        _LOGGER.info(
            "tool_call_backend",
            extra={"backend": "github-workflow", "enforce": github_workflow_enforce},
        )
    from fdai.core.chaos.scenario_catalog import load_all as load_all_chaos_scenarios
    from fdai.core.chaos.scenario_catalog import load_promoted as load_promoted_chaos_scenarios
    from fdai.delivery.chaos.factories import default_factory as default_chaos_factory
    from fdai.delivery.chaos.tool import ChaosExperimentToolExecutor

    chaos_context_raw = os.environ.get("FDAI_CHAOS_CONTEXT_JSON", "").strip()
    try:
        chaos_context = json.loads(chaos_context_raw) if chaos_context_raw else {}
    except json.JSONDecodeError as exc:
        raise RuntimeError("FDAI_CHAOS_CONTEXT_JSON MUST be valid JSON") from exc
    if not isinstance(chaos_context, dict):
        raise RuntimeError("FDAI_CHAOS_CONTEXT_JSON MUST be a JSON object")
    chaos_signal_writer = None
    state_dsn = os.environ.get("FDAI_STATE_STORE_DSN", "").strip()
    if state_dsn:
        from fdai.delivery.persistence import (
            PostgresReportSignalStore,
            PostgresReportSignalStoreConfig,
        )

        chaos_signal_writer = PostgresReportSignalStore(
            config=PostgresReportSignalStoreConfig(dsn=state_dsn)
        )
    all_chaos_scenarios = load_all_chaos_scenarios()
    promoted_chaos_scenarios = load_promoted_chaos_scenarios()
    chaos_tool = ChaosExperimentToolExecutor(
        entries=all_chaos_scenarios,
        promoted_ids=frozenset(entry.id for entry in promoted_chaos_scenarios),
        factory=default_chaos_factory(),
        context=chaos_context,
        signal_writer=chaos_signal_writer,
    )
    routes["tool.run-chaos-experiment"] = chaos_tool
    chaos_enforce = os.environ.get("FDAI_CHAOS_ENFORCE", "").strip() == "1"
    if chaos_enforce:
        if not chaos_context:
            raise RuntimeError("FDAI_CHAOS_ENFORCE=1 requires FDAI_CHAOS_CONTEXT_JSON")
        enforce_actions.add("tool.run-chaos-experiment")
    _LOGGER.info(
        "tool_call_backend",
        extra={
            "backend": "chaos-experiment",
            "enforce": chaos_enforce,
            "promoted_scenarios": len(promoted_chaos_scenarios),
        },
    )
    if metric_provider is not None:
        from fdai.delivery.investigation import InvestigationToolExecutor

        routes["tool.run-investigation"] = InvestigationToolExecutor(
            metric_provider=metric_provider,
            signal_writer=chaos_signal_writer,
        )
        enforce_actions.add("tool.run-investigation")
    jira_base_url = os.environ.get("FDAI_JIRA_BASE_URL", "").strip()
    if jira_base_url:
        if http_client is None:
            raise RuntimeError("FDAI_JIRA_BASE_URL requires a shared HTTP client")
        dsn = os.environ.get("FDAI_STATE_STORE_DSN", "").strip()
        if not dsn:
            raise RuntimeError("Jira tool execution requires FDAI_STATE_STORE_DSN")
        account_email = os.environ.get("FDAI_JIRA_ACCOUNT_EMAIL", "").strip()
        token_secret = os.environ.get("FDAI_JIRA_API_TOKEN_SECRET", "").strip()
        raw_map = os.environ.get("FDAI_JIRA_TOOL_MAP_JSON", "").strip()
        if not account_email or not token_secret or not raw_map:
            raise RuntimeError(
                "Jira tool execution requires account email, token secret, and tool map"
            )
        try:
            decoded_map = json.loads(raw_map)
        except json.JSONDecodeError as exc:
            raise RuntimeError("FDAI_JIRA_TOOL_MAP_JSON MUST be valid JSON") from exc
        if not isinstance(decoded_map, dict) or not all(
            isinstance(key, str) and key and isinstance(value, str) and value
            for key, value in decoded_map.items()
        ):
            raise RuntimeError("FDAI_JIRA_TOOL_MAP_JSON MUST map strings to strings")
        from fdai.delivery.jira.tool import JiraToolExecutor, JiraToolExecutorConfig
        from fdai.delivery.persistence import (
            PostgresIdempotencyStoreConfig,
            PostgresJiraLedger,
        )
        from fdai.shared.providers.local import EnvSecretProvider

        jira_adapter: Any = JiraToolExecutor(
            config=JiraToolExecutorConfig(
                base_url=jira_base_url,
                account_email=account_email,
                api_token_secret=token_secret,
                tool_map=decoded_map,
            ),
            http_client=http_client,
            secrets=EnvSecretProvider(),
            ledger=PostgresJiraLedger(config=PostgresIdempotencyStoreConfig(dsn=dsn)),
        )
        jira_enforce = os.environ.get("FDAI_JIRA_ENFORCE", "").strip() == "1"
        routes.update({name: jira_adapter for name in decoded_map})
        if jira_enforce:
            enforce_actions.update(decoded_map)
        _LOGGER.info(
            "tool_call_backend",
            extra={"backend": "jira", "enforce": jira_enforce},
        )
    elif os.environ.get("FDAI_TOOL_CALL_FAKE", "").strip() == "1":
        fallback = RecordingToolExecutor()
        _LOGGER.info("tool_call_backend", extra={"backend": "recording"})

    if os.environ.get("FDAI_VM_TASK_ENABLED", "").strip() == "1":
        if http_client is None:
            raise RuntimeError("FDAI_VM_TASK_ENABLED requires a shared HTTP client")
        dsn = os.environ.get("FDAI_STATE_STORE_DSN", "").strip()
        if not dsn:
            raise RuntimeError("VM task execution requires FDAI_STATE_STORE_DSN")
        from fdai.delivery.azure.vm_task import AzureVmTaskRunner, AzureVmTaskRunnerConfig
        from fdai.delivery.azure.workload_identity import ManagedIdentityWorkloadIdentity
        from fdai.delivery.persistence.postgres_vm_task import (
            PostgresPythonTaskArtifactStore,
            PostgresVmTaskConfig,
            PostgresVmTaskTargetResolver,
        )
        from fdai.delivery.vm_task import VmPythonToolExecutor

        vm_config = PostgresVmTaskConfig(dsn=dsn)
        vm_adapter = VmPythonToolExecutor(
            artifacts=PostgresPythonTaskArtifactStore(config=vm_config),
            targets=PostgresVmTaskTargetResolver(config=vm_config),
            runner=AzureVmTaskRunner(
                identity=ManagedIdentityWorkloadIdentity(http_client=http_client),
                http_client=http_client,
                config=AzureVmTaskRunnerConfig(
                    endpoint=os.environ.get(
                        "FDAI_ARM_ENDPOINT", "https://management.azure.com"
                    ).strip(),
                    run_as_user=os.environ.get("FDAI_VM_TASK_RUN_AS_USER", "fdai-task").strip(),
                    task_root=os.environ.get("FDAI_VM_TASK_ROOT", "/var/lib/fdai/tasks").strip(),
                ),
            ),
        )
        routes["tool.run-python-on-vm"] = vm_adapter
        vm_enforce = os.environ.get("FDAI_VM_TASK_ENFORCE", "").strip() == "1"
        if vm_enforce:
            enforce_actions.add("tool.run-python-on-vm")
        _LOGGER.info(
            "tool_call_backend",
            extra={"backend": "azure-vm-task", "enforce": vm_enforce},
        )

    if not routes and fallback is None:
        _LOGGER.info("tool_call_backend", extra={"backend": "none"})
        return None

    from fdai.delivery.tool_router import RoutingToolExecutor

    adapter = RoutingToolExecutor(
        routes=routes,
        enforce_actions=frozenset(enforce_actions),
        fallback=fallback,
    )

    return ToolCallShadowExecutor(
        executor=adapter,
        audit_store=audit_store,
        resource_lock=resource_lock,
        idempotency=idempotency,
        receipt_observer=receipt_observer,
        enforce=bool(enforce_actions),
    )


def _build_incident_notifier(audit_store: Any) -> Any:
    """Compose durable A2 incident delivery for the control-plane process."""
    from fdai.core.incident import (
        DurableIncidentLifecycleNotifier,
        InMemoryIncidentNotificationDeliveryStore,
        RoutedIncidentLifecycleNotifier,
    )
    from fdai.core.notifications.router import ChannelRegistry, NotificationRouter
    from fdai.delivery.notifications import StateStoreHilEscalationSink

    dsn = os.environ.get("FDAI_STATE_STORE_DSN", "").strip()
    if dsn:
        from fdai.delivery.persistence import (
            PostgresIncidentNotificationDeliveryStore,
            PostgresStateStoreConfig,
        )

        delivery_store: Any = PostgresIncidentNotificationDeliveryStore(
            config=PostgresStateStoreConfig(dsn=dsn)
        )
    else:
        delivery_store = InMemoryIncidentNotificationDeliveryStore()
    matrix = load_matrix_from_yaml(
        _resolve_catalog_root().parent / "config" / "notifications-matrix.yaml"
    )
    router = NotificationRouter(
        matrix=matrix,
        registry=ChannelRegistry(),
        audit_store=audit_store,
        hil_sink=StateStoreHilEscalationSink(state_store=audit_store),
    )
    return DurableIncidentLifecycleNotifier(
        delegate=RoutedIncidentLifecycleNotifier(dispatcher=router),
        delivery_store=delivery_store,
    )
