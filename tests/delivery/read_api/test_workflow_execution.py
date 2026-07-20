"""Shadow workflow command route and Process journal integration."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from fdai.core.notifications.matrix import load_matrix_from_mapping
from fdai.core.rbac.resolver import GroupMapping, Principal, RoleResolver
from fdai.core.rbac.roles import Role
from fdai.core.reporting.models import RenderedReport
from fdai.core.views import ViewEngine
from fdai.core.workflow.approval import WorkflowApprovalPlanner
from fdai.core.workflow.orchestrator import WorkflowOrchestrator
from fdai.delivery.read_api.auth import build_authenticator
from fdai.delivery.read_api.main import ReadApiConfig, build_app
from fdai.delivery.read_api.read_model import InMemoryConsoleReadModel
from fdai.delivery.read_api.routes.process_views import ProcessViewsConfig
from fdai.delivery.read_api.routes.workflow_execution import (
    WorkflowExecutionConfig,
    make_workflow_run_route,
)
from fdai.shared.contracts.models import (
    Mode,
    OntologyActionType,
    Operation,
    PromotionGate,
    RollbackKind,
    Workflow,
    WorkflowStep,
    WorkflowTrigger,
    WorkflowTriggerKind,
)
from fdai.shared.providers.testing import InMemoryProcessRuntimeStore, InMemoryStateStore

_TRIGGER_TS = datetime(2026, 7, 15, 9, 30, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _dev_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FDAI_READ_API_DEV_MODE", "1")


class _Reports:
    async def render(self, report_id: str, *, variables: dict[str, str]) -> RenderedReport:
        raise AssertionError("generic process journal MUST NOT render a report")


def _workflow() -> Workflow:
    return Workflow(
        schema_version="1.0.0",
        name="sample-flow",
        version="1.0.0",
        trigger=WorkflowTrigger(
            kind=WorkflowTriggerKind.SIGNAL,
            signal_type="object.drift",
        ),
        default_mode=Mode.SHADOW,
        promotion_gate=PromotionGate(
            min_shadow_days=14,
            min_samples=100,
            min_accuracy=0.95,
            max_policy_escapes=0,
        ),
        steps=[WorkflowStep(id="inspect", action_type_ref="ops.inspect")],
    )


class _Dispatcher:
    async def dispatch(self, **_kwargs: object) -> str:
        return "proposal-1"


def _client(
    *,
    role: Role = Role.CONTRIBUTOR,
    enforce_workflows: frozenset[str] = frozenset(),
) -> TestClient:
    action = OntologyActionType(
        schema_version="1.0.0",
        name="ops.inspect",
        version="1.0.0",
        operation=Operation.RESTART,
        rollback_contract=RollbackKind.STATE_FORWARD_ONLY,
        default_mode=Mode.SHADOW,
        promotion_gate=PromotionGate(
            min_shadow_days=14,
            min_samples=100,
            min_accuracy=0.95,
            max_policy_escapes=0,
        ),
        description="Inspect a target in shadow.",
    )
    actions = {action.name: action}
    store = InMemoryProcessRuntimeStore()
    group_mapping = GroupMapping(
        reader_group_id="readers",
        contributor_group_id="contributors",
        approver_group_id="approvers",
        owner_group_id="owners",
        break_glass_group_id="break-glass",
    )
    planner = WorkflowApprovalPlanner(
        action_types=actions,
        group_mapping=group_mapping,
        matrix=load_matrix_from_mapping(
            {
                "matrix": {
                    "version": 1,
                    "default_route": "hil_approval",
                    "routes": {
                        "hil_approval": {
                            "trust_tier": "a1_hil_approval",
                            "primary": "teams-hil-prd",
                            "fallback": [],
                        }
                    },
                }
            }
        ),
    )
    workflow = _workflow()
    orchestrator = WorkflowOrchestrator(
        planner=planner,
        action_types=actions,
        audit_store=InMemoryStateStore(),
        process_store=store,
        action_dispatcher=_Dispatcher(),
    )
    engine = ViewEngine(specs=(), reports=_Reports(), processes=store)  # type: ignore[arg-type]
    auth = build_authenticator(
        verifier=lambda token: {"oid": "operator", "roles": [role.value]},
        resolver=RoleResolver(group_mapping=group_mapping),
    )
    app = build_app(
        authenticator=auth,
        read_model=InMemoryConsoleReadModel(),
        config=ReadApiConfig(
            dev_mode=True,
            workflow_execution=WorkflowExecutionConfig(
                workflows=(workflow,),
                orchestrator=orchestrator,
                enforce_workflows=enforce_workflows,
            ),
            process_views=ProcessViewsConfig(engine=engine),
        ),
    )
    return TestClient(app)


def _enforce_client(*, role: Role, enforce_workflows: frozenset[str]) -> TestClient:
    action = OntologyActionType(
        schema_version="1.0.0",
        name="ops.inspect",
        version="1.0.0",
        operation=Operation.RESTART,
        rollback_contract=RollbackKind.STATE_FORWARD_ONLY,
        default_mode=Mode.SHADOW,
        promotion_gate=PromotionGate(
            min_shadow_days=14,
            min_samples=100,
            min_accuracy=0.95,
            max_policy_escapes=0,
        ),
        description="Inspect a target in shadow.",
    )
    actions = {action.name: action}
    orchestrator = WorkflowOrchestrator(
        planner=WorkflowApprovalPlanner(
            action_types=actions,
            group_mapping=GroupMapping(
                reader_group_id="readers",
                contributor_group_id="contributors",
                approver_group_id="approvers",
                owner_group_id="owners",
                break_glass_group_id="break-glass",
            ),
            matrix=load_matrix_from_mapping(
                {
                    "matrix": {
                        "version": 1,
                        "default_route": "hil_approval",
                        "routes": {
                            "hil_approval": {
                                "trust_tier": "a1_hil_approval",
                                "primary": "teams-hil-prd",
                                "fallback": [],
                            }
                        },
                    }
                }
            ),
        ),
        action_types=actions,
        audit_store=InMemoryStateStore(),
        process_store=InMemoryProcessRuntimeStore(),
        action_dispatcher=_Dispatcher(),
    )

    async def authorize(_request):  # type: ignore[no-untyped-def]
        return Principal(oid="operator", roles=frozenset({role}))

    route = make_workflow_run_route(
        config=WorkflowExecutionConfig(
            workflows=(_workflow(),),
            orchestrator=orchestrator,
            enforce_workflows=enforce_workflows,
        ),
        authorize_principal=authorize,
    )
    return TestClient(Starlette(routes=[route]))


def test_shadow_command_creates_process_visible_through_journal() -> None:
    client = _client()

    run = client.post(
        "/workflows/run",
        json={
            "workflow": "sample-flow",
            "target_resource_id": "resource-1",
            "trigger_ts": _TRIGGER_TS.isoformat(),
        },
    )

    assert run.status_code == 200
    body = run.json()
    assert body["process"]["status"] == "succeeded"
    assert body["process"]["mode"] == "shadow"
    journal = client.get(body["links"]["events"])
    assert journal.status_code == 200
    assert journal.json()["process"]["workflow_ref"] == "sample-flow"
    assert journal.json()["events"][-1]["kind"] == "process.completed"


def test_shadow_command_is_idempotent_for_same_trigger() -> None:
    client = _client()
    payload = {
        "workflow": "sample-flow",
        "target_resource_id": "resource-1",
        "trigger_ts": _TRIGGER_TS.isoformat(),
    }

    first = client.post("/workflows/run", json=payload)
    second = client.post("/workflows/run", json=payload)

    assert first.json()["process"]["id"] == second.json()["process"]["id"]
    assert second.json()["process"]["replayed"] is True


def test_shadow_command_rejects_unknown_workflow_and_bad_context() -> None:
    client = _client()

    missing = client.post(
        "/workflows/run",
        json={"workflow": "missing", "target_resource_id": "resource-1"},
    )
    bad_context = client.post(
        "/workflows/run",
        json={
            "workflow": "sample-flow",
            "target_resource_id": "resource-1",
            "context": {"attempt": 1},
        },
    )

    assert missing.status_code == 404
    assert bad_context.status_code == 400


def test_owner_may_start_allowlisted_enforce_workflow() -> None:
    client = _enforce_client(
        role=Role.OWNER,
        enforce_workflows=frozenset({"sample-flow"}),
    )

    response = client.post(
        "/workflows/run",
        json={
            "workflow": "sample-flow",
            "target_resource_id": "resource-1",
            "trigger_ts": _TRIGGER_TS.isoformat(),
            "mode": "enforce",
        },
    )

    assert response.status_code == 200
    assert response.json()["process"]["mode"] == "enforce"
    assert response.json()["step_results"][0]["reason"] == "action_proposal_dispatched"


def test_enforce_workflow_requires_owner_and_allowlist() -> None:
    contributor = _enforce_client(
        role=Role.CONTRIBUTOR,
        enforce_workflows=frozenset({"sample-flow"}),
    )
    owner_without_allowlist = _enforce_client(
        role=Role.OWNER,
        enforce_workflows=frozenset(),
    )
    payload = {
        "workflow": "sample-flow",
        "target_resource_id": "resource-1",
        "trigger_ts": _TRIGGER_TS.isoformat(),
        "mode": "enforce",
    }

    assert contributor.post("/workflows/run", json=payload).status_code == 403
    assert owner_without_allowlist.post("/workflows/run", json=payload).status_code == 409
