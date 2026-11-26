from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
from fdai_operator_service.postgres import (
    PostgresOperatorReadModel,
    PostgresOperatorReadModelConfig,
)
from fdai_service_contracts import BrowserEvidenceWorkspaceQuery


def _dsn(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        pytest.skip(f"{name} is unset")
    return value.replace("postgresql+psycopg://", "postgresql://", 1)


def _operator_dsn() -> str:
    return _dsn(
        "FDAI_OPERATOR_DATABASE_URL"
        if os.environ.get("FDAI_OPERATOR_DATABASE_URL", "").strip()
        else "FDAI_DATABASE_URL"
    )


@pytest.mark.integration
async def test_workspace_postgres_role_exposes_only_admitted_metadata() -> None:
    admin_dsn = _dsn("FDAI_ADMIN_DATABASE_URL")
    operator_dsn = _operator_dsn()
    suffix = uuid4().hex
    now = datetime.now(UTC)
    admitted = _record(suffix, "admitted", now=now)
    malformed_audit = _record(
        suffix,
        "malformed-audit",
        now=now,
        custody_ref=f"custody-reference-{suffix}",
    )
    underscore_host = _record(
        suffix,
        "underscore-host",
        now=now,
        source_host="my_host.example",
    )
    unverified = _record(suffix, "unverified", now=now, isolation_verified=False)
    malformed = _record(suffix, "malformed", now=now, browser_version="x" * 257)
    overlong_host = _record(
        suffix,
        "overlong-host",
        now=now,
        source_host=f"{'a' * 250}.com",
    )
    overlong_label = _record(
        suffix,
        "overlong-label",
        now=now,
        source_host=f"{'a' * 64}.example",
    )
    padded_custody = _record(
        suffix,
        "padded-custody",
        now=now,
        custody_ref=f" {uuid4()}",
    )
    padded_hold = _record(
        suffix,
        "padded-hold",
        now=now,
        legal_hold_ref=" case:workspace-test ",
    )
    unicode_hold = _record(
        suffix,
        "unicode-hold",
        now=now,
        legal_hold_ref="\N{NO-BREAK SPACE}case:workspace-test",
    )
    records = (
        admitted,
        malformed_audit,
        underscore_host,
        unverified,
        malformed,
        overlong_host,
        overlong_label,
        padded_custody,
        padded_hold,
        unicode_hold,
    )
    async with await psycopg.AsyncConnection.connect(admin_dsn) as connection:
        for record in records:
            await connection.execute(
                """
                INSERT INTO browser_evidence_artifact (
                    artifact_id, content_digest, policy_id, policy_version,
                    canonical_source_url, canonical_final_url,
                    captured_at, expires_at, selectors,
                    screenshot, visible_text, aria_snapshot,
                    screenshot_hash, text_hash, snapshot_hash,
                    redaction_manifest, browser_version,
                    chain_of_custody_audit_ref, prompt_injection_findings,
                    isolation, untrusted,
                    legal_hold, legal_hold_ref, legal_hold_at
                ) VALUES (
                    %(artifact_id)s, %(content_digest)s, 'workspace-test', 1,
                    %(canonical_source_url)s,
                    %(canonical_final_url)s,
                    %(captured_at)s, %(expires_at)s, '["main"]'::jsonb,
                    NULL, NULL, NULL, NULL, NULL, NULL,
                    '[]'::jsonb, %(browser_version)s,
                    %(custody_ref)s, %(findings)s::jsonb,
                    %(isolation)s::jsonb, TRUE,
                    %(legal_hold)s, %(legal_hold_ref)s, %(legal_hold_at)s
                )
                """,
                record,
            )
        await connection.execute(
            """
            INSERT INTO audit_log (
                event_id, correlation_id, actor, action_kind, mode, entry,
                previous_hash, entry_hash
            ) VALUES (
                %(custody_ref)s, %(correlation_id)s, 'fdai.browser_evidence',
                'browser_evidence.capture', 'shadow',
                JSONB_BUILD_OBJECT(
                    'content_digest', %(content_digest)s::text,
                    'untrusted', TRUE,
                    'can_authorize_action', FALSE
                ), '', %(entry_hash)s
            )
            """,
            {
                "custody_ref": admitted["custody_ref"],
                "correlation_id": f"browser-correlation-{suffix}",
                "content_digest": admitted["content_digest"],
                "entry_hash": hashlib.sha256(f"audit:{suffix}:one".encode()).hexdigest(),
            },
        )
        await connection.commit()
    try:
        model = PostgresOperatorReadModel(PostgresOperatorReadModelConfig(dsn=operator_dsn))
        payload = (
            await model.list_browser_evidence_workspace(
                BrowserEvidenceWorkspaceQuery(
                    limit=25,
                    artifact_id=str(admitted["artifact_id"]),
                    host="status.example",
                    host_scope="final",
                    policy_id="workspace-test",
                    policy_version=1,
                    captured_from=now - timedelta(minutes=10),
                    captured_before=now + timedelta(minutes=1),
                    retention="retained",
                    finding="present",
                    custody_ref=str(admitted["custody_ref"]),
                    sort="newest",
                )
            )
        ).to_dict()

        assert payload["loaded_count"] == 1
        assert payload["snapshot_total_count"] >= 10
        assert payload["snapshot_withheld_count"] >= 7
        items = payload["items"]
        assert isinstance(items, list) and len(items) == 1
        item = items[0]
        assert isinstance(item, dict)
        assert item["artifact_id"] == admitted["artifact_id"]
        assert item["source_host"] == "dashboard.example"
        assert item["final_host"] == "status.example"
        audit = item["audit"]
        assert isinstance(audit, dict)
        assert audit["state"] == "exact"
        assert isinstance(audit["sequence"], str) and audit["sequence"].isdigit()
        assert audit["correlation_id"] == f"browser-correlation-{suffix}"
        no_match = (
            await model.list_browser_evidence_workspace(
                BrowserEvidenceWorkspaceQuery(
                    limit=25,
                    host="status.example",
                    host_scope="requested",
                    policy_id="workspace-test",
                )
            )
        ).to_dict()
        assert no_match["matching_admitted_count"] == 0
        assert no_match["items"] == []
        malformed_audit_payload = (
            await model.list_browser_evidence_workspace(
                BrowserEvidenceWorkspaceQuery(
                    limit=25,
                    artifact_id=str(malformed_audit["artifact_id"]),
                )
            )
        ).to_dict()
        malformed_audit_items = malformed_audit_payload["items"]
        assert isinstance(malformed_audit_items, list)
        assert len(malformed_audit_items) == 1
        malformed_audit_item = malformed_audit_items[0]
        assert isinstance(malformed_audit_item, dict)
        assert malformed_audit_item["audit"] == {
            "state": "malformed",
            "sequence": None,
            "correlation_id": None,
        }
        underscore_payload = (
            await model.list_browser_evidence_workspace(
                BrowserEvidenceWorkspaceQuery(
                    limit=25,
                    artifact_id=str(underscore_host["artifact_id"]),
                )
            )
        ).to_dict()
        underscore_items = underscore_payload["items"]
        assert isinstance(underscore_items, list) and len(underscore_items) == 1
        underscore_item = underscore_items[0]
        assert isinstance(underscore_item, dict)
        assert underscore_item["source_host"] == "my_host.example"
        async with await psycopg.AsyncConnection.connect(admin_dsn) as connection:
            await connection.execute(
                """
                INSERT INTO audit_log (
                    event_id, correlation_id, actor, action_kind, mode, entry,
                    previous_hash, entry_hash
                ) VALUES (
                    %(custody_ref)s, %(correlation_id)s, 'fdai.browser_evidence',
                    'browser_evidence.capture', 'shadow',
                    JSONB_BUILD_OBJECT(
                        'content_digest', %(content_digest)s::text,
                        'untrusted', TRUE,
                        'can_authorize_action', FALSE
                    ), '', %(entry_hash)s
                )
                """,
                {
                    "custody_ref": admitted["custody_ref"],
                    "correlation_id": f"browser-correlation-{suffix}",
                    "content_digest": admitted["content_digest"],
                    "entry_hash": hashlib.sha256(f"audit:{suffix}:two".encode()).hexdigest(),
                },
            )
            await connection.commit()
        ambiguous_payload = (
            await model.list_browser_evidence_workspace(
                BrowserEvidenceWorkspaceQuery(
                    limit=25,
                    artifact_id=str(admitted["artifact_id"]),
                )
            )
        ).to_dict()
        ambiguous_items = ambiguous_payload["items"]
        assert isinstance(ambiguous_items, list) and len(ambiguous_items) == 1
        ambiguous_item = ambiguous_items[0]
        assert isinstance(ambiguous_item, dict)
        assert ambiguous_item["audit"] == {
            "state": "ambiguous",
            "sequence": None,
            "correlation_id": None,
        }
        async with await psycopg.AsyncConnection.connect(operator_dsn) as connection:
            admitted_row = await (
                await connection.execute(
                    """
                    SELECT artifact_id
                      FROM operator_browser_evidence_workspace
                     WHERE policy_id = 'workspace-test'
                    """
                )
            ).fetchall()
            assert {str(row[0]) for row in admitted_row} == {
                admitted["artifact_id"],
                malformed_audit["artifact_id"],
                underscore_host["artifact_id"],
            }
            summary_cursor = await connection.execute(
                "SELECT * FROM operator_browser_evidence_workspace_summary"
            )
            summary_columns = [column.name for column in summary_cursor.description or ()]
            summary_row = await summary_cursor.fetchone()
            assert summary_row is not None
            assert summary_row[2] >= 6
            assert summary_row[4] >= 1
            assert summary_columns == [
                "snapshot_total_count",
                "snapshot_admitted_count",
                "withheld_invalid_metadata_count",
                "withheld_trust_invalid_count",
                "withheld_isolation_unverified_count",
                "source_observed_at",
            ]
        async with await psycopg.AsyncConnection.connect(operator_dsn) as connection:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                await connection.execute(
                    "SELECT artifact_id FROM browser_evidence_artifact LIMIT 1"
                )
        async with await psycopg.AsyncConnection.connect(operator_dsn) as connection:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                await connection.execute(
                    "SELECT artifact_id FROM operator_browser_evidence_admission_internal LIMIT 1"
                )
    finally:
        async with await psycopg.AsyncConnection.connect(admin_dsn) as connection:
            await connection.execute(
                "DELETE FROM browser_evidence_artifact WHERE artifact_id = ANY(%s)",
                ([record["artifact_id"] for record in records],),
            )
            await connection.execute(
                "DELETE FROM audit_log WHERE event_id = %s",
                (admitted["custody_ref"],),
            )
            await connection.commit()


def _record(
    suffix: str,
    label: str,
    *,
    now: datetime,
    isolation_verified: bool = True,
    browser_version: str = "chromium-test",
    source_host: str = "dashboard.example",
    custody_ref: str | None = None,
    legal_hold_ref: str | None = None,
) -> dict[str, object]:
    digest = hashlib.sha256(f"{suffix}:{label}".encode()).hexdigest()
    resolved_custody_ref = custody_ref or str(uuid4())
    isolation = {
        "executor_identity_present": False,
        "host_filesystem_mounted": False,
        "environment_scrubbed": True,
        "restricted_egress": isolation_verified,
        "ephemeral_profile": True,
    }
    return {
        "artifact_id": f"sha256:{digest}",
        "content_digest": digest,
        "canonical_source_url": f"https://{source_host}/evidence",
        "canonical_final_url": "https://status.example/evidence",
        "captured_at": now - timedelta(minutes=5),
        "expires_at": now + timedelta(days=30),
        "browser_version": browser_version,
        "custody_ref": resolved_custody_ref,
        "findings": '["instruction_override"]' if label == "admitted" else "[]",
        "isolation": (
            "{"
            + ",".join(f'"{key}":{str(value).lower()}' for key, value in isolation.items())
            + "}"
        ),
        "legal_hold": legal_hold_ref is not None,
        "legal_hold_ref": legal_hold_ref,
        "legal_hold_at": (now - timedelta(minutes=1) if legal_hold_ref is not None else None),
    }
