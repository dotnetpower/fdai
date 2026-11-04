#!/usr/bin/env python3
"""Rehearse and verify coordinated runtime cutover for inventory shared storage (#2702).

Exercises all six Issue #2702 exit criteria on an isolated schema in the loopback
port-5433 validation PostgreSQL cluster (and provides deterministic unit helpers):
1. Select the exact runtime checkout/source and a coordinated stopped-reader/writer
   maintenance window with the runtime owner, verifying zero competing locks.
2. Verify reversible upgrade/downgrade migration on the selected scope before cutover.
3. Apply the storage migrations and verify exact schema state, replay, and least-privilege
   ``SET LOCAL ROLE fdai_core`` orphan cleanup without ``UPDATE`` privilege.
4. Measure existing-row conversion separately from prospective deduplication while
   retaining legacy/evidence data (and proving append-only deletion protection).
5. Supply a deployment-owned purpose, finite retention policy, applicable holds
   (canonical incident rows, Saga 512-row window, 512-row hot tail), verified zstd
   archive coverage, and full prefix+suffix restore certification.
6. Confirm zero binary/legacy cache payloads and preserve the retain-by-default boundary.
"""

from __future__ import annotations

import argparse
import ast
import asyncio
import hashlib
import json
import os
import re
import tempfile
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import psycopg
from fdai.delivery.inventory_sync import PromotedInventoryObservation
from fdai.delivery.persistence import PostgresStateStore, PostgresStateStoreConfig
from fdai.delivery.persistence.postgres_audit_history import AUDIT_ARCHIVE_ANCHOR_KEY
from fdai.delivery.persistence.postgres_inventory_observation_records import snapshot_records
from fdai.delivery.persistence.postgres_inventory_observation_write import append_records
from fdai.delivery.persistence.postgres_inventory_shared_membership import (
    canonical_json,
    content_digest,
)
from fdai.delivery.persistence.postgres_inventory_shared_properties import (
    prune_shared_properties,
)
from fdai.delivery.persistence.postgres_inventory_snapshot_membership import (
    load_snapshot_generation_records,
    store_snapshot_membership,
)
from fdai.delivery.persistence.postgres_inventory_snapshot_support import stage_snapshot_batch
from fdai.rule_catalog.schema.zstd_codec import compress_bytes, decompress_bytes
from fdai.shared.providers.audit_hash import GENESIS_HASH, next_hash
from fdai.shared.providers.inventory import InventoryBatch, ResourceRecord
from fdai.shared.providers.state_evidence import STATE_FACT_METADATA_PROPERTY
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row

_REPO_ROOT = Path(__file__).resolve().parents[3]
_GIT_SHA_RE = re.compile(r"^[a-f0-9]{40}$")
_HOT_TAIL_ROWS = 512
_SAGA_WINDOW_ROWS = 512
NOW = datetime(2026, 11, 5, 0, 0, tzinfo=UTC)

_BASE_MIGRATION = "alembic/versions/20260714_0015_inventory_snapshots.py"
_MEMBERSHIP_MIGRATION = (
    "service-migrations/branches/core-control-plane/versions/"
    "20261029_core_inventory_snapshot_membership.py"
)
_CACHE_EFFICIENCY_MIGRATION = (
    "service-migrations/branches/core-control-plane/versions/"
    "20261030_core_cache_storage_efficiency.py"
)
_EFFICIENCY_MIGRATION = (
    "service-migrations/branches/core-control-plane/versions/"
    "20261030_core_inventory_storage_efficiency.py"
)
_STATE_EFFICIENCY_MIGRATION = (
    "service-migrations/branches/core-control-plane/versions/"
    "20261030_core_state_storage_efficiency.py"
)
_REQUIRED_STORAGE_MIGRATIONS = (
    _CACHE_EFFICIENCY_MIGRATION,
    _EFFICIENCY_MIGRATION,
    _STATE_EFFICIENCY_MIGRATION,
)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(f"inventory cutover rehearsal invariant failed: {message}")


def evaluate_legacy_cache_and_binary_offload(
    details: Mapping[str, Any],
    *,
    selected_rollback_contract: str | None = None,
) -> dict[str, Any]:
    """Assess legacy cache retirement and binary offload from measured storage details."""

    binary_relations = ("conversation_image", "trusted_artifact")
    cache_relations = ("t2_cache", "t2_cache_legacy_default")
    binary_rows = 0
    binary_payload_bytes = 0
    for rel in binary_relations:
        entry = details.get(rel)
        if not isinstance(entry, Mapping):
            raise ValueError(f"storage details missing required binary relation {rel!r}")
        if "status" in entry and entry.get("status") != "available":
            raise ValueError(
                f"storage details relation {rel!r} is not available: {entry.get('status')!r}"
            )
        if "rows" not in entry or "payload_bytes" not in entry:
            raise ValueError(f"storage details relation {rel!r} lacks rows/payload_bytes")
        rows = int(entry["rows"])
        payload_bytes = int(entry["payload_bytes"])
        if rows < 0 or payload_bytes < 0:
            raise ValueError(f"storage details relation {rel!r} reported negative counts")
        binary_rows += rows
        binary_payload_bytes += payload_bytes

    cache_counts: dict[str, dict[str, int]] = {}
    for rel in cache_relations:
        entry = details.get(rel)
        if not isinstance(entry, Mapping):
            raise ValueError(f"storage details missing required cache relation {rel!r}")
        if "status" in entry and entry.get("status") != "available":
            raise ValueError(
                f"storage details relation {rel!r} is not available: {entry.get('status')!r}"
            )
        if "rows" not in entry or "expired_rows" not in entry:
            raise ValueError(f"storage details relation {rel!r} lacks rows/expired_rows")
        rows = int(entry["rows"])
        expired = int(entry["expired_rows"])
        if rows < 0 or expired < 0 or expired > rows:
            raise ValueError(f"storage details relation {rel!r} reported invalid row counts")
        cache_counts[rel] = {"expired_rows": expired, "rows": rows}

    legacy_cache_rows = cache_counts["t2_cache_legacy_default"]["rows"]
    contract_ref = (selected_rollback_contract or "").strip() or None
    if binary_payload_bytes == 0 and legacy_cache_rows == 0:
        disposition = "defer_retirement_and_offload_zero_measured_payloads"
        action_permitted = False
    elif contract_ref is None:
        disposition = "hold_requires_selected_rollback_and_storage_contract"
        action_permitted = False
    else:
        disposition = "eligible_for_governed_reassessment"
        action_permitted = True

    body: dict[str, Any] = {
        "action_permitted": action_permitted,
        "binary_payload_bytes": binary_payload_bytes,
        "binary_rows": binary_rows,
        "cache_relations": cache_counts,
        "disposition": disposition,
        "legacy_cache_rows": legacy_cache_rows,
        "selected_rollback_contract": contract_ref,
    }
    return {**body, "assessment_digest": content_digest(canonical_json(body))}


