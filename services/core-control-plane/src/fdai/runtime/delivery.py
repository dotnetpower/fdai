"""Environment-selected remediation, HIL, tool, and incident delivery adapters."""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import httpx

from fdai.core.executor.direct_api import DirectApiShadowExecutor
from fdai.core.executor.tool_call import ToolCallShadowExecutor, ToolReceiptObserver
from fdai.core.notifications.matrix import NotificationMatrix, load_matrix_from_yaml
from fdai.core.notifications.router import ChannelRegistry
from fdai.delivery.direct_api_router import RoutedDirectApiExecutor
from fdai.runtime.configuration import _resolve_catalog_root
from fdai.runtime.human_access import build_human_access_direct_api
from fdai.runtime.notification_registry import (
    _build_notification_registry as _build_notification_registry,
)
from fdai.runtime.notification_registry import (
    build_notification_delivery_store as build_notification_delivery_store,
)
from fdai.shared.providers.direct_api import DirectApiExecutor
from fdai.shared.providers.idempotency import IdempotencyStore
from fdai.shared.providers.resource_lock import ResourceLock
from fdai.shared.providers.testing.direct_api import RecordingDirectApiExecutor
from fdai.shared.providers.testing.remediation_pr import RecordingRemediationPrPublisher
from fdai.shared.providers.testing.tool import RecordingToolExecutor
from fdai.shared.providers.workload_identity import WorkloadIdentity

_LOGGER = logging.getLogger("fdai.startup")
_ACS_SCOPE = "https://communication.azure.com/.default"
_TEAMS_WORKFLOW_SCOPE = "https://service.flow.microsoft.com/.default"


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


def _build_hil_channel(
    http_client: httpx.AsyncClient | None,
    identity: WorkloadIdentity | None = None,
) -> Any:
    """Select the :class:`HilChannel` backend for this process.

    Presence of ``FDAI_TEAMS_APPROVAL_ACTIVITY_URL`` opts into the real
    :class:`TeamsHilAdapter`; missing channel configuration returns ``None`` so the caller
    falls back to its persisted HIL queue (existing P1 behavior - see
    ``docs/roadmap/interfaces/channels-and-notifications.md § 6``). The
    ``HilChannel`` Protocol is the contract, so ``core/`` neither knows
    nor cares which backend is active.

    Env vars (Bot Framework mode):

    - ``FDAI_TEAMS_APPROVAL_ACTIVITY_URL`` - fixed group-connected channel activity endpoint.
    - ``FDAI_TEAMS_APPROVAL_TEAM_ID`` / ``FDAI_TEAMS_APPROVAL_CHANNEL_ID`` - callback audience.
    - ``FDAI_CHATOPS_TIMEOUT_SECONDS`` - optional per-request
      timeout (default 15s).

    The injected workload identity requests the Bot Framework token. ``http_client`` remains
    composition-owned, and Incoming Webhooks are not accepted because they cannot deliver
    ``Action.Execute`` approval callbacks.
    """
    webhook_url = os.environ.get("FDAI_CHATOPS_WEBHOOK_URL", "").strip()
    activity_url = os.environ.get("FDAI_TEAMS_APPROVAL_ACTIVITY_URL", "").strip()
    if not webhook_url and not activity_url:
        _LOGGER.info("hil_channel_backend", extra={"backend": "none"})
        return None
    if not activity_url:
        raise RuntimeError(
            "FDAI_TEAMS_APPROVAL_ACTIVITY_URL is required because Incoming Webhooks "
            "cannot deliver Action.Execute approval callbacks"
        )
    if identity is None:
        raise RuntimeError("Teams approval Bot delivery requires a workload identity")

    if http_client is None:
        raise RuntimeError(
            "Teams approval Bot delivery has no HTTP client available. "
            "The composition root MUST create an httpx.AsyncClient "
            "before building the HIL channel."
        )

    from fdai.delivery.chatops.teams_adapter import TeamsHilAdapter, TeamsHilAdapterConfig

    approve_cb = os.environ.get("FDAI_CHATOPS_APPROVE_CALLBACK_URL", "").strip() or None
    reject_cb = os.environ.get("FDAI_CHATOPS_REJECT_CALLBACK_URL", "").strip() or None
    approval_team_id = os.environ.get("FDAI_TEAMS_APPROVAL_TEAM_ID", "").strip()
    approval_channel_id = os.environ.get("FDAI_TEAMS_APPROVAL_CHANNEL_ID", "").strip()
    if bool(approval_team_id) != bool(approval_channel_id):
        raise RuntimeError(
            "FDAI_TEAMS_APPROVAL_TEAM_ID and FDAI_TEAMS_APPROVAL_CHANNEL_ID "
            "MUST be configured together"
        )
    approval_audience = (
        f"teams:{approval_team_id}:{approval_channel_id}" if approval_team_id else None
    )

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
            "backend": "teams-bot",
            "workload_identity": True,
            "approve_callback_configured": approve_cb is not None,
            "reject_callback_configured": reject_cb is not None,
        },
    )
    return TeamsHilAdapter(
        config=TeamsHilAdapterConfig(
            webhook_url=activity_url,
            webhook_secret=None,
            approve_callback_url=approve_cb,
            reject_callback_url=reject_cb,
            approval_audience=approval_audience,
            timeout_seconds=timeout_seconds,
        ),
        http_client=http_client,
        identity=identity,
    )


