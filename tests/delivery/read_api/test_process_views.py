"""Read-only dynamic Process view routes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import cast

import pytest
from starlette.responses import Response
from starlette.routing import Route
from starlette.testclient import TestClient

from fdai.core.rbac.resolver import GroupMapping, RoleResolver
from fdai.core.reporting.engine import ReportEngine
from fdai.core.reporting.models import RenderedReport
from fdai.core.views import ViewAppliesTo, ViewEngine, ViewRegion, ViewSpec
from fdai.delivery.read_api.auth import build_authenticator
from fdai.delivery.read_api.main import ReadApiConfig, build_app
from fdai.delivery.read_api.read_model import InMemoryConsoleReadModel
from fdai.delivery.read_api.routes.dynamic_views import validate_route_method_collisions
from fdai.delivery.read_api.routes.process_views import ProcessViewsConfig
from fdai.shared.providers.process_runtime import (
    ProcessEvent,
    ProcessEventKind,
    ProcessSnapshot,
    ProcessStatus,
)
from fdai.shared.providers.testing import InMemoryProcessRuntimeStore

_NOW = datetime(2026, 7, 13, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _dev_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FDAI_READ_API_DEV_MODE", "1")


class _Reports:
    async def render(self, report_id: str, *, variables: dict[str, str]) -> RenderedReport:
        return RenderedReport(
            id=report_id,
            version="1.0.0",
            name="Review",
            description="",
            generated_at=_NOW,
            time_range=(_NOW - timedelta(days=1), _NOW),
            variables=variables,
            widgets=(),
        )


class _BrokenReports:
    async def render(self, report_id: str, *, variables: dict[str, str]) -> RenderedReport:
        raise KeyError("renderer defect")


async def _process_store() -> InMemoryProcessRuntimeStore:
    store = InMemoryProcessRuntimeStore()
    await store.create(
        snapshot=ProcessSnapshot(
            process_id="process-1",
            workflow_ref="architecture-review",
            workflow_version="1.0.0",
            status=ProcessStatus.WAITING,
            current_step="evidence",
            target_resource_id="scope-1",
            started_at=_NOW,
            updated_at=_NOW,
            correlation_id="corr-1",
        ),
        event=ProcessEvent(
            event_id="event-1",
            process_id="process-1",
            kind=ProcessEventKind.PROCESS_CREATED,
            idempotency_key="process-1:create",
            recorded_at=_NOW,
            correlation_id="corr-1",
        ),
    )
    return store


async def _client(
    *,
    reports: object | None = None,
    prefix: str = "/views/process",
    raise_server_exceptions: bool = True,
) -> TestClient:
    store = await _process_store()
    view = ViewSpec(
        id="architecture-review",
        version="1.0.0",
        name="Architecture Review",
        description="",
        route="/processes/{process_id}",
        applies_to=ViewAppliesTo(workflow_ref="architecture-review"),
        regions=(ViewRegion(id="review", report_ref="architecture-review-process"),),
    )
    engine = ViewEngine(
        specs=(view,),
        reports=cast(ReportEngine, reports or _Reports()),
        processes=store,
    )
    auth = build_authenticator(
        verifier=lambda token: {"oid": "u"},
        resolver=RoleResolver(
            group_mapping=GroupMapping(
                reader_group_id="readers",
                contributor_group_id="contributors",
                approver_group_id="approvers",
                owner_group_id="owners",
                break_glass_group_id="break-glass",
            )
        ),
    )
    app = build_app(
        authenticator=auth,
        read_model=InMemoryConsoleReadModel(),
        config=ReadApiConfig(
            dev_mode=True,
            process_views=ProcessViewsConfig(engine=engine, prefix=prefix),
        ),
    )
    return TestClient(app, raise_server_exceptions=raise_server_exceptions)


async def test_process_view_list_and_render() -> None:
    client = await _client()
    listing = client.get("/views/process?workflow_ref=architecture-review")
    rendered = client.get("/views/process/process-1")

    assert listing.status_code == 200
    assert listing.json()["items"][0]["has_view"] is True
    assert rendered.status_code == 200
    assert rendered.json()["process"]["current_step"] == "evidence"
    assert rendered.json()["regions"][0]["report"]["id"] == "architecture-review-process"


async def test_process_view_rejects_bad_or_missing_id() -> None:
    client = await _client()
    malformed = client.get("/views/process/%20")
    missing = client.get("/views/process/process-missing")
    bad_status = client.get("/views/process?status=not-a-status")

    assert malformed.status_code in {400, 404}
    assert missing.status_code == 404
    assert bad_status.status_code == 400


async def test_process_view_does_not_mask_renderer_key_error_as_not_found() -> None:
    client = await _client(reports=_BrokenReports(), raise_server_exceptions=False)

    response = client.get("/views/process/process-1")

    assert response.status_code == 500


async def test_process_view_prefix_collision_with_core_route_fails_fast() -> None:
    with pytest.raises(ValueError, match="collides with a core route"):
        await _client(prefix="/audit")


async def test_process_view_prefix_collision_with_optional_route_fails_fast() -> None:
    store = await _process_store()
    engine = ViewEngine(
        specs=(),
        reports=cast(ReportEngine, _Reports()),
        processes=store,
    )
    auth = build_authenticator(
        verifier=lambda token: {"oid": "u"},
        resolver=RoleResolver(
            group_mapping=GroupMapping(
                reader_group_id="readers",
                contributor_group_id="contributors",
                approver_group_id="approvers",
                owner_group_id="owners",
                break_glass_group_id="break-glass",
            )
        ),
    )
    with pytest.raises(ValueError, match="collides with an extra route"):
        build_app(
            authenticator=auth,
            read_model=InMemoryConsoleReadModel(),
            config=ReadApiConfig(
                dev_mode=True,
                expose_pantheon=True,
                process_views=ProcessViewsConfig(engine=engine, prefix="/pantheon/graph"),
            ),
        )


def test_route_collision_validator_checks_late_optional_routes_by_method() -> None:
    async def endpoint(_: object) -> Response:
        return Response()

    with pytest.raises(ValueError, match="method '.*' collides"):
        validate_route_method_collisions(
            [
                Route("/chat/health", endpoint, methods=["GET"]),
                Route("/chat/health", endpoint, methods=["GET"]),
            ]
        )

    validate_route_method_collisions(
        [
            Route("/chat", endpoint, methods=["GET"]),
            Route("/chat", endpoint, methods=["POST"]),
        ]
    )