async def verify_stopped_maintenance_window(
    connection: psycopg.AsyncConnection[Any],
    *,
    schema: str,
) -> int:
    """Fail closed if any other PostgreSQL backend holds a relation lock in ``schema``."""

    competing_locks = await (
        await connection.execute(
            """
            SELECT count(*) AS count
            FROM pg_locks l
            JOIN pg_class c ON l.relation = c.oid
            JOIN pg_namespace n ON c.relnamespace = n.oid
            WHERE n.nspname = %s
              AND l.pid <> pg_backend_pid()
            """,
            (schema,),
        )
    ).fetchone()
    count = int(competing_locks["count"]) if competing_locks is not None else 1
    if count != 0:
        raise RuntimeError(
            f"competing reader/writer lock detected in maintenance window for {schema!r}: {count}"
        )
    return count


async def _measure_schema_storage_details(
    connection: psycopg.AsyncConnection[Any],
    *,
    schema: str,
) -> dict[str, Any]:
    details: dict[str, Any] = {}
    for relation, column in (
        ("conversation_image", "content"),
        ("trusted_artifact", "artifact"),
    ):
        qualified = f"{schema}.{relation}"
        exists = await (
            await connection.execute("SELECT to_regclass(%s) AS reg", (qualified,))
        ).fetchone()
        if exists is None or exists["reg"] is None:
            details[relation] = {"status": "not_installed"}
            continue
        access = await (
            await connection.execute(
                "SELECT has_table_privilege(current_user, %s::regclass, 'SELECT') AS ok",
                (qualified,),
            )
        ).fetchone()
        if access is None or not access["ok"]:
            details[relation] = {"status": "select_permission_required"}
            continue
        row = await (
            await connection.execute(
                sql.SQL(
                    "SELECT count(*) AS rows, COALESCE(sum(octet_length({})), 0) AS bytes "
                    "FROM {}.{}"
                ).format(
                    sql.Identifier(column),
                    sql.Identifier(schema),
                    sql.Identifier(relation),
                )
            )
        ).fetchone()
        if row is None:
            raise RuntimeError(f"storage details returned no row for {qualified}")
        details[relation] = {"rows": int(row["rows"]), "payload_bytes": int(row["bytes"])}

    for relation in ("t2_cache", "t2_cache_legacy_default"):
        qualified = f"{schema}.{relation}"
        exists = await (
            await connection.execute("SELECT to_regclass(%s) AS reg", (qualified,))
        ).fetchone()
        if exists is None or exists["reg"] is None:
            details[relation] = {"status": "not_installed"}
            continue
        access = await (
            await connection.execute(
                "SELECT has_table_privilege(current_user, %s::regclass, 'SELECT') AS ok",
                (qualified,),
            )
        ).fetchone()
        if access is None or not access["ok"]:
            details[relation] = {"status": "select_permission_required"}
            continue
        row = await (
            await connection.execute(
                sql.SQL(
                    "SELECT count(*) AS rows, "
                    "count(*) FILTER (WHERE expires_at <= CURRENT_TIMESTAMP) AS expired "
                    "FROM {}.{}"
                ).format(sql.Identifier(schema), sql.Identifier(relation))
            )
        ).fetchone()
        if row is None:
            raise RuntimeError(f"storage details returned no row for {qualified}")
        details[relation] = {"rows": int(row["rows"]), "expired_rows": int(row["expired"])}
    return details


def require_validation_postgres_dsn(dsn: str) -> str:
    """Accept only the loopback port-5433 validation PostgreSQL cluster."""

    normalized = dsn.strip().replace("postgresql+psycopg://", "postgresql://", 1)
    parsed = urlparse(normalized)
    if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("cutover rehearsal PostgreSQL DSN MUST target a loopback host")
    if parsed.port != 5433:
        raise ValueError(
            "cutover rehearsal requires explicit port 5433 and refuses default or port-5432 DSNs"
        )
    return normalized


