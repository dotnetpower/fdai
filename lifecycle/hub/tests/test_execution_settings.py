from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from fdai_lifecycle_hub import audit, models
from fdai_lifecycle_hub.api import create_app
from fdai_lifecycle_hub.domain import Installation, Issued, Planner
from fdai_lifecycle_hub.execution_settings import (
    ExecutionSettingsError,
    ExecutionSettingsRequest,
    WindowRequest,
)
from fdai_lifecycle_hub.schemas import maintenance_window_record
from fdai_lifecycle_hub.store import HubStore


def test_settings_digest_is_stable_across_python_hash_seeds() -> None:
    source = """
from fdai_lifecycle_hub.domain import Settings
from fdai_lifecycle_hub.execution_settings import settings_digest
print(settings_digest(Settings(
    channel="DEV", version_range="*", region="region-a", windows=(),
    allowed_regions=frozenset({"region-a", "region-b", "region-c", "region-d"}),
)))
"""
    results = [
        subprocess.run(  # noqa: S603 - fixed test interpreter and synthetic source
            [sys.executable, "-c", source],
            env={
                **os.environ,
                "PYTHONPATH": os.pathsep.join(sys.path),
                "PYTHONHASHSEED": seed,
            },
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        ).stdout.strip()
        for seed in ("1", "2", "123")
    ]
    assert len(set(results)) == 1
    assert len(results[0]) == 64


def command_body(store: HubStore, installation_id: str) -> dict[str, object]:
    digest = store.execution_settings(installation_id)["settings_digest"]
    return {
        "request_id": str(uuid4()),
        "expected_settings_digest": digest,
        "windows": [
            {
                "start": "00:00:00",
                "duration_minutes": 30,
                "timezone": "UTC",
                "allows_downtime": False,
            }
        ],
        "plan_duration_minutes": 20,
        "reason_code": "operator_schedule_change",
        "confirmation": f"update execution settings {installation_id} {digest}",
    }


def parse(body: dict[str, object]) -> ExecutionSettingsRequest:
    return ExecutionSettingsRequest.model_validate_json(json.dumps(body))


def test_update_changes_only_schedule_and_audits_once(
    enrolled_store: HubStore, installation: Installation, now: datetime
) -> None:
    store, identifier = enrolled_store, installation.installation_id
    with Session(store.engine) as session:
        row = session.get(models.Installation, identifier)
        assert row is not None
        before = dict(row.settings)
    command = parse(command_body(store, identifier))
    result = store.update_execution_settings(identifier, command, operator="owner", now=now)
    assert result["changed"] is True
    assert result["settings_digest"] == store.execution_settings(identifier)["settings_digest"]
    assert store.current_plan(identifier, now=now) is None
    with Session(store.engine) as session:
        row = session.get(models.Installation, identifier)
        assert row is not None
        changed = {key for key in before if before[key] != row.settings[key]}
        assert changed == {"windows", "plan_duration"}
        records = session.scalars(
            select(models.AuditRecord).where(
                models.AuditRecord.action == "installation.execution_settings_changed"
            )
        ).all()
        assert len(records) == 1
        assert records[0].payload["operator"] == "owner"
        assert records[0].payload["request_digest"] == command.digest
        assert audit.chain_intact(session)
    restarted = HubStore(store.engine)
    assert restarted.update_execution_settings(identifier, command, operator="owner", now=now) == {
        "changed": False,
        "settings_digest": result["settings_digest"],
    }


def test_schedule_persists_on_supported_backends(
    hub_store: HubStore,
    enroll: Callable[[HubStore, Installation], None],
    installation: Installation,
    now: datetime,
) -> None:
    enroll(hub_store, installation)
    identifier = installation.installation_id
    command = parse(command_body(hub_store, identifier))
    result = hub_store.update_execution_settings(identifier, command, operator="owner", now=now)
    restarted = HubStore(hub_store.engine)
    assert restarted.execution_settings(identifier)["settings_digest"] == result["settings_digest"]
    assert restarted.load(identifier).configuration == installation.configuration
    assert restarted.update_execution_settings(identifier, command, operator="owner", now=now) == {
        "changed": False,
        "settings_digest": result["settings_digest"],
    }


