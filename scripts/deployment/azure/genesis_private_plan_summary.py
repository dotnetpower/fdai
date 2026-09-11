#!/usr/bin/env python3
"""Create a bounded value-free action summary for an exact Terraform plan."""

from __future__ import annotations

import argparse
import json
import os
import stat
from collections import Counter
from pathlib import Path
from typing import Any

from fdai_deployment_cli.contracts import canonical_digest, load_json_object
from fdai_deployment_cli.private_output import write_private_output

_MAX_PLAN_BYTES = 64 * 1024 * 1024
_MAX_RESOURCE_CHANGES = 10_000
_ACTIONS = {
    ("create",): "create",
    ("update",): "update",
    ("delete",): "delete",
    ("delete", "create"): "replace",
    ("create", "delete"): "replace",
    ("no-op",): "no_op",
    ("read",): "read",
}


def summarize_plan(plan: dict[str, Any]) -> dict[str, object]:
    """Return action and resource-type counts without addresses or planned values."""

    if plan.get("format_version") not in {"1.1", "1.2"}:
        raise ValueError("Terraform plan format is unsupported")
    changes = plan.get("resource_changes")
    if not isinstance(changes, list) or len(changes) > _MAX_RESOURCE_CHANGES:
        raise ValueError("Terraform resource changes are invalid or exceed the bound")
    action_counts: Counter[str] = Counter()
    type_counts: dict[str, Counter[str]] = {}
    for entry in changes:
        if not isinstance(entry, dict) or entry.get("mode", "managed") != "managed":
            continue
        resource_type = entry.get("type")
        change = entry.get("change")
        actions = change.get("actions") if isinstance(change, dict) else None
        if (
            not isinstance(resource_type, str)
            or not resource_type
            or len(resource_type) > 128
            or not isinstance(actions, list)
            or any(not isinstance(action, str) for action in actions)
        ):
            raise ValueError("Terraform resource change is malformed")
        category = _ACTIONS.get(tuple(actions))
        if category is None:
            raise ValueError("Terraform resource actions are unsupported")
        action_counts[category] += 1
        type_counts.setdefault(resource_type, Counter())[category] += 1
    normalized_actions = {name: action_counts[name] for name in sorted(set(_ACTIONS.values()))}
    normalized_types = {
        resource_type: {name: count for name, count in sorted(counts.items()) if count}
        for resource_type, counts in sorted(type_counts.items())
    }
    body: dict[str, object] = {
        "schema_version": "fdai.deployment-plan-summary.v1",
        "action_counts": normalized_actions,
        "resource_type_counts": normalized_types,
        "managed_resources": sum(normalized_actions.values()),
        "destructive": bool(normalized_actions["delete"] or normalized_actions["replace"]),
    }
    body["summary_digest"] = canonical_digest(body)
    return body


def load_plan(path: Path) -> dict[str, Any]:
    """Read one bounded regular plan projection without following links."""

    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        details = os.fstat(stream.fileno())
        if not stat.S_ISREG(details.st_mode) or details.st_size > _MAX_PLAN_BYTES:
            raise ValueError("Terraform plan projection must be a bounded regular file")
        payload = stream.read(_MAX_PLAN_BYTES + 1)
    return load_json_object(payload, label="Terraform plan projection", max_bytes=_MAX_PLAN_BYTES)


def main() -> int:
    """Write one private summary from a Terraform JSON projection."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan-json", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    summary = summarize_plan(load_plan(args.plan_json))
    write_private_output(
        args.output,
        json.dumps(summary, sort_keys=True, separators=(",", ":")) + "\n",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