@dataclass(frozen=True, slots=True)
class CoordinatedCutoverWindow:
    """Selected runtime source and stopped-reader/writer maintenance window."""

    runtime_owner: str
    source_revision: str
    target_scope: str
    window_start: datetime
    window_end: datetime
    readers_stopped: bool
    writers_stopped: bool

    def __post_init__(self) -> None:
        if not self.runtime_owner.strip() or not self.target_scope.strip():
            raise ValueError("cutover window requires non-empty runtime_owner and target_scope")
        if _GIT_SHA_RE.fullmatch(self.source_revision) is None:
            raise ValueError("source_revision MUST be a 40-character lowercase hex Git SHA")
        if self.window_start.tzinfo is None or self.window_end.tzinfo is None:
            raise ValueError("cutover window timestamps MUST be timezone-aware")
        if self.window_end <= self.window_start:
            raise ValueError("cutover window_end MUST be after window_start")
        if not self.readers_stopped or not self.writers_stopped:
            raise ValueError(
                "coordinated cutover requires both readers_stopped=True and writers_stopped=True"
            )

    def to_mapping(self) -> dict[str, object]:
        body: dict[str, object] = {
            "readers_stopped": self.readers_stopped,
            "runtime_owner": self.runtime_owner,
            "source_revision": self.source_revision,
            "target_scope": self.target_scope,
            "window_end": self.window_end.astimezone(UTC).isoformat(),
            "window_start": self.window_start.astimezone(UTC).isoformat(),
            "writers_stopped": self.writers_stopped,
        }
        return {**body, "window_digest": content_digest(canonical_json(body))}


@dataclass(frozen=True, slots=True)
class AuditPurgePolicySpec:
    """Deployment-owned purpose, finite retention policy, and holds for audit/observation data."""

    deployment_purpose: str
    observation_disposition: str
    hot_tail_rows: int = _HOT_TAIL_ROWS
    saga_window_rows: int = _SAGA_WINDOW_ROWS
    older_than_days: int = 2
    applicable_holds: tuple[str, ...] = (
        "canonical_incident_rows",
        "saga_compact_checkpoint_window",
        "hot_tail_512",
    )

    def __post_init__(self) -> None:
        if not self.deployment_purpose.strip():
            raise ValueError("deployment_purpose MUST be non-empty")
        if self.observation_disposition != "retain":
            raise ValueError("inventory observation disposition MUST be 'retain'")
        if self.hot_tail_rows < 512 or self.saga_window_rows < 512 or self.older_than_days < 1:
            raise ValueError("audit retention policy bounds are below required safety floors")
        required_holds = {
            "canonical_incident_rows",
            "saga_compact_checkpoint_window",
            "hot_tail_512",
        }
        if not required_holds.issubset(set(self.applicable_holds)):
            raise ValueError("audit retention policy MUST include all required holds")


def _migration_revision(relative_path: str) -> str:
    path = _REPO_ROOT / relative_path
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "revision"
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            return node.value.value
    raise RuntimeError(f"migration {relative_path} lacks a string revision assignment")


def _migration_statements(relative_path: str, direction: str = "upgrade") -> tuple[str, ...]:
    path = _REPO_ROOT / relative_path
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    statements: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == direction:
            for call in ast.walk(node):
                if (
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute)
                    and call.func.attr == "execute"
                    and call.args
                    and isinstance(call.args[0], ast.Constant)
                    and isinstance(call.args[0].value, str)
                ):
                    statements.append(call.args[0].value)
    return tuple(statements)


async def _apply_migration(
    connection: psycopg.AsyncConnection[Any],
    relative_path: str,
    direction: str = "upgrade",
    *,
    schema: str | None = None,
) -> None:
    for statement in _migration_statements(relative_path, direction):
        adapted = statement
        if schema is not None:
            adapted = adapted.replace("public.", f"{schema}.")
            adapted = adapted.replace(
                "SET search_path = pg_catalog, public",
                f"SET search_path = pg_catalog, {schema}, public",
            )
        adapted = adapted.replace("DROP INDEX CONCURRENTLY ", "DROP INDEX ")
        adapted = adapted.replace("CREATE INDEX CONCURRENTLY ", "CREATE INDEX ")
        await connection.execute(adapted)


def _build_observations(
    generation: str,
    *,
    at: datetime,
    count: int = 16,
    state: str = "running",
) -> tuple[Any, ...]:
    return snapshot_records(
        PromotedInventoryObservation(
            generation=generation,
            recorded_at=at + timedelta(seconds=2),
            resources=tuple(
                ResourceRecord(
                    resource_id=f"resource-{index:04}",
                    type="compute.vm",
                    last_seen=at.isoformat(),
                    props={
                        "state": state,
                        "sku": "Standard_D4s_v5",
                        STATE_FACT_METADATA_PROPERTY: {
                            "state": {
                                "effective_at": at.isoformat(),
                                "recorded_at": (at + timedelta(seconds=2)).isoformat(),
                                "evidence_cutoff": at.isoformat(),
                                "source_identity": "provider:principal-a",
                                "source_revision": generation,
                                "evidence_refs": ["receipt:principal-a", generation],
                            }
                        },
                    },
                )
                for index in range(count)
            ),
            links=(),
            complete=True,
        ),
        scope_refs=("scope-cutover-test",),
    )


async def _save_generation(
    connection: psycopg.AsyncConnection[Any],
    observations: tuple[Any, ...],
    *,
    watermark: int,
) -> int:
    generation = observations[0].source_revision
    return await store_snapshot_membership(
        connection,
        generation_id=generation,
        source="provider",
        observation_kind="observed",
        scopes=("scope-cutover-test",),
        resource_types=("compute.vm",),
        coverage_scope="full_provider_scope",
        semantic_content_digest="sha256:" + "a" * 64,
        journal_high_watermark=watermark,
        recorded_at=observations[0].recorded_at,
        history_visible=True,
        links_complete=True,
        records=observations,
    )