@pytest.mark.integration
def test_postgres_serializes_competing_schedule_changes(
    hub_store: HubStore,
    enroll: Callable[[HubStore, Installation], None],
    installation: Installation,
    now: datetime,
) -> None:
    if hub_store.engine.dialect.name != "postgresql":
        pytest.skip("Concurrent row locking requires PostgreSQL.")
    enroll(hub_store, installation)
    identifier = installation.installation_id
    first, second = command_body(hub_store, identifier), command_body(hub_store, identifier)
    second["plan_duration_minutes"] = 25

    def update(body: dict[str, object]) -> dict[str, object]:
        try:
            return HubStore(hub_store.engine).update_execution_settings(
                identifier, parse(body), operator="owner", now=now
            )
        except ExecutionSettingsError as error:
            return {"error": str(error)}

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(update, [first, second]))
    assert sum(result.get("changed") is True for result in results) == 1
    assert {"error": "execution_settings_revision_conflict"} in results
    with Session(hub_store.engine) as session:
        assert (
            len(
                session.scalars(
                    select(models.AuditRecord).where(
                        models.AuditRecord.action == "installation.execution_settings_changed"
                    )
                ).all()
            )
            == 1
        )
        assert audit.chain_intact(session)


@pytest.mark.parametrize("seconds", [60.000001, 90.5, 86399.999999])
def test_window_projection_preserves_subminute_precision(seconds: float) -> None:
    request = WindowRequest.model_validate_json(
        json.dumps({"start": "00:00:00", "duration_minutes": seconds / 60, "timezone": "UTC"})
    )
    window = request.to_window()
    assert window.duration == timedelta(seconds=seconds)
    projected = maintenance_window_record(window)
    assert WindowRequest.model_validate_json(json.dumps(projected)).to_window() == window


def test_unchanged_schedule_is_audited_without_a_state_write(
    enrolled_store: HubStore, installation: Installation, now: datetime
) -> None:
    store, identifier = enrolled_store, installation.installation_id
    first = store.update_execution_settings(
        identifier, parse(command_body(store, identifier)), operator="owner", now=now
    )
    with Session(store.engine) as session:
        before = session.get(models.Installation, identifier)
        assert before is not None
        recorded_at = before.recorded_at
    result = store.update_execution_settings(
        identifier,
        parse(command_body(store, identifier)),
        operator="owner",
        now=now + timedelta(minutes=1),
    )
    assert result == {"changed": False, "settings_digest": first["settings_digest"]}
    with Session(store.engine) as session:
        after = session.get(models.Installation, identifier)
        assert after is not None
        assert after.recorded_at == recorded_at
        records = session.scalars(
            select(models.AuditRecord).where(
                models.AuditRecord.action == "installation.execution_settings_changed"
            )
        ).all()
        assert [record.payload["changed"] for record in records] == [True, False]
        assert audit.chain_intact(session)


def test_retry_returns_historical_digest_without_reverting_later_settings(
    enrolled_store: HubStore, installation: Installation, now: datetime
) -> None:
    store, identifier = enrolled_store, installation.installation_id
    first = parse(command_body(store, identifier))
    applied = store.update_execution_settings(identifier, first, operator="owner", now=now)
    next_body = command_body(store, identifier)
    next_body["plan_duration_minutes"] = 25
    second = store.update_execution_settings(
        identifier, parse(next_body), operator="owner", now=now
    )
    replay = store.update_execution_settings(identifier, first, operator="owner", now=now)
    assert replay == {"changed": False, "settings_digest": applied["settings_digest"]}
    assert store.execution_settings(identifier)["settings_digest"] == second["settings_digest"]


