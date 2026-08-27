"""Authoritative active-inventory freshness receipts for planned-change assessment."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fdai.core.impact_analysis import (
    GraphFreshnessReceipt,
    build_graph_freshness_receipt,
)
from fdai.delivery.persistence.postgres_inventory_snapshot import (
    PostgresInventorySnapshotStoreConfig,
)

_PROMOTION_LOCK: Final[int] = 732_410_991
_REQUIRED_LINK_TYPES = frozenset({"contains", "attached_to", "depends_on"})


class PostgresGraphFreshnessReceiptSource:
    """Read one exact active generation under the inventory promotion lock."""

    def __init__(
        self,
        *,
        config: PostgresInventorySnapshotStoreConfig,
        ontology_release_digest: str,
    ) -> None:
        if not ontology_release_digest.startswith("sha256:") or len(ontology_release_digest) != 71:
            raise ValueError("ontology release digest MUST be a SHA-256 digest")
        self._config = config
        self._ontology_release_digest = ontology_release_digest

    async def resolve(self, *, target_ref: str) -> GraphFreshnessReceipt | None:
        """Return a content-addressed receipt, including explicit completeness gaps."""

        if not target_ref.strip():
            raise ValueError("graph freshness target MUST be non-empty")
        async with await psycopg.AsyncConnection.connect(
            self._config.dsn,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        ) as connection:
            async with connection.transaction():
                await connection.execute(
                    "SELECT set_config('statement_timeout', %s, true)",
                    (str(self._config.statement_timeout_ms),),
                )
                await connection.execute(
                    "SELECT pg_advisory_xact_lock_shared(%s)",
                    (_PROMOTION_LOCK,),
                )
                cursor = await connection.execute(
                    "SELECT s.id, s.observation_kind, s.metadata, s.completed_at, "
                    "a.updated_at, NOW() AS recorded_at, "
                    "EXISTS (SELECT 1 FROM inventory_realtime_resource d "
                    "WHERE d.resource_id=%s AND d.change_kind='upsert') OR ("
                    "EXISTS (SELECT 1 FROM inventory_snapshot_resource r "
                    "WHERE r.snapshot_id=s.id AND r.resource_id=%s) AND NOT EXISTS ("
                    "SELECT 1 FROM inventory_realtime_resource d WHERE d.resource_id=%s)) "
                    "AS resource_present, EXISTS ("
                    "SELECT 1 FROM inventory_realtime_resource d WHERE d.resource_id=%s"
                    ") AS realtime_pending, EXISTS (SELECT 1 FROM inventory_snapshot newer "
                    "WHERE newer.id<>s.id AND newer.started_at>s.completed_at AND ("
                    "newer.status='failed' OR (newer.status='collecting' AND "
                    "newer.started_at < NOW() - INTERVAL '30 minutes'))) AS newer_failure "
                    "FROM inventory_active a JOIN inventory_snapshot s ON s.id=a.snapshot_id "
                    "WHERE a.singleton=TRUE AND s.status='active'",
                    (target_ref, target_ref, target_ref, target_ref),
                )
                row = await cursor.fetchone()
        if row is None:
            return None
        return _receipt_from_row(
            row,
            target_ref=target_ref,
            ontology_release_digest=self._ontology_release_digest,
            freshness_budget=timedelta(seconds=self._config.freshness_budget_seconds),
        )


def _receipt_from_row(
    row: Mapping[str, Any],
    *,
    target_ref: str,
    ontology_release_digest: str,
    freshness_budget: timedelta,
) -> GraphFreshnessReceipt:
    source_generation = _text(row, "id")
    observed_at = _timestamp(row, "completed_at")
    recorded_at = _timestamp(row, "recorded_at")
    active_updated_at = _timestamp(row, "updated_at")
    metadata = _metadata(row.get("metadata"))
    conflicts = _completeness_gaps(row, metadata)
    graph_revision = _graph_revision(
        source_generation=source_generation,
        observed_at=observed_at,
        active_updated_at=active_updated_at,
        metadata=metadata,
    )
    truncated = bool(metadata.get("truncated") is True)
    if truncated:
        conflicts = (*conflicts, "inventory_truncated")
    normalized_conflicts = tuple(sorted(set(conflicts)))
    return build_graph_freshness_receipt(
        ontology_release_digest=ontology_release_digest,
        target_ref=target_ref,
        source_generation=source_generation,
        graph_revision=graph_revision,
        observed_at=observed_at,
        recorded_at=recorded_at,
        valid_until=observed_at + freshness_budget,
        complete=not normalized_conflicts,
        truncated=truncated,
        conflicts=normalized_conflicts,
    )


def _completeness_gaps(
    row: Mapping[str, Any],
    metadata: Mapping[str, Any],
) -> tuple[str, ...]:
    gaps: list[str] = []
    if row.get("resource_present") is not True:
        gaps.append("graph_target_missing")
    if row.get("realtime_pending") is True:
        gaps.append("graph_realtime_pending")
    if row.get("newer_failure") is True:
        gaps.append("newer_inventory_failure")
    if row.get("observation_kind") != "observed":
        gaps.append("graph_not_observed")
    if metadata.get("relationship_complete") is not True:
        gaps.append("graph_relationship_incomplete")
    link_types = metadata.get("link_types")
    if not isinstance(link_types, list) or not _REQUIRED_LINK_TYPES.issubset(
        item for item in link_types if isinstance(item, str)
    ):
        gaps.append("graph_link_coverage_incomplete")
    coverage = metadata.get("provider_scope_coverage")
    if not isinstance(coverage, Mapping) or coverage.get("provider_identity_complete") is not True:
        gaps.append("graph_provider_identity_incomplete")
    source_states = metadata.get("derived_source_states")
    if not isinstance(source_states, list) or any(
        not isinstance(item, Mapping) or item.get("status") != "available" for item in source_states
    ):
        gaps.append("graph_source_incomplete")
    return tuple(sorted(set(gaps)))


def _graph_revision(
    *,
    source_generation: str,
    observed_at: datetime,
    active_updated_at: datetime,
    metadata: Mapping[str, Any],
) -> str:
    encoded = json.dumps(
        {
            "source_generation": source_generation,
            "observed_at": observed_at.isoformat(),
            "active_updated_at": active_updated_at.isoformat(),
            "metadata": metadata,
        },
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _metadata(value: object) -> Mapping[str, Any]:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, Mapping):
        raise ValueError("inventory freshness metadata MUST be an object")
    return value


def _text(row: Mapping[str, Any], name: str) -> str:
    value = row.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"inventory freshness {name} MUST be non-empty")
    return value


def _timestamp(row: Mapping[str, Any], name: str) -> datetime:
    value = row.get(name)
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"inventory freshness {name} MUST be timezone-aware")
    return value


__all__ = ["PostgresGraphFreshnessReceiptSource"]
