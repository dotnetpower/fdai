"""Independent readback for one full-subscription inventory generation."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import psycopg
from fdai_service_contracts.inventory_progress import (
    InventoryClosureReceipt,
    InventoryProgressRecord,
    inventory_closure_receipt_digest,
)
from psycopg.rows import dict_row

from fdai.delivery.inventory_progress import INVENTORY_PROGRESS_GENESIS_DIGEST
from fdai.shared.providers.inventory import UNCLASSIFIED_RESOURCE_TYPE

_MAX_PROGRESS_RECORDS = 100_000


@dataclass(frozen=True, slots=True)
class PostgresInventoryClosureVerifierConfig:
    """Read-only connection and bound settings for closure verification."""

    dsn: str
    statement_timeout_ms: int = 15_000
    connect_timeout_s: int = 10

    def __post_init__(self) -> None:
        if not self.dsn:
            raise ValueError("inventory closure PostgreSQL DSN MUST NOT be empty")
        if self.statement_timeout_ms < 1 or self.connect_timeout_s < 1:
            raise ValueError("inventory closure PostgreSQL timeouts MUST be positive")


class PostgresInventoryClosureVerifier:
    """Read the active generation independently and fail closed on incomplete coverage."""

    def __init__(self, *, config: PostgresInventoryClosureVerifierConfig) -> None:
        self._config = config

    async def latest_progress(self, *, run_id: str, attempt_id: str) -> InventoryProgressRecord:
        """Return and validate the latest retained chain record for finalization."""

        async with await self._connect() as connection:
            await connection.set_read_only(True)
            cursor = await connection.execute(
                "SELECT payload FROM inventory_progress_event "
                "WHERE run_id=%s AND attempt_id=%s ORDER BY sequence ASC LIMIT %s",
                (run_id, attempt_id, _MAX_PROGRESS_RECORDS + 1),
            )
            rows = await cursor.fetchall()
        if not rows:
            raise ValueError("inventory closure progress record is unavailable")
        if len(rows) > _MAX_PROGRESS_RECORDS:
            raise ValueError("inventory closure progress chain exceeds its bound")
        previous = INVENTORY_PROGRESS_GENESIS_DIGEST
        records: list[InventoryProgressRecord] = []
        for expected_sequence, row in enumerate(rows, start=1):
            try:
                record = InventoryProgressRecord.model_validate(row["payload"])
            except (TypeError, ValueError) as exc:
                raise ValueError("inventory closure progress record is invalid") from exc
            if record.sequence != expected_sequence or record.previous_digest != previous:
                raise ValueError("inventory closure progress chain is invalid")
            previous = record.record_digest
            records.append(record)
        return records[-1]

    async def verify(self, *, run_id: str, attempt_id: str) -> InventoryClosureReceipt:
        progress_record = await self.latest_progress(run_id=run_id, attempt_id=attempt_id)
        async with await self._connect() as connection:
            await connection.set_read_only(True)
            async with connection.transaction():
                await connection.execute(
                    "SELECT set_config('statement_timeout', %s, true)",
                    (str(self._config.statement_timeout_ms),),
                )
                active = await (
                    await connection.execute(
                        "SELECT s.id, s.status, s.source, s.observation_kind, s.scopes, "
                        "s.resource_types, s.metadata, s.promoted_at, "
                        "(SELECT COUNT(*) FROM inventory_snapshot_resource r "
                        " WHERE r.snapshot_id=s.id) AS resource_count, "
                        "(SELECT COUNT(*) FROM inventory_snapshot_link l "
                        " WHERE l.snapshot_id=s.id) AS link_count, "
                        "(SELECT COUNT(*) FROM inventory_snapshot_resource r "
                        " WHERE r.snapshot_id=s.id AND r.resource_type=%s) AS unmapped_count, "
                        "(SELECT COUNT(*) FROM inventory_realtime_resource) AS overlay_count, "
                        "(SELECT value FROM state_kv "
                        " WHERE key='inventory-observation:watermarks') AS watermarks "
                        "FROM inventory_active a JOIN inventory_snapshot s ON s.id=a.snapshot_id "
                        "WHERE a.singleton=TRUE",
                        (UNCLASSIFIED_RESOURCE_TYPE,),
                    )
                ).fetchone()
        if active is None:
            raise ValueError("inventory closure evidence is unavailable")
        metadata = _mapping(active["metadata"], "inventory metadata")
        coverage = _mapping(metadata.get("provider_scope_coverage"), "provider scope coverage")
        watermarks = _mapping(active["watermarks"], "inventory projection watermarks")
        derived = metadata.get("derived_source_states")
        if not isinstance(derived, list):
            raise ValueError("inventory closure child-source evidence is unavailable")
        child_sources_complete = all(
            isinstance(item, Mapping) and item.get("status") in {"available", "unavailable"}
            for item in derived
        )
        started_at = progress_record.started_at
        promoted_at = active["promoted_at"]
        coverage_gaps = len(metadata.get("relationship_drop_reasons", []))
        conditions = {
            "verified_progress": (
                (
                    progress_record.state.value == "running"
                    and progress_record.stage.value == "verify"
                    and progress_record.fraction < 1.0
                )
                or (
                    progress_record.state.value == "complete"
                    and progress_record.stage.value == "complete"
                    and progress_record.fraction == 1.0
                )
            ),
            "active": active["status"] == "active",
            "active_generation": progress_record.generation_digest
            == "sha256:" + hashlib.sha256(str(active["id"]).encode("utf-8")).hexdigest(),
            "observed": active["observation_kind"] == "observed",
            "source": active["source"] in {"arg", "arm"},
            "single_scope": isinstance(active["scopes"], list) and len(active["scopes"]) == 1,
            "full_scope": metadata.get("coverage_scope") == "full_provider_scope",
            "provider_coverage": coverage.get("provider_identity_complete") is True,
            "unmapped_reconciled": (
                int(coverage.get("materialized_unmapped_provider_object_count", -1))
                == int(active["unmapped_count"])
            ),
            "overlay_closed": int(active["overlay_count"]) == 0,
            "child_sources": child_sources_complete,
            "projection": (
                watermarks.get("ontology_generation") == active["id"]
                and int(watermarks.get("ontology_projection_watermark", -1))
                == int(watermarks.get("journal_high_watermark", -2))
            ),
            "fresh_generation": isinstance(promoted_at, datetime) and promoted_at >= started_at,
        }
        failed = sorted(name for name, passed in conditions.items() if not passed)
        if failed:
            raise ValueError("inventory closure verification failed: " + ",".join(failed))
        observed_at = datetime.now(tz=UTC)
        values: dict[str, object] = {
            "run_id": run_id,
            "attempt_id": attempt_id,
            "generation_digest": "sha256:"
            + hashlib.sha256(str(active["id"]).encode("utf-8")).hexdigest(),
            "subscription_root": True,
            "resource_type_filter": False,
            "final_fence": True,
            "provider_coverage_complete": True,
            "truncated": False,
            "active_generation_matches": True,
            "overlay_open": False,
            "child_sources_complete": True,
            "observer_distinct": True,
            "resource_count": int(active["resource_count"]),
            "link_count": int(active["link_count"]),
            "unmapped_object_count": int(active["unmapped_count"]),
            "coverage_gap_count": coverage_gaps,
            "observed_at": observed_at,
        }
        return InventoryClosureReceipt(
            run_id=run_id,
            attempt_id=attempt_id,
            generation_digest=str(values["generation_digest"]),
            subscription_root=True,
            resource_type_filter=False,
            final_fence=True,
            provider_coverage_complete=True,
            truncated=False,
            active_generation_matches=True,
            overlay_open=False,
            child_sources_complete=True,
            observer_distinct=True,
            resource_count=int(active["resource_count"]),
            link_count=int(active["link_count"]),
            unmapped_object_count=int(active["unmapped_count"]),
            coverage_gap_count=coverage_gaps,
            observed_at=observed_at,
            receipt_digest=inventory_closure_receipt_digest(**values),
        )

    async def _connect(self) -> psycopg.AsyncConnection[dict[str, Any]]:
        return await psycopg.AsyncConnection.connect(
            self._config.dsn,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        )


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} MUST be an object")
    return value


__all__ = ["PostgresInventoryClosureVerifier", "PostgresInventoryClosureVerifierConfig"]
