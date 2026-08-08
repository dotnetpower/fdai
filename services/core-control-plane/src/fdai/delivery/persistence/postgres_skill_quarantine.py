"""PostgreSQL persistence for skill quarantine and revocation provenance."""

# ruff: noqa: S608 - SQL identifiers are module constants; runtime values are parametrized.

from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime
from typing import Any, Final

from fdai.core.supply_chain.skill_quarantine import (
    QuarantinedSkillArtifact,
    QuarantinedSkillFile,
    SkillQuarantineState,
    SkillRevocation,
    SkillScanFinding,
    SkillScanSeverity,
    SkillScanVerdict,
    SkillUpdateCandidate,
)
from fdai.core.supply_chain.skill_source_admin import SkillSourceRevocationResult
from fdai.delivery.persistence.postgres_skill_source import (
    PostgresSkillSourceStoreConfig,
    _PostgresSkillSourceBase,
)

_QUARANTINE_COLUMNS: Final = (
    "quarantine_id, source_id, source_revision, artifact_digest, files, "
    "publisher_signature, fetched_at, scanner_version, findings, verdict, state, "
    "prior_installed_digest"
)
_CANDIDATE_COLUMNS: Final = (
    "candidate_id, quarantine_id, artifact_digest, prior_installed_digest, created_at, disabled"
)
_REVOCATION_COLUMNS: Final = "revocation_id, source_id, artifact_digest, reason, revoked_at"


class PostgresSkillQuarantineStore(_PostgresSkillSourceBase):
    def __init__(self, *, config: PostgresSkillSourceStoreConfig) -> None:
        super().__init__(config=config)

    async def put(self, artifact: QuarantinedSkillArtifact) -> QuarantinedSkillArtifact:
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            cursor = await connection.execute(
                f"INSERT INTO skill_quarantine ({_QUARANTINE_COLUMNS}) "
                "VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s::jsonb, %s, %s, %s) "
                "ON CONFLICT (quarantine_id) DO UPDATE SET "
                "scanner_version = EXCLUDED.scanner_version, findings = EXCLUDED.findings, "
                "verdict = EXCLUDED.verdict, state = EXCLUDED.state, "
                "prior_installed_digest = EXCLUDED.prior_installed_digest "
                "WHERE skill_quarantine.artifact_digest = EXCLUDED.artifact_digest "
                "AND (skill_quarantine.state <> 'revoked' OR EXCLUDED.state = 'revoked') "
                f"RETURNING {_QUARANTINE_COLUMNS}",
                _artifact_values(artifact),
            )
            row = await cursor.fetchone()
        if row is None:
            raise ValueError("quarantine id conflicts with different content")
        return _artifact_from_row(row)

    async def get(self, quarantine_id: str) -> QuarantinedSkillArtifact | None:
        async with await self._connect() as connection:
            await self._timeout(connection)
            cursor = await connection.execute(
                f"SELECT {_QUARANTINE_COLUMNS} FROM skill_quarantine WHERE quarantine_id = %s",
                (quarantine_id,),
            )
            row = await cursor.fetchone()
        return _artifact_from_row(row) if row is not None else None

    async def list(self, *, source_id: str | None = None) -> tuple[QuarantinedSkillArtifact, ...]:
        where = " WHERE source_id = %s" if source_id is not None else ""
        params = (source_id,) if source_id is not None else ()
        async with await self._connect() as connection:
            await self._timeout(connection)
            cursor = await connection.execute(
                f"SELECT {_QUARANTINE_COLUMNS} FROM skill_quarantine{where} "
                "ORDER BY fetched_at, quarantine_id",
                params,
            )
            rows = await cursor.fetchall()
        return tuple(_artifact_from_row(row) for row in rows)

    async def mark_revoked(
        self, *, source_id: str, artifact_digest: str | None = None
    ) -> tuple[QuarantinedSkillArtifact, ...]:
        digest_clause = " AND artifact_digest = %s" if artifact_digest is not None else ""
        params: tuple[object, ...] = (
            (source_id, artifact_digest) if artifact_digest is not None else (source_id,)
        )
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            cursor = await connection.execute(
                "UPDATE skill_quarantine SET state = 'revoked' WHERE source_id = %s"
                f"{digest_clause} RETURNING {_QUARANTINE_COLUMNS}",
                params,
            )
            rows = await cursor.fetchall()
        return tuple(_artifact_from_row(row) for row in rows)


