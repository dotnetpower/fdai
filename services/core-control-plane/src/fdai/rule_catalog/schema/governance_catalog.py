"""Directory loader for the governance catalog-as-code.

Reads every assignment, rule-set, and exemption file under a catalog root and
returns a :class:`GovernanceCatalog`. This is the I/O boundary (it reads files); the
per-document validation + domain mapping stays in
:mod:`fdai.rule_catalog.schema.governance_loader`, which is pure. Issues from
every file are aggregated so one load surfaces the whole catalog's problems.

Layout (CSP-neutral, catalog-as-code):

    <root>/assignments/*.{yaml,yml}   -> Assignment
    <root>/rule-sets/*.{yaml,yml}     -> RuleSet
    <root>/exemptions/*.json          -> Exemption

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
from fdai.rule_catalog.schema.exemption import (
    Exemption,
    ExemptionError,
    ExemptionState,
    load_exemption_from_mapping,
    parse_exemption_json,
)
from fdai.rule_catalog.schema.governance_loader import (
    GovernanceLoadError,
    GovernanceLoadIssue,
    load_assignment_from_mapping,
    load_rule_set_from_mapping,
)
from fdai.rule_catalog.schema.rule_set import RuleSet

_ASSIGNMENTS_DIR = "assignments"
_RULE_SETS_DIR = "rule-sets"
_EXEMPTIONS_DIR = "exemptions"


@dataclass(frozen=True, slots=True)
class GovernanceCatalog:
    """The immutable assignment, rule-set, and exemption catalog."""

    assignments: tuple[Assignment, ...] = ()
    rule_sets: tuple[RuleSet, ...] = ()
    exemptions: tuple[Exemption, ...] = ()


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


def _load_exemptions(
    directory: Path,
    issues: list[GovernanceLoadIssue],
) -> tuple[Exemption, ...]:
    if not directory.is_dir():
        return ()
    loaded: list[Exemption] = []
    seen: dict[str, str] = {}
    for path in sorted(directory.glob("*.json")):
        try:
            raw = parse_exemption_json(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            issues.append(GovernanceLoadIssue(key=path.name, message=f"invalid JSON: {exc}"))
            continue
        except UnicodeDecodeError as exc:
            issues.append(GovernanceLoadIssue(key=path.name, message=f"not UTF-8 text: {exc}"))
            continue
        try:
            exemption = load_exemption_from_mapping(raw)
        except ExemptionError as exc:
            issues.extend(
                GovernanceLoadIssue(key=f"{path.name}:{issue.key}", message=issue.message)
                for issue in exc.issues
            )
            continue
        if exemption.id in seen:
            issues.append(
                GovernanceLoadIssue(
                    key=path.name,
                    message=f"duplicate id {exemption.id!r} (also in {seen[exemption.id]})",
                )
            )
            continue
        seen[exemption.id] = path.name
        loaded.append(exemption)
    return tuple(loaded)


def load_governance_catalog(
    root: Path,
    *,
    known_rule_versions: Mapping[str, str] | None = None,
) -> GovernanceCatalog:
    """Load every governed assignment, rule-set, and exemption under ``root``.

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
    if known_rule_versions is not None:
        issues.extend(_assignment_reference_issues(assignments, known_rule_versions))
    exemptions = _load_exemptions(root / _EXEMPTIONS_DIR, issues)
    issues.extend(_duplicate_active_exemption_issues(exemptions))
    if known_rule_versions is not None:
        issues.extend(_exemption_reference_issues(exemptions, known_rule_versions))
    if issues:
        raise GovernanceLoadError(issues)
    return GovernanceCatalog(
        assignments=assignments,
        rule_sets=rule_sets,
        exemptions=exemptions,
    )


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


def _exemption_reference_issues(
    exemptions: tuple[Exemption, ...],
    known_rule_versions: Mapping[str, str],
) -> list[GovernanceLoadIssue]:
    return [
        GovernanceLoadIssue(
            key=f"{exemption.id}:{exemption.rule_id}",
            message="references unknown rule id",
        )
        for exemption in exemptions
        if exemption.rule_id not in known_rule_versions
    ]


def _assignment_reference_issues(
    assignments: tuple[Assignment, ...],
    known_rule_versions: Mapping[str, str],
) -> list[GovernanceLoadIssue]:
    return [
        GovernanceLoadIssue(
            key=f"{assignment.id}:{rule_id}",
            message="references unknown rule id",
        )
        for assignment in assignments
        for rule_id in sorted(assignment.target_rule_ids)
        if rule_id not in known_rule_versions
    ]


def _duplicate_active_exemption_issues(
    exemptions: tuple[Exemption, ...],
) -> list[GovernanceLoadIssue]:
    issues: list[GovernanceLoadIssue] = []
    seen: dict[tuple[str, str, str], str] = {}
    for exemption in exemptions:
        if exemption.state is not ExemptionState.ACTIVE:
            continue
        scope = exemption.scope
        if scope.resource_ref is not None:
            scope_kind = "resource"
            scope_value = scope.resource_ref.casefold()
        else:
            scope_kind = "resource-group"
            scope_value = f"{scope.subscription_id}/{scope.resource_group}".casefold()
        key = (exemption.rule_id, scope_kind, scope_value)
        prior = seen.get(key)
        if prior is not None:
            issues.append(
                GovernanceLoadIssue(
                    key=exemption.id,
                    message=(
                        "duplicate active exemption scope for rule "
                        f"{exemption.rule_id!r} (also in {prior!r})"
                    ),
                )
            )
        else:
            seen[key] = exemption.id
    return issues


__all__ = ["GovernanceCatalog", "load_governance_catalog"]