@pytest.mark.parametrize("different_actor", [False, True])
def test_retry_identity_cannot_be_reused_for_another_request_or_actor(
    enrolled_store: HubStore, installation: Installation, now: datetime, different_actor: bool
) -> None:
    store, identifier = enrolled_store, installation.installation_id
    body = command_body(store, identifier)
    store.update_execution_settings(identifier, parse(body), operator="owner", now=now)
    if not different_actor:
        body["plan_duration_minutes"] = 25
    before = store.execution_settings(identifier)
    with pytest.raises(ExecutionSettingsError, match="request_conflict"):
        store.update_execution_settings(
            identifier, parse(body), operator="other" if different_actor else "owner", now=now
        )
    assert store.execution_settings(identifier) == before


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("expected_settings_digest", "0" * 64, "revision_conflict"),
        ("confirmation", "update execution settings", "confirmation_mismatch"),
    ],
)
def test_stale_or_unconfirmed_requests_do_not_change_state(
    enrolled_store: HubStore,
    installation: Installation,
    now: datetime,
    field: str,
    value: str,
    reason: str,
) -> None:
    store, identifier = enrolled_store, installation.installation_id
    body = command_body(store, identifier)
    body[field] = value
    before = store.execution_settings(identifier)
    with pytest.raises(ExecutionSettingsError, match=reason):
        store.update_execution_settings(identifier, parse(body), operator="owner", now=now)
    assert store.execution_settings(identifier) == before


def test_pending_plan_blocks_schedule_changes(
    enrolled_store: HubStore, installation: Installation, planner: Planner, now: datetime
) -> None:
    store, identifier = enrolled_store, installation.installation_id
    command = parse(command_body(store, identifier))
    outcome = store.recompute(identifier, planner, now=now)
    assert isinstance(outcome, Issued)
    before = store.execution_settings(identifier)
    with pytest.raises(ExecutionSettingsError, match="plan_pending"):
        store.update_execution_settings(identifier, command, operator="owner", now=now)
    assert store.execution_settings(identifier) == before


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("plan_duration_minutes", 0),
        ("plan_duration_minutes", True),
        ("plan_duration_minutes", 1441),
        ("plan_duration_minutes", "30"),
        ("channel", "stable"),
        ("fencing_generation", 999),
        ("operator", "forged"),
        ("reason_code", ""),
        ("windows", [{"start": "00:00:00", "duration_minutes": 30, "timezone": "Unknown/Zone"}]),
        ("windows", [{"start": "00:00:00", "duration_minutes": 0, "timezone": "UTC"}]),
        ("windows", [{"start": "00:00:00", "duration_minutes": True, "timezone": "UTC"}]),
        ("windows", [{"start": "00:00:00", "duration_minutes": 1441, "timezone": "UTC"}]),
        ("windows", [{"start": "00:00:00+00:00", "duration_minutes": 30, "timezone": "UTC"}]),
        (
            "windows",
            [{"start": "00:00:00", "duration_minutes": 30, "timezone": "UTC", "authority": True}],
        ),
        ("windows", [{"start": "00:00:00", "duration_minutes": 30, "timezone": "UTC"}] * 33),
    ],
)
def test_input_bounds_and_unknown_fields_are_rejected(
    enrolled_store: HubStore, installation: Installation, field: str, value: object
) -> None:
    body = command_body(enrolled_store, installation.installation_id)
    body[field] = value
    with pytest.raises(ValidationError):
        parse(body)


def test_loopback_names_do_not_authorize_execution_settings(
    enrolled_store: HubStore, installation: Installation
) -> None:
    identifier = installation.installation_id
    with TestClient(create_app(enrolled_store)) as client:
        path = f"/v1/installations/{identifier}/execution-settings"
        assert client.get(path, headers={"X-Operator": "owner"}).status_code == 403
        assert (
            client.post(
                path,
                headers={"X-Operator": "owner"},
                json=command_body(enrolled_store, identifier),
            ).status_code
            == 403
        )