class PostgresSkillUpdateCandidateStore(_PostgresSkillSourceBase):
    async def put(self, candidate: SkillUpdateCandidate) -> SkillUpdateCandidate:
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            cursor = await connection.execute(
                f"INSERT INTO skill_update_candidate ({_CANDIDATE_COLUMNS}) "
                "VALUES (%s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (candidate_id) DO NOTHING "
                f"RETURNING {_CANDIDATE_COLUMNS}",
                _candidate_values(candidate),
            )
            row = await cursor.fetchone()
            if row is None:
                current = await connection.execute(
                    f"SELECT {_CANDIDATE_COLUMNS} FROM skill_update_candidate "
                    "WHERE candidate_id = %s",
                    (candidate.candidate_id,),
                )
                row = await current.fetchone()
        if row is None or _candidate_from_row(row) != candidate:
            raise ValueError("candidate id conflicts with different content")
        return candidate

    async def get(self, candidate_id: str) -> SkillUpdateCandidate | None:
        async with await self._connect() as connection:
            await self._timeout(connection)
            cursor = await connection.execute(
                f"SELECT {_CANDIDATE_COLUMNS} FROM skill_update_candidate WHERE candidate_id = %s",
                (candidate_id,),
            )
            row = await cursor.fetchone()
        return _candidate_from_row(row) if row is not None else None

    async def list(self, *, source_id: str | None = None) -> tuple[SkillUpdateCandidate, ...]:
        join = ""
        where = ""
        params: tuple[object, ...] = ()
        if source_id is not None:
            join = " JOIN skill_quarantine q ON q.quarantine_id = c.quarantine_id"
            where = " WHERE q.source_id = %s"
            params = (source_id,)
        async with await self._connect() as connection:
            await self._timeout(connection)
            cursor = await connection.execute(
                f"SELECT {', '.join(f'c.{item}' for item in _CANDIDATE_COLUMNS.split(', '))} "
                f"FROM skill_update_candidate c{join}{where} "
                "ORDER BY c.created_at, c.candidate_id",
                params,
            )
            rows = await cursor.fetchall()
        return tuple(_candidate_from_row(row) for row in rows)


class PostgresSkillRevocationStore(_PostgresSkillSourceBase):
    async def put(self, revocation: SkillRevocation) -> SkillRevocation:
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            cursor = await connection.execute(
                f"INSERT INTO skill_revocation ({_REVOCATION_COLUMNS}) "
                "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (revocation_id) DO NOTHING "
                f"RETURNING {_REVOCATION_COLUMNS}",
                _revocation_values(revocation),
            )
            row = await cursor.fetchone()
            if row is None:
                current = await connection.execute(
                    f"SELECT {_REVOCATION_COLUMNS} FROM skill_revocation WHERE revocation_id = %s",
                    (revocation.revocation_id,),
                )
                row = await current.fetchone()
        if row is None or _revocation_from_row(row) != revocation:
            raise ValueError("revocation id conflicts with different content")
        return revocation

    async def list(self, *, source_id: str | None = None) -> tuple[SkillRevocation, ...]:
        where = " WHERE source_id = %s" if source_id is not None else ""
        params = (source_id,) if source_id is not None else ()
        async with await self._connect() as connection:
            await self._timeout(connection)
            cursor = await connection.execute(
                f"SELECT {_REVOCATION_COLUMNS} FROM skill_revocation{where} "
                "ORDER BY revoked_at, revocation_id",
                params,
            )
            rows = await cursor.fetchall()
        return tuple(_revocation_from_row(row) for row in rows)

    async def is_revoked(self, *, source_id: str, artifact_digest: str) -> bool:
        async with await self._connect() as connection:
            await self._timeout(connection)
            cursor = await connection.execute(
                "SELECT 1 FROM skill_revocation WHERE source_id = %s "
                "AND artifact_digest = %s LIMIT 1",
                (source_id, artifact_digest),
            )
            return await cursor.fetchone() is not None


class PostgresSkillSourceRevoker(_PostgresSkillSourceBase):
    async def revoke_source(
        self, *, source_id: str, reason: str, revoked_at: datetime
    ) -> SkillSourceRevocationResult:
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            source_cursor = await connection.execute(
                "UPDATE skill_source SET enabled = FALSE, updated_at = %s "
                "WHERE source_id = %s RETURNING source_id",
                (revoked_at, source_id),
            )
            if await source_cursor.fetchone() is None:
                raise LookupError("skill source not found")
            quarantine_cursor = await connection.execute(
                "UPDATE skill_quarantine SET state = 'revoked' WHERE source_id = %s "
                "RETURNING artifact_digest",
                (source_id,),
            )
            quarantine_digests = {
                str(row["artifact_digest"]) for row in await quarantine_cursor.fetchall()
            }
            installed_cursor = await connection.execute(
                "SELECT artifact_id, content_sha256 FROM trusted_artifact "
                "WHERE artifact_kind = 'skill' AND source = %s ORDER BY artifact_id",
                (source_id,),
            )
            installed_rows = await installed_cursor.fetchall()
            await connection.execute(
                "UPDATE trusted_artifact SET state = 'disabled', revision = revision + 1, "
                "updated_at = %s WHERE artifact_kind = 'skill' AND source = %s "
                "AND state <> 'disabled'",
                (revoked_at, source_id),
            )
            digests = tuple(
                sorted(quarantine_digests | {str(row["content_sha256"]) for row in installed_rows})
            )
            for digest in digests:
                revocation_id = _revocation_id(source_id, digest)
                await connection.execute(
                    f"INSERT INTO skill_revocation ({_REVOCATION_COLUMNS}) "
                    "VALUES (%s, %s, %s, %s, %s) "
                    "ON CONFLICT (revocation_id) DO NOTHING",
                    (revocation_id, source_id, digest, reason, revoked_at),
                )
        return SkillSourceRevocationResult(
            source_id=source_id,
            revoked_digests=digests,
            disabled_artifact_ids=tuple(str(row["artifact_id"]) for row in installed_rows),
        )


