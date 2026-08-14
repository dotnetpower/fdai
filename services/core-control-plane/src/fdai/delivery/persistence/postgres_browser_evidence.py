"""PostgreSQL custody and retention for bounded browser evidence artifacts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, Literal, cast

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from fdai.core.browser_evidence.storage import verify_stored_browser_evidence
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
_REDACTION_SURFACES: Final = frozenset({"screenshot", "visible_text", "aria_snapshot"})
_ISOLATION_FIELDS: Final = frozenset(
    {
        "executor_identity_present",
        "host_filesystem_mounted",
        "environment_scrubbed",
        "restricted_egress",
        "ephemeral_profile",
    }
)


@dataclass(frozen=True, slots=True)
class PostgresBrowserEvidenceArtifactStoreConfig:
    """Validated database settings for browser-evidence custody."""

    dsn: str
    statement_timeout_ms: int = 15_000
    connect_timeout_s: int = 10

    def __post_init__(self) -> None:
        if not self.dsn:
            raise ValueError("browser evidence PostgreSQL DSN MUST NOT be empty")
        if self.statement_timeout_ms < 1 or self.connect_timeout_s < 1:
            raise ValueError("browser evidence PostgreSQL timeouts MUST be positive")


class PostgresBrowserEvidenceArtifactStore:
    """Persist exact payload bytes and delete only unheld expired artifacts."""

    def __init__(self, *, config: PostgresBrowserEvidenceArtifactStoreConfig) -> None:
        self._config = config

    async def put(self, evidence: StoredBrowserEvidence) -> bool:
        verify_stored_browser_evidence(evidence)
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            cursor = await connection.execute(
                f"""
                INSERT INTO browser_evidence_artifact ({_COLUMNS})
                VALUES ({", ".join(["%s"] * 21)})
                ON CONFLICT DO NOTHING
                RETURNING artifact_id
                """,  # noqa: S608 - columns and placeholders are module constants
                _values(evidence),
            )
            if await cursor.fetchone() is not None:
                return True
            existing = await self._get(connection, evidence.artifact.artifact_id, lock=True)
            if existing is None:
                raise ValueError("browser artifact digest or custody reference conflicts")
            if existing != evidence:
                raise ValueError("browser artifact id collision")
            return False

    async def get(self, artifact_id: str) -> StoredBrowserEvidence | None:
        async with await self._connect() as connection:
            await self._timeout(connection)
            return await self._get(connection, artifact_id)

    async def list_artifacts(self, *, limit: int) -> tuple[BrowserEvidenceArtifact, ...]:
        if not 1 <= limit <= 500:
            raise ValueError("browser artifact list limit MUST be in [1, 500]")
        async with await self._connect() as connection:
            await self._timeout(connection)
            cursor = await connection.execute(
                f"SELECT {_COLUMNS} FROM browser_evidence_artifact "  # noqa: S608
                "ORDER BY captured_at DESC, artifact_id DESC LIMIT %s",
                (limit,),
            )
            rows = await cursor.fetchall()
        return tuple(_row_to_stored(row).artifact for row in rows)

    async def purge_expired(self, *, now: datetime, limit: int) -> tuple[str, ...]:
        if now.tzinfo is None:
            raise ValueError("browser artifact retention time MUST include timezone")
        if not 1 <= limit <= 500:
            raise ValueError("browser artifact retention limit MUST be in [1, 500]")
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            cursor = await connection.execute(
                """
                WITH claimed AS (
                    SELECT artifact_id
                      FROM browser_evidence_artifact
                     WHERE expires_at <= %s AND legal_hold = FALSE
                     ORDER BY expires_at, artifact_id
                     FOR UPDATE SKIP LOCKED
                     LIMIT %s
                )
                DELETE FROM browser_evidence_artifact AS artifact
                 USING claimed
                 WHERE artifact.artifact_id = claimed.artifact_id
                RETURNING artifact.artifact_id
                """,
                (now, limit),
            )
            rows = await cursor.fetchall()
        return tuple(str(row["artifact_id"]) for row in rows)

    async def place_legal_hold(
        self,
        *,
        artifact_id: str,
        hold_ref: str,
        held_at: datetime,
    ) -> bool | None:
        """Place one monotonic hold; release belongs to a future governed workflow."""

        if not hold_ref or len(hold_ref) > 512 or any(ord(char) < 32 for char in hold_ref):
            raise ValueError("browser artifact legal hold reference MUST be bounded text")
        if held_at.tzinfo is None:
            raise ValueError("browser artifact legal hold time MUST include timezone")
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            cursor = await connection.execute(
                "SELECT legal_hold, legal_hold_ref FROM browser_evidence_artifact "
                "WHERE artifact_id = %s FOR UPDATE",
                (artifact_id,),
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            if bool(row["legal_hold"]):
                if str(row["legal_hold_ref"]) != hold_ref:
                    raise ValueError("browser artifact already has a different legal hold")
                return False
            await connection.execute(
                "UPDATE browser_evidence_artifact "
                "SET legal_hold = TRUE, legal_hold_ref = %s, legal_hold_at = %s "
                "WHERE artifact_id = %s",
                (hold_ref, held_at, artifact_id),
            )
            return True

    async def _get(
        self,
        connection: psycopg.AsyncConnection[dict[str, Any]],
        artifact_id: str,
        *,
        lock: bool = False,
    ) -> StoredBrowserEvidence | None:
        cursor = await connection.execute(
            f"SELECT {_COLUMNS} FROM browser_evidence_artifact "  # noqa: S608
            "WHERE artifact_id = %s" + (" FOR UPDATE" if lock else ""),
            (artifact_id,),
        )
        row = await cursor.fetchone()
        return _row_to_stored(row) if row is not None else None

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
        Jsonb(list(artifact.selectors)),
        payload.screenshot,
        payload.visible_text,
        payload.aria_snapshot,
        artifact.screenshot_hash,
        artifact.text_hash,
        artifact.snapshot_hash,
        Jsonb(
            [
                {
                    "surface": item.surface,
                    "rule": item.rule,
                    "replacements": item.replacements,
                }
                for item in artifact.redaction_manifest
            ]
        ),
        artifact.browser_version,
        artifact.chain_of_custody_audit_ref,
        Jsonb(list(artifact.prompt_injection_findings)),
        Jsonb(
            {
                "executor_identity_present": artifact.isolation.executor_identity_present,
                "host_filesystem_mounted": artifact.isolation.host_filesystem_mounted,
                "environment_scrubbed": artifact.isolation.environment_scrubbed,
                "restricted_egress": artifact.isolation.restricted_egress,
                "ephemeral_profile": artifact.isolation.ephemeral_profile,
            }
        ),
        artifact.untrusted,
    )


def _row_to_stored(row: dict[str, Any]) -> StoredBrowserEvidence:
    redactions = tuple(
        _redaction(item, index=index)
        for index, item in enumerate(_json_array(row["redaction_manifest"], "redaction_manifest"))
    )
    isolation_raw = _json_object(row["isolation"], "isolation")
    if frozenset(isolation_raw) != _ISOLATION_FIELDS:
        raise ValueError("browser evidence isolation fields are invalid")
    isolation = BrowserRuntimeIsolation(
        executor_identity_present=_boolean(isolation_raw, "executor_identity_present"),
        host_filesystem_mounted=_boolean(isolation_raw, "host_filesystem_mounted"),
        environment_scrubbed=_boolean(isolation_raw, "environment_scrubbed"),
        restricted_egress=_boolean(isolation_raw, "restricted_egress"),
        ephemeral_profile=_boolean(isolation_raw, "ephemeral_profile"),
    )
    stored = StoredBrowserEvidence(
        artifact=BrowserEvidenceArtifact(
            artifact_id=str(row["artifact_id"]),
            policy_id=str(row["policy_id"]),
            policy_version=int(row["policy_version"]),
            canonical_source_url=str(row["canonical_source_url"]),
            canonical_final_url=str(row["canonical_final_url"]),
            captured_at=row["captured_at"],
            selectors=_text_tuple(row["selectors"], "selectors"),
            screenshot_hash=_optional_str(row["screenshot_hash"]),
            text_hash=_optional_str(row["text_hash"]),
            snapshot_hash=_optional_str(row["snapshot_hash"]),
            redaction_manifest=redactions,
            browser_version=str(row["browser_version"]),
            chain_of_custody_audit_ref=str(row["chain_of_custody_audit_ref"]),
            content_digest=str(row["content_digest"]),
            prompt_injection_findings=_text_tuple(
                row["prompt_injection_findings"],
                "prompt_injection_findings",
            ),
            isolation=isolation,
            expires_at=row["expires_at"],
            untrusted=_exact_bool(row["untrusted"], "untrusted"),
        ),
        payload=BrowserEvidencePayload(
            screenshot=bytes(row["screenshot"]) if row["screenshot"] is not None else None,
            visible_text=_optional_str(row["visible_text"]),
            aria_snapshot=_optional_str(row["aria_snapshot"]),
        ),
    )
    verify_stored_browser_evidence(stored)
    return stored


def _optional_str(value: object) -> str | None:
    return str(value) if value is not None else None


def _json_array(value: object, field: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"browser evidence {field} MUST be an array")
    return value


def _json_object(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"browser evidence {field} MUST be an object")
    return value


def _text_tuple(value: object, field: str) -> tuple[str, ...]:
    items = _json_array(value, field)
    if not all(isinstance(item, str) for item in items):
        raise ValueError(f"browser evidence {field} MUST contain strings")
    return tuple(cast(str, item) for item in items)


def _redaction(value: object, *, index: int) -> BrowserRedactionEntry:
    field = f"redaction_manifest[{index}]"
    item = _json_object(value, field)
    if frozenset(item) != {"surface", "rule", "replacements"}:
        raise ValueError(f"browser evidence {field} fields are invalid")
    surface = item["surface"]
    rule = item["rule"]
    replacements = item["replacements"]
    if not isinstance(surface, str) or surface not in _REDACTION_SURFACES:
        raise ValueError(f"browser evidence {field}.surface is invalid")
    if not isinstance(rule, str) or not rule:
        raise ValueError(f"browser evidence {field}.rule MUST be non-empty text")
    if isinstance(replacements, bool) or not isinstance(replacements, int) or replacements < 0:
        raise ValueError(f"browser evidence {field}.replacements MUST be non-negative")
    return BrowserRedactionEntry(
        surface=cast(Literal["screenshot", "visible_text", "aria_snapshot"], surface),
        rule=rule,
        replacements=replacements,
    )


def _boolean(value: Mapping[str, object], field: str) -> bool:
    return _exact_bool(value[field], f"isolation.{field}")


def _exact_bool(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"browser evidence {field} MUST be a boolean")
    return value


__all__ = [
    "PostgresBrowserEvidenceArtifactStore",
    "PostgresBrowserEvidenceArtifactStoreConfig",
]
