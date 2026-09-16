from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta

from fdai_operator_service.postgres_family_store import (
    StoredProposal,
    StoredStatePage,
    StoredStateRecord,
)
from fdai_operator_service.postgres_report_line_contacts import (
    PostgresReportLineContacts,
)
from fdai_service_contracts import build_report_line_contact_command

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


async def test_contact_context_uses_shorter_consent_expiry_and_persists_command() -> None:
    store = Store()
    adapter = PostgresReportLineContacts(store, clock=lambda: NOW)  # type: ignore[arg-type]
    approval_id = "approval-1"
    consent_id = "00000000-0000-0000-0000-000000000003"
    store.state["hil_park:" + approval_id] = {
        "status": "awaiting_contact_consent",
        "approval_id": approval_id,
        "submitter_oid": "person-a",
        "contact_consent_id": consent_id,
        "action_hash": "a" * 64,
        "action": {
            "action_type": "ops.restart-service",
            "target_resource_ref": "scope://service/example",
        },
        "approval_context": {"expires_at": (NOW + timedelta(minutes=30)).isoformat()},
        "report_line_route": {
            "route_digest": "b" * 64,
            "graph_revision": "c" * 64,
            "path_revision": "d" * 64,
            "rungs": [{"subject_ref": "person-b"}],
        },
    }
    store.state["human_reporting:approval-consent:" + consent_id] = {
        "state": "pending",
        "requester_ref": "person-a",
        "action_digest": "a" * 64,
        "route_digest": "b" * 64,
        "path_revision": "d" * 64,
        "revision": 0,
        "created_at": NOW.isoformat(),
        "expires_at": (NOW + timedelta(minutes=5)).isoformat(),
    }

    context = await adapter.get_report_line_contact_context(approval_id)
    assert context is not None
    assert context.consent_requested_at == NOW
    assert context.expires_at == NOW + timedelta(minutes=5)
    assert await adapter.list_report_line_contact_contexts(
        requester_ref="person-a",
        limit=10,
    ) == (context,)

    command = build_report_line_contact_command(
        approval_id=approval_id,
        requester_ref="person-a",
        consent=True,
        expected_consent_revision=0,
        requested_at=NOW,
        idempotency_key="contact-1",
    )
    await adapter.enqueue_report_line_contact(command)
    assert any(
        value.get("operation") == "hil.report-line-contact.enqueue"
        for value in store.state.values()
    )
