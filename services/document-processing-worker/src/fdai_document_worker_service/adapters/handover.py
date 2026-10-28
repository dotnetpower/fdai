"""Durable PostgreSQL storage for worker-produced handover drafts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Literal, cast
from uuid import UUID

import psycopg
from fdai_service_contracts import (
    HandoverDraftArtifact,
    StewardDuty,
    StewardKind,
    StewardResponsibility,
    StewardshipAgentInput,
    StewardshipInput,
    StewardshipSubject,
)

_COVERAGE_PROJECTION_KEY = "operator-projection:operations:stewardship.coverage"


def stewardship_input_from_projection(projection: object) -> StewardshipInput | None:
    """Project the Core-materialized stewardship coverage record into a worker baseline."""
    if not isinstance(projection, Mapping):
        return None
    raw_map = projection.get("map")
    if not isinstance(raw_map, Mapping):
        return None
    raw_version = raw_map.get("version", 1)
    if isinstance(raw_version, bool) or raw_version not in {1, 2}:
        return None
    version = cast(Literal[1, 2], raw_version)
    raw_maintainers = raw_map.get("maintainers")
    if not isinstance(raw_maintainers, list):
        return None
    maintainers = tuple(
        str(item).strip() for item in raw_maintainers if isinstance(item, str) and item.strip()
    )
    if not maintainers:
        return None
    raw_agents = raw_map.get("agents")
    if not isinstance(raw_agents, list):
        return None
    agents: list[StewardshipAgentInput] = []
    for entry in raw_agents:
        if not isinstance(entry, Mapping):
            return None
        name = str(entry.get("name") or "").strip()
        if not name:
            return None
        raw_stewards = entry.get("stewards")
        if not isinstance(raw_stewards, list):
            return None
        stewards: list[StewardshipSubject] = []
        for subject in raw_stewards:
            if not isinstance(subject, Mapping):
                return None
            oid = str(subject.get("id") or subject.get("oid") or "").strip()
            kind = str(subject.get("kind") or "").strip()
            responsibility = str(subject.get("responsibility") or "").strip()
            raw_duty = subject.get("duty")
            duty_str = str(raw_duty).strip() if isinstance(raw_duty, str) else ""
            if not oid or not kind or not responsibility:
                return None
            try:
                stewards.append(
                    StewardshipSubject(
                        kind=StewardKind(kind),
                        oid=oid,
                        responsibility=StewardResponsibility(responsibility),
                        duty=(
                            StewardDuty(duty_str)
                            if version == 2
                            and duty_str
                            and responsibility == StewardResponsibility.ACCOUNTABLE
                            else None
                        ),
                    )
                )
            except ValueError:
                return None
        raw_reason = entry.get("accept_autonomous_reason")
        reason = (
            raw_reason.strip()
            if isinstance(raw_reason, str) and raw_reason.strip() and not stewards
            else None
        )
        agents.append(
            StewardshipAgentInput(
                agent_name=name,
                stewards=tuple(stewards),
                accept_autonomous_reason=reason,
            )
        )
    hop_timeout = raw_map.get("hop_timeout_seconds", 900)
    over_assigned = raw_map.get("over_assigned_max", 5)
    canonical = json.dumps(
        {
            "version": version,
            "maintainers": maintainers,
            "agents": [item.model_dump(mode="json") for item in agents],
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    try:
        return StewardshipInput(
            version=version,
            revision=hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16],
            maintainers=maintainers,
            agents=tuple(agents),
            hop_timeout_seconds=(
                hop_timeout
                if isinstance(hop_timeout, int) and not isinstance(hop_timeout, bool)
                else 900
            ),
            over_assigned_max=(
                over_assigned
                if isinstance(over_assigned, int) and not isinstance(over_assigned, bool)
                else 5
            ),
        )
    except ValueError:
        return None


class PostgresHandoverDraftStore:
    """Upsert a review-only draft into the shared state projection."""

    def __init__(self, *, dsn: str, connect_timeout_s: int = 10) -> None:
        if not dsn:
            raise ValueError("handover draft PostgreSQL DSN MUST NOT be empty")
        if connect_timeout_s < 1:
            raise ValueError("handover draft connect timeout MUST be positive")
        self._dsn = dsn
        self._connect_timeout_s = connect_timeout_s

    async def put(self, artifact: HandoverDraftArtifact) -> None:
        async with await psycopg.AsyncConnection.connect(
            self._dsn,
            connect_timeout=self._connect_timeout_s,
        ) as connection:
            await connection.execute(
                "INSERT INTO state_kv (key, value) VALUES (%s, %s::jsonb) "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                (
                    f"handover_draft:{artifact.upload_id}",
                    json.dumps(artifact.to_dict(), separators=(",", ":")),
                ),
            )

    async def reserve_model_calls(
        self,
        *,
        document_id: UUID,
        version_id: UUID,
        source_sha256: str,
    ) -> bool:
        """Reserve two calls once for the exact document version without restart refunds."""
        key = f"handover_draft:model-budget:{document_id}:{version_id}"
        reservation = {
            "schema_version": "1.0.0",
            "document_id": str(document_id),
            "version_id": str(version_id),
            "source_sha256": source_sha256,
            "reserved_calls": 2,
            "execution_authority": False,
        }
        async with await psycopg.AsyncConnection.connect(
            self._dsn,
            connect_timeout=self._connect_timeout_s,
        ) as connection:
            row = await (
                await connection.execute(
                    "INSERT INTO state_kv (key, value) VALUES (%s, %s::jsonb) "
                    "ON CONFLICT (key) DO NOTHING RETURNING key",
                    (key, json.dumps(reservation, separators=(",", ":"))),
                )
            ).fetchone()
        return row is not None

    async def get(self, upload_id: UUID) -> HandoverDraftArtifact | None:
        """Replay only an exact existing upload draft, never re-run its model."""
        async with await psycopg.AsyncConnection.connect(
            self._dsn,
            connect_timeout=self._connect_timeout_s,
        ) as connection:
            row = await (
                await connection.execute(
                    "SELECT value FROM state_kv WHERE key = %s",
                    (f"handover_draft:{upload_id}",),
                )
            ).fetchone()
        if row is None:
            return None
        return HandoverDraftArtifact.model_validate(row[0])

    async def read_stewardship_input(self) -> StewardshipInput | None:
        """Read the authoritative Core-materialized stewardship map when env bindings are absent."""
        async with await psycopg.AsyncConnection.connect(
            self._dsn,
            connect_timeout=self._connect_timeout_s,
        ) as connection:
            row = await (
                await connection.execute(
                    "SELECT value FROM state_kv WHERE key = %s",
                    (_COVERAGE_PROJECTION_KEY,),
                )
            ).fetchone()
        if row is None:
            return None
        return stewardship_input_from_projection(row[0])

    async def record_model_usage(
        self,
        *,
        document_id: UUID,
        version_id: UUID,
        stage: str,
        prompt_tokens: int,
        completion_tokens: int,
        cost_micros: int,
        pricing_sha256: str,
    ) -> None:
        """Retain measured author/reviewer cost even when interpretation is rejected."""
        if stage not in {"author", "reviewer"}:
            raise ValueError("handover model usage stage is invalid")
        key = f"handover_draft:model-budget:{document_id}:{version_id}"
        measured = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "cost_micros": cost_micros,
            "pricing_sha256": pricing_sha256,
        }
        async with await psycopg.AsyncConnection.connect(
            self._dsn,
            connect_timeout=self._connect_timeout_s,
        ) as connection:
            row = await (
                await connection.execute(
                    "UPDATE state_kv SET value = jsonb_set(value, ARRAY[%s], %s::jsonb) "
                    "WHERE key = %s AND value->>'reserved_calls' = '2' "
                    "AND NOT (value ? %s) RETURNING key",
                    (stage, json.dumps(measured, separators=(",", ":")), key, stage),
                )
            ).fetchone()
        if row is None:
            raise ValueError("handover measured usage cannot replace an existing call receipt")
