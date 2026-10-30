"""Content-addressed membership pages with exact, generation-local clock bindings."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import psycopg

MEMBER_FIELDS = (
    "subject_kind",
    "subject_ref",
    "subject_type",
    "semantic_digest",
    "provider_ref",
    "scope_ref",
    "observed_at",
    "freshness_properties",
    "from_id",
    "from_type",
    "link_type",
    "to_id",
    "to_type",
)
MAX_PAGE_BYTES = 4 * 1024 * 1024
MAX_PAGE_MEMBERS = 1000
MAX_ROOT_BYTES = 16 * 1024 * 1024


async def inventory_storage_available(
    connection: psycopg.AsyncConnection[Any], related: Sequence[str]
) -> bool:
    """Never bind a private logical inventory to backing relations from a fallback schema."""
    cursor = await connection.execute(
        "SELECT bool_and(backing.oid IS NOT NULL AND "
        "backing.relnamespace=logical.relnamespace) AS available "
        "FROM pg_catalog.pg_class logical CROSS JOIN unnest(%s::text[]) requested(name) "
        "LEFT JOIN pg_catalog.pg_class backing ON backing.oid=to_regclass(requested.name) "
        "WHERE logical.oid=to_regclass('inventory_snapshot_resource')",
        (list(related),),
    )
    row = await cursor.fetchone()
    return bool(row and row["available"])


async def require_membership_namespace(connection: psycopg.AsyncConnection[Any]) -> None:
    if not await inventory_storage_available(
        connection,
        (
            "inventory_snapshot",
            "inventory_active",
            "inventory_snapshot_link",
            "inventory_observation_journal",
            "inventory_observation_snapshot_member",
            "inventory_observation_snapshot_member_legacy",
            "inventory_observation_snapshot_generation",
            "inventory_observation_snapshot_page",
            "inventory_observation_snapshot_set",
            "inventory_observation_snapshot_binding",
        ),
    ):
        raise ValueError(
            "shared inventory membership is unavailable in the logical inventory schema"
        )


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def content_digest(body: str) -> str:
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SharedMembership:
    root_digest: str
    root_body: str
    pages: Mapping[str, str]
    bindings: str


def pack_membership(
    members: Sequence[tuple[object, ...]], *, generation_id: str, recorded_at: datetime
) -> SharedMembership:
    """Factor only exact string equality; nonuniform clocks and evidence stay literal.

    Substitutions live outside the original JSON, so even marker-shaped user values
    round-trip without collisions. Hash partitioning avoids copying the full set when
    one subject changes. A root references pages, never an earlier generation.
    """
    ordered = sorted(members, key=lambda member: (str(member[1]), str(member[2])))
    observed_at = ordered[0][7] if ordered else recorded_at
    if not isinstance(observed_at, datetime):
        raise ValueError("inventory snapshot membership clock is malformed")
    bindings = {
        "observed_at": observed_at.isoformat(),
        "recorded_at": recorded_at.isoformat(),
        "observed_at_z": observed_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "recorded_at_z": recorded_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "generation_id": generation_id,
    }
    buckets: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    seen: set[tuple[str, str]] = set()
    for member in ordered:
        row = dict(zip(MEMBER_FIELDS, member[1:], strict=True))
        identity = (str(row["subject_kind"]), str(row["subject_ref"]))
        if identity in seen:
            raise ValueError("inventory snapshot contains duplicate subject membership")
        seen.add(identity)
        clock = row["observed_at"]
        if not isinstance(clock, datetime):
            raise ValueError("inventory snapshot membership clock is malformed")
        row["observed_at"] = clock.isoformat()
        row["freshness_properties"] = json.loads(str(row["freshness_properties"]))
        evidence = {
            "observed_at": row.pop("observed_at"),
            "freshness_properties": row.pop("freshness_properties"),
        }
        substitutions: list[dict[str, Any]] = []
        body = _factor(evidence, bindings, (), substitutions)
        key = hashlib.sha256(canonical_json(identity).encode("utf-8")).hexdigest()
        buckets.setdefault(key[:2], []).append(
            (key, {"member": row, "evidence": {"body": body, "substitutions": substitutions}})
        )
    pages: dict[str, str] = {}
    descriptors: list[list[str]] = []

    def partition(prefix: str, items: list[tuple[str, dict[str, Any]]]) -> None:
        member_body = canonical_json([item["member"] for _, item in items])
        evidence_body = canonical_json([item["evidence"] for _, item in items])
        if (
            len(items) <= MAX_PAGE_MEMBERS
            and max(len(member_body.encode("utf-8")), len(evidence_body.encode("utf-8")))
            <= MAX_PAGE_BYTES
        ):
            member_digest = content_digest(member_body)
            evidence_digest = content_digest(evidence_body)
            pages[member_digest] = member_body
            pages[evidence_digest] = evidence_body
            descriptors.append([prefix, member_digest, evidence_digest])
            return
        if len(prefix) >= 64:
            raise ValueError("inventory snapshot membership page exceeds its bound")
        children: dict[str, list[tuple[str, dict[str, Any]]]] = {}
        for key, item in items:
            children.setdefault(key[: len(prefix) + 1], []).append((key, item))
        for child, values in sorted(children.items()):
            partition(child, values)

    for prefix, items in sorted(buckets.items()):
        partition(prefix, items)
    root_body = canonical_json({"count": len(ordered), "pages": descriptors})
    if len(root_body.encode("utf-8")) > MAX_ROOT_BYTES:
        raise ValueError("inventory snapshot membership root exceeds its bound")
    return SharedMembership(content_digest(root_body), root_body, pages, canonical_json(bindings))


def _factor(
    value: Any,
    bindings: Mapping[str, str],
    path: tuple[str, ...],
    substitutions: list[dict[str, Any]],
) -> Any:
    if isinstance(value, str):
        for name, binding in bindings.items():
            if value == binding:
                substitutions.append({"path": list(path), "binding": name})
                return None
    if isinstance(value, dict):
        return {
            key: _factor(item, bindings, (*path, key), substitutions) for key, item in value.items()
        }
    if isinstance(value, list):
        return [
            _factor(item, bindings, (*path, str(index)), substitutions)
            for index, item in enumerate(value)
        ]
    return value


async def store_shared_membership(
    connection: psycopg.AsyncConnection[Any],
    *,
    generation_id: str,
    members: Sequence[tuple[object, ...]],
    recorded_at: datetime,
) -> None:
    await require_membership_namespace(connection)
    packed = pack_membership(members, generation_id=generation_id, recorded_at=recorded_at)
    cursor = connection.cursor()
    await cursor.executemany(
        "INSERT INTO inventory_observation_snapshot_page (digest, body) VALUES (%s, %s) "
        "ON CONFLICT (digest) DO NOTHING",
        sorted(packed.pages.items()),
    )
    await connection.execute(
        "INSERT INTO inventory_observation_snapshot_set (digest, body) VALUES (%s, %s) "
        "ON CONFLICT (digest) DO NOTHING",
        (packed.root_digest, packed.root_body),
    )
    await connection.execute(
        "INSERT INTO inventory_observation_snapshot_binding "
        "(generation_id, set_digest, bindings) VALUES (%s, %s, %s::jsonb)",
        (generation_id, packed.root_digest, packed.bindings),
    )
