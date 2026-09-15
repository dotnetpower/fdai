"""Task-only SQL proof for scoped immutable outbox, Core ownership, and revision delivery."""

from __future__ import annotations

import json
import runpy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import psycopg
import pytest
from fdai.core.human_assignment.request_intake import AssignmentRequestIntake
from fdai.core.human_assignment.request_processor import AssignmentRequestProcessor
from fdai.core.human_assignment.scoped_duties import DutyResolution, ScopedDutyPolicy
from fdai.core.human_assignment.scoped_duty_case_service import ScopedDutyCaseService
from fdai.core.human_assignment.scoped_duty_planning import ScopedDutyPlanner
from fdai.core.human_assignment.scoped_duty_requests import ScopedDutyRequestProcessor
from fdai.core.human_assignment.service import AssignmentCaseService
from fdai.delivery.identity.scoped_duty_catalog import FileScopedDutyCatalog
from fdai.delivery.persistence.postgres import PostgresStateStore, PostgresStateStoreConfig
from fdai.delivery.persistence.postgres_assignment_receipts import PostgresAssignmentReceiptReader
from fdai_operator_service.assignment_notice import assignment_notice_from_record
from fdai_operator_service.families.iam.contracts import IamPrincipal
from fdai_operator_service.postgres_assignment_outbox import PostgresAssignmentOutbox
from fdai_operator_service.postgres_family_store import (
    PostgresFamilyStore,
    PostgresFamilyStoreConfig,
)
from fdai_operator_service.postgres_iam import PostgresIamAdapters
from fdai_operator_service.postgres_scoped_duties import PostgresScopedDuties
from fdai_service_contracts import OperatorRole
from fdai_service_contracts.scoped_duty import ScopedDutyRequest

_support = runpy.run_path(str(Path(__file__).with_name("test_assignment_receipt_postgres.py")))
database = _support["database"]
_role = _support["_role"]
pytestmark = pytest.mark.integration


async def test_real_scoped_receipt_core_case_and_revision_outbox_remain_separate(
    database, tmp_path
):
    operator_config = PostgresFamilyStoreConfig(dsn=_role(database, "fdai_operator"))
    operator_store = PostgresFamilyStore(operator_config)
    outbox = PostgresScopedDuties(operator_store)
    transport = PostgresAssignmentOutbox(operator_config)
    core_config = PostgresStateStoreConfig(dsn=_role(database, "fdai_core"))
    core_store = PostgresStateStore(config=core_config)
    intake = AssignmentRequestIntake(PostgresAssignmentReceiptReader(core_config), core_store)
    path = tmp_path / "scoped.json"
    path.write_text(
        json.dumps({"schema_version": "1.0.0", "scopes": ["scope:example"], "shifts": []})
    )
    catalog = FileScopedDutyCatalog(path)
    now = datetime.now(UTC)
    clock = {"at": now}

    async def resolve(subject, *, at):
        return DutyResolution(
            subject,
            at,
            (subject,),
            at,
            at + timedelta(minutes=5),
            "directory:synthetic",
            "a" * 64,
            True,
        )

    scoped = ScopedDutyRequestProcessor(
        intake,
        ScopedDutyCaseService(
            core_store,
            ScopedDutyPlanner(
                SimpleNamespace(resolve=resolve),
                catalog,
                lambda: clock["at"],
                ScopedDutyPolicy(timedelta(minutes=5), 5.0, 30.0),
            ),
            SimpleNamespace(is_current_owner=AsyncMock(return_value=True)),
            lambda: clock["at"],
        ),
    )
    processor = AssignmentRequestProcessor(intake, AssignmentCaseService(core_store), scoped)
    principal = IamPrincipal("human:owner", frozenset({OperatorRole.OWNER}))
    request = ScopedDutyRequest.model_validate(
        {
            "source_revision": catalog.validate().revision,
            "bindings": [
                {
                    "subject": {"kind": "user", "ref": "human:" + duty},
                    "agent_name": "Odin",
                    "scope_ref": "scope:example",
                    "duty": duty,
                    "fallback": None,
                    "effective_from": now - timedelta(minutes=1),
                    "effective_until": now + timedelta(hours=1),
                }
                for duty in ("primary", "backup")
            ],
        }
    )
    created = await outbox.create(
        principal=principal,
        idempotency_key="scoped-sql",
        request=request,
        justification="Synthetic SQL test of scoped operational ownership.",
    )
    claimed = await transport.claim()
    assert claimed is not None
    notice = assignment_notice_from_record(claimed.record)
    assert notice.schema_version == "1.2.0"
    clock["at"] = notice.accepted_at
    assert (await intake.receive(notice, at=clock["at"])).status == "awaiting_agent_review"
    result = await processor.apply(notice, at=clock["at"])
    assert result["state"] == "draft"
    assert await transport.finish(claimed)
    case_id = str(created["case_id"])
    projection = await outbox.get(case_id)
    assert projection["revision"] == 1 and projection["state"] == "draft"
    await outbox.transition(principal=principal, case_id=case_id, expected_revision=1)
    second = await transport.claim()
    assert second is not None, (
        "scoped submit must observe its scoped Core revision, not wait five minutes"
    )
    submission = assignment_notice_from_record(second.record)
    assert submission.operation == "assignments.submit"
    clock["at"] = submission.accepted_at
    assert (await processor.apply(submission, at=clock["at"]))["state"] == "pending_review"
    assert await transport.finish(second)
    assert not await PostgresIamAdapters(operator_store)._assignment_cases()
    assert not await core_store.read_states("human_assignment:case:", limit=10)
    with (
        pytest.raises(psycopg.errors.RaiseException),
        psycopg.connect(_role(database, "fdai_operator")) as connection,
    ):
        connection.execute(
            "UPDATE state_kv SET value=value || '{\"revision\":999}'::jsonb WHERE key=%s",
            ("human_assignment:scoped-case:" + result["case_id"],),
        )
    with (
        pytest.raises(psycopg.errors.InsufficientPrivilege),
        psycopg.connect(_role(database, "fdai_core")) as connection,
    ):
        connection.execute("UPDATE operator_assignment_receipt SET record=record")
