"""Directory loader for the governance catalog-as-code.

Reads every assignment and rule-set YAML file under a catalog root and returns a
:class:`GovernanceCatalog`. This is the I/O boundary (it reads files); the
per-document validation + domain mapping stays in
:mod:`fdai.rule_catalog.schema.governance_loader`, which is pure. Issues from
every file are aggregated so one load surfaces the whole catalog's problems.

Layout (CSP-neutral, catalog-as-code):

    <root>/assignments/*.{yaml,yml}   -> Assignment
    <root>/rule-sets/*.{yaml,yml}     -> RuleSet

A missing subdirectory is empty, not an error. Duplicate ids within a kind are
rejected (a catalog cannot bind two assignments under one id).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from fdai.rule_catalog.schema.assignment import Assignment
from fdai.rule_catalog.schema.governance_loader import (
    GovernanceLoadError,
    GovernanceLoadIssue,
    load_assignment_from_mapping,
    load_rule_set_from_mapping,
)
from fdai.rule_catalog.schema.rule_set import RuleSet

_ASSIGNMENTS_DIR = "assignments"
_RULE_SETS_DIR = "rule-sets"


@dataclass(frozen=True, slots=True)
class GovernanceCatalog:
    """The loaded governance catalog: all assignments + rule-sets."""

    assignments: tuple[Assignment, ...] = ()
    rule_sets: tuple[RuleSet, ...] = ()


def _load_dir[T](
    directory: Path,
    loader: Callable[[dict[str, Any]], T],
    id_of: Callable[[T], str],
    issues: list[GovernanceLoadIssue],
) -> tuple[T, ...]:
    if not directory.is_dir():
        return ()
    loaded: list[T] = []
    seen: dict[str, str] = {}
    # Accept both extensions - a governance artifact saved as `.yml` must not be
    # silently ignored (a scope would go ungoverned with no error).
    paths = sorted([*directory.glob("*.yaml"), *directory.glob("*.yml")])
    for path in paths:
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            issues.append(GovernanceLoadIssue(key=path.name, message=f"invalid YAML: {exc}"))
            continue
        except UnicodeDecodeError as exc:
            issues.append(GovernanceLoadIssue(key=path.name, message=f"not UTF-8 text: {exc}"))
            continue
        if not isinstance(raw, dict):
            issues.append(GovernanceLoadIssue(key=path.name, message="not a YAML mapping"))
            continue
        try:
            obj = loader(raw)
        except GovernanceLoadError as exc:
            issues.extend(
                GovernanceLoadIssue(key=f"{path.name}:{i.key}", message=i.message)
                for i in exc.issues
            )
            continue
        except ValueError as exc:  # domain-constructor invariant (e.g. duplicate member)
            issues.append(GovernanceLoadIssue(key=path.name, message=str(exc)))
            continue
        obj_id = id_of(obj)
        if obj_id in seen:
            issues.append(
                GovernanceLoadIssue(
                    key=path.name,
                    message=f"duplicate id {obj_id!r} (also in {seen[obj_id]})",
                )
            )
            continue
        seen[obj_id] = path.name
        loaded.append(obj)
    return tuple(loaded)


def load_governance_catalog(
    root: Path,
    *,
    known_rule_versions: Mapping[str, str] | None = None,
) -> GovernanceCatalog:
    """Load every assignment + rule-set YAML under ``root``.

    Rule-sets load first so an assignment that binds a rule-set (by ``rule_set``
    id, rather than an explicit ``target_rule_ids`` list) can be resolved. Raises
    :class:`GovernanceLoadError` aggregating the issues from every file (keyed by
    file name) when any document is invalid, an id collides, or an assignment
    references an unknown rule-set.
    """
    issues: list[GovernanceLoadIssue] = []
    rule_sets = _load_dir(root / _RULE_SETS_DIR, load_rule_set_from_mapping, lambda r: r.id, issues)
    if known_rule_versions is not None:
        issues.extend(_rule_set_reference_issues(rule_sets, known_rule_versions))
    rule_sets_by_id = {rs.id: rs for rs in rule_sets}
    assignments = _load_dir(
        root / _ASSIGNMENTS_DIR,
        lambda raw: load_assignment_from_mapping(raw, rule_sets=rule_sets_by_id),
        lambda a: a.id,
        issues,
    )
    if issues:
        raise GovernanceLoadError(issues)
    return GovernanceCatalog(assignments=assignments, rule_sets=rule_sets)


def _rule_set_reference_issues(
    rule_sets: tuple[RuleSet, ...],
    known_rule_versions: Mapping[str, str],
) -> list[GovernanceLoadIssue]:
    issues: list[GovernanceLoadIssue] = []
    for rule_set in rule_sets:
        for member in rule_set.members:
            actual_version = known_rule_versions.get(member.rule_id)
            key = f"{rule_set.id}:{member.rule_id}"
            if actual_version is None:
                issues.append(GovernanceLoadIssue(key=key, message="references unknown rule id"))
            elif actual_version != member.version:
                issues.append(
                    GovernanceLoadIssue(
                        key=key,
                        message=(
                            f"pins version {member.version!r}, but catalog has {actual_version!r}"
                        ),
                    )
                )
    return issues


__all__ = ["GovernanceCatalog", "load_governance_catalog"]
