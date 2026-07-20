"""PostgreSQL content-addressed storage for immutable browser evidence."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fdai.core.browser_evidence.service import verify_stored_browser_evidence
from fdai.shared.providers.browser_evidence import (
    BrowserEvidenceArtifact,
    BrowserEvidencePayload,
    BrowserRedactionEntry,
    BrowserRuntimeIsolation,
    StoredBrowserEvidence,
)

_COLUMNS: Final = (
    "artifact_id, content_digest, policy_id, policy_version, canonical_source_url, "
    "canonical_final_url, captured_at, expires_at, selectors, screenshot, visible_text, "
    "aria_snapshot, screenshot_hash, text_hash, snapshot_hash, redaction_manifest, "
    "browser_version, chain_of_custody_audit_ref, prompt_injection_findings, isolation, "
    "untrusted"
)


@dataclass(frozen=True, slots=True)
class PostgresBrowserEvidenceStoreConfig:
    dsn: str
    statement_timeout_ms: int = 15_000
    connect_timeout_s: int = 10

    def __post_init__(self) -> None:
        if not self.dsn:
            raise ValueError("PostgresBrowserEvidenceStoreConfig.dsn MUST NOT be empty")
        if self.statement_timeout_ms < 1 or self.connect_timeout_s < 1:
            raise ValueError("Postgres browser evidence timeouts MUST be positive")


class PostgresBrowserEvidenceArtifactStore:
    """Insert-only artifact store keyed by the complete content digest."""

    def __init__(self, *, config: PostgresBrowserEvidenceStoreConfig) -> None:
        self._config = config

    async def put(self, evidence: StoredBrowserEvidence) -> bool:
        verify_stored_browser_evidence(evidence)
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            cursor = await connection.execute(
                f"INSERT INTO browser_evidence_artifact ({_COLUMNS}) "  # noqa: S608
                "VALUES ("
                "%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, "
                "%s, %s::jsonb, %s, %s, %s::jsonb, %s::jsonb, %s"
                ") ON CONFLICT (artifact_id) DO NOTHING RETURNING artifact_id",
                _values(evidence),
            )
            created = await cursor.fetchone() is not None
        existing = await self.get(evidence.artifact.artifact_id)
        if existing is None or (not created and existing != evidence):
            raise ValueError("browser artifact id was reused with different evidence")
        return created

    async def get(self, artifact_id: str) -> StoredBrowserEvidence | None:
        async with await self._connect() as connection:
            await self._timeout(connection)
            cursor = await connection.execute(
                f"SELECT {_COLUMNS} FROM browser_evidence_artifact "  # noqa: S608
                "WHERE artifact_id = %s",
                (artifact_id,),
            )
            row = await cursor.fetchone()
        return _row_to_evidence(row) if row is not None else None

    async def list_artifacts(self, *, limit: int) -> tuple[BrowserEvidenceArtifact, ...]:
        if not 1 <= limit <= 500:
            raise ValueError("browser artifact list limit MUST be in [1, 500]")
        async with await self._connect() as connection:
            await self._timeout(connection)
            cursor = await connection.execute(
                f"SELECT {_COLUMNS} FROM browser_evidence_artifact "  # noqa: S608
                "ORDER BY captured_at DESC, artifact_id LIMIT %s",
                (limit,),
            )
            rows = await cursor.fetchall()
        return tuple(_row_to_evidence(row).artifact for row in rows)

    async def purge_expired(self, *, now: datetime, limit: int) -> tuple[str, ...]:
        if not 1 <= limit <= 500:
            raise ValueError("browser artifact retention limit MUST be in [1, 500]")
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            cursor = await connection.execute(
                "WITH expired AS ("
                "SELECT artifact_id FROM browser_evidence_artifact "
                "WHERE expires_at <= %s ORDER BY expires_at, artifact_id LIMIT %s "
                "FOR UPDATE SKIP LOCKED"
                ") DELETE FROM browser_evidence_artifact artifact "
                "USING expired WHERE artifact.artifact_id = expired.artifact_id "
                "RETURNING artifact.artifact_id",
                (now, limit),
            )
            rows = await cursor.fetchall()
        return tuple(str(row["artifact_id"]) for row in rows)

    async def _connect(self) -> psycopg.AsyncConnection[dict[str, Any]]:
        return await psycopg.AsyncConnection.connect(
            self._config.dsn,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        )

    async def _timeout(self, connection: psycopg.AsyncConnection[Any]) -> None:
        await connection.execute(
            "SELECT set_config('statement_timeout', %s, true)",
            (str(self._config.statement_timeout_ms),),
        )


def _values(evidence: StoredBrowserEvidence) -> tuple[object, ...]:
    artifact = evidence.artifact
    payload = evidence.payload
    return (
        artifact.artifact_id,
        artifact.content_digest,
        artifact.policy_id,
        artifact.policy_version,
        artifact.canonical_source_url,
        artifact.canonical_final_url,
        artifact.captured_at,
        artifact.expires_at,
        json.dumps(list(artifact.selectors), separators=(",", ":")),
        payload.screenshot,
        payload.visible_text,
        payload.aria_snapshot,
        artifact.screenshot_hash,
        artifact.text_hash,
        artifact.snapshot_hash,
        json.dumps([asdict(entry) for entry in artifact.redaction_manifest]),
        artifact.browser_version,
        artifact.chain_of_custody_audit_ref,
        json.dumps(list(artifact.prompt_injection_findings), separators=(",", ":")),
        json.dumps(asdict(artifact.isolation), separators=(",", ":")),
        artifact.untrusted,
    )


def _row_to_evidence(row: dict[str, Any]) -> StoredBrowserEvidence:
    redactions = tuple(
        BrowserRedactionEntry(
            surface=str(item["surface"]),  # type: ignore[arg-type]
            rule=str(item["rule"]),
            replacements=int(item["replacements"]),
        )
        for item in _list(row["redaction_manifest"])
        if isinstance(item, dict)
    )
    isolation = _object(row["isolation"])
    artifact = BrowserEvidenceArtifact(
        artifact_id=str(row["artifact_id"]),
        policy_id=str(row["policy_id"]),
        policy_version=int(row["policy_version"]),
        canonical_source_url=str(row["canonical_source_url"]),
        canonical_final_url=str(row["canonical_final_url"]),
        captured_at=row["captured_at"],
        selectors=tuple(str(item) for item in _list(row["selectors"])),
        screenshot_hash=_optional_str(row["screenshot_hash"]),
        text_hash=_optional_str(row["text_hash"]),
        snapshot_hash=_optional_str(row["snapshot_hash"]),
        redaction_manifest=redactions,
        browser_version=str(row["browser_version"]),
        chain_of_custody_audit_ref=str(row["chain_of_custody_audit_ref"]),
        content_digest=str(row["content_digest"]),
        prompt_injection_findings=tuple(
            str(item) for item in _list(row["prompt_injection_findings"])
        ),
        isolation=BrowserRuntimeIsolation(
            executor_identity_present=bool(isolation["executor_identity_present"]),
            host_filesystem_mounted=bool(isolation["host_filesystem_mounted"]),
            environment_scrubbed=bool(isolation["environment_scrubbed"]),
            restricted_egress=bool(isolation["restricted_egress"]),
            ephemeral_profile=bool(isolation["ephemeral_profile"]),
        ),
        expires_at=row["expires_at"],
        untrusted=bool(row["untrusted"]),
    )
    screenshot = row["screenshot"]
    evidence = StoredBrowserEvidence(
        artifact=artifact,
        payload=BrowserEvidencePayload(
            screenshot=(bytes(screenshot) if screenshot is not None else None),
            visible_text=_optional_str(row["visible_text"]),
            aria_snapshot=_optional_str(row["aria_snapshot"]),
        ),
    )
    verify_stored_browser_evidence(evidence)
    return evidence


def _list(value: object) -> list[Any]:
    decoded = json.loads(value) if isinstance(value, str) else value
    if not isinstance(decoded, list):
        raise ValueError("browser evidence JSON column MUST be an array")
    return decoded


def _object(value: object) -> dict[str, Any]:
    decoded = json.loads(value) if isinstance(value, str) else value
    if not isinstance(decoded, dict):
        raise ValueError("browser evidence JSON column MUST be an object")
    return decoded


def _optional_str(value: object) -> str | None:
    return str(value) if value is not None else None


__all__ = [
    "PostgresBrowserEvidenceArtifactStore",
    "PostgresBrowserEvidenceStoreConfig",
]