async def _fetch_scalar(
    connection: psycopg.AsyncConnection[Any],
    query: str,
    field: str = "count",
) -> Any:
    row = await (await connection.execute(query)).fetchone()
    if row is None or field not in row:
        raise RuntimeError(f"expected scalar field {field!r} from query")
    return row[field]


async def _seed_and_certify_audit_archive_restore(
    scoped_dsn: str,
    policy: AuditPurgePolicySpec,
) -> dict[str, Any]:
    """Seed 600 hash-chained audit rows with an incident hold at seq 50 and certify restore."""

    total_rows = 600
    incident_hold_seq = 50
    base_time = NOW - timedelta(days=5)
    records: list[dict[str, Any]] = []
    prev_hash = GENESIS_HASH

    async with await psycopg.AsyncConnection.connect(
        scoped_dsn, row_factory=dict_row
    ) as connection:
        async with connection.transaction():
            for seq in range(1, total_rows + 1):
                is_incident = seq == incident_hold_seq
                action_kind = "incident.opened" if is_incident else "audit.record"
                actor = "Heimdall" if is_incident else "Saga"
                created_at = (
                    base_time + timedelta(seconds=seq)
                    if seq <= 88
                    else NOW - timedelta(minutes=total_rows - seq)
                )
                entry_payload: dict[str, Any] = {
                    "action_kind": action_kind,
                    "actor": actor,
                    "kind": action_kind,
                    "mode": "shadow",
                    "seq": seq,
                    "timestamp": created_at.isoformat(),
                }
                entry_hash = next_hash(prev_hash, entry_payload)
                event_id = str(uuid.uuid5(uuid.NAMESPACE_OID, f"cutover-audit-{seq}"))
                await connection.execute(
                    """
                    INSERT INTO audit_log (
                        seq, event_id, correlation_id, actor, action_kind, mode,
                        entry, previous_hash, entry_hash, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s)
                    """,
                    (
                        seq,
                        event_id,
                        f"corr-{seq}",
                        actor,
                        action_kind,
                        "shadow",
                        canonical_json(entry_payload),
                        prev_hash,
                        entry_hash,
                        created_at,
                    ),
                )
                records.append(
                    {
                        "seq": seq,
                        "event_id": event_id,
                        "correlation_id": f"corr-{seq}",
                        "actor": actor,
                        "action_kind": action_kind,
                        "mode": "shadow",
                        "entry": entry_payload,
                        "previous_hash": prev_hash,
                        "entry_hash": entry_hash,
                        "created_at": created_at.isoformat(),
                    }
                )
                prev_hash = entry_hash

    original_head_hash = prev_hash
    # Eligible prefix before hot tail (600 - 512 = 88) AND before incident hold at seq 50 is 1..49.
    prunable_through_seq = incident_hold_seq - 1
    archived_slice = records[:prunable_through_seq]

    with tempfile.TemporaryDirectory(prefix="fdai-cutover-archive-") as tmp_dir:
        gen_dir_name = hashlib.sha256(
            f"{archived_slice[0]['entry_hash']}|{archived_slice[0]['created_at']}".encode()
        ).hexdigest()[:16]
        out = Path(tmp_dir) / gen_dir_name
        out.mkdir(parents=True, exist_ok=True)
        raw_jsonl = (
            "\n".join(
                json.dumps(item, sort_keys=True, separators=(",", ":")) for item in archived_slice
            )
            + "\n"
        ).encode("utf-8")
        envelope = compress_bytes(raw_jsonl, level=10)
        seg_name = (
            f"segment-{archived_slice[0]['seq']:012d}-{archived_slice[-1]['seq']:012d}.jsonl.zst"
        )
        seg_path = out / seg_name
        seg_path.write_bytes(envelope.compressed_bytes)
        manifest_entry = {
            "segment": seg_name,
            "first_seq": archived_slice[0]["seq"],
            "last_seq": archived_slice[-1]["seq"],
            "rows": len(archived_slice),
            "first_previous_hash": GENESIS_HASH,
            "last_entry_hash": archived_slice[-1]["entry_hash"],
            "uncompressed_sha256": envelope.uncompressed_sha256,
            "compressed_sha256": "sha256:" + hashlib.sha256(envelope.compressed_bytes).hexdigest(),
            "uncompressed_size": envelope.uncompressed_size,
            "compressed_size": envelope.compressed_size,
        }
        manifest_bytes = (json.dumps(manifest_entry, sort_keys=True) + "\n").encode("utf-8")
        (out / "manifest.jsonl").write_bytes(manifest_bytes)
        manifest_sha256 = "sha256:" + hashlib.sha256(manifest_bytes).hexdigest()

        anchor_record = {
            "schema_version": "1.0.0",
            "generation_id": out.name,
            "first_seq": 1,
            "first_entry_hash": str(archived_slice[0]["entry_hash"]),
            "first_created_at": str(archived_slice[0]["created_at"]),
            "through_seq": prunable_through_seq,
            "last_entry_hash": str(archived_slice[-1]["entry_hash"]),
            "archived_rows": len(archived_slice),
            "segment_count": 1,
            "manifest_sha256": manifest_sha256,
        }
        async with await psycopg.AsyncConnection.connect(
            scoped_dsn, row_factory=dict_row
        ) as connection:
            async with connection.transaction():
                await connection.execute(
                    "INSERT INTO state_kv (key, value, updated_at) VALUES (%s, %s::jsonb, NOW())",
                    (AUDIT_ARCHIVE_ANCHOR_KEY, json.dumps(anchor_record, sort_keys=True)),
                )
                deleted = (
                    await connection.execute(
                        "DELETE FROM audit_log WHERE seq <= %s",
                        (prunable_through_seq,),
                    )
                ).rowcount

        state_store = PostgresStateStore(config=PostgresStateStoreConfig(dsn=scoped_dsn))
        try:
            suffix_chain_verified = await state_store.verify_chain()
        finally:
            await state_store.aclose()

        # Certify full restore from the zstd segment + live suffix in audit_log.
        decompressed = decompress_bytes(
            seg_path.read_bytes(),
            max_output_size=64 * 1024 * 1024,
            expected_uncompressed_sha256=envelope.uncompressed_sha256,
        )
        restored_prefix = [
            json.loads(line) for line in decompressed.decode("utf-8").splitlines() if line
        ]
        async with await psycopg.AsyncConnection.connect(
            scoped_dsn, row_factory=dict_row
        ) as connection:
            suffix_rows = await (
                await connection.execute(
                    "SELECT seq, entry, previous_hash, entry_hash FROM audit_log ORDER BY seq ASC"
                )
            ).fetchall()

        combined = restored_prefix + [dict(row) for row in suffix_rows]
        running_hash = GENESIS_HASH
        for row in combined:
            _require(row["previous_hash"] == running_hash, "restored chain link")
            _require(
                row["entry_hash"] == next_hash(running_hash, row["entry"]),
                "restored entry hash",
            )
            running_hash = str(row["entry_hash"])
        _require(len(combined) == total_rows, "restored row count")
        _require(running_hash == original_head_hash, "restored head hash")

    body: dict[str, Any] = {
        "applicable_holds": list(policy.applicable_holds),
        "archive_manifest_sha256": manifest_sha256,
        "archive_verified": True,
        "archived_prefix_rows": len(archived_slice),
        "deleted_prefix_rows": deleted,
        "deployment_purpose": policy.deployment_purpose,
        "finite_policy": {
            "hot_tail_rows": policy.hot_tail_rows,
            "older_than_days": policy.older_than_days,
            "saga_window_rows": policy.saga_window_rows,
        },
        "incident_hold_preserved_at_seq": incident_hold_seq,
        "observation_disposition": policy.observation_disposition,
        "observation_rows_purged": 0,
        "original_head_hash": original_head_hash,
        "restore_certified": True,
        "restored_head_hash": running_hash,
        "restored_total_rows": len(combined),
        "retained_suffix_rows": len(suffix_rows),
        "suffix_chain_verified": suffix_chain_verified,
    }
    return {**body, "certification_digest": content_digest(canonical_json(body))}


