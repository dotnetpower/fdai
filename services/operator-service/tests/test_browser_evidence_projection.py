from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fdai_operator_service.postgres import (
    PostgresOperatorReadModel,
    PostgresOperatorReadModelConfig,
)
from fdai_operator_service.postgres_sql import BROWSER_EVIDENCE_PAGE_SQL
from fdai_operator_service.projections import ProjectionUnavailableError
from fdai_service_contracts import BrowserEvidenceQuery

_NOW = datetime(2026, 8, 15, tzinfo=UTC)


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


async def test_browser_evidence_query_is_bounded_and_payload_free() -> None:
    model = _ReadModel([_row()])

    payload = (await model.list_browser_evidence(BrowserEvidenceQuery(limit=25))).to_dict()

    assert payload["count"] == 1
    items = payload["items"]
    assert isinstance(items, list)
    first = items[0]
    assert isinstance(first, dict)
    assert first["artifact_id"] == "sha256:digest"
    assert model.calls == [(BROWSER_EVIDENCE_PAGE_SQL, {"limit": 25})]
    assert "FROM operator_browser_evidence_metadata" in BROWSER_EVIDENCE_PAGE_SQL
    for forbidden in ("screenshot,", "visible_text", "aria_snapshot"):
        assert forbidden not in BROWSER_EVIDENCE_PAGE_SQL


async def test_browser_evidence_query_rejects_malformed_durable_metadata() -> None:
    malformed = _row()
    malformed["untrusted"] = "true"

    with pytest.raises(ProjectionUnavailableError, match="metadata is malformed"):
        await _ReadModel([malformed]).list_browser_evidence(BrowserEvidenceQuery(limit=25))


@pytest.mark.parametrize("limit", (1, 500))
def test_browser_evidence_query_accepts_exact_limit_boundaries(limit: int) -> None:
    assert BrowserEvidenceQuery(limit=limit).limit == limit


@pytest.mark.parametrize("limit", (0, 501))
def test_browser_evidence_query_rejects_out_of_range_limits(limit: int) -> None:
    with pytest.raises(ValueError, match="limit must be in"):
        BrowserEvidenceQuery(limit=limit)


async def test_browser_evidence_query_rejects_unverified_isolation() -> None:
    row = _row()
    row["isolation_verified"] = False

    with pytest.raises(ProjectionUnavailableError, match="metadata is malformed"):
        await _ReadModel([row]).list_browser_evidence(BrowserEvidenceQuery(limit=25))


def test_operator_migration_grants_metadata_columns_only() -> None:
    migration = (
        Path(__file__).resolve().parents[3]
        / "service-migrations/branches/operator-service/versions"
        / "20260815_operator_browser_evidence_read.py"
    ).read_text(encoding="utf-8")

    assert "REVOKE ALL PRIVILEGES ON TABLE browser_evidence_artifact" in migration
    assert "WITH (security_barrier = true)" in migration
    assert "GRANT SELECT ON TABLE operator_browser_evidence_metadata" in migration
    assert "GRANT SELECT (" not in migration
    assert "TO fdai_operator" not in migration.split("CREATE VIEW", 1)[0]


def _row() -> dict[str, object]:
    return {
        "artifact_id": "sha256:digest",
        "policy_id": "dashboard",
        "policy_version": 1,
        "canonical_source_url": "https://dashboard.example/evidence",
        "canonical_final_url": "https://dashboard.example/evidence",
        "captured_at": _NOW,
        "expires_at": _NOW,
        "selector_count": 1,
        "screenshot_hash": "screenshot-hash",
        "text_hash": "text-hash",
        "snapshot_hash": "snapshot-hash",
        "redaction_count": 1,
        "browser_version": "fake",
        "chain_of_custody_audit_ref": "custody-1",
        "prompt_injection_finding_count": 0,
        "isolation_verified": True,
        "untrusted": True,
        "legal_hold": False,
        "legal_hold_ref": None,
        "legal_hold_at": None,
    }
