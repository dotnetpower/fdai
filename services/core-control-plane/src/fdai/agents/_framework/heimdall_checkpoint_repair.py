"""Explicit offline planning for an interrupted legacy sensing checkpoint.

This never runs during normal rehydration and never writes state. An operator
must stop the writer, preserve the original rows, review the plan, and audit an
atomic root replacement. Only superseded hash links are repaired; missing or
malformed subjects still fail the normal checkpoint verifier.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from types import SimpleNamespace
from typing import Any

from fdai.agents._framework import heimdall_sensing_persistence as persistence
from fdai.agents._framework.heimdall_constants import _STATE_KEY


@dataclass(frozen=True)
class CheckpointRepairPlan:
    original_root: Mapping[str, Any]
    root: Mapping[str, Any]
    immutable_records: Mapping[str, Mapping[str, Any]]
    relinked_records: int
    subject_count: int


async def plan_interrupted_checkpoint(
    rows: Mapping[str, tuple[Mapping[str, Any], datetime]],
) -> CheckpointRepairPlan:
    """Validate a frozen legacy graph and return non-authoritative index writes."""
    root, committed_at = rows[_STATE_KEY]
    if root.get("storage_layout") != persistence.BUCKET_LAYOUT or root.get("immutable_records"):
        raise ValueError("repair requires an interrupted legacy bucket checkpoint")
    if root.get("bucket_node_format") != persistence.NODE_FORMAT:
        raise ValueError("repair requires the known radix node format")
    if committed_at.tzinfo is None:
        raise ValueError("repair timestamps must be timezone-aware")
    if not any(at > committed_at for _body, at in rows.values()):
        raise ValueError("repair has no interrupted writes after the committed root")
    bodies = {key: deepcopy(dict(body)) for key, (body, _at) in rows.items()}
    versions: dict[str, Mapping[str, Any]] = {}
    seen: set[str] = set()
    ranks: list[int] = []
    relinked = 0
    subject_count = 0

    def retain(body: Mapping[str, Any]) -> str:
        digest = persistence._subject_digest(body)
        versions[persistence.VERSION_PREFIX + digest] = deepcopy(dict(body))
        return digest

    def visit(slot: int, path: str) -> str:
        nonlocal relinked, subject_count
        key = persistence.bucket_key(slot) + ("/" + path if path else "")
        if key in seen or key not in rows:
            raise ValueError("repair graph contains missing or repeated nodes")
        seen.add(key)
        original, written_at = rows[key]
        body = bodies[key]
        if body.get("slot") != slot or body.get("path") != path:
            raise ValueError("repair node identity is malformed")
        node_type = body.get("node_type")
        if node_type == "branch":
            children = body.get("children")
            if not isinstance(children, dict) or len(path) >= 56:
                raise ValueError("repair branch is malformed")
            for digit, old_digest in list(children.items()):
                if digit not in "0123456789abcdef" or len(digit) != 1:
                    raise ValueError("repair branch path is malformed")
                digest = visit(slot, path + digit)
                if digest != old_digest:
                    child = persistence._node_key(slot, path + digit)
                    if rows[child][1] <= written_at or rows[child][1] <= committed_at:
                        raise ValueError(
                            "repair cannot explain a changed child by interrupted writes"
                        )
                    children[digit] = digest
        elif node_type == "leaf":
            entries = body.get("entries")
            if not isinstance(entries, dict):
                raise ValueError("repair leaf is malformed")
            for subject_key, entry in entries.items():
                if not isinstance(entry, dict):
                    raise ValueError("repair subject reference is malformed")
                if entry.get("family") == "metadata":
                    continue
                if subject_key not in rows:
                    raise ValueError("repair cannot replace a missing subject")
                subject, subject_at = rows[subject_key]
                digest = retain(subject)
                if digest != entry.get("digest"):
                    if subject_at <= written_at or subject_at <= committed_at:
                        raise ValueError(
                            "repair cannot explain a changed subject by interrupted writes"
                        )
                    entry["digest"] = digest
                rank = entry.get("rank")
                if type(rank) is not int or rank < 0:
                    raise ValueError("repair rank is malformed")
                ranks.append(rank)
                subject_count += 1
        else:
            # Large fragment chains need a separately reviewed repair path.
            raise ValueError("repair supports only complete leaf/branch graphs")
        if body != original:
            relinked += 1
        return retain(body)

    digests = [visit(slot, "") for slot in range(persistence.BUCKET_COUNT)]
    commitment = persistence._bucket_commitment(digests)
    if commitment == root.get("bucket_digest"):
        raise ValueError("checkpoint is already consistent; no repair is needed")
    versions[persistence.MANIFEST_PREFIX + commitment] = {"bucket_digests": digests}
    repaired = {
        **root,
        "revision": int(root["revision"]) + 1,
        "immutable_records": True,
        "bucket_digest": commitment,
        "next_ordinal": max(int(root["next_ordinal"]), max(ranks, default=-1) + 1),
    }

    class FrozenStore:
        async def read_state(self, key: str) -> Mapping[str, Any] | None:
            return versions.get(key)

    agent = SimpleNamespace(_state_store=FrozenStore(), _persisted_sensing_records={})
    await persistence.read_bucket_records(agent, repaired)
    return CheckpointRepairPlan(root, repaired, versions, relinked, subject_count)
