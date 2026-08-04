from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.testclient import TestClient

from fdai.core.conversation import CreateScheduledTaskCommand, Principal, Role
from fdai.core.detection.configuration_drift import (
    ConfigurationDriftReport,
    ConfigurationResource,
    ConfigurationReviewCampaignService,
    DriftVerdict,
    FrozenConfigurationBaseline,
    KnowledgeGroundingStatus,
)
from fdai.core.scheduler.blueprints import (
    AutomationBlueprintReviewService,
    AutomationBlueprintState,
    InMemoryAutomationBlueprintStore,
)
from fdai.core.scheduler.store import InMemoryScheduleStore
from fdai.delivery.configuration_drift_report_store import (
    StateStoreConfigurationDriftReportStore,
)
from fdai.delivery.configuration_review_runtime import ConfigurationReviewRuntime
from fdai.delivery.configuration_review_store import (
    StateStoreConfigurationReviewCampaignStore,
)
from fdai.delivery.operator_api.routes.configuration_review import (
    make_configuration_review_routes,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_NOW = datetime(2026, 8, 4, tzinfo=UTC)
_BASELINE = FrozenConfigurationBaseline(
    version="v1",
    created_at=_NOW,
    scope="example-scope",
    source="reviewed snapshot",
    document_sha256="a" * 64,
    resources=(
        ConfigurationResource(
            local_name="service-a",
            resource_type="example/service",
            region="example-region",
        ),
    ),
)


class _BaselineSource:
    async def load(self) -> FrozenConfigurationBaseline:
        return _BASELINE


class _DriftService:
    async def run(self) -> ConfigurationDriftReport:
        return ConfigurationDriftReport(
            baseline_version=_BASELINE.version,
            baseline_sha256=_BASELINE.sha256,
            scope=_BASELINE.scope,
            observed_at=_NOW,
            verdict=DriftVerdict.PASSED,
            findings=(),
            knowledge_status=KnowledgeGroundingStatus.CITED,
            knowledge_citations=("knowledge:baseline:v1#digest#0",),
        )


class _BlueprintAuthorizer:
    def can_review(self, principal: Principal) -> bool:
        return principal.role in {Role.APPROVER, Role.OWNER}


class _Audit:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def append(self, event: Mapping[str, Any]) -> None:
        self.events.append(dict(event))


def _runtime() -> tuple[
    ConfigurationReviewRuntime,
    AutomationBlueprintReviewService,
    InMemoryAutomationBlueprintStore,
    InMemoryScheduleStore,
    InMemoryStateStore,
]:
    state_store = InMemoryStateStore()
    blueprints = InMemoryAutomationBlueprintStore()
    schedules = InMemoryScheduleStore()
    blueprint_service = AutomationBlueprintReviewService(
        store=blueprints,
        authorizer=_BlueprintAuthorizer(),
        audit=_Audit(),
        schedule_command=CreateScheduledTaskCommand(store=schedules),
    )
    campaigns = ConfigurationReviewCampaignService(
        StateStoreConfigurationReviewCampaignStore(state_store, clock=lambda: _NOW),
        StateStoreConfigurationDriftReportStore(state_store, clock=lambda: _NOW),
    )
    return (
        ConfigurationReviewRuntime(
            baseline_source=_BaselineSource(),
            drift_service=_DriftService(),
            campaigns=campaigns,
            blueprints=blueprint_service,
        ),
        blueprint_service,
        blueprints,
        schedules,
        state_store,
    )


async def test_three_runs_submit_inert_blueprint_then_independent_review_materializes() -> None:
    runtime, blueprint_service, blueprints, schedules, state_store = _runtime()
    for index in range(1, 4):
        result = await runtime.run(
            principal_id="operator-1",
            run_id=f"run-{index}",
            now=_NOW,
        )

    assert result.campaign.state.value == "ready-for-weekly"
    assert result.blueprint is not None
    assert result.blueprint.state is AutomationBlueprintState.DRAFT
    assert result.blueprint.enabled is False
    assert result.blueprint.shadow_only is True
    assert result.blueprint.mutation_tool_ids == ()
    assert len(result.blueprint.evidence_fingerprints) == 3
    assert await schedules.list_all() == ()

    approver = Principal(id="approver-1", role=Role.APPROVER)
    accepted = await blueprint_service.review(
        result.blueprint.candidate_id,
        principal=approver,
        approve=True,
        reason="Three exact evidence runs passed.",
        at=_NOW,
    )
    materialized = await blueprint_service.materialize(
        accepted.candidate_id,
        principal=approver,
        at=_NOW,
    )
    tasks = await schedules.list_all()

    assert materialized.state is AutomationBlueprintState.MATERIALIZED
    assert len(tasks) == 1
    assert tasks[0].event_type == "configuration.drift.check.requested"
    assert tasks[0].cron_expression == "0 9 * * 1"
    assert tasks[0].event_payload["shadow_only"] is True
    assert await state_store.verify_chain()
    assert len(await blueprints.list_all()) == 1


def test_review_run_route_requires_idempotency_key_and_records_one_run() -> None:
    runtime, _review, _blueprints, _schedules, _state = _runtime()

    async def authorize(_request: Request) -> Principal:
        return Principal(id="operator-1", role=Role.CONTRIBUTOR)

    app = Starlette(
        routes=list(make_configuration_review_routes(runtime=runtime, authorize=authorize))
    )
    with TestClient(app) as client:
        missing = client.post("/configuration-baselines/review/run")
        recorded = client.post(
            "/configuration-baselines/review/run",
            headers={"Idempotency-Key": "run-1"},
        )
        duplicate = client.post(
            "/configuration-baselines/review/run",
            headers={"Idempotency-Key": "run-1"},
        )

    assert missing.status_code == 400
    assert recorded.status_code == 200
    assert recorded.json()["completed_runs"] == 1
    assert duplicate.json()["completed_runs"] == 1
