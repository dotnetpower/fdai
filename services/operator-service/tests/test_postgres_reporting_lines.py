from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta

from fdai_operator_service.families.iam.contracts import (
    IamPrincipal,
    ReportingLineCaseQuery,
    ReportingLineCreateCommand,
)
from fdai_operator_service.postgres_family_store import (
    StoredProposal,
    StoredStatePage,
    StoredStateRecord,
)
from fdai_operator_service.postgres_reporting_lines import PostgresReportingLines
from fdai_service_contracts import OperatorRole

NOW = datetime(2026, 9, 16, 1, 0, tzinfo=UTC)


class Store:
    def __init__(self) -> None:
        self.state: dict[str, dict[str, object]] = {}

    async def append_proposal(
        self,
        *,
        family: str,
        operation: str,
        principal_id: str | None,
        idempotency_key: str,
        payload: dict[str, object],
    ) -> StoredProposal:
        request = {
            "family": family,
            "operation": operation,
            "principal_id": principal_id,
            "idempotency_key": idempotency_key,
            "payload": payload,
        }
        digest = hashlib.sha256(
            json.dumps(request, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        proposal_id = "operator-" + digest[:32]
        record = {
            **request,
            "kind": "operator.proposal",
            "mode": "shadow",
            "proposal_id": proposal_id,
            "request_digest": digest,
            "accepted_at": NOW.isoformat(),
            "dispatch_status": "pending",
        }
        key = "operator-proposal:iam:" + hashlib.sha256(idempotency_key.encode()).hexdigest()
        self.state[key] = record
        return StoredProposal(
            proposal_id=proposal_id,
            accepted_at=NOW.isoformat(),
            duplicate=False,
            record=record,
        )

    async def read_state(self, key: str):
        return self.state.get(key)

    async def read_state_page(
        self,
        *,
        prefix: str,
        limit: int,
        match_field: str | None = None,
        match_value: str | None = None,
    ) -> StoredStatePage:
        del match_field, match_value
        records = tuple(
            StoredStateRecord(key=key, value=value, updated_at=NOW)
            for key, value in self.state.items()
            if key.startswith(prefix)
        )
        return StoredStatePage(records=records[:limit], truncated=len(records) > limit)


def _principal(oid: str, role: OperatorRole) -> IamPrincipal:
    return IamPrincipal(oid=oid, roles=frozenset({role}))


async def test_reporting_projection_joins_exact_core_case_and_filters_endpoints() -> None:
    store = Store()
    adapter = PostgresReportingLines(store)  # type: ignore[arg-type]
    created = await adapter.create_report_line_case(
        ReportingLineCreateCommand(
            principal=_principal("uploader", OperatorRole.CONTRIBUTOR),
            idempotency_key="create-1",
            upload_id="00000000-0000-0000-0000-000000000001",
            candidate_id="report-line-" + "a" * 32,
            effective_from=NOW,
            effective_until=NOW + timedelta(days=90),
            supersedes_case_id=None,
        )
    )
    operator_case_id = str(created["operator_case_id"])
    core_case_id = "00000000-0000-0000-0000-000000000002"
    store.state["human_assignment:operator-case:" + operator_case_id] = {
        "case_kind": "report_line",
        "case_id": core_case_id,
        "request_digest": created["request_digest"],
    }
    store.state["human_reporting:case:" + core_case_id] = {
        "case_id": core_case_id,
        "candidate_id": created["candidate_id"],
        "upload_id": created["upload_id"],
        "requester_ref": "uploader",
        "subject_ref": "person-a",
        "manager_ref": "person-b",
        "effective_from": NOW.isoformat(),
        "effective_until": (NOW + timedelta(days=90)).isoformat(),
        "state": "pending_confirmation",
        "revision": 1,
        "edge_digest": "b" * 64,
        "directory_comparison": "matched",
        "confirmation": None,
        "owner_review": None,
        "execution_authority": False,
        "approval_authority": False,
    }

    endpoint, _ = await adapter.list_report_line_case_page(
        ReportingLineCaseQuery(
            principal=_principal("person-a", OperatorRole.READER),
            limit=10,
            offset=0,
        )
    )
    stranger, _ = await adapter.list_report_line_case_page(
        ReportingLineCaseQuery(
            principal=_principal("person-x", OperatorRole.READER),
            limit=10,
            offset=0,
        )
    )

    assert endpoint[0]["can_confirm"] is True
    assert endpoint[0]["can_review"] is False
    assert stranger == []
