"""Read-only dynamic Process view routes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import cast

import pytest
from starlette.testclient import TestClient

from fdai.core.rbac.resolver import GroupMapping, RoleResolver
from fdai.core.reporting.engine import ReportEngine
from fdai.core.reporting.models import RenderedReport
from fdai.core.views import ViewAppliesTo, ViewEngine, ViewRegion, ViewSpec
from fdai.delivery.read_api.auth import build_authenticator
from fdai.delivery.read_api.main import ReadApiConfig, build_app
from fdai.delivery.read_api.read_model import InMemoryConsoleReadModel
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


async def _client() -> TestClient:
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
    app = build_app(
        authenticator=auth,
        read_model=InMemoryConsoleReadModel(),
        config=ReadApiConfig(
            dev_mode=True,
            process_views=ProcessViewsConfig(engine=engine),
        ),
    )
    return TestClient(app)


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