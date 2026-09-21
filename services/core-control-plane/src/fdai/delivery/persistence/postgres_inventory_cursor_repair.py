"""Explicit read-model cursor repair with graph readback and immutable audit receipt."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import hashlib
import json
import os
import re
from collections.abc import Mapping
from datetime import datetime
from operator import itemgetter
from typing import Any
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from fdai.delivery.persistence.postgres_ontology import (
    _SUBGRAPH_REPLACEMENT_LOCK,
    PostgresOntologyInstanceStoreConfig,
)
from fdai.delivery.persistence.postgres_ontology_publication import versioned_storage_active
from fdai.runtime.inventory_ontology import (
    INVENTORY_ONTOLOGY_CURSOR_FLOOR_KEY,
    INVENTORY_ONTOLOGY_INVALIDATION_KEY,
    INVENTORY_ONTOLOGY_MANIFEST_KEY,
    INVENTORY_ONTOLOGY_STATUS_KEY,
)
from fdai.runtime.inventory_ontology_manifest import _bounded_digest

_DIGEST = re.compile(r"sha256:[a-f0-9]{64}")
_REPAIR_PREFIX = "inventory-ontology:cursor-repair:"


def damage_digest(marker: object, floor: object) -> str:
    return _bounded_digest({"marker": marker, "floor": floor})


async def _read_basis(connection: psycopg.AsyncConnection[Any]) -> dict[str, Any]:
    cursor = await connection.execute(
        "SELECT key, value FROM state_kv WHERE key=ANY(%s::text[]) ORDER BY key FOR UPDATE",
        (
            [
                INVENTORY_ONTOLOGY_INVALIDATION_KEY,
                INVENTORY_ONTOLOGY_CURSOR_FLOOR_KEY,
                INVENTORY_ONTOLOGY_MANIFEST_KEY,
                INVENTORY_ONTOLOGY_STATUS_KEY,
            ],
        ),
    )
    return {row["key"]: row["value"] for row in await cursor.fetchall()}


async def _verify_graph(
    connection: psycopg.AsyncConnection[Any], manifest: Mapping[str, Any]
) -> None:
    objects = manifest.get("object_content")
    links = manifest.get("link_content")
    if (
        not isinstance(objects, list)
        or len(objects) > 50_000
        or not isinstance(links, list)
        or len(links) > 200_000
        or manifest.get("schema_version") != "1.3.0"
        or manifest.get("complete") is not True
        or _bounded_digest(
            {key: value for key, value in manifest.items() if key != "manifest_digest"}
        )
        != manifest.get("manifest_digest")
    ):
        raise ValueError("inventory cursor repair requires a complete content-bound graph manifest")
    identifiers = manifest["object_ids"]
    if identifiers != [item["id"] for item in objects] or len(set(identifiers)) != len(identifiers):
        raise ValueError("inventory cursor repair object identities changed")
    keys = [[item["from_id"], item["link_type"], item["to_id"]] for item in links]
    if keys != manifest["link_keys"] or len({tuple(key) for key in keys}) != len(keys):
        raise ValueError("inventory cursor repair relationship identities changed")
    await connection.execute("LOCK TABLE ontology_resource, ontology_link IN SHARE MODE")
    cursor = await connection.execute(
        "SELECT id, object_type, properties, catalog_digest FROM ontology_resource "
        "WHERE id=ANY(%s::text[]) LIMIT 50001",
        (identifiers,),
    )
    actual_objects = await cursor.fetchall()
    if any(
        row.pop("catalog_digest") != manifest["ontology_release_digest"] for row in actual_objects
    ):
        raise ValueError("inventory cursor repair object release changed")
    cursor = await connection.execute(
        "SELECT link.from_id, link.link_type, link.to_id, link.properties, link.catalog_digest "
        "FROM ontology_link link JOIN jsonb_to_recordset(%s::jsonb) "
        "AS expected(from_id TEXT, link_type TEXT, to_id TEXT) "
        "ON (link.from_id,link.link_type,link.to_id)="
        "(expected.from_id,expected.link_type,expected.to_id) LIMIT 200001",
        (Jsonb(links),),
    )
    actual_links = await cursor.fetchall()
    if any(
        row.pop("catalog_digest") != manifest["ontology_release_digest"] for row in actual_links
    ):
        raise ValueError("inventory cursor repair relationship release changed")
    ordering = itemgetter("from_id", "link_type", "to_id")
    expected = {
        "objects": sorted(objects, key=lambda item: item["id"]),
        "links": sorted(links, key=ordering),
    }
    actual = {
        "objects": sorted(actual_objects, key=lambda item: item["id"]),
        "links": sorted(actual_links, key=ordering),
    }
    if _bounded_digest(expected) != _bounded_digest(actual):
        raise ValueError("inventory cursor repair graph readback differs from committed content")


async def repair_inventory_cursor(
    config: PostgresOntologyInstanceStoreConfig,
    *,
    actor: str,
    repair_id: str,
    expected_generation: str,
    expected_manifest_digest: str,
    expected_damage_digest: str,
) -> Mapping[str, Any]:
    """Repair only the selected committed graph; replaying the same request is a no-op."""
    if (
        any(
            not isinstance(value, str) or not value.strip() or len(value) > 256
            for value in (actor, repair_id, expected_generation)
        )
        or _DIGEST.fullmatch(expected_manifest_digest) is None
        or _DIGEST.fullmatch(expected_damage_digest) is None
    ):
        raise ValueError("inventory cursor repair requires exact bounded identities and digests")
    request = {
        "actor": actor,
        "repair_id": repair_id,
        "generation": expected_generation,
        "manifest_digest": expected_manifest_digest,
        "damage_digest": expected_damage_digest,
    }
    request_digest = _bounded_digest(request)
    key = _REPAIR_PREFIX + hashlib.sha256(repair_id.encode()).hexdigest()
    async with (
        asyncio.timeout(30),
        await psycopg.AsyncConnection.connect(
            config.dsn,
            row_factory=dict_row,
            connect_timeout=config.connect_timeout_s,
        ) as connection,
    ):
        await connection.execute(
            "SELECT set_config('statement_timeout', %s, true)", (str(config.statement_timeout_ms),)
        )
        await connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            ("inventory-ontology-projection",),
        )
        if await versioned_storage_active(connection):
            await _read_basis(connection)
        await connection.execute("SELECT pg_advisory_xact_lock(%s)", (_SUBGRAPH_REPLACEMENT_LOCK,))
        cursor = await connection.execute(
            "SELECT value FROM state_kv WHERE key=%s FOR UPDATE", (key,)
        )
        retained = await cursor.fetchone()
        if retained is not None:
            receipt = retained["value"]
            if receipt.get("request_digest") != request_digest or receipt.get(
                "content_digest"
            ) != _bounded_digest(
                {name: value for name, value in receipt.items() if name != "content_digest"}
            ):
                raise ValueError("inventory cursor repair receipt conflicts with the request")
            return dict(receipt)
        cursor = await connection.execute(
            "SELECT active.snapshot_id, snapshot.completed_at, current_user AS database_actor, "
            "clock_timestamp() AS repaired_at FROM inventory_active active "
            "JOIN inventory_snapshot snapshot ON snapshot.id=active.snapshot_id "
            "WHERE active.singleton=TRUE FOR UPDATE OF active",
            (),
        )
        active = await cursor.fetchone()
        if active is None or active["snapshot_id"] != expected_generation:
            raise ValueError("inventory cursor repair active generation changed")
        before = await _read_basis(connection)
        if (
            damage_digest(
                before.get(INVENTORY_ONTOLOGY_INVALIDATION_KEY),
                before.get(INVENTORY_ONTOLOGY_CURSOR_FLOOR_KEY),
            )
            != expected_damage_digest
        ):
            raise ValueError("inventory cursor repair damaged state changed")
        manifest = before.get(INVENTORY_ONTOLOGY_MANIFEST_KEY)
        status = before.get(INVENTORY_ONTOLOGY_STATUS_KEY)
        if (
            not isinstance(manifest, Mapping)
            or not isinstance(status, Mapping)
            or manifest.get("generation") != expected_generation
            or manifest.get("manifest_digest") != expected_manifest_digest
            or status.get("generation") != expected_generation
            or status.get("manifest_digest") != expected_manifest_digest
            or status.get("status") != "available"
            or status.get("complete") is not True
        ):
            raise ValueError(
                "inventory cursor repair requires matching committed status and manifest"
            )
        await _verify_graph(connection, manifest)
        observed_at = active["completed_at"]
        if (
            not isinstance(observed_at, datetime)
            or observed_at.tzinfo is None
            or observed_at > active["repaired_at"]
        ):
            raise ValueError("inventory cursor repair original observation time is invalid")
        epoch = uuid4().hex
        marker = {
            "schema_version": "2.0.0",
            "epoch": epoch,
            "sequence": 1,
            "generation": expected_generation,
            "manifest_digest": expected_manifest_digest,
            "recorded_at": observed_at.isoformat(),
            "complete": True,
            "execution_authority": False,
            "mutation_authority": False,
        }
        receipt = {
            "schema_version": "1.0.0",
            "request_digest": request_digest,
            **request,
            "database_actor": active["database_actor"],
            "epoch": epoch,
            "repaired_at": active["repaired_at"].isoformat(),
            "observed_at": observed_at.isoformat(),
            "graph_readback_verified": True,
            "execution_authority": False,
            "mutation_authority": False,
        }
        receipt["content_digest"] = _bounded_digest(receipt)
        await connection.execute(
            "INSERT INTO state_kv (key,value) VALUES (%s,%s)", (key, Jsonb(receipt))
        )
        for state_key, value in (
            (INVENTORY_ONTOLOGY_INVALIDATION_KEY, marker),
            (INVENTORY_ONTOLOGY_CURSOR_FLOOR_KEY, {"epoch": epoch, "sequence": 1}),
        ):
            await connection.execute(
                "INSERT INTO state_kv (key,value) VALUES (%s,%s) ON CONFLICT (key) "
                "DO UPDATE SET value=EXCLUDED.value,updated_at=NOW()",
                (state_key, Jsonb(value)),
            )
    return receipt


async def inspect_inventory_cursor(
    config: PostgresOntologyInstanceStoreConfig,
) -> Mapping[str, Any]:
    """Return a bounded read-only repair basis; inspection never certifies a repair."""
    async with (
        asyncio.timeout(10),
        await psycopg.AsyncConnection.connect(
            config.dsn,
            row_factory=dict_row,
            connect_timeout=config.connect_timeout_s,
        ) as connection,
    ):
        await connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        await connection.execute("SELECT set_config('statement_timeout', %s, true)", ("10000",))
        cursor = await connection.execute(
            "SELECT active.snapshot_id, manifest.value AS manifest, "
            "marker.value AS marker, floor.value AS floor "
            "FROM inventory_active active LEFT JOIN state_kv manifest ON manifest.key=%s "
            "LEFT JOIN state_kv marker ON marker.key=%s LEFT JOIN state_kv floor ON floor.key=%s "
            "WHERE active.singleton=TRUE",
            (
                INVENTORY_ONTOLOGY_MANIFEST_KEY,
                INVENTORY_ONTOLOGY_INVALIDATION_KEY,
                INVENTORY_ONTOLOGY_CURSOR_FLOOR_KEY,
            ),
        )
        row = await cursor.fetchone()
        if row is None or not isinstance(row["manifest"], Mapping):
            raise ValueError("inventory cursor inspection requires a committed manifest")
        manifest = row["manifest"]
        if manifest.get("generation") != row["snapshot_id"] or not isinstance(
            manifest.get("manifest_digest"), str
        ):
            raise ValueError("inventory cursor inspection generation is inconsistent")
        return {
            "status": "inspected",
            "expected_generation": row["snapshot_id"],
            "expected_manifest_digest": manifest["manifest_digest"],
            "expected_damage_digest": damage_digest(row["marker"], row["floor"]),
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--inspect", action="store_true")
    for name in (
        "repair-id",
        "expected-generation",
        "expected-manifest-digest",
        "expected-damage-digest",
    ):
        parser.add_argument("--" + name)
    arguments = vars(parser.parse_args())
    arguments.pop("apply")
    inspect = arguments.pop("inspect")
    if not inspect and any(value is None for value in arguments.values()):
        parser.error("apply requires repair identity and all exact inspection values")
    dsn = os.environ.get("FDAI_STATE_STORE_DSN", "").strip()
    if not dsn:
        parser.error("FDAI_STATE_STORE_DSN must select the maintenance target")
    try:
        if inspect:
            print(
                json.dumps(
                    asyncio.run(
                        inspect_inventory_cursor(PostgresOntologyInstanceStoreConfig(dsn=dsn))
                    )
                )
            )
            return 0
        receipt = asyncio.run(
            repair_inventory_cursor(
                PostgresOntologyInstanceStoreConfig(dsn=dsn), actor=getpass.getuser(), **arguments
            )
        )
    except (ValueError, psycopg.Error, TimeoutError):
        print(json.dumps({"status": "blocked", "reason": "cursor_repair_verification_failed"}))
        return 1
    print(
        json.dumps(
            {
                "status": "repaired",
                "receipt_digest": receipt["content_digest"],
                "epoch": receipt["epoch"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