def _build_direct_api_executor(
    *,
    audit_store: Any,
    resource_lock: ResourceLock,
    idempotency: IdempotencyStore | None = None,
    http_client: httpx.AsyncClient | None = None,
    identity: WorkloadIdentity | None = None,
    human_access_enabled: bool = True,
    promotion_registry: Any = None,
    graph_model_promotion_registry: Any = None,
    action_types_by_name: Mapping[str, Any] | None = None,
    execution_identities: Mapping[str, WorkloadIdentity] | None = None,
) -> DirectApiShadowExecutor | None:
    """Select the direct-API executor for this process.

    Operations-gateway actions use the existing fallback adapter. Human-access
    ActionTypes route to a dedicated Entra adapter only when all role-group and
    workload-identity settings are present. The fake remains an isolated test
    mode and cannot be combined with live human access.
    """

    fake_enabled = os.environ.get("FDAI_DIRECT_API_FAKE", "").strip() == "1"
    gateway_url = os.environ.get("FDAI_DEV_OPERATIONS_GATEWAY_URL", "").strip()
    gateway_audience = os.environ.get("FDAI_DEV_OPERATIONS_GATEWAY_AUDIENCE", "").strip()
    human_access_configured = bool(os.environ.get("FDAI_HUMAN_ACCESS_ROLE_GROUPS_JSON", "").strip())
    if fake_enabled and gateway_url:
        raise RuntimeError("FDAI_DIRECT_API_FAKE conflicts with the operations gateway binding")
    if fake_enabled and human_access_configured:
        raise RuntimeError("FDAI_DIRECT_API_FAKE conflicts with the human access binding")
    if bool(gateway_url) != bool(gateway_audience):
        raise RuntimeError("operations gateway URL and audience MUST be configured together")

    fallback: DirectApiExecutor | None = None
    routes: dict[str, DirectApiExecutor] = {}
    identity_routes: dict[str, DirectApiExecutor] = {}
    allow_enforce = False
    if gateway_url:
        if http_client is None or identity is None:
            raise RuntimeError("operations gateway binding requires HTTP and workload identity")
        from fdai.delivery.azure.gateway_direct_api import (
            AzureGatewayDirectApiConfig,
            AzureGatewayDirectApiExecutor,
        )

        _LOGGER.info("direct_api_backend", extra={"backend": "azure-functions-gateway"})
        fallback = AzureGatewayDirectApiExecutor(
            config=AzureGatewayDirectApiConfig(
                base_url=gateway_url,
                audience=gateway_audience,
            ),
            identity=identity,
            http_client=http_client,
        )
        for identity_ref, selected_identity in (execution_identities or {}).items():
            identity_routes[identity_ref] = AzureGatewayDirectApiExecutor(
                config=AzureGatewayDirectApiConfig(
                    base_url=gateway_url,
                    audience=gateway_audience,
                ),
                identity=selected_identity,
                http_client=http_client,
            )
        allow_enforce = True
    elif fake_enabled:
        _LOGGER.info("direct_api_backend", extra={"backend": "recording"})
        fallback = RecordingDirectApiExecutor()

    if promotion_registry is not None and action_types_by_name:
        from fdai.delivery.persistence import (
            StateStoreActionPromotionRegistry,
            StateStoreOperationalPromotionReceiptStore,
        )
        from fdai.delivery.promotion import (
            PROMOTION_ACTION_TYPE,
            GovernancePromotionDispatcher,
            OperationalPromotionDirectApiExecutor,
            StateStorePromotionAttestationStore,
        )

        if isinstance(promotion_registry, StateStoreActionPromotionRegistry):
            routes[PROMOTION_ACTION_TYPE] = GovernancePromotionDispatcher(
                OperationalPromotionDirectApiExecutor(
                    action_types=action_types_by_name,
                    receipts=StateStoreOperationalPromotionReceiptStore(audit_store),
                    registry=promotion_registry,
                ),
                attestation_store=StateStorePromotionAttestationStore(audit_store),
            )
            allow_enforce = True

    if graph_model_promotion_registry is not None and action_types_by_name:
        from fdai.delivery.graph_model_promotion import (
            PROMOTE_EFFECT_MODEL_ACTION_TYPE,
            GraphModelPromotionDirectApiExecutor,
        )

        if PROMOTE_EFFECT_MODEL_ACTION_TYPE in action_types_by_name:
            routes[PROMOTE_EFFECT_MODEL_ACTION_TYPE] = GraphModelPromotionDirectApiExecutor(
                registry=graph_model_promotion_registry,
            )
            allow_enforce = True

    human_access = build_human_access_direct_api(
        audit_store=audit_store,
        http_client=http_client,
        enabled=human_access_enabled,
    )
    executor: DirectApiExecutor | None = fallback
    if human_access is not None:
        from fdai.delivery.identity import HUMAN_ACCESS_ACTIONS

        _LOGGER.info("direct_api_human_access_backend", extra={"backend": "entra"})
        routes.update({action_type: human_access for action_type in HUMAN_ACCESS_ACTIONS})
    if routes or identity_routes:
        executor = RoutedDirectApiExecutor(
            routes=routes,
            identity_routes=identity_routes,
            fallback=fallback,
        )
    if executor is None:
        _LOGGER.info("direct_api_backend", extra={"backend": "none"})
        return None

    return DirectApiShadowExecutor(
        executor=executor,
        audit_store=audit_store,
        resource_lock=resource_lock,
        idempotency=idempotency,
        allow_enforce=allow_enforce,
    )


