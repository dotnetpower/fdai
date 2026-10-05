#!/usr/bin/env python3
"""Summarize refresh-only Terraform drift and bind it to one reviewable digest.

A refresh-only plan proposes only to record remote changes and root outputs in state. The summary
names every changed address, attribute path, output, and move, and hashes each before and after
value so the digest binds exact values without printing a sensitive one. Reconciliation applies a
saved refresh-only plan only when every root's recomputed summary reproduces the reviewed digest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "fdai.refresh-drift-summary.v1"
_NO_OP = ["no-op"]


class RefreshDriftError(ValueError):
    """Raised when a plan isn't a reviewable refresh-only plan."""


def _value_digest(value: object) -> str:
    canonical = json.dumps(value, separators=(",", ":"), sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _leaf_paths(value: object, prefix: tuple[str, ...] = ()) -> Iterator[tuple[str, ...]]:
    if isinstance(value, Mapping):
        if not value:
            yield prefix
        for key in value:
            yield from _leaf_paths(value[key], (*prefix, str(key)))
    elif isinstance(value, list):
        if not value:
            yield prefix
        for index, item in enumerate(value):
            yield from _leaf_paths(item, (*prefix, str(index)))
    else:
        yield prefix


def _lookup(value: object, path: Sequence[str]) -> object:
    current = value
    for part in path:
        if isinstance(current, Mapping):
            if part not in current:
                return None
            current = current[part]
        elif isinstance(current, list):
            index = int(part)
            if index >= len(current):
                return None
            current = current[index]
        else:
            return None
    return current


def _changed_paths(before: object, after: object) -> list[dict[str, str]]:
    paths = {path for side in (before, after) for path in _leaf_paths(side)}
    changes: list[dict[str, str]] = []
    for path in sorted(paths):
        old = _lookup(before, path)
        new = _lookup(after, path)
        if old != new:
            changes.append(
                {
                    "path": ".".join(path) or "<root>",
                    "before_sha256": _value_digest(old),
                    "after_sha256": _value_digest(new),
                }
            )
    return changes


def summarize(plan: Mapping[str, Any], *, root_id: str) -> dict[str, Any]:
    """Return the canonical drift summary of one refresh-only plan."""

    if not root_id or "\n" in root_id:
        raise RefreshDriftError("drift summary requires a single-line root id")
    for change in plan.get("resource_changes") or []:
        actions = (change.get("change") or {}).get("actions")
        if actions not in (_NO_OP, ["read"]):
            raise RefreshDriftError(
                f"{change.get('address')} proposes {actions}; only refresh-only plans reconcile"
            )
    resource_drift = []
    for drift in plan.get("resource_drift") or []:
        change = drift.get("change") or {}
        actions = change.get("actions")
        if actions == _NO_OP:
            continue
        resource_drift.append(
            {
                "address": str(drift.get("address")),
                "actions": list(actions or []),
                "changes": _changed_paths(change.get("before"), change.get("after")),
            }
        )
    outputs = []
    for name, change in sorted((plan.get("output_changes") or {}).items()):
        if change.get("actions") == _NO_OP:
            continue
        outputs.append(
            {
                "name": str(name),
                "actions": list(change.get("actions") or []),
                "before_sha256": _value_digest(change.get("before")),
                "after_sha256": _value_digest(change.get("after")),
            }
        )
    moves = sorted(
        (
            {"from": str(change["previous_address"]), "to": str(change.get("address"))}
            for change in plan.get("resource_changes") or []
            if change.get("previous_address")
        ),
        key=lambda move: (move["from"], move["to"]),
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "root_id": root_id,
        "resource_drift": sorted(resource_drift, key=lambda item: item["address"]),
        "output_changes": outputs,
        "moves": moves,
    }


def aggregate_digest(summaries: Sequence[Mapping[str, Any]]) -> str:
    """Bind every root summary, ordered by root id, into one digest."""

    root_ids = [str(summary.get("root_id")) for summary in summaries]
    if len(set(root_ids)) != len(root_ids):
        raise RefreshDriftError("drift summaries contain a duplicate root")
    for summary in summaries:
        if summary.get("schema_version") != SCHEMA_VERSION:
            raise RefreshDriftError("drift summary has an unsupported schema version")
    ordered = sorted(summaries, key=lambda summary: str(summary["root_id"]))
    canonical = json.dumps(ordered, separators=(",", ":"), sort_keys=True)
    return "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()


def has_drift(summary: Mapping[str, Any]) -> bool:
    return bool(summary["resource_drift"] or summary["output_changes"] or summary["moves"])


def render(summaries: Sequence[Mapping[str, Any]]) -> str:
    """Render addresses and attribute paths only; values never appear."""

    lines: list[str] = []
    for summary in sorted(summaries, key=lambda item: str(item["root_id"])):
        lines.append(f"{summary['root_id']}: {'drift' if has_drift(summary) else 'no drift'}")
        for drift in summary["resource_drift"]:
            paths = ", ".join(change["path"] for change in drift["changes"]) or "<none>"
            lines.append(f"  changed outside Terraform: {drift['address']} [{paths}]")
        for move in summary["moves"]:
            lines.append(f"  moved: {move['from']} -> {move['to']}")
        for output in summary["output_changes"]:
            lines.append(f"  output {'/'.join(output['actions'])}: {output['name']}")
    return "\n".join(lines)


def _load(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RefreshDriftError(f"{path.name} must contain a JSON object")
    return payload


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    summary = commands.add_parser("summarize")
    summary.add_argument("--root-id", required=True)
    summary.add_argument("--plan-json", type=Path, required=True)
    digest = commands.add_parser("digest")
    digest.add_argument("summaries", type=Path, nargs="+")
    rendered = commands.add_parser("render")
    rendered.add_argument("summaries", type=Path, nargs="+")
    args = parser.parse_args(argv)
    try:
        if args.command == "summarize":
            result = summarize(_load(args.plan_json), root_id=args.root_id)
            print(json.dumps(result, separators=(",", ":"), sort_keys=True))
        elif args.command == "digest":
            print(aggregate_digest([_load(path) for path in args.summaries]))
        else:
            print(render([_load(path) for path in args.summaries]))
    except (RefreshDriftError, OSError, json.JSONDecodeError, KeyError) as error:
        print(f"refresh drift summary failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
