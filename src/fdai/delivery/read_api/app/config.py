"""Public configuration contract for the console read API factory."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from fdai.core.hil_resume import HilResumeCoordinator
from fdai.core.rbac.resolver import Principal
from fdai.delivery.read_api.routes.hil_callback import HilCallbackConfig
from fdai.delivery.read_api.routes.panels import ReadPanel
from fdai.delivery.read_api.streaming.agent_activity_stream import AgentActivityStreamConfig
from fdai.delivery.read_api.streaming.live_stream import LiveStreamConfig
from fdai.delivery.read_api.streaming.provision_stream import ProvisionStreamConfig
from fdai.shared.providers.hil_registry import HilApprovalRegistry


@dataclass(frozen=True, slots=True)
class ReadApiConfig:
    """Composition-root configuration for :func:`build_app`.

    ``dev_mode`` short-circuits authentication for automated tests. It MUST
    default to ``False`` and MUST NOT be true in interactive local or a
    production composition root - the fork's IaC pipeline enforces that
    by never setting ``FDAI_READ_API_DEV_MODE`` on deployed
    revisions.
    """

    dev_mode: bool = False
    """When True, unauthenticated requests are treated as anonymous
    Readers. Only for pytest fixtures."""

    local_cli_principal: Principal | None = None
    """Current ``az login`` user projected into the local dev harness.

    Requires ``FDAI_READ_API_LOCAL_AZURE_CLI=1`` and is refused in staging
    or production. The associated access token never enters this config.
    """

    local_cli_profile: Mapping[str, object] | None = None
    """Browser-safe profile served by ``GET /local-auth/me`` in CLI mode."""

    cors_allow_origins: tuple[str, ...] = ()
    """Origins the console SPA is served from. Empty tuple disables CORS
    (same-origin deployment). MUST NOT be ``('*',)`` in production."""

    extra_panels: tuple[ReadPanel, ...] = ()
    """Fork-supplied read-only console panels (see
    :mod:`fdai.delivery.read_api.panels`). Empty by default so the
    upstream UI stays minimal; a fork registers vertical dashboards here.
    Each panel is registered as a ``GET``-only route, preserving the
    read-only invariant. The app factory fails fast on a malformed or
    colliding panel path."""

    hil_callback: HilCallbackConfig | None = None
    """Opt-in ChatOps HIL callback config. When set, registers a single
    ``POST /hil/{approval_id}/decision`` route that verifies an HMAC
    signature over the request body. ``None`` (the default) keeps the
    read-API strictly GET-only. The route consumes a
    :class:`~fdai.shared.providers.hil_registry.HilApprovalRegistry`
    instead of the executor identity, so no privilege boundary is
    crossed. See Wave W1.3 in
    [implementation-plan.md](../../../../docs/roadmap/fork-and-sequencing/implementation-plan.md)."""

    hil_registry: HilApprovalRegistry | None = None
    """Registry consumed by the HIL callback route. When
    ``hil_callback`` is set, this MUST also be set - the app factory
    fails fast otherwise."""

    hil_coordinator: HilResumeCoordinator | None = None
    """Optional park-and-resume coordinator for the HIL callback route.
    When set, an inbound decision is applied to a control-loop-parked
    action first (APPROVE re-dispatches it to the executor); an
    approval with no matching park falls through to the registry path.
    ``None`` keeps the callback registry-only (console-pull approvals)."""

    hil_decision_publisher: Any = None
    """Optional async publisher for durable HIL decision receipts. Production
    uses this instead of giving the read API an executor identity."""

    shutdown_callbacks: tuple[Callable[[], Awaitable[None]], ...] = ()
    """Async delivery resources closed when the ASGI lifespan exits."""

    startup_callbacks: tuple[Callable[[], Awaitable[None]], ...] = ()
    """Async delivery services started before the ASGI app accepts traffic.
    A callback that raises fails startup rather than exposing a half-wired
    action path."""

    webhook_ingress: Any = None
    """Opt-in inbound webhook POST route (P2-7). When set (a
    :class:`~fdai.delivery.webhook.ingress.WebhookIngress`), registers a
    single ``POST /webhook`` route that authenticates an HMAC-signed
    request, normalizes the body into an ``Event``, and publishes it onto
    the ingest topic. ``None`` (the default) keeps the read-API strictly
    GET-only. The ingress never executes a change - it only injects an
    event, so no privilege boundary is crossed. See
    :mod:`fdai.delivery.read_api.routes.webhook`."""

    webhook_path: str = "/webhook"
    """Path the ``webhook_ingress`` route is mounted at. Ignored when
    ``webhook_ingress`` is ``None``."""

    live_stream: LiveStreamConfig | None = None
    """Opt-in live SSE fan-out. When set, registers a ``GET`` streaming
    route (default ``/live/stream``) that broadcasts control-plane
    events to any subscriber. The default is ``None`` - upstream ships
    strictly three GET routes; a fork (or the dev harness in
    :mod:`fdai.delivery.read_api.dev.local`) opts in. See
    :mod:`fdai.delivery.read_api.live_stream` for the read-only /
    fan-out contract."""

    provision_stream: ProvisionStreamConfig | None = None
    """Opt-in provisioning progress SSE surface. When set, registers a
    ``GET`` streaming route (default ``/provision/stream``) that fans out
    ``provision.*`` events to the Genesis console. Read-only: the console
    renders progress, it never executes provisioning. The producer (the
    ``azd up`` terraform bridge, or an in-product relay) publishes onto
    the shared sink via
    :class:`~fdai.delivery.read_api.streaming.provision_stream.SseProvisionPublisher`.
    Default ``None``. See
    :mod:`fdai.delivery.read_api.provision_stream`."""

    agent_activity: AgentActivityStreamConfig | None = None
    """Opt-in agent-activity SSE surface. When set, registers a ``GET``
    streaming route (default ``/agents/stream``) that fans out
    ``agent.state`` / ``incident.ticket`` / ``conversation.turn`` events to
    the ``Now > Agents`` console panel. Read-only: the console renders agent
    collaboration, it never executes. Interactive local development leaves
    this unset unless an actual runtime relay is bound; synthetic activity is
    test-only. Default ``None``. See
    :mod:`fdai.delivery.read_api.streaming.agent_activity_stream`."""

    blast_radius_graph: Any = None
    """Opt-in blast-radius simulator. When set (an
    :class:`~fdai.core.risk_gate.blast_radius_simulator.OntologyGraph`),
    registers ``GET /simulate/blast-radius``. Read-only projection: the
    caller supplies a target Resource id + traversal spec, gets back
    the depth-N reachable subgraph. The default is ``None`` so upstream
    stays minimal; a fork wires its Postgres-backed graph adapter here.
    See :mod:`fdai.delivery.read_api.blast_radius`."""

    ontology_object_types: tuple[Any, ...] = ()
    """Opt-in ontology explorer input. Tuple of
    :class:`~fdai.shared.contracts.models.OntologyObjectType`. When
    combined with :attr:`ontology_link_types`, the app registers
    ``GET /ontology/graph`` returning a Mermaid ``classDiagram`` plus
    node/edge counts. Empty by default."""

    ontology_link_types: tuple[Any, ...] = ()
    """Opt-in ontology explorer input. Tuple of
    :class:`~fdai.shared.contracts.models.OntologyLinkType`. See
    :attr:`ontology_object_types` for the pairing contract."""

    ontology_action_types: tuple[Any, ...] = ()
    """ActionType safety contracts exposed by ``GET /ontology/graph``.
    Empty by default; ObjectType and LinkType exploration remains available
    without an ActionType catalog."""

    inventory_graph_provider: Any = None
    """Opt-in deployed-inventory graph projection. An async callable
    ``(scope, depth, link_types) -> mapping`` returning CSP-neutral
    ``resources`` and ``links`` plus freshness metadata. When set, registers
    Reader-gated ``GET /inventory/graph``. The provider reads the inventory
    projection only; the console never receives a cloud or executor identity."""

    scope_source: Any = None
    """Opt-in effective-scope view: a
    :class:`~fdai.delivery.read_api.routes.scope.ScopeSource`. When set,
    registers Reader-gated read-only ``GET /scope``."""

    rule_catalog_rules: tuple[Any, ...] = ()
    """Opt-in rule-catalog explorer input: the *active* catalog. Tuple of
    :class:`~fdai.shared.contracts.models.Rule` loaded at
    composition-root time via
    :func:`~fdai.rule_catalog.schema.rule.load_rule_catalog` (the curated
    ``rule-catalog/catalog/`` tier T0 evaluates). When this OR
    :attr:`rule_catalog_collected_rules` is non-empty, the app registers
    a paginated ``GET /rules`` returning rule summaries tagged
    ``origin=active`` plus facet counts, so the console's Knowledge >
    Rules panel can render every policy the system knows. Empty by
    default so upstream stays minimal. Read-only projection - the route
    never mutates state. See :mod:`fdai.delivery.read_api.rule_catalog`."""

    rule_catalog_collected_rules: tuple[Any, ...] = ()
    """Opt-in rule-catalog explorer input: the *collected* corpus. Tuple
    of :class:`~fdai.shared.contracts.models.Rule` parsed from the
    imported ``rule-catalog/collected/`` tree (Azure Policy built-ins,
    kube-bench). Thousands of candidate / reference rules that are not
    all normalized to the canonical vocabulary yet; served tagged
    ``origin=collected`` alongside the active tier on ``GET /rules``.
    Empty by default. Same read-only projection contract as
    :attr:`rule_catalog_rules`."""

    rule_catalog_policies_root: Any = None
    """Opt-in filesystem root (:class:`pathlib.Path`) for the rule detail
    view. When set, ``GET /rules/{id}`` resolves a rule's
    ``check_logic.reference`` (e.g. ``policies/x.rego``) to the file body
    so the console drawer can show the actual Rego. Reads are sandboxed
    to this root; a traversal or non-file reference yields ``null``.
    ``None`` serves metadata only."""

    rule_catalog_remediation_root: Any = None
    """Opt-in filesystem root (:class:`pathlib.Path`) for the rule detail
    view. When set, ``GET /rules/{id}`` resolves a rule's
    ``remediation.template_ref`` (e.g. ``remediation/x.tftpl``) to the
    file body. Same sandbox contract as
    :attr:`rule_catalog_policies_root`."""

    rule_catalog_findings_provider: Any = None
    """Opt-in findings source for ``GET /rules/{id}/findings`` (the
    affected-resources view). A callable ``(rule_id, origin) ->
    awaitable[sequence[mapping]]`` where each mapping describes one
    resource violating the rule plus the attribute at fault. ``None``
    (default) makes the endpoint report ``evaluated=false`` with no
    findings - upstream never fabricates resource impact. A fork wires
    an inventory-evaluation source (assurance_twin / T0 over real
    inventory)."""

    rule_catalog_findings_summary_provider: Any = None
    """Opt-in count source for ``GET /rules/findings-summary`` (the
    at-a-glance affected-count badge on the list). A callable ``() ->
    awaitable[mapping[rule_id, int]]``. ``None`` (default) makes the
    endpoint report ``evaluated=false``; a fork wires the same
    inventory-evaluation source as :attr:`rule_catalog_findings_provider`."""

    promotion_gate_action_types: tuple[Any, ...] = ()
    """Opt-in promotion-gate dashboard input: tuple of
    :class:`~fdai.shared.contracts.models.OntologyActionType`."""

    promotion_gate_source: Any = None
    """Opt-in promotion-gate dashboard input:
    :class:`~fdai.core.measurement.promotion_gate.ShadowVerdictSource`.
    When BOTH this and :attr:`promotion_gate_action_types` are set,
    the app registers ``GET /kpi/promotion-gates``."""

    trace_reader: Any = None
    """Opt-in rule-fire trace viewer. When set (an
    :class:`~fdai.core.audit.rule_fire_trace.AuditTraceReader`),
    registers ``GET /audit/{correlation_id}/trace``. The reader plugs
    into any audit backing store; the shipped
    :class:`~fdai.core.audit.rule_fire_trace.ConsoleReadModelTraceReader`
    wraps the existing :class:`ConsoleReadModel` and works with the
    in-memory store out of the box."""

    bitemporal_reader: Any = None
    """Opt-in bitemporal snapshot route. When set (an
    :class:`~fdai.core.audit.rule_fire_trace.AuditTraceReader`),
    registers ``GET /audit/{correlation_id}/bitemporal``. Typically the
    same reader used for :attr:`trace_reader`."""

    what_if_reader: Any = None
    """Opt-in what-if replay route reader. When BOTH this and
    :attr:`what_if_evaluators` are set, registers
    ``GET /audit/{correlation_id}/what-if?scenario=<name>``."""

    what_if_evaluators: Mapping[str, Any] = field(default_factory=dict)
    """Named pre-registered
    :class:`~fdai.core.audit.what_if_replay.WhatIfEvaluator` implementations.
    Empty by default so upstream stays minimal; a fork registers each
    scenario at composition-root time."""

    chat: Any = None
    """Opt-in CommandDeck chat backend. When set (an implementer of
    :class:`~fdai.delivery.read_api.routes.chat.ChatBackend`), registers
    ``POST /chat`` for the console's screen-aware conversational
    surface. The backend is a read-only translator - it never issues a
    privileged call. Wire :class:`~fdai.delivery.read_api.routes.chat.OpenAiCompatibleChatBackend`
    (or a fork adapter) at composition root; leave ``None`` to keep the
    endpoint unregistered (the FE deck then falls back to its built-in
    deterministic answerer)."""

    chat_web_search: Any = None
    """Optional controlled public-web evidence resolver for chat turns.
    The resolver remains deny-by-default, sends only the bounded operator
    query, and never receives the current screen snapshot or history."""

    chat_probe_interval_seconds: int = 300
    """Periodic latency-probe interval for routed narrator deployments.
    The first benchmark warms every candidate; later rounds add one sample
    per candidate so the rolling p50 adapts without excessive model calls."""

    chat_agent_delegate: Any = None
    """Optional read-only Bragi delegation adapter. When set alongside
    :attr:`chat`, the server routes domain questions to the owning pantheon
    agent and supplies that result to the narrator as server-owned evidence.
    The adapter cannot submit actions or materialize handoffs; those remain on
    their dedicated typed paths."""

    conversation_policy_store: Any = None
    """Optional principal-scoped typed response-policy store for the narrator.
    Raw user prose is never read from this seam; the chat route compiles only
    confirmed allowlisted policy fields into a bounded system layer."""

    conversation_history_store: Any = None
    """Optional principal-scoped durable Conversation and Turn store. When
    configured, both chat routes append authenticated inbound turns and final
    verified answers using request-id idempotency."""

    user_context_ontology_projector: Any = None
    """Optional metadata-only projector for Conversation, Turn, preference,
    memory, briefing, and workflow ownership records."""

    console_action: Any = None
    """Opt-in console action submitter
    (:class:`~fdai.delivery.read_api.routes.console_action.ConsoleActionSubmitter`).
    When set, registers ``POST /chat/action`` - the ONE write-direction
    conversational path. Ordinary mutation requests publish an operator
    ``ActionProposal`` for pantheon judgment; incident requests prepare and
    confirm an audited control-plane record. It holds no executor identity and
    never mutates a cloud resource directly. RBAC is server-derived
    (Contributor+ ``author-draft-pr``). Leave ``None`` to keep the console
    read-only with no action-submit surface."""

    kill_switch_command: Any = None
    """Opt-in Owner/BreakGlass emergency-stop command service.

    Registers ``POST /system/kill-switch`` without exposing a console control
    or executor identity. The service changes control-plane authority state
    atomically with its audit record. Production wires the shared Postgres
    state store; local and test compositions remain off unless explicit.
    """

    iam_access: Any = None  # Governed IAM projections and request commands.
    iam_directory: Any = None  # Cloud-neutral Owner search and roster provider.
    iam_identity_provider: str = "entra"  # Provider stamped on new requests.
    iam_role_group_ids: Mapping[str, str] = field(default_factory=dict)  # Role groups.

    expose_pantheon: bool = False
    """Opt-in pantheon graph + workflows endpoints. When True, registers
    two read-only routes: ``GET /pantheon/graph`` (15 agents, org chart
    edges, owned object types, LLM hot-path flag) and
    ``GET /pantheon/workflows`` (10 cross-agent workflow catalog). Both
    are pure projections of the in-memory pantheon registry
    (``fdai.agents``); no state, no side effects. Reader-role gate.
    See :mod:`fdai.delivery.read_api.pantheon`."""

    stewardship_map: Any = None
    """Opt-in agent-stewardship / handover-map endpoint. When set (a
    :class:`~fdai.core.stewardship.model.StewardshipMap` loaded from
    ``config/agent-stewardship.yaml`` at composition-root time), registers
    a read-only ``GET /stewardship`` route returning the handover map
    (maintainers + 15 agents + stewards) plus the coverage report
    (bus-factor / over-assignment / maintainer findings). ``None`` (the
    default) keeps the endpoint unregistered. Read-only projection - the
    console renders it; edits are governance draft PRs, never a console
    mutation. See :mod:`fdai.delivery.read_api.routes.stewardship`."""

    workflow_authoring: Any = None
    """Opt-in custom workflow authoring routes. When set (a
    :class:`~fdai.delivery.read_api.routes.workflow_authoring.WorkflowAuthoringConfig`),
    registers ``GET /workflows/action-types`` (the ActionType palette the
    builder maps steps onto) and ``POST /workflows/validate`` (validate a
    draft Workflow and return a canonical YAML preview). Both are
    read-only: the validate route is a pure function that writes no state
    and never creates a PR - the console copies the previewed YAML into a
    remediation PR through the git-native path. Reader-role gate. Unset by
    default so upstream stays minimal.
    See :mod:`fdai.delivery.read_api.workflow_authoring`."""

    workflow_execution: Any = None
    """Opt-in Contributor-gated ``POST /workflows/run`` shadow command."""
    workflow_definitions: Any = None
    """Opt-in principal-scoped WorkflowDefinition and WorkflowBinding routes."""
    user_context: Any = None
    """Opt-in principal-scoped conversation, preference, memory, policy, and
    briefing routes under ``/me``."""
    model_settings: Any = None
    """Opt-in sanitized model catalog, runtime latency, and per-user narrator preference."""
    python_tasks: Any = None
    """Opt-in governed Python task author, plan, schedule, and proposal routes."""
    reporting: Any = None
    """Opt-in reporting subsystem routes. When set (a
    :class:`~fdai.delivery.read_api.routes.reporting.ReportingConfig`),
    registers four ``GET`` routes under the configured prefix (default
    ``/reports``): catalog listing, registry inspection, per-report
    definition, and per-report render (with ``?format=json|markdown|
    csv``). All read-only; every route hits the reader-role gate. See
    :mod:`fdai.delivery.read_api.reporting` and
    :mod:`fdai.core.reporting` for the fork-extensible datasource /
    widget / format seams. Unset by default so upstream stays minimal."""

    process_views: Any = None
    """Opt-in dynamic Process views. When set, registers Reader-gated
    ``GET /views/process`` and ``GET /views/process/{process_id}``. The
    response is a bounded RenderedView projection selected by Workflow ref;
    no ontology layout or workflow decision is computed in the browser."""


__all__ = ["ReadApiConfig"]