def _build_tool_executor(
    *,
    audit_store: Any,
    resource_lock: ResourceLock,
    idempotency: IdempotencyStore | None = None,
    receipt_observer: ToolReceiptObserver | None = None,
    http_client: httpx.AsyncClient | None = None,
    metric_provider: Any = None,
    chaos_catalog_root: Path | None = None,
    governed_chaos_execution: Any = None,
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
    all_chaos_scenarios = (
        load_all_chaos_scenarios(root=chaos_catalog_root)
        if chaos_catalog_root is not None
        else load_all_chaos_scenarios()
    )
    promoted_chaos_scenarios = (
        load_promoted_chaos_scenarios(root=chaos_catalog_root)
        if chaos_catalog_root is not None
        else load_promoted_chaos_scenarios()
    )
    chaos_tool = ChaosExperimentToolExecutor(
        entries=all_chaos_scenarios,
        promoted_ids=frozenset(entry.id for entry in promoted_chaos_scenarios),
        factory=default_chaos_factory(),
        context=chaos_context,
        signal_writer=chaos_signal_writer,
        governed_execution=governed_chaos_execution,
    )
    routes["tool.run-chaos-experiment"] = chaos_tool
    chaos_enforce = os.environ.get("FDAI_CHAOS_ENFORCE", "").strip() == "1"
    if chaos_enforce:
        if not chaos_context:
            raise RuntimeError("FDAI_CHAOS_ENFORCE=1 requires FDAI_CHAOS_CONTEXT_JSON")
        if governed_chaos_execution is None:
            raise RuntimeError("FDAI_CHAOS_ENFORCE=1 requires a governed chaos execution provider")
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


def _validate_incident_notification_route(
    matrix: NotificationMatrix,
    registry: ChannelRegistry,
) -> None:
    """Report an unavailable A2 route without disabling unrelated runtime paths."""

    route = matrix.resolve("operational_alert")
    eligible = tuple(
        channel_id
        for channel_id in route.channel_ids
        if (channel := registry.resolve(channel_id)) is not None
        and route.trust_tier in channel.trust_tiers
    )
    if eligible:
        return
    _LOGGER.warning(
        "notification_route_unavailable",
        extra={
            "route": route.category,
            "required_trust_tier": route.trust_tier.value,
            "configured_channel_count": len(registry.channels),
        },
    )


def _incident_roster_url() -> str:
    console_base_url = os.environ.get("FDAI_CONSOLE_BASE_URL", "").strip().rstrip("/")
    return f"{console_base_url}/incidents" if console_base_url else "/incidents"


def _build_incident_notifier(
    audit_store: Any,
    *,
    http_client: httpx.AsyncClient | None = None,
    notification_delivery_store: Any = None,
    endpoint_overrides: Mapping[str, str] | None = None,
) -> Any:
    """Compose durable A2 incident delivery for the control-plane process.

    ``notification_delivery_store`` MUST be the same per-channel store the
    publication-receipt consumer applies observations to; otherwise a receipt
    could never find the delivery it confirms.
    """
    from fdai.core.incident import (
        DurableIncidentLifecycleNotifier,
        InMemoryIncidentNotificationDeliveryStore,
        RoutedIncidentLifecycleNotifier,
    )
    from fdai.core.notifications.router import NotificationRouter
    from fdai.delivery.notifications import StateStoreHilEscalationSink

    dsn = os.environ.get("FDAI_STATE_STORE_DSN", "").strip()
    if dsn:
        from fdai.delivery.persistence import (
            PostgresIncidentNotificationDeliveryStore,
            PostgresStateStoreConfig,
        )

        incident_delivery_store: Any = PostgresIncidentNotificationDeliveryStore(
            config=PostgresStateStoreConfig(dsn=dsn)
        )
    else:
        incident_delivery_store = InMemoryIncidentNotificationDeliveryStore()
    if notification_delivery_store is None:
        notification_delivery_store = build_notification_delivery_store()
    matrix = load_matrix_from_yaml(
        _resolve_catalog_root().parent / "config" / "notifications-matrix.yaml"
    )
    registry = _build_notification_registry(http_client, endpoint_overrides)
    _validate_incident_notification_route(matrix, registry)
    router = NotificationRouter(
        matrix=matrix,
        registry=registry,
        audit_store=audit_store,
        hil_sink=StateStoreHilEscalationSink(state_store=audit_store),
        delivery_store=notification_delivery_store,
    )
    return DurableIncidentLifecycleNotifier(
        delegate=RoutedIncidentLifecycleNotifier(
            dispatcher=router,
            incidents_url=_incident_roster_url(),
        ),
        delivery_store=incident_delivery_store,
    )
