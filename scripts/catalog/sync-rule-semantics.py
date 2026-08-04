#!/usr/bin/env python3
"""Synchronize Rule semantic axes from the authored Rego AST."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml

from fdai.rule_catalog.schema.rego_semantics import load_rego_semantics, property_ref

_METRIC_TOKENS = (
    "cpu_",
    "dtu_",
    "hit_rate",
    "memory_",
    "network_p95",
    "server_load",
)


def _signal_type(rule_id: str, property_paths: tuple[str, ...]) -> str:
    if rule_id == "ops.change-summary":
        return "change.observed"
    if rule_id == "llm-endpoint.t2-proposer-unavailable":
        return "runtime.capability.observed"
    if any(any(token in path for token in _METRIC_TOKENS) for path in property_paths):
        return "resource.metric.observed"
    return "resource.configuration.observed"


def _synchronized(raw: dict[str, Any], *, repo_root: Path) -> dict[str, Any]:
    reference = raw.get("check_logic", {}).get("reference")
    if not isinstance(reference, str) or not reference.startswith("policies/"):
        raise ValueError("rule check_logic.reference MUST name a policies/ Rego file")
    semantics = load_rego_semantics(repo_root / reference)
    rule_id = str(raw.get("id", ""))
    if semantics.rule_id != rule_id:
        raise ValueError(f"Rego metadata rule_id mismatch for {rule_id!r}: {semantics.rule_id!r}")
    resource_type = str(raw.get("resource_type", ""))
    properties = [property_ref(resource_type, path) for path in semantics.property_paths]
    updated = dict(raw)
    updated["triggered_by"] = [_signal_type(rule_id, semantics.property_paths)]
    updated["evaluates"] = properties
    criteria = [
        item
        for item in raw.get("submission_criteria", [])
        if isinstance(item, dict) and item.get("kind") != "property_exists"
    ]
    criteria.extend({"kind": "property_exists", "value": item} for item in properties)
    updated["submission_criteria"] = criteria
    return updated


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    changed: list[str] = []
    for path in sorted((repo_root / "rule-catalog" / "catalog").glob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"rule file MUST contain an object: {path}")
        updated = _synchronized(raw, repo_root=repo_root)
        rendered = yaml.safe_dump(updated, sort_keys=False, allow_unicode=True)
        if rendered != path.read_text(encoding="utf-8"):
            changed.append(path.relative_to(repo_root).as_posix())
            if not args.check:
                path.write_text(rendered, encoding="utf-8")
    if changed:
        print("rule semantic drift: " + ", ".join(changed), file=sys.stderr)
        return 1 if args.check else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