def _artifact_values(artifact: QuarantinedSkillArtifact) -> tuple[object, ...]:
    return (
        artifact.quarantine_id,
        artifact.source_id,
        artifact.source_revision,
        artifact.artifact_digest,
        _files_json(artifact.files),
        artifact.publisher_signature,
        artifact.fetched_at,
        artifact.scanner_version,
        _findings_json(artifact.findings),
        artifact.verdict.value if artifact.verdict is not None else None,
        artifact.state.value,
        artifact.prior_installed_digest,
    )


def _artifact_from_row(row: dict[str, Any]) -> QuarantinedSkillArtifact:
    return QuarantinedSkillArtifact(
        quarantine_id=str(row["quarantine_id"]),
        source_id=str(row["source_id"]),
        source_revision=str(row["source_revision"]),
        artifact_digest=str(row["artifact_digest"]),
        files=_files(row["files"]),
        publisher_signature=bytes(row["publisher_signature"]),
        fetched_at=row["fetched_at"],
        scanner_version=(
            str(row["scanner_version"]) if row["scanner_version"] is not None else None
        ),
        findings=_findings(row["findings"]),
        verdict=SkillScanVerdict(str(row["verdict"])) if row["verdict"] is not None else None,
        state=SkillQuarantineState(str(row["state"])),
        prior_installed_digest=(
            str(row["prior_installed_digest"])
            if row["prior_installed_digest"] is not None
            else None
        ),
    )


def _files_json(files: tuple[QuarantinedSkillFile, ...]) -> str:
    return json.dumps(
        [
            {
                "path": item.path,
                "content_sha256": item.content_sha256,
                "content_base64": base64.b64encode(item.content).decode("ascii"),
                "media_type": item.media_type,
                "is_symlink": item.is_symlink,
            }
            for item in files
        ],
        sort_keys=True,
    )


def _files(raw: Any) -> tuple[QuarantinedSkillFile, ...]:
    values = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(values, list):
        raise ValueError("skill quarantine files MUST be a JSON array")
    return tuple(
        QuarantinedSkillFile(
            path=str(item["path"]),
            content_sha256=str(item["content_sha256"]),
            content=base64.b64decode(str(item["content_base64"]), validate=True),
            media_type=str(item["media_type"]),
            is_symlink=bool(item["is_symlink"]),
        )
        for item in values
    )


def _findings_json(findings: tuple[SkillScanFinding, ...]) -> str:
    return json.dumps(
        [
            {
                "scanner": item.scanner,
                "code": item.code,
                "severity": item.severity.value,
                "path": item.path,
                "detail": item.detail,
            }
            for item in findings
        ],
        sort_keys=True,
    )


def _findings(raw: Any) -> tuple[SkillScanFinding, ...]:
    values = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(values, list):
        raise ValueError("skill quarantine findings MUST be a JSON array")
    return tuple(
        SkillScanFinding(
            scanner=str(item["scanner"]),
            code=str(item["code"]),
            severity=SkillScanSeverity(str(item["severity"])),
            path=str(item["path"]),
            detail=str(item["detail"]),
        )
        for item in values
    )


def _candidate_values(candidate: SkillUpdateCandidate) -> tuple[object, ...]:
    return (
        candidate.candidate_id,
        candidate.quarantine_id,
        candidate.artifact_digest,
        candidate.prior_installed_digest,
        candidate.created_at,
        candidate.disabled,
    )


def _candidate_from_row(row: dict[str, Any]) -> SkillUpdateCandidate:
    return SkillUpdateCandidate(
        candidate_id=str(row["candidate_id"]),
        quarantine_id=str(row["quarantine_id"]),
        artifact_digest=str(row["artifact_digest"]),
        prior_installed_digest=(
            str(row["prior_installed_digest"])
            if row["prior_installed_digest"] is not None
            else None
        ),
        created_at=row["created_at"],
        disabled=bool(row["disabled"]),
    )


def _revocation_values(revocation: SkillRevocation) -> tuple[object, ...]:
    return (
        revocation.revocation_id,
        revocation.source_id,
        revocation.artifact_digest,
        revocation.reason,
        revocation.revoked_at,
    )


def _revocation_from_row(row: dict[str, Any]) -> SkillRevocation:
    return SkillRevocation(
        revocation_id=str(row["revocation_id"]),
        source_id=str(row["source_id"]),
        artifact_digest=str(row["artifact_digest"]),
        reason=str(row["reason"]),
        revoked_at=row["revoked_at"],
    )


def _revocation_id(source_id: str, artifact_digest: str) -> str:
    digest = hashlib.sha256(f"{source_id}\0{artifact_digest}".encode()).hexdigest()
    return f"skill-revocation-{digest[:24]}"


__all__ = [
    "PostgresSkillQuarantineStore",
    "PostgresSkillRevocationStore",
    "PostgresSkillSourceRevoker",
    "PostgresSkillUpdateCandidateStore",
]
