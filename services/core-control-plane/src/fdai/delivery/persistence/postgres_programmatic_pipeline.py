"""PostgreSQL receipt and aggregate store for programmatic pipelines."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fdai.core.programmatic_pipeline.models import (
    ProgrammaticCallStatus,
    ProgrammaticPipelineCallReceipt,
    ProgrammaticPipelineStats,
    ProgrammaticPipelineStatus,
    ProgrammaticToolPipelineResult,
)


@dataclass(frozen=True, slots=True)
class PostgresProgrammaticPipelineStoreConfig:
    dsn: str
    statement_timeout_ms: int = 15_000
    connect_timeout_s: int = 10

    def __post_init__(self) -> None:
        if not self.dsn:
            raise ValueError("PostgresProgrammaticPipelineStoreConfig.dsn MUST NOT be empty")
        if self.statement_timeout_ms < 1 or self.connect_timeout_s < 1:
            raise ValueError("Postgres programmatic pipeline timeouts MUST be positive")


class PostgresProgrammaticPipelineStore:
    def __init__(self, *, config: PostgresProgrammaticPipelineStoreConfig) -> None:
        self._config = config

    async def append_call(self, receipt: ProgrammaticPipelineCallReceipt) -> None:
        payload = json.dumps(_receipt_to_dict(receipt), separators=(",", ":"))
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            cursor = await connection.execute(
                "INSERT INTO programmatic_pipeline_call "
                "(run_id, call_id, sequence, tool_id, status, receipt, recorded_at) "
                "VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s) "
                "ON CONFLICT (run_id, call_id) DO NOTHING RETURNING receipt",
                (
                    receipt.run_id,
                    receipt.call_id,
                    receipt.sequence,
                    receipt.tool_id,
                    receipt.status.value,
                    payload,
                    receipt.finished_at,
                ),
            )
            row = await cursor.fetchone()
            if row is None:
                existing = await connection.execute(
                    "SELECT receipt FROM programmatic_pipeline_call "
                    "WHERE run_id = %s AND call_id = %s",
                    (receipt.run_id, receipt.call_id),
                )
                row = await existing.fetchone()
        if row is None or _receipt_from_dict(_mapping(row["receipt"])) != receipt:
            raise ValueError("pipeline call receipt conflicts with an existing row")

    async def complete(
        self,
        *,
        idempotency_key: str,
        result: ProgrammaticToolPipelineResult,
    ) -> None:
        payload = json.dumps(_result_to_dict(result), separators=(",", ":"))
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            cursor = await connection.execute(
                "INSERT INTO programmatic_pipeline_run "
                "(idempotency_key, run_id, source_digest, status, result) "
                "VALUES (%s, %s, %s, %s, %s::jsonb) "
                "ON CONFLICT (idempotency_key) DO NOTHING RETURNING result",
                (
                    idempotency_key,
                    result.run_id,
                    result.source_digest,
                    result.status.value,
                    payload,
                ),
            )
            row = await cursor.fetchone()
            if row is None:
                existing = await connection.execute(
                    "SELECT result FROM programmatic_pipeline_run WHERE idempotency_key = %s",
                    (idempotency_key,),
                )
                row = await existing.fetchone()
        if row is None or _result_from_dict(_mapping(row["result"])) != result:
            raise ValueError("pipeline idempotency key conflicts with another result")

    async def result_for(self, idempotency_key: str) -> ProgrammaticToolPipelineResult | None:
        async with await self._connect() as connection:
            await self._timeout(connection)
            cursor = await connection.execute(
                "SELECT result FROM programmatic_pipeline_run WHERE idempotency_key = %s",
                (idempotency_key,),
            )
            row = await cursor.fetchone()
        return _result_from_dict(_mapping(row["result"])) if row is not None else None

    async def calls_for(self, run_id: str) -> tuple[ProgrammaticPipelineCallReceipt, ...]:
        async with await self._connect() as connection:
            await self._timeout(connection)
            cursor = await connection.execute(
                "SELECT receipt FROM programmatic_pipeline_call "
                "WHERE run_id = %s ORDER BY sequence",
                (run_id,),
            )
            rows = await cursor.fetchall()
        return tuple(_receipt_from_dict(_mapping(row["receipt"])) for row in rows)

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


def _receipt_to_dict(value: ProgrammaticPipelineCallReceipt) -> dict[str, object]:
    return {
        "run_id": value.run_id,
        "call_id": value.call_id,
        "tool_id": value.tool_id,
        "sequence": value.sequence,
        "status": value.status.value,
        "input_digest": value.input_digest,
        "output_digest": value.output_digest,
        "receipt_ref": value.receipt_ref,
        "started_at": value.started_at.isoformat(),
        "finished_at": value.finished_at.isoformat(),
        "latency_ms": value.latency_ms,
        "input_bytes": value.input_bytes,
        "output_bytes": value.output_bytes,
        "error_code": value.error_code,
    }


def _receipt_from_dict(raw: dict[str, Any]) -> ProgrammaticPipelineCallReceipt:
    return ProgrammaticPipelineCallReceipt(
        run_id=str(raw["run_id"]),
        call_id=str(raw["call_id"]),
        tool_id=str(raw["tool_id"]),
        sequence=int(raw["sequence"]),
        status=ProgrammaticCallStatus(str(raw["status"])),
        input_digest=str(raw["input_digest"]),
        output_digest=(str(raw["output_digest"]) if raw.get("output_digest") is not None else None),
        receipt_ref=str(raw["receipt_ref"]),
        started_at=datetime.fromisoformat(str(raw["started_at"])),
        finished_at=datetime.fromisoformat(str(raw["finished_at"])),
        latency_ms=int(raw["latency_ms"]),
        input_bytes=int(raw["input_bytes"]),
        output_bytes=int(raw["output_bytes"]),
        error_code=str(raw["error_code"]) if raw.get("error_code") is not None else None,
    )


def _result_to_dict(value: ProgrammaticToolPipelineResult) -> dict[str, object]:
    stats = value.stats
    return {
        "run_id": value.run_id,
        "status": value.status.value,
        "source_digest": value.source_digest,
        "stdout": value.stdout,
        "stderr": value.stderr,
        "final_json": value.final_json,
        "receipt_refs": list(value.receipt_refs),
        "stats": {
            "tool_calls": stats.tool_calls,
            "succeeded_calls": stats.succeeded_calls,
            "failed_calls": stats.failed_calls,
            "input_bytes": stats.input_bytes,
            "output_bytes": stats.output_bytes,
            "duration_ms": stats.duration_ms,
        },
        "complete": value.complete,
        "detail": value.detail,
        "truncated": value.truncated,
    }


def _result_from_dict(raw: dict[str, Any]) -> ProgrammaticToolPipelineResult:
    stats = _mapping(raw["stats"])
    return ProgrammaticToolPipelineResult(
        run_id=str(raw["run_id"]),
        status=ProgrammaticPipelineStatus(str(raw["status"])),
        source_digest=str(raw["source_digest"]),
        stdout=str(raw["stdout"]),
        stderr=str(raw["stderr"]),
        final_json=str(raw["final_json"]) if raw.get("final_json") is not None else None,
        receipt_refs=tuple(str(item) for item in raw["receipt_refs"]),
        stats=ProgrammaticPipelineStats(
            tool_calls=int(stats["tool_calls"]),
            succeeded_calls=int(stats["succeeded_calls"]),
            failed_calls=int(stats["failed_calls"]),
            input_bytes=int(stats["input_bytes"]),
            output_bytes=int(stats["output_bytes"]),
            duration_ms=int(stats["duration_ms"]),
        ),
        complete=bool(raw["complete"]),
        detail=str(raw["detail"]) if raw.get("detail") is not None else None,
        truncated=bool(raw["truncated"]),
    )


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        decoded = json.loads(value)
        if isinstance(decoded, dict):
            return decoded
    raise RuntimeError("programmatic pipeline JSON column is not an object")


__all__ = [
    "PostgresProgrammaticPipelineStore",
    "PostgresProgrammaticPipelineStoreConfig",
]