async def rehearse_inventory_shared_storage_cutover(dsn: str) -> dict[str, Any]:
    """Execute the complete #2702 coordinated cutover qualification on an isolated schema."""

    loopback_dsn = require_validation_postgres_dsn(dsn)
    window = CoordinatedCutoverWindow(
        runtime_owner="dotnetpower",
        source_revision="b5b201f4d2bf0174ca65d926d5bad251188c261a",
        target_scope="loopback-isolated-cutover-qualification",
        window_start=NOW,
        window_end=NOW + timedelta(minutes=30),
        readers_stopped=True,
        writers_stopped=True,
    )
    policy = AuditPurgePolicySpec(
        deployment_purpose="local-development-lifecycle-retention",
        observation_disposition="retain",
    )

    schema = f"inventory_cutover_{uuid.uuid4().hex[:12]}"
    async with await psycopg.AsyncConnection.connect(loopback_dsn, autocommit=True) as admin:
        await admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        scoped_dsn = make_conninfo(loopback_dsn, options=f"-c search_path={schema},public")
        try:
            async with await psycopg.AsyncConnection.connect(
                scoped_dsn, row_factory=dict_row
            ) as connection:
                await _apply_migration(connection, _BASE_MIGRATION)
                await connection.execute(
                    """
                    DO $$
                    BEGIN
                        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'fdai_core') THEN
                            CREATE ROLE fdai_core NOLOGIN;
                        END IF;
                    END
                    $$;
                    CREATE TABLE inventory_observation_journal (
                        watermark BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                        observation_id TEXT NOT NULL UNIQUE,
                        content_digest TEXT NOT NULL,
                        schema_version TEXT NOT NULL DEFAULT '1.0.0',
                        idempotency_key TEXT NOT NULL,
                        subject_kind TEXT NOT NULL,
                        observation_kind TEXT NOT NULL,
                        mutation_kind TEXT NOT NULL,
                        subject_ref TEXT NOT NULL,
                        subject_type TEXT NOT NULL,
                        properties JSONB NOT NULL,
                        property_mask TEXT[] NOT NULL DEFAULT '{}',
                        properties_complete BOOLEAN NOT NULL,
                        links_complete BOOLEAN NOT NULL,
                        tombstone_confirmed BOOLEAN NOT NULL,
                        provider_ref TEXT,
                        scope_ref TEXT,
                        operation TEXT,
                        operation_status TEXT,
                        source_identity TEXT NOT NULL,
                        source_event_id TEXT NOT NULL,
                        source_revision TEXT NOT NULL,
                        effective_at TIMESTAMPTZ NOT NULL,
                        observed_at TIMESTAMPTZ NOT NULL,
                        evidence_cutoff TIMESTAMPTZ NOT NULL,
                        recorded_at TIMESTAMPTZ NOT NULL,
                        provider_event_at TIMESTAMPTZ,
                        ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        from_id TEXT,
                        from_type TEXT,
                        link_type TEXT,
                        to_id TEXT,
                        to_type TEXT,
                        projection_mode TEXT NOT NULL DEFAULT 'shadow',
                        UNIQUE (idempotency_key, subject_kind, subject_ref)
                    );
                    CREATE TABLE inventory_observation_pending_tombstone (
                        resource_id TEXT PRIMARY KEY
                    );
                    CREATE TABLE state_kv (
                        key TEXT PRIMARY KEY,
                        value JSONB NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    );
                    CREATE TABLE audit_log (
                        seq BIGSERIAL PRIMARY KEY,
                        event_id UUID NOT NULL,
                        correlation_id TEXT,
                        actor TEXT NOT NULL,
                        action_kind TEXT NOT NULL,
                        mode TEXT NOT NULL CHECK (mode IN ('shadow', 'enforce')),
                        entry JSONB NOT NULL,
                        previous_hash TEXT NOT NULL,
                        entry_hash TEXT NOT NULL UNIQUE,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    );
                    CREATE TABLE conversation_image (
                        image_id TEXT PRIMARY KEY,
                        content BYTEA NOT NULL
                    );
                    CREATE TABLE trusted_artifact (
                        kind TEXT NOT NULL,
                        artifact_id TEXT NOT NULL,
                        artifact BYTEA NOT NULL,
                        PRIMARY KEY (kind, artifact_id)
                    );
                    CREATE TABLE t2_cache (
                        catalog_version TEXT NOT NULL,
                        id TEXT NOT NULL,
                        input_hash TEXT NOT NULL,
                        expires_at TIMESTAMPTZ NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        PRIMARY KEY (catalog_version, id)
                    );
                    CREATE TABLE t2_cache_legacy_default (
                        catalog_version TEXT NOT NULL,
                        id TEXT NOT NULL,
                        input_hash TEXT NOT NULL,
                        expires_at TIMESTAMPTZ NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        PRIMARY KEY (catalog_version, id)
                    );
                    CREATE TABLE t2_cache_rotation_receipt (
                        rotation_id TEXT PRIMARY KEY,
                        active_catalog_version TEXT NOT NULL,
                        rollback_catalog_version TEXT NOT NULL,
                        rotated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    );
                    GRANT SELECT, INSERT ON inventory_observation_journal TO fdai_core;
                    GRANT SELECT ON conversation_image, trusted_artifact,
                        t2_cache, t2_cache_legacy_default TO fdai_core;
                    GRANT SELECT, INSERT, UPDATE, DELETE ON inventory_snapshot_resource,
                        inventory_snapshot_link, t2_cache TO fdai_core;
                    """
                )
                await connection.execute(
                    sql.SQL("GRANT USAGE ON SCHEMA {} TO fdai_core").format(sql.Identifier(schema))
                )
                await _apply_migration(connection, _MEMBERSHIP_MIGRATION)
                await _apply_migration(connection, _EFFICIENCY_MIGRATION)
                await connection.commit()

                # Seed 3 pre-cutover generations (16 resources each = 48 rows), then downgrade
                # to the exact pre-cutover legacy schema state before the maintenance window.
                legacy_generations: list[tuple[Any, ...]] = []
                for idx in range(3):
                    gen_id = f"legacy-gen-{idx}"
                    gen_time = NOW + timedelta(minutes=idx)
                    obs = _build_observations(gen_id, at=gen_time, count=16)
                    legacy_generations.append(obs)
                    append_res = await append_records(connection, obs if idx == 0 else ())
                    await _save_generation(connection, obs, watermark=append_res.high_watermark)
                    await connection.execute(
                        "INSERT INTO inventory_snapshot VALUES "
                        "(%s,'superseded','provider','observed','[]','[]','{}',%s,%s,NULL,NULL,NULL)",
                        (gen_id, gen_time, gen_time),
                    )
                    await stage_snapshot_batch(
                        connection,
                        attempt_id=gen_id,
                        batch=InventoryBatch(
                            resources=tuple(
                                ResourceRecord(
                                    resource_id=f"resource-{r_idx:04}",
                                    type="compute.vm",
                                    props={"state": "running", "slot": r_idx},
                                )
                                for r_idx in range(16)
                            )
                        ),
                        write_batch_size=16,
                    )
                async with connection.transaction():
                    await _apply_migration(connection, _EFFICIENCY_MIGRATION, "downgrade")
                await connection.commit()

                # Criterion 1: Verify stopped-reader/writer lock fence before cutover.
                competing_lock_count = await verify_stopped_maintenance_window(
                    connection, schema=schema
                )
                _require(competing_lock_count == 0, "zero competing locks in maintenance window")

                legacy_res_before = int(
                    await _fetch_scalar(
                        connection,
                        "SELECT count(*) AS count FROM inventory_snapshot_resource",
                    )
                )
                legacy_mem_before = int(
                    await _fetch_scalar(
                        connection,
                        "SELECT count(*) AS count FROM inventory_observation_snapshot_member",
                    )
                )
                _require(legacy_res_before == 48, "48 legacy resource rows before cutover")
                _require(legacy_mem_before == 48, "48 legacy member rows before cutover")

                # Apply all three 20261030 storage-efficiency migrations in the window.
                async with connection.transaction():
                    await _apply_migration(
                        connection, _CACHE_EFFICIENCY_MIGRATION, "upgrade", schema=schema
                    )
                    await _apply_migration(
                        connection, _EFFICIENCY_MIGRATION, "upgrade", schema=schema
                    )
                    await _apply_migration(
                        connection, _STATE_EFFICIENCY_MIGRATION, "upgrade", schema=schema
                    )

                # Criterion 2: Verify reversible downgrade -> upgrade round-trip for all three.
                async with connection.transaction():
                    await _apply_migration(
                        connection, _STATE_EFFICIENCY_MIGRATION, "downgrade", schema=schema
                    )
                    await _apply_migration(
                        connection, _EFFICIENCY_MIGRATION, "downgrade", schema=schema
                    )
                    await _apply_migration(
                        connection, _CACHE_EFFICIENCY_MIGRATION, "downgrade", schema=schema
                    )
                async with connection.transaction():
                    await _apply_migration(
                        connection, _CACHE_EFFICIENCY_MIGRATION, "upgrade", schema=schema
                    )
                    await _apply_migration(
                        connection, _EFFICIENCY_MIGRATION, "upgrade", schema=schema
                    )
                    await _apply_migration(
                        connection, _STATE_EFFICIENCY_MIGRATION, "upgrade", schema=schema
                    )

                # Convert the 3 existing snapshot resource batches into shared property bodies.
                await connection.execute("DELETE FROM inventory_snapshot_resource_row")
                for idx in range(3):
                    gen_id = f"legacy-gen-{idx}"
                    await stage_snapshot_batch(
                        connection,
                        attempt_id=gen_id,
                        batch=InventoryBatch(
                            resources=tuple(
                                ResourceRecord(
                                    resource_id=f"resource-{r_idx:04}",
                                    type="compute.vm",
                                    props={"state": "running", "slot": r_idx},
                                )
                                for r_idx in range(16)
                            )
                        ),
                        write_batch_size=16,
                    )
                await connection.commit()

                # Criterion 4a: Measure existing-row conversion separately.
                converted_res_rows = int(
                    await _fetch_scalar(
                        connection,
                        "SELECT count(*) AS count FROM inventory_snapshot_resource_row",
                    )
                )
                shared_prop_bodies = int(
                    await _fetch_scalar(
                        connection,
                        "SELECT count(*) AS count FROM inventory_snapshot_properties",
                    )
                )
                legacy_mem_retained = int(
                    await _fetch_scalar(
                        connection,
                        "SELECT count(*) AS count "
                        "FROM inventory_observation_snapshot_member_legacy",
                    )
                )
                _require(converted_res_rows == 48, "48 converted resource rows")
                _require(shared_prop_bodies == 16, "16 deduplicated property bodies")
                _require(legacy_mem_retained == 48, "48 legacy member rows retained")

                # Prove legacy evidence rows are protected from deletion (append-only).
                legacy_delete_blocked = False
                try:
                    async with connection.transaction():
                        await connection.execute(
                            "DELETE FROM inventory_observation_snapshot_member_legacy"
                        )
                except psycopg.errors.RaiseException:
                    legacy_delete_blocked = True
                _require(legacy_delete_blocked is True, "legacy member table is append-only")

                # Criterion 4b: Measure prospective deduplication across 3 post-cutover generations.
                prospective_generations: list[tuple[Any, ...]] = []
                watermark = 16
                pages_after_first = 0
                for idx in range(3):
                    gen_id = f"prospective-gen-{idx}"
                    gen_time = NOW + timedelta(minutes=10 + idx)
                    obs = _build_observations(gen_id, at=gen_time, count=16)
                    prospective_generations.append(obs)
                    watermark = await _save_generation(connection, obs, watermark=watermark)
                    if idx == 0:
                        pages_after_first = int(
                            await _fetch_scalar(
                                connection,
                                "SELECT count(*) AS count FROM inventory_observation_snapshot_page",
                            )
                        )
                await connection.commit()

                prospective_sets = int(
                    await _fetch_scalar(
                        connection,
                        "SELECT count(*) AS count FROM inventory_observation_snapshot_set",
                    )
                )
                prospective_pages = int(
                    await _fetch_scalar(
                        connection,
                        "SELECT count(*) AS count FROM inventory_observation_snapshot_page",
                    )
                )
                prospective_bindings = int(
                    await _fetch_scalar(
                        connection,
                        "SELECT count(*) AS count "
                        "FROM inventory_observation_snapshot_binding "
                        "WHERE generation_id LIKE 'prospective-gen-%'",
                    )
                )
                _require(prospective_sets == 1, "prospective generations share 1 snapshot set")
                _require(
                    prospective_pages == pages_after_first and prospective_pages > 0,
                    "subsequent unchanged prospective generations add zero new snapshot pages",
                )
                _require(prospective_bindings == 3, "3 prospective bindings recorded")

                for expected in (*legacy_generations, *prospective_generations):
                    recovered = await load_snapshot_generation_records(
                        connection,
                        generation_id=expected[0].source_revision,
                        limit=32,
                    )
                    _require(recovered == expected, "generation round-trip equality")

                # Criterion 3: Verify least-privilege fdai_core orphan cleanup.
                async with connection.transaction():
                    await connection.execute("SET LOCAL ROLE fdai_core")
                    can_update = bool(
                        await _fetch_scalar(
                            connection,
                            "SELECT has_table_privilege(current_user, "
                            "'inventory_snapshot_properties','UPDATE') AS can_update",
                            field="can_update",
                        )
                    )
                    _require(can_update is False, "fdai_core lacks UPDATE on shared properties")
                    pruned = await prune_shared_properties(connection, limit=10)
                    _require(pruned == 0, "referenced properties are not pruned")
                    expired_cache_pruned = int(
                        await _fetch_scalar(
                            connection,
                            "SELECT fdai_t2_cache_prune_expired(NOW(), 10) AS count",
                        )
                    )
                    _require(
                        expired_cache_pruned == 0,
                        "fdai_core executes fdai_t2_cache_prune_expired",
                    )
                await connection.execute("RESET ROLE")

                summary_idx_exists = await (
                    await connection.execute(
                        "SELECT to_regclass(%s) AS reg",
                        (f"{schema}.state_kv_conversation_summary_idx",),
                    )
                ).fetchone()
                cache_idx_exists = await (
                    await connection.execute(
                        "SELECT to_regclass(%s) AS reg",
                        (f"{schema}.idx_t2_cache_expiry_cleanup",),
                    )
                ).fetchone()
                _require(
                    summary_idx_exists is not None and summary_idx_exists["reg"] is not None,
                    "state_kv_conversation_summary_idx created by state efficiency migration",
                )
                _require(
                    cache_idx_exists is not None and cache_idx_exists["reg"] is not None,
                    "idx_t2_cache_expiry_cleanup created by cache efficiency migration",
                )

                journal_rows_retained = int(
                    await _fetch_scalar(
                        connection,
                        "SELECT count(*) AS count FROM inventory_observation_journal",
                    )
                )
                _require(journal_rows_retained == 16, "observation journal rows retained")

                # Criterion 6: Measure binary payload and legacy cache tables on the seeded
                # fixture schema and evaluate conditional retirement/offload disposition.
                measured_details = await _measure_schema_storage_details(connection, schema=schema)
                fixture_offload_reassessment = {
                    **evaluate_legacy_cache_and_binary_offload(measured_details),
                    "measurement_scope": "seeded_validation_fixture",
                }
                _require(
                    fixture_offload_reassessment["disposition"]
                    == "defer_retirement_and_offload_zero_measured_payloads",
                    "zero measured payloads defer legacy cache retirement and binary offload",
                )
                verified_revisions = tuple(
                    _migration_revision(path) for path in _REQUIRED_STORAGE_MIGRATIONS
                )
                _require(
                    verified_revisions
                    == (
                        "core_cache_storage_efficiency_20261030",
                        "core_inventory_storage_efficiency_20261030",
                        "core_state_storage_efficiency_20261030",
                    ),
                    "all three storage-efficiency service migration revisions verified",
                )

            # Criterion 5: Certify audit/observation retention, holds, archive, and restore.
            purge_certification = await _seed_and_certify_audit_archive_restore(scoped_dsn, policy)

            existing_conversion = {
                "converted_resource_rows": converted_res_rows,
                "existing_body_deduplication_ratio": round(
                    converted_res_rows / shared_prop_bodies, 2
                ),
                "legacy_evidence_delete_blocked": legacy_delete_blocked,
                "legacy_member_rows_retained": legacy_mem_retained,
                "legacy_resource_rows_before": legacy_res_before,
                "shared_property_bodies_after_conversion": shared_prop_bodies,
            }
            prospective_deduplication = {
                "additional_pages_on_unchanged_generations": prospective_pages - pages_after_first,
                "all_generations_round_trip_verified": True,
                "prospective_bindings": prospective_bindings,
                "prospective_generations": 3,
                "prospective_logical_members": 48,
                "prospective_page_rows": prospective_pages,
                "prospective_set_deduplication_ratio": round(3 / prospective_sets, 2),
                "prospective_set_rows": prospective_sets,
            }
            summary_body: dict[str, Any] = {
                "criteria_satisfied": {
                    "criterion_1_source_and_stopped_maintenance_window": (
                        competing_lock_count == 0
                    ),
                    "criterion_2_reversible_migration_verified": True,
                    "criterion_3_service_heads_replay_and_core_role_permissions": (
                        can_update is False and len(verified_revisions) == 3
                    ),
                    "criterion_4_existing_conversion_vs_prospective_deduplication": (
                        converted_res_rows == 48
                        and shared_prop_bodies == 16
                        and prospective_pages == pages_after_first
                    ),
                    "criterion_5_purpose_policy_holds_archive_and_restore_certified": bool(
                        purge_certification["restore_certified"]
                    ),
                    "criterion_6_legacy_cache_and_binary_offload_reassessed": (
                        fixture_offload_reassessment["disposition"]
                        == "defer_retirement_and_offload_zero_measured_payloads"
                    ),
                },
                "existing_conversion": existing_conversion,
                "execution_authority": False,
                "fixture_offload_reassessment": fixture_offload_reassessment,
                "journal_rows_retained": journal_rows_retained,
                "prospective_deduplication": prospective_deduplication,
                "purge_certification": purge_certification,
                "venue": "isolated-validation-postgres-5433",
                "verified_storage_migration_revisions": list(verified_revisions),
                "window": window.to_mapping(),
            }
            return {
                **summary_body,
                "cutover_receipt_digest": content_digest(canonical_json(summary_body)),
            }
        finally:
            await admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


async def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dsn",
        default=os.environ.get("FDAI_DATABASE_URL", ""),
        help="Loopback port-5433 validation PostgreSQL DSN (defaults to FDAI_DATABASE_URL).",
    )
    args = parser.parse_args()
    if not args.dsn.strip():
        raise RuntimeError("FDAI_DATABASE_URL or --dsn is required")
    result = await rehearse_inventory_shared_storage_cutover(args.dsn)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
