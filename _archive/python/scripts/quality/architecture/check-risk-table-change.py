#!/usr/bin/env python3
"""Enforce the locally-provable half of the risk-table change contract.

`rule-catalog/risk-classification.yaml` is the authoritative Axis A input
for the RiskGate, so it gates the whole autonomy surface. The governance
contract for changing it lives in
`docs/roadmap/decisioning/risk-classification.md` (Change Process) and
splits into two halves:

- A **review** half - a two-person `aw-approvers` quorum, plus an
  Owner-tier reviewer for loosening changes. That half is enforced by
  branch protection on the deployment's fork and cannot be proven from a
  local checkout, so this gate never claims to check it.
- A **metadata** half - every change bumps the table version, ownership
  stays with the Owner-tier group, and every rule carries a written
  justification. That half is fully decidable from the diff, and this
  gate enforces it.

The gate additionally classifies the change direction. A *loosening*
change (widening auto, dropping a deny, lowering a quorum, or editing a
match condition in a way this gate cannot prove is safety-side) MUST bump
at least the minor version. Rationale: the catalog version is what the
authority audit payload serializes, so a replayed decision only shows the
version string. If a loosening could hide behind a patch bump it would be
indistinguishable from a typo fix when someone replays a historical
action months later.

Direction classification is fail-closed. Anything this gate cannot prove
is tightening is reported as loosening, so an unrecognized edit shape
raises the bar instead of lowering it.

Exit codes: 0 clean, 1 on any violation, 2 on invocation error.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from typing import Any, Final

import yaml

TABLE_PATH: Final = "rule-catalog/risk-classification.yaml"

_PERMISSIVENESS: Final[dict[str, int]] = {"deny": 0, "hil": 1, "auto": 2}
"""Higher means the table lets more through without a human."""

_FAIL_CLOSE_DEFAULTS: Final = frozenset({"hil", "deny"})


def parse_version(raw: object) -> tuple[int, int, int] | None:
    """Return the semver triple, or ``None`` when the value is not semver."""
    if not isinstance(raw, str):
        return None
    parts = raw.split(".")
    if len(parts) != 3:
        return None
    try:
        major, minor, patch = (int(part) for part in parts)
    except ValueError:
        return None
    if major < 0 or minor < 0 or patch < 0:
        return None
    return (major, minor, patch)


def metadata_violations(raw: Any) -> list[str]:
    """Return every metadata-contract violation in one table revision."""
    if not isinstance(raw, dict):
        return ["risk table must be a mapping"]

    errors: list[str] = []

    if parse_version(raw.get("version")) is None:
        errors.append("version must be a MAJOR.MINOR.PATCH string")

    owner_group = raw.get("owner_group")
    if not isinstance(owner_group, str) or not owner_group.strip():
        errors.append("owner_group must be a non-empty string")

    rules = raw.get("rules")
    if not isinstance(rules, list) or not rules:
        errors.append("rules must be a non-empty list")
        return errors

    seen: set[str] = set()
    default_indexes: list[int] = []
    for index, rule in enumerate(rules):
        label = f"rules[{index}]"
        if not isinstance(rule, dict):
            errors.append(f"{label} must be a mapping")
            continue

        rule_id = rule.get("id")
        if not isinstance(rule_id, str) or not rule_id.strip():
            errors.append(f"{label} must carry a non-empty id")
        elif rule_id in seen:
            errors.append(f"{label} repeats rule id '{rule_id}'")
        else:
            seen.add(rule_id)
            label = f"rule '{rule_id}'"

        reason = rule.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            errors.append(f"{label} must carry a non-empty reason as its written justification")

        has_default = "default" in rule
        has_decision = "decision" in rule
        if has_default and has_decision:
            errors.append(f"{label} must set either decision or default, not both")
        elif has_default:
            default_indexes.append(index)
            if rule.get("default") not in _FAIL_CLOSE_DEFAULTS:
                errors.append(f"{label} default must fail close to hil or deny")
        elif has_decision:
            if rule.get("decision") not in _PERMISSIVENESS:
                errors.append(f"{label} decision must be deny, hil, or auto")
        else:
            errors.append(f"{label} must set a decision or a default")

    if len(default_indexes) != 1:
        errors.append("table must carry exactly one fail-close default entry")
    elif default_indexes[0] != len(rules) - 1:
        errors.append("the fail-close default entry must be the last rule")

    return errors


def _rule_index(raw: Any) -> dict[str, dict[str, Any]]:
    rules = raw.get("rules") if isinstance(raw, dict) else None
    if not isinstance(rules, list):
        return {}
    indexed: dict[str, dict[str, Any]] = {}
    for rule in rules:
        if isinstance(rule, dict) and isinstance(rule.get("id"), str):
            indexed[rule["id"]] = rule
    return indexed


def _rank(rule: dict[str, Any]) -> int:
    """Return the permissiveness of a rule, defaulting to the strictest."""
    value = rule.get("decision", rule.get("default"))
    return _PERMISSIVENESS.get(value, 0) if isinstance(value, str) else 0


def _order(raw: Any) -> list[str]:
    return list(_rule_index(raw))


def change_direction(previous: Any, current: Any) -> str:
    """Classify a table edit as ``loosening``, ``tightening``, or ``neutral``.

    Fail-closed: any edit whose safety direction is not provable here is
    reported as ``loosening`` so it inherits the stricter review bar.
    """
    before = _rule_index(previous)
    after = _rule_index(current)

    loosened = False
    tightened = False

    for rule_id, rule in before.items():
        if rule_id not in after:
            # Dropping a guardrail lets more through; dropping an auto
            # rule sends its cases to the fail-close default.
            if _rank(rule) < _PERMISSIVENESS["auto"]:
                loosened = True
            else:
                tightened = True

    for rule_id, rule in after.items():
        if rule_id not in before:
            if _rank(rule) == _PERMISSIVENESS["auto"]:
                loosened = True
            else:
                tightened = True
            continue

        original = before[rule_id]
        if _rank(rule) > _rank(original):
            loosened = True
        elif _rank(rule) < _rank(original):
            tightened = True

        old_quorum = original.get("quorum", 1)
        new_quorum = rule.get("quorum", 1)
        if isinstance(old_quorum, int) and isinstance(new_quorum, int):
            if new_quorum < old_quorum:
                loosened = True
            elif new_quorum > old_quorum:
                tightened = True

        if rule.get("if") != original.get("if"):
            # A match condition changed. Whether that narrows or widens the
            # rule depends on the whole first-match chain, so assume the
            # answer that demands the stricter review.
            loosened = True

    shared = [rule_id for rule_id in _order(previous) if rule_id in after]
    if shared != [rule_id for rule_id in _order(current) if rule_id in before]:
        # First-match wins, so reordering can silently change every verdict.
        loosened = True

    if loosened:
        return "loosening"
    return "tightening" if tightened else "neutral"


def change_violations(previous: Any, current: Any) -> list[str]:
    """Return every violation of the contract for one table revision step."""
    errors: list[str] = []

    old_version = parse_version(previous.get("version") if isinstance(previous, dict) else None)
    new_version = parse_version(current.get("version") if isinstance(current, dict) else None)
    if old_version is None or new_version is None:
        # metadata_violations already reports an unparseable current version,
        # and an unparseable previous one cannot be compared against.
        return errors

    if new_version <= old_version:
        errors.append(
            f"version must increase on every change: {'.'.join(map(str, old_version))} "
            f"-> {'.'.join(map(str, new_version))}"
        )
        return errors

    old_owner = previous.get("owner_group") if isinstance(previous, dict) else None
    new_owner = current.get("owner_group") if isinstance(current, dict) else None
    if old_owner != new_owner:
        errors.append(
            f"owner_group must not change in a table edit: {old_owner!r} -> {new_owner!r}"
        )

    if change_direction(previous, current) == "loosening" and new_version[:2] == old_version[:2]:
        errors.append(
            "a loosening change must bump at least the minor version so the catalog "
            "version in a replayed audit record distinguishes it from a patch"
        )

    return errors


def _git_show(revision: str) -> str | None:
    """Return the table at a revision, or ``None`` when it is not there.

    An empty revision names the staged index entry, which is how the
    pre-commit invocation reads exactly what is about to be committed.
    """
    result = subprocess.run(
        ["git", "show", f"{revision}:{TABLE_PATH}"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout if result.returncode == 0 else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cached",
        action="store_true",
        help="compare the staged table against HEAD instead of the working tree",
    )
    args = parser.parse_args(argv)

    current_text = _git_show("") if args.cached else None
    if current_text is None:
        try:
            with open(TABLE_PATH, encoding="utf-8") as stream:
                current_text = stream.read()
        except OSError as exc:
            print(f"check-risk-table-change: cannot read {TABLE_PATH}: {exc}", file=sys.stderr)
            return 2

    try:
        current = yaml.safe_load(current_text)
    except yaml.YAMLError as exc:
        print(f"check-risk-table-change: {TABLE_PATH} is not valid YAML: {exc}", file=sys.stderr)
        return 1

    errors = metadata_violations(current)

    previous_text = _git_show("HEAD")
    direction = "unchanged"
    if previous_text is not None and previous_text != current_text:
        try:
            previous = yaml.safe_load(previous_text)
        except yaml.YAMLError:
            previous = None
        if previous is not None:
            direction = change_direction(previous, current)
            errors.extend(change_violations(previous, current))

    if errors:
        for error in errors:
            print(f"check-risk-table-change: {error}", file=sys.stderr)
        print(file=sys.stderr)
        print(f"check-risk-table-change: FAILED ({len(errors)} violation(s)).", file=sys.stderr)
        print(
            "Policy: docs/roadmap/decisioning/risk-classification.md (Change Process)",
            file=sys.stderr,
        )
        return 1

    version = current.get("version") if isinstance(current, dict) else "?"
    print(f"check-risk-table-change: OK (version {version}, {direction})")
    if direction == "loosening":
        print(
            "check-risk-table-change: this change loosens the table and needs an "
            "Owner-tier reviewer in the approval quorum."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
