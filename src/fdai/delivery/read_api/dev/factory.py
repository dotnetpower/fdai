"""Azure-backed local entrypoint for the console read API.

The interactive factory requires the current Azure CLI identity and never
seeds runtime evidence. Repository catalogs remain available as reference
data; Azure runtime panels stay empty or unavailable until their authoritative
Azure data-plane adapters are configured.

**Never wire this in production.** The env-var tripwire in
:func:`fdai.delivery.read_api.main.build_app` refuses to build a
dev-mode app unless ``FDAI_READ_API_DEV_MODE=1`` is set - this
module also asserts that at build time so a stray production revision
that boots it fails fast.

Usage (uvicorn's ``--factory`` flag calls :func:`app` at server start,
so importing this module during unrelated tooling - pytest collection,
mypy, IDE indexing - has no side effect)::

    FDAI_READ_API_LOCAL_AZURE_CLI=1 \
        uv run uvicorn 'fdai.delivery.read_api.dev.local:app' \
            --factory --port 8000

Synthetic composition is available only through the explicit
``test_fixtures=True`` argument used by pytest integration tests.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

from starlette.applications import Starlette

# Dev harness: make our own INFO logs visible so live-stream open/close
# events show up alongside uvicorn's access log.
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(name)s: %(message)s")

from fdai.core.audit.what_if_replay import WhatIfEvaluator  # noqa: E402
from fdai.core.measurement.promotion_gate import (  # noqa: E402
    InMemoryShadowVerdictSource,
)
from fdai.core.metering import (  # noqa: E402
    InMemoryMeteringSink,
)
from fdai.core.onboarding import EmptyResourceProbe  # noqa: E402
from fdai.core.operator_memory import (  # noqa: E402
    InMemoryMemoryCompactionRepository,
    InMemoryOperatorMemoryStore,
    OperatorMemoryReviewService,
)
from fdai.core.rbac.access_request import AccessRequestService  # noqa: E402
from fdai.core.rbac.resolver import RoleResolver  # noqa: E402
from fdai.core.scheduler import (  # noqa: E402
    InMemoryScheduleRunLedger,
    ScheduleRunHistoryService,
)
from fdai.delivery.read_api.auth import (  # noqa: E402
    UnsafeClaimsExtractor,
    build_authenticator,
)
from fdai.delivery.read_api.dev.azure_cli_identity import (  # noqa: E402
    resolve_azure_cli_identity,
)
from fdai.delivery.read_api.dev.config import (  # noqa: E402
    cors_origins_from_env as _cors_origins_from_env,
)
from fdai.delivery.read_api.dev.config import (  # noqa: E402
    entra_application_id_from_env,
    local_entra_verifier_environment,
)
from fdai.delivery.read_api.dev.config import (  # noqa: E402
    group_mapping_from_env as _group_mapping_from_env,
)
from fdai.delivery.read_api.dev.fixtures.dynamic_views import (  # noqa: E402
    _build_blast_radius_graph,
    _build_scope_view,
    _DemoTighterTagsEvaluator,
)
from fdai.delivery.read_api.dev.fixtures.seed_data import (  # noqa: E402
    _seed,
    _synthetic_llm_invocations,
    _synthetic_verdicts,
)
from fdai.delivery.read_api.dev.helpers import (  # noqa: E402
    build_agent_streams as _build_agent_streams,
)
from fdai.delivery.read_api.dev.helpers import (  # noqa: E402
    build_chat_backend as _build_chat_backend,
)
from fdai.delivery.read_api.dev.helpers import (  # noqa: E402
    build_chat_web_search as _build_chat_web_search,
)
from fdai.delivery.read_api.dev.helpers import (  # noqa: E402
    build_inventory_graph_provider as _build_inventory_graph_provider,
)
from fdai.delivery.read_api.dev.helpers import (  # noqa: E402
    build_live_stream_config as _build_live_stream_config,
)
from fdai.delivery.read_api.dev.helpers import (  # noqa: E402
    build_stewardship_map as _build_stewardship_map,
)
from fdai.delivery.read_api.dev.helpers import (  # noqa: E402
    chat_probe_interval_seconds as _chat_probe_interval_seconds,
)
from fdai.delivery.read_api.dev.iam_directory import (  # noqa: E402
    build_local_iam_directory,
)
from fdai.delivery.read_api.dev.model_wiring import build_local_model_wiring  # noqa: E402
from fdai.delivery.read_api.dev.runtime_wiring import build_local_runtime_wiring  # noqa: E402
from fdai.delivery.read_api.dev.view_wiring import build_local_view_wiring  # noqa: E402
from fdai.delivery.read_api.entra_verifier import (  # noqa: E402
    EntraJwtVerifier,
)
from fdai.delivery.read_api.main import ReadApiConfig, build_app  # noqa: E402
from fdai.delivery.read_api.read_model import (  # noqa: E402
    InMemoryConsoleReadModel,
)
from fdai.delivery.read_api.routes.chat_agent_delegate import (  # noqa: E402
    PantheonChatDelegate,
)
from fdai.delivery.read_api.routes.llm_cost import LlmCostPanel  # noqa: E402
from fdai.delivery.read_api.routes.measurement_summary import (  # noqa: E402
    AutonomyMeasurementPanel,
)
from fdai.delivery.read_api.routes.onboarding import OnboardingPanel  # noqa: E402
from fdai.delivery.read_api.routes.operator_memory import OperatorMemoryPanel  # noqa: E402
from fdai.delivery.read_api.routes.panels import (  # noqa: E402
    CapabilityCatalogPanel,
    ExampleFinOpsPanel,
)
from fdai.delivery.read_api.routes.rule_fire_trace_reader import (  # noqa: E402
    ConsoleReadModelTraceReader,
)
from fdai.delivery.read_api.routes.scheduler_runs import SchedulerRunsPanel  # noqa: E402
from fdai.delivery.read_api.streaming.agent_activity_stream import (  # noqa: E402
    runtime_agent_state_snapshot,
)
from fdai.delivery.read_api.streaming.provision_stream import ProvisionStreamConfig  # noqa: E402
from fdai.shared.providers.testing.state_store import InMemoryStateStore  # noqa: E402

_DEV_ENV = "FDAI_READ_API_DEV_MODE"
_LOCAL_ENTRA_ENV = "FDAI_READ_API_LOCAL_ENTRA"
_LOCAL_AZURE_CLI_ENV = "FDAI_READ_API_LOCAL_AZURE_CLI"
_LOCAL_ACTION_TOPIC = "aw.events"
# local.py lives at src/fdai/delivery/read_api/dev/local.py, so the repo root
# is six levels up (parents[5]): dev -> read_api -> delivery -> fdai -> src ->
# repo root. This was parents[4] before the module moved into dev/ (bc11c981);
# an index off by one made _REPO_ROOT resolve to src/ and every catalog-backed
# route (ontology, rules, promotion-gates, workflows) 404 with empty catalogs.
_REPO_ROOT = Path(__file__).resolve().parents[5]

# One seed audit row: (agent, tier, action_kind, outcome, finished_hhmmss,
# correlation, summary, detail, work_ms, inputs, outputs).


def build_local_app(
    *,
    identity_resolver: Callable[[], Any] = resolve_azure_cli_identity,
    test_fixtures: bool = False,
) -> Starlette:
    """Factory. uvicorn invokes this once at server start with ``--factory``."""
    dev_mode = os.environ.get(_DEV_ENV) == "1"
    local_entra = os.environ.get(_LOCAL_ENTRA_ENV) == "1"
    local_azure_cli = os.environ.get(_LOCAL_AZURE_CLI_ENV) == "1"
    if test_fixtures and "PYTEST_CURRENT_TEST" not in os.environ:
        raise RuntimeError("synthetic local fixtures are pytest-only")
    if not test_fixtures and (dev_mode or not (local_entra or local_azure_cli)):
        raise RuntimeError(
            "interactive local read API requires FDAI_READ_API_LOCAL_ENTRA=1 or "
            "FDAI_READ_API_LOCAL_AZURE_CLI=1; dev-mode and synthetic fallback are test-only"
        )
    if not test_fixtures and os.environ.get("FDAI_LOCAL_SCENARIO_REPLAY", "").strip() == "1":
        raise RuntimeError("interactive local scenario replay is not supported; use Azure evidence")
    if local_azure_cli and (dev_mode or local_entra):
        raise RuntimeError(
            f"{_LOCAL_AZURE_CLI_ENV} MUST NOT be combined with {_DEV_ENV} or {_LOCAL_ENTRA_ENV}"
        )
    if not dev_mode and not local_entra and not local_azure_cli:
        raise RuntimeError(
            f"fdai.delivery.read_api.dev.local requires {_DEV_ENV}=1 (auth bypassed) "
            f"or {_LOCAL_ENTRA_ENV}=1 (real Entra sign-in against seed data) or "
            f"{_LOCAL_AZURE_CLI_ENV}=1 (current az login user); this module is a "
            "local dev entrypoint and MUST NOT boot in production."
        )
    local_cli_identity = identity_resolver() if local_azure_cli else None
    read_model = InMemoryConsoleReadModel()
    if test_fixtures:
        _seed(read_model)
    group_mapping = _group_mapping_from_env()
    resolver = RoleResolver(group_mapping=group_mapping)
    # dev_mode (auth off) wins when both flags are set. Otherwise this is the
    # local real-login harness: verify genuine Entra access tokens against the
    # tenant JWKS (FDAI_ENTRA_TENANT_ID + FDAI_API_AUDIENCE required) while the
    # console still renders the in-memory seed above - so an engineer can drive
    # the full MSAL sign-in + App-Role gate locally without a live audit store.
    if dev_mode or local_azure_cli:
        authenticator = build_authenticator(
            verifier=UnsafeClaimsExtractor(),
            resolver=resolver,
        )
    else:
        authenticator = build_authenticator(
            verifier=EntraJwtVerifier.from_env(local_entra_verifier_environment()),
            resolver=resolver,
        )

    iam = build_local_iam_directory(
        group_mapping,
        use_graph=local_entra or local_azure_cli,
        application_id=entra_application_id_from_env(),
    )

    views = build_local_view_wiring(
        repo_root=_REPO_ROOT,
        read_model=read_model,
        include_test_fixtures=test_fixtures,
    )
    catalog = views.catalog
    ontology_object_types = catalog.object_types
    ontology_link_types = catalog.link_types
    action_types = catalog.action_types
    rule_catalog_rules = catalog.rules
    rule_catalog_collected = catalog.collected_rules
    policies_root = catalog.policies_root
    remediation_root = catalog.remediation_root
    rule_catalog_findings_provider = catalog.findings_provider
    rule_catalog_findings_summary_provider = catalog.findings_summary_provider
    built_in_workflows = catalog.workflows
    workflow_authoring = catalog.workflow_authoring

    trace_reader = ConsoleReadModelTraceReader(read_model)
    what_if_evaluators: dict[str, WhatIfEvaluator] = {
        "tighter-tags": _DemoTighterTagsEvaluator(),
    }

    user_context_group = views.user_context
    conversation_history_store = user_context_group.conversation_history_store
    conversation_policy_store = user_context_group.conversation_policy_store
    user_context_ontology_projector = user_context_group.ontology_projector
    user_context = user_context_group.routes
    workflow_definitions = user_context_group.workflow_definitions
    seed_user_workflow_ontology = user_context_group.seed_callback

    live_stream_config = None
    agent_activity_config = None
    runtime = None
    if test_fixtures:
        live_stream_config, agent_activity_config = _build_agent_streams()
        local_operator_oid = (
            local_cli_identity.principal.oid if local_cli_identity is not None else "dev-anon"
        )
        runtime = build_local_runtime_wiring(
            read_model=read_model,
            action_types=tuple(action_types),
            workflows=tuple(built_in_workflows),
            live_stream_config=live_stream_config,
            local_operator_oid=local_operator_oid,
            action_topic=_LOCAL_ACTION_TOPIC,
            repo_root=_REPO_ROOT,
        )
        agent_activity_config = replace(
            agent_activity_config,
            snapshot_factory=lambda: runtime_agent_state_snapshot(
                runtime.pantheon_runtime.health()
            ),
        )
    metering = InMemoryMeteringSink(
        initial=_synthetic_llm_invocations() if test_fixtures else (),
    )
    models = build_local_model_wiring(_REPO_ROOT, metering_sink=metering)

    async def open_narrator_endpoint() -> None:
        """Local-dev startup hook (on by default; disable with
        ``FDAI_NARRATOR_AUTO_OPEN_AOAI=0``): ensure the narrator's Azure OpenAI
        account allows this machine's IP so the CommandDeck LLM path is
        reachable instead of falling back to the deterministic answerer.
        Best-effort and fail-safe - see
        :mod:`fdai.delivery.read_api.dev.narrator_endpoint_access`."""
        from fdai.delivery.read_api.dev.narrator_endpoint_access import (
            ensure_narrator_endpoint_open,
        )

        await ensure_narrator_endpoint_open(models.backend)

    application = build_app(
        authenticator=authenticator,
        read_model=read_model,
        config=ReadApiConfig(
            dev_mode=dev_mode,
            local_cli_principal=(
                local_cli_identity.principal if local_cli_identity is not None else None
            ),
            local_cli_profile=(
                local_cli_identity.to_dict() if local_cli_identity is not None else None
            ),
            cors_allow_origins=_cors_origins_from_env(),
            live_stream=live_stream_config,
            provision_stream=ProvisionStreamConfig() if test_fixtures else None,
            agent_activity=agent_activity_config,
            blast_radius_graph=_build_blast_radius_graph() if test_fixtures else None,
            ontology_object_types=tuple(ontology_object_types),
            ontology_link_types=tuple(ontology_link_types),
            ontology_action_types=tuple(action_types),
            conversation_history_store=conversation_history_store,
            conversation_policy_store=conversation_policy_store,
            user_context_ontology_projector=user_context_ontology_projector,
            user_context=user_context,
            model_settings=models.settings,
            workflow_definitions=workflow_definitions,
            inventory_graph_provider=_build_inventory_graph_provider(),
            rule_catalog_rules=tuple(rule_catalog_rules),
            rule_catalog_collected_rules=tuple(rule_catalog_collected),
            rule_catalog_policies_root=policies_root if policies_root.is_dir() else None,
            rule_catalog_remediation_root=(remediation_root if remediation_root.is_dir() else None),
            rule_catalog_findings_provider=rule_catalog_findings_provider,
            rule_catalog_findings_summary_provider=rule_catalog_findings_summary_provider,
            promotion_gate_action_types=tuple(action_types) if test_fixtures else (),
            promotion_gate_source=(
                InMemoryShadowVerdictSource(verdicts=_synthetic_verdicts())
                if test_fixtures
                else None
            ),
            scope_source=_build_scope_view() if test_fixtures else None,
            extra_panels=(
                (
                    ExampleFinOpsPanel(read_model),
                    AutonomyMeasurementPanel(read_model),
                    CapabilityCatalogPanel(),
                    OperatorMemoryPanel(
                        service=OperatorMemoryReviewService(store=InMemoryOperatorMemoryStore()),
                        compactions=InMemoryMemoryCompactionRepository(),
                    ),
                    SchedulerRunsPanel(
                        service=ScheduleRunHistoryService(ledger=InMemoryScheduleRunLedger()),
                        source="synthetic-dev",
                        durable=False,
                    ),
                    OnboardingPanel(probe=EmptyResourceProbe(), configured=False),
                    LlmCostPanel(
                        metering,
                        source="synthetic-dev",
                    ),
                )
                if test_fixtures
                else ()
            ),
            trace_reader=trace_reader if test_fixtures else None,
            bitemporal_reader=trace_reader if test_fixtures else None,
            what_if_reader=trace_reader if test_fixtures else None,
            what_if_evaluators=what_if_evaluators if test_fixtures else {},
            chat=models.backend,
            chat_web_search=models.web_search,
            chat_probe_interval_seconds=_chat_probe_interval_seconds(),
            chat_agent_delegate=(
                PantheonChatDelegate(runtime.pantheon_runtime) if runtime is not None else None
            ),
            console_action=runtime.console_action if runtime is not None else None,
            iam_access=AccessRequestService(store=InMemoryStateStore()),
            iam_directory=iam.directory,
            iam_role_group_ids=iam.role_group_ids,
            expose_pantheon=True,
            stewardship_map=_build_stewardship_map() if test_fixtures else None,
            workflow_authoring=workflow_authoring,
            workflow_execution=views.workflow_execution if test_fixtures else None,
            python_tasks=runtime.python_tasks if runtime is not None else None,
            reporting=views.reporting if test_fixtures else None,
            process_views=views.process_views if test_fixtures else None,
            startup_callbacks=(seed_user_workflow_ontology, open_narrator_endpoint)
            + ((runtime.start_pantheon_runtime,) if runtime is not None else ())
            + (
                (runtime.operator_runtime.start,)
                if runtime is not None and runtime.operator_runtime is not None
                else ()
            ),
            shutdown_callbacks=((runtime.stop_pantheon_runtime,) if runtime is not None else ())
            + (
                (runtime.operator_runtime.stop,)
                if runtime is not None and runtime.operator_runtime is not None
                else ()
            )
            + iam.shutdown_callbacks,
        ),
    )
    application.state.pantheon_runtime = runtime.pantheon_runtime if runtime is not None else None
    application.state.local_operator_runtime = (
        runtime.operator_runtime if runtime is not None else None
    )
    return application


__all__ = [
    "_build_agent_streams",
    "_build_chat_backend",
    "_build_chat_web_search",
    "_build_inventory_graph_provider",
    "_build_live_stream_config",
    "_build_stewardship_map",
    "_chat_probe_interval_seconds",
    "_cors_origins_from_env",
    "_group_mapping_from_env",
    "build_local_app",
]
