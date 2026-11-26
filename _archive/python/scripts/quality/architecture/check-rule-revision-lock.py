#!/usr/bin/env python3
"""Block in-place revisions of shipped Rules until activations can upgrade revisions safely.

An installed Rule activation generation pins each member Rule's exact version and digest, and
the activation ledger has no revision upgrade transition. Changing a shipped Rule's definition
therefore makes upgraded installations fail to resolve their active generation. A change to the
referenced Rego also changes executable behavior without changing the activation digest at all.

This gate records each curated Rule's canonical definition digest and the digest of its
referenced policy file in `rule-catalog/rule-revision-lock.json`. A locked Rule's version,
definition, or policy content must not change, and a locked Rule must not disappear; deprecate it
instead. `--write` only adds Rules that aren't locked yet. See the Rule revision upgrade
requirement in docs/roadmap/rules-and-detection/rule-governance.md#lifecycle-and-versioning.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[3]
CATALOG = ROOT / "rule-catalog/catalog"
LOCK = ROOT / "rule-catalog/rule-revision-lock.json"
_GUIDANCE = (
    "Shipped Rule revisions can't change in place until the Rule revision upgrade path exists "
    "(docs/roadmap/rules-and-detection/rule-governance.md#lifecycle-and-versioning). Ship the "
    "change as a new Rule id, or implement the upgrade path first."
)


def _canonical(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def current_entries(root: Path = ROOT) -> dict[str, dict[str, str]]:
    """Return the lock entry for every curated Rule under ``rule-catalog/catalog``."""

    entries: dict[str, dict[str, str]] = {}
    for path in sorted((root / "rule-catalog/catalog").glob("*.yaml")):
        loaded: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict) or not isinstance(loaded.get("id"), str):
            raise SystemExit(f"{path.relative_to(root)}: not a Rule definition")
        reference = (loaded.get("check_logic") or {}).get("reference")
        policy_digest = "none"
        if isinstance(reference, str) and reference.startswith("policies/"):
            policy = root / reference
            if not policy.is_file():
                raise SystemExit(f"{path.relative_to(root)}: policy {reference} is missing")
            policy_digest = "sha256:" + hashlib.sha256(policy.read_bytes()).hexdigest()
        entries[loaded["id"]] = {
            "version": str(loaded.get("version")),
            "definition_digest": _canonical(loaded),
            "policy_digest": policy_digest,
        }
    return entries


def violations(locked: dict[str, dict[str, str]], current: dict[str, dict[str, str]]) -> list[str]:
    problems: list[str] = []
    for rule_id, expected in sorted(locked.items()):
        actual = current.get(rule_id)
        if actual is None:
            problems.append(f"{rule_id}: locked Rule was removed; deprecate it instead")
            continue
        for field in ("version", "definition_digest", "policy_digest"):
            if actual[field] != expected[field]:
                problems.append(f"{rule_id}: {field} changed from the locked revision")
    problems.extend(
        f"{rule_id}: new Rule is not locked; run with --write"
        for rule_id in sorted(set(current) - set(locked))
    )
    return problems


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--write", action="store_true", help="lock Rules that aren't locked yet")
    args = parser.parse_args(argv)
    current = current_entries()
    locked: dict[str, dict[str, str]] = {}
    if LOCK.is_file():
        locked = json.loads(LOCK.read_text(encoding="utf-8"))["rules"]
    if args.write:
        merged = {**{key: current[key] for key in set(current) - set(locked)}, **locked}
        LOCK.write_text(
            json.dumps({"schema_version": "1.0.0", "rules": dict(sorted(merged.items()))}, indent=2)
            + "\n",
            encoding="utf-8",
        )
        locked = merged
    problems = violations(locked, current)
    if problems:
        for problem in problems:
            print(f"rule-revision-lock: {problem}", file=sys.stderr)
        print(f"rule-revision-lock: {_GUIDANCE}", file=sys.stderr)
        return 1
    print(f"rule-revision-lock: OK ({len(current)} Rule revision(s) locked)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
