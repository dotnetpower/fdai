"""Current H10 production binders and expiring scoped projections with no live providers."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fdai.core.human_assignment.request_intake import AssignmentRequestIntake
from fdai.delivery.identity.scoped_duty_catalog import FileScopedDutyCatalog
from fdai.runtime.assignment_transport import build_assignment_transport
from fdai.runtime.scoped_duties import build_scoped_duty_processor, build_scoped_duty_projection
from fdai.runtime.scoped_duty_projection import (
    SCOPED_OBSERVATION_KEY,
    ScopedDutyProjectionPublisher,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts.scoped_duty import ScopedDutyRequest
from tests.core.human_assignment.test_scoped_duty_cases import (
    REQUESTER,
    SECOND,
    command,
    request,
    review,
)
from tests.core.human_assignment.test_scoped_duty_cases import runtime as runtime
from tests.core.human_assignment.test_scoped_duty_ownership import delivery

ROOT = Path(__file__).resolve().parents[4]
AT = datetime(2026, 9, 14, 12, tzinfo=UTC)


def config(tmp_path):
    path = tmp_path / "scoped.json"
    path.write_text(
        json.dumps({"schema_version": "1.0.0", "scopes": ["scope:example"], "shifts": []})
    )
    return {
        "FDAI_SCOPED_DUTY_CATALOG_PATH": str(path),
        "FDAI_STATE_STORE_DSN": "postgresql://example",
        "FDAI_RBAC_OWNERS_GROUP_ID": "00000000-0000-0000-0000-000000000008",
    }


async def test_production_transport_binds_current_sources_without_construction_io(tmp_path):
    environment = config(tmp_path)
    identity = SimpleNamespace(
        get_token=AsyncMock(side_effect=AssertionError("token during startup"))
    )
    store = InMemoryStateStore()
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: pytest.fail("network during startup"))
    ) as client:
        transport = build_assignment_transport(
            store=store,
            environment=environment,
            catalog_root=ROOT / "rule-catalog",
            http_client=client,
            identity=identity,
        )
        assert transport is not None and transport.scoped is not None
        assert transport.workflow.materializer.scoped is transport.scoped
        assert isinstance(transport.scoped.cases.planner.scopes, FileScopedDutyCatalog)
        assert transport.scoped.cases.owners.directory.roster_cache_seconds == 0
        assert transport.scoped.cases.owners.directory.max_attempts == 1
        assert transport.scoped.cases.owners.role_group_ids.keys() == {"Owner"}
        identity.get_token.assert_not_awaited()


async def test_missing_catalog_does_not_invent_a_source_but_partial_binding_fails(tmp_path):
    intake = AssignmentRequestIntake(InMemoryStateStore(), InMemoryStateStore())
    assert (
        build_scoped_duty_processor(
            intake=intake, environment={}, catalog_root=None, http_client=None, identity=None
        )
        is None
    )
    with pytest.raises(ValueError, match="bindings"):
        build_scoped_duty_processor(
            intake=intake,
            environment=config(tmp_path),
            catalog_root=None,
            http_client=None,
            identity=None,
        )


async def test_catalog_available_without_git_publisher_and_is_expiring(tmp_path):
    intake = AssignmentRequestIntake(InMemoryStateStore(), InMemoryStateStore())
    environment = config(tmp_path)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: pytest.fail("network"))
    ) as client:
        processor = build_scoped_duty_processor(
            intake=intake,
            environment=environment,
            catalog_root=ROOT / "rule-catalog",
            http_client=client,
            identity=SimpleNamespace(get_token=AsyncMock()),
            clock=lambda: AT,
        )
        projection = build_scoped_duty_projection(
            processor=processor,
            environment=environment,
            http_client=client,
            publisher=None,
            locks=SimpleNamespace(distributed=True),
        )
        assert projection is not None and projection.ownership is None
        await projection.publish()
        record = await intake.store.read_state(SCOPED_OBSERVATION_KEY)
        assert record["scopes"] == ["scope:example"] and record["items"] == []
        assert (
            record["artifact_delivery_available"] is False
            and record["execution_authority"] is False
        )
        assert datetime.fromisoformat(record["expires_at"]) == AT + timedelta(seconds=60)


async def fixture_projection(runtime, tmp_path):
    environment = config(tmp_path)
    catalog = FileScopedDutyCatalog(Path(environment["FDAI_SCOPED_DUTY_CATALOG_PATH"]))
    revision = catalog.validate().revision
    service, time, owners = runtime
    service = replace(service, planner=replace(service.planner, scopes=catalog))
    intent = ScopedDutyRequest.model_validate(
        {**request().model_dump(), "source_revision": revision}
    )
    case = await service.create(
        actor=REQUESTER,
        idempotency_key="example-scoped-case",
        request=intent,
        justification="Review explicit scoped operational coverage.",
        command=command(1 << 240),
        accepted_at=AT,
    )
    case = await service.submit(
        case_id=case.case_id,
        actor=REQUESTER,
        expected_revision=case.revision,
        command=command(2 << 240),
        accepted_at=AT,
    )
    case = await review(service, case)
    case = await review(service, case, actor=SECOND, number=4)
    owner = delivery((service, time, owners))
    opened = await owner.open_proposal(case.case_id, expected_revision=case.revision)
    projection = ScopedDutyProjectionPublisher(service, catalog, owner)
    return projection, opened


async def test_exact_scope_projection_withdraws_on_lost_merge_source(runtime, tmp_path):
    projection, opened = await fixture_projection(runtime, tmp_path)
    await projection.publish()
    record = await projection.cases.store.read_state(SCOPED_OBSERVATION_KEY)
    assert record["items"][0]["state"] == "observed"
    projection.ownership.merges.read.side_effect = None
    projection.ownership.merges.read.return_value = None
    await projection.publish()
    record = await projection.cases.store.read_state(SCOPED_OBSERVATION_KEY)
    assert record["items"][0]["state"] == "held" and not record["items"][0]["primary_refs"]
    assert await projection.cases.get(opened.case_id) == opened


async def test_catalog_revision_mismatch_cannot_stamp_other_source_as_current(runtime, tmp_path):
    projection, _ = await fixture_projection(runtime, tmp_path)
    await projection.publish()
    projection.catalog.path.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "scopes": ["scope:example", "scope:other"],
                "shifts": [],
            }
        )
    )
    await projection.publish()
    record = await projection.cases.store.read_state(SCOPED_OBSERVATION_KEY)
    assert record["items"][0]["state"] == "held"


async def test_partial_scan_and_malformed_cases_never_prove_scope_coverage(
    runtime, tmp_path, monkeypatch
):
    projection, opened = await fixture_projection(runtime, tmp_path)
    original = projection.cases.store.read_state_page

    async def partial(*args, **kwargs):
        rows, count = await original(*args, **kwargs)
        return rows, count + 20

    with monkeypatch.context() as patch:
        patch.setattr(projection.cases.store, "read_state_page", partial)
        await projection.publish()
    record = await projection.cases.store.read_state(SCOPED_OBSERVATION_KEY)
    assert record["partial"] is True and record["items"][0]["state"] == "held"
    await projection.cases.store.write_state(
        "human_assignment:scoped-case:invalid", {"revision": 1}
    )
    await projection.publish()
    record = await projection.cases.store.read_state(SCOPED_OBSERVATION_KEY)
    assert record["invalid_cases"] == 1 and record["items"][0]["state"] == "held"


async def test_projection_audit_failure_cannot_refresh_prior_observation(
    runtime, tmp_path, monkeypatch
):
    projection, _ = await fixture_projection(runtime, tmp_path)
    monkeypatch.setattr(
        projection.cases.store,
        "write_state_with_audit_if_absent",
        AsyncMock(side_effect=RuntimeError("audit failed")),
    )
    with pytest.raises(RuntimeError):
        await projection.publish()
    assert await projection.cases.store.read_state(SCOPED_OBSERVATION_KEY) is None


async def test_late_catalog_read_does_not_publish_expired_positive_rows(
    runtime, tmp_path, monkeypatch
):
    from fdai.core.human_assignment.scoped_duty_ownership import ScopedDutyOwnership

    projection, _ = await fixture_projection(runtime, tmp_path)
    original = FileScopedDutyCatalog.snapshot
    observed = ScopedDutyOwnership.observe
    armed = False

    async def observe_merge(self, case):
        nonlocal armed
        rows = await observed(self, case)
        assert rows
        armed = True
        return rows

    async def slow_catalog(self):
        result = await original(self)
        if armed:
            runtime[1]["now"] = AT + timedelta(seconds=60)
        return result

    monkeypatch.setattr(ScopedDutyOwnership, "observe", observe_merge)
    monkeypatch.setattr(FileScopedDutyCatalog, "snapshot", slow_catalog)
    await projection.publish()
    record = await projection.cases.store.read_state(SCOPED_OBSERVATION_KEY)
    assert record["observed_at"] == runtime[1]["now"].isoformat()
    assert all(row["state"] != "observed" for row in record["items"])


async def test_pending_new_request_cannot_withdraw_previously_observed_ownership(runtime, tmp_path):
    projection, old = await fixture_projection(runtime, tmp_path)
    await projection.publish()
    service = projection.cases
    candidate = await service.create(
        actor=REQUESTER,
        idempotency_key="new-unreviewed",
        request=old.request,
        justification="Propose another current scoped duty plan.",
        command=command(5 << 240),
        accepted_at=AT,
    )
    await service.submit(
        case_id=candidate.case_id,
        actor=REQUESTER,
        expected_revision=1,
        command=command(6 << 240),
        accepted_at=AT,
    )
    await projection.publish()
    record = await service.store.read_state(SCOPED_OBSERVATION_KEY)
    assert record["items"][0]["state"] == "observed"
    assert record["items"][0]["case_id"] == old.case_id


async def test_verified_successor_retires_old_case_without_automatic_reactivation(
    runtime, tmp_path
):
    projection, old = await fixture_projection(runtime, tmp_path)
    await projection.publish()
    service = projection.cases
    new_request = ScopedDutyRequest.model_validate(
        {
            **old.request.model_dump(),
            "supersedes_case_id": old.case_id,
        }
    )
    current = await service.create(
        actor=REQUESTER,
        idempotency_key="reviewed-successor",
        request=new_request,
        justification="Replace the previous exact scoped duty plan.",
        command=command(5 << 240),
        accepted_at=AT,
    )
    current = await service.submit(
        case_id=current.case_id,
        actor=REQUESTER,
        expected_revision=1,
        command=command(6 << 240),
        accepted_at=AT,
    )
    current = await review(service, current, number=7)
    current = await review(service, current, actor=SECOND, number=8)
    current = await projection.ownership.open_proposal(
        current.case_id, expected_revision=current.revision
    )
    await projection.publish()
    record = await service.store.read_state(SCOPED_OBSERVATION_KEY)
    assert record["items"][0]["case_id"] == current.case_id
    assert record["superseded_case_ids"] == [old.case_id]
    projection.ownership.merges.read.side_effect = None
    projection.ownership.merges.read.return_value = None
    await projection.publish()
    record = await service.store.read_state(SCOPED_OBSERVATION_KEY)
    assert record["items"][0]["state"] == "held"
    assert not record["items"][0]["primary_refs"]
    assert record["superseded_case_ids"] == [old.case_id]
