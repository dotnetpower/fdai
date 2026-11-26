from __future__ import annotations

import base64
import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fdai_operator_service.browser_evidence_cursor import (
    decode_browser_evidence_cursor,
    encode_browser_evidence_cursor,
)
from fdai_operator_service.postgres import (
    PostgresOperatorReadModel,
    PostgresOperatorReadModelConfig,
)
from fdai_operator_service.postgres_sql import BROWSER_EVIDENCE_WORKSPACE_SQL
from fdai_service_contracts import BrowserEvidenceWorkspaceQuery


class _ReadModel(PostgresOperatorReadModel):
    def __init__(self, rows: list[dict[str, object]]) -> None:
        super().__init__(PostgresOperatorReadModelConfig(dsn="postgresql://example.invalid/db"))
        self.rows = rows
        self.calls: list[tuple[str, Mapping[str, object]]] = []

    async def _fetch_all(
        self,
        statement: str,
        parameters: Mapping[str, object],
    ) -> list[dict[str, Any]]:
        self.calls.append((statement, parameters))
        return self.rows


async def test_workspace_read_model_uses_bounded_filters_and_emits_cursor() -> None:
    observed_at = datetime.now(UTC)
    rows = [
        _row(observed_at, "a", attention_rank=0),
        _row(
            observed_at,
            "b",
            attention_rank=4,
            captured_at=observed_at - timedelta(minutes=2),
        ),
    ]
    query = BrowserEvidenceWorkspaceQuery(
        limit=1,
        host="dashboard.example",
        retention="retained",
        sort="attention",
    )
    model = _ReadModel(rows)

    payload = (await model.list_browser_evidence_workspace(query)).to_dict()

    assert payload["loaded_count"] == 1
    assert payload["has_more"] is True
    cursor = payload["next_cursor"]
    assert isinstance(cursor, str)
    statement, parameters = model.calls[0]
    assert statement == BROWSER_EVIDENCE_WORKSPACE_SQL
    assert parameters["host"] == "dashboard.example"
    assert parameters["fetch"] == 2
    assert parameters["cursor_captured_at"] is None
    decoded = decode_browser_evidence_cursor(
        cursor,
        query=BrowserEvidenceWorkspaceQuery(
            limit=1,
            cursor=cursor,
            host="dashboard.example",
            retention="retained",
            sort="attention",
        ),
        now=observed_at + timedelta(minutes=1),
    )
    assert decoded == (0, observed_at - timedelta(minutes=1), f"sha256:{'a' * 64}")
    for forbidden in ("visible_text", "aria_snapshot", "screenshot,"):
        assert forbidden not in statement
    for required in (
        "observation.observed_at + INTERVAL '168 hours'",
        "audit.event_id = page.custody_audit_uuid",
        "audit.actor = 'fdai.browser_evidence'",
        "audit.action_kind = 'browser_evidence.capture'",
        "audit.entry->>'content_digest'",
        "audit.entry->>'untrusted' = 'true'",
        "audit.entry->>'can_authorize_action' = 'false'",
    ):
        assert required in statement
    assert "INTERVAL '7 days'" not in statement
    assert "audit.event_id::TEXT" not in statement


def test_workspace_cursor_binds_filters_and_expires() -> None:
    observed_at = datetime.now(UTC)
    query = BrowserEvidenceWorkspaceQuery(limit=25, sort="newest")
    model = _ReadModel([_row(observed_at, "a")])

    cursor = _cursor_from_row(model.rows[0], query)

    with pytest.raises(ValueError, match="invalid or expired"):
        decode_browser_evidence_cursor(
            cursor,
            query=BrowserEvidenceWorkspaceQuery(
                limit=25,
                finding="present",
                cursor=cursor,
                sort="newest",
            ),
            now=observed_at,
        )
    with pytest.raises(ValueError, match="invalid or expired"):
        decode_browser_evidence_cursor(
            cursor,
            query=BrowserEvidenceWorkspaceQuery(
                limit=25,
                cursor=cursor,
                sort="newest",
            ),
            now=observed_at + timedelta(minutes=16),
        )


def test_workspace_cursor_rejects_unknown_fields() -> None:
    observed_at = datetime.now(UTC)
    query = BrowserEvidenceWorkspaceQuery(limit=25)
    cursor = _cursor_from_row(_row(observed_at, "a"), query)
    padded = cursor + "=" * (-len(cursor) % 4)
    payload = json.loads(base64.urlsafe_b64decode(padded).decode())
    payload["unexpected"] = True
    encoded = (
        base64.urlsafe_b64encode(
            json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        )
        .rstrip(b"=")
        .decode()
    )

    with pytest.raises(ValueError, match="invalid or expired"):
        decode_browser_evidence_cursor(
            encoded,
            query=BrowserEvidenceWorkspaceQuery(limit=25, cursor=encoded),
            now=observed_at,
        )


def _cursor_from_row(
    row: Mapping[str, object],
    query: BrowserEvidenceWorkspaceQuery,
) -> str:
    return encode_browser_evidence_cursor(row, query=query)


def _row(
    observed_at: datetime,
    digest: str,
    *,
    attention_rank: int = 0,
    captured_at: datetime | None = None,
) -> dict[str, object]:
    captured = captured_at or observed_at - timedelta(minutes=1)
    return {
        "observed_at": observed_at,
        "source_observed_at": observed_at - timedelta(seconds=1),
        "snapshot_total_count": 2,
        "snapshot_admitted_count": 2,
        "snapshot_withheld_count": 0,
        "withheld_invalid_metadata_count": 0,
        "withheld_trust_invalid_count": 0,
        "withheld_isolation_unverified_count": 0,
        "matching_admitted_count": 2,
        "security_finding_count": 0,
        "legal_hold_count": 0,
        "expiring_count": 0,
        "expired_pending_purge_count": 0,
        "retained_count": 2,
        "artifact_id": f"sha256:{digest * 64}",
        "policy_id": "dashboard",
        "policy_version": 4,
        "source_host": "dashboard.example",
        "final_host": "dashboard.example",
        "captured_at": captured,
        "expires_at": observed_at + timedelta(days=30),
        "selector_count": 1,
        "has_screenshot_digest": True,
        "has_text_digest": True,
        "has_snapshot_digest": False,
        "redaction_count": 1,
        "browser_version": "chromium-test",
        "chain_of_custody_audit_ref": "00000000-0000-0000-0000-000000000000",
        "prompt_injection_finding_count": 0,
        "legal_hold": False,
        "legal_hold_ref": None,
        "legal_hold_at": None,
        "retention_state": "retained",
        "attention_rank": attention_rank,
        "audit_link_state": "missing",
        "audit_sequence": None,
        "audit_correlation_id": None,
    }
