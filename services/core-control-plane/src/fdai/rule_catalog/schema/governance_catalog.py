"""Directory loader for the governance catalog-as-code.

Reads every assignment, rule-set, exemption, override, and retirement file under a catalog
root and returns a :class:`GovernanceCatalog`. This is the I/O boundary (it
reads files); the per-document validation + domain mapping stays in
:mod:`fdai.rule_catalog.schema.governance_loader`, which is pure. Issues from
every file are aggregated so one load surfaces the whole catalog's problems.

Layout (CSP-neutral, catalog-as-code):

    <root>/assignments/*.{yaml,yml}   -> Assignment
    <root>/rule-sets/*.{yaml,yml}     -> RuleSet
    <root>/exemptions/*.json          -> Exemption
    <root>/overrides/*.{yaml,yml}     -> Override
    <root>/retirements/*.{yaml,yml}   -> RuleRetirement

A missing subdirectory is empty, not an error. Duplicate ids within a kind are
rejected (a catalog cannot bind two assignments under one id); an override
additionally rejects a second active override on the same (rule, scope) pair
(rule-governance.md "Overrides § Precedence" - overrides never stack).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

import yaml

from fdai.rule_catalog.schema.assignment import Assignment
from fdai.rule_catalog.schema.exemption import (
    Exemption,
    ExemptionError,
    ExemptionState,
    exemption_duration_issues,
    load_exemption_from_mapping,
    parse_exemption_json,
)
from fdai.rule_catalog.schema.governance_loader import (
    GovernanceLoadError,
    GovernanceLoadIssue,
    load_assignment_from_mapping,
    load_override_from_mapping,
    load_rule_set_from_mapping,
)
from fdai.rule_catalog.schema.override import Override, OverrideMode
from fdai.rule_catalog.schema.parameter_relaxation_policy import ParameterRelaxationPolicy
from fdai.rule_catalog.schema.retirement import RuleRetirement, load_retirement_from_mapping
from fdai.rule_catalog.schema.rule_set import RuleSet

_ASSIGNMENTS_DIR = "assignments"
_RULE_SETS_DIR = "rule-sets"
_EXEMPTIONS_DIR = "exemptions"
_OVERRIDES_DIR = "overrides"
_RETIREMENTS_DIR = "retirements"


@dataclass(frozen=True, slots=True)
class GovernanceCatalog:
    """The immutable assignment, rule-set, exemption, override, and retirement catalog."""

    assignments: tuple[Assignment, ...] = ()
    rule_sets: tuple[RuleSet, ...] = ()
    exemptions: tuple[Exemption, ...] = ()
    overrides: tuple[Override, ...] = ()
    retirements: tuple[RuleRetirement, ...] = ()


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


def _load_retirements(
    directory: Path,
    issues: list[GovernanceLoadIssue],
) -> tuple[RuleRetirement, ...]:
    if not directory.is_dir():
        return ()
    loaded: list[RuleRetirement] = []
    seen: dict[str, str] = {}
    for path in sorted([*directory.glob("*.yaml"), *directory.glob("*.yml")]):
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("not a YAML mapping")
            retirement = load_retirement_from_mapping(raw)
            if path.stem != retirement.rule_id:
                raise ValueError("retirement filename MUST match rule_id")
        except (OSError, UnicodeDecodeError, yaml.YAMLError, ValueError) as exc:
            issues.append(GovernanceLoadIssue(key=path.name, message=f"invalid retirement: {exc}"))
            continue
        if retirement.rule_id in seen:
            issues.append(
                GovernanceLoadIssue(
                    key=path.name,
                    message=(
                        f"duplicate retirement for {retirement.rule_id!r} "
                        f"(also in {seen[retirement.rule_id]})"
                    ),
                )
            )
            continue
        seen[retirement.rule_id] = path.name
        loaded.append(retirement)
    return tuple(loaded)


def load_governance_catalog(
    root: Path,
    *,
    known_rule_versions: Mapping[str, str] | None = None,
    max_exemption_duration: timedelta | None = None,
    parameter_relaxation_policies: Mapping[str, ParameterRelaxationPolicy] | None = None,
) -> GovernanceCatalog:
    """Load assignments, rule-sets, exemptions, overrides, and retirements under ``root``.

    Rule-sets load first so an assignment that binds a rule-set (by ``rule_set``
    id, rather than an explicit ``target_rule_ids`` list) can be resolved. Raises
    :class:`GovernanceLoadError` aggregating the issues from every file (keyed by
    file name) when any document is invalid, an id collides, or an assignment
    references an unknown rule-set.

    ``max_exemption_duration``, when supplied, enforces the configured maximum
    exemption duration (rule-governance.md "Exemptions";
    ``AppConfig.rule_governance.exemption_max_duration_days``): any exemption
    whose ``expires_at - created_at`` exceeds it fails the catalog load closed,
    alongside every other exemption issue.

    ``parameter_relaxation_policies``, when supplied, is the separately reviewed
    per-rule allowlist (:mod:`fdai.rule_catalog.schema.parameter_relaxation_policy`)
    an override's ``mode: parameter-relaxation`` MUST stay inside. A key absent
    from the rule's policy, or a value outside its declared bound, fails the
    catalog load closed - the safe design decision from rule-governance.md
    "Overrides § Rules (MUST)": no ambient/implicit relaxation, and no runtime
    HIL fallback (an override that violates the policy never reaches a
    resource, because the catalog carrying it never loads). Omitting this
    argument (``None``) is stricter still: no rule may use
    ``parameter-relaxation`` at all.
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
    if max_exemption_duration is not None:
        issues.extend(
            GovernanceLoadIssue(key=issue.key, message=issue.message)
            for issue in exemption_duration_issues(exemptions, max_duration=max_exemption_duration)
        )
    overrides = _load_dir(root / _OVERRIDES_DIR, load_override_from_mapping, lambda o: o.id, issues)
    issues.extend(_duplicate_override_scope_issues(overrides))
    if known_rule_versions is not None:
        issues.extend(_override_reference_issues(overrides, known_rule_versions))
    issues.extend(
        _override_parameter_relaxation_issues(overrides, parameter_relaxation_policies or {})
    )
    retirements = _load_retirements(root / _RETIREMENTS_DIR, issues)
    if known_rule_versions is not None:
        issues.extend(
            GovernanceLoadIssue(key=item.rule_id, message="references unknown rule id")
            for item in retirements
            if item.rule_id not in known_rule_versions
        )
    if issues:
        raise GovernanceLoadError(issues)
    return GovernanceCatalog(
        assignments=assignments,
        rule_sets=rule_sets,
        exemptions=exemptions,
        overrides=overrides,
        retirements=retirements,
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


def _override_reference_issues(
    overrides: tuple[Override, ...],
    known_rule_versions: Mapping[str, str],
) -> list[GovernanceLoadIssue]:
    return [
        GovernanceLoadIssue(
            key=f"{override.id}:{override.target_rule}",
            message="references unknown rule id",
        )
        for override in overrides
        if override.target_rule not in known_rule_versions
    ]


def _duplicate_override_scope_issues(
    overrides: tuple[Override, ...],
) -> list[GovernanceLoadIssue]:
    """Reject a second override on the same (target_rule, scope) pair.

    rule-governance.md "Overrides § Precedence": overrides never stack - at
    most one per (rule, scope) pair. Unlike an exemption, an override has no
    ``state`` lifecycle field, so every loaded override counts (removal is by
    deleting the catalog-as-code file, not a state transition).
    """
    issues: list[GovernanceLoadIssue] = []
    seen: dict[tuple[str, str], str] = {}
    for override in overrides:
        key = (override.target_rule, override.scope.render().casefold())
        prior = seen.get(key)
        if prior is not None:
            issues.append(
                GovernanceLoadIssue(
                    key=override.id,
                    message=(
                        "duplicate active override for rule "
                        f"{override.target_rule!r} at scope {override.scope.render()!r} "
                        f"(also in {prior!r}) - overrides never stack"
                    ),
                )
            )
        else:
            seen[key] = override.id
    return issues


def _override_parameter_relaxation_issues(
    overrides: tuple[Override, ...],
    policies: Mapping[str, ParameterRelaxationPolicy],
) -> list[GovernanceLoadIssue]:
    """Fail closed on a parameter-relaxation override outside its reviewed policy.

    rule-governance.md "Overrides § Rules (MUST)" + Open Decisions: the safe
    design decision is a separately reviewed governance-level allowlist
    (:mod:`fdai.rule_catalog.schema.parameter_relaxation_policy`), not the
    rule's own (not-yet-declared) schema bounds and not a runtime HIL
    fallback - an override that names an unlisted key, or a value outside its
    declared bound, never reaches a resource because the catalog carrying it
    never loads.
    """
    issues: list[GovernanceLoadIssue] = []
    for override in overrides:
        if override.mode is not OverrideMode.PARAMETER_RELAXATION:
            continue
        policy = policies.get(override.target_rule)
        for key, value in override.parameter_overrides.items():
            if policy is None or not policy.allows(key, value):
                issues.append(
                    GovernanceLoadIssue(
                        key=f"{override.id}:{key}",
                        message=(
                            f"parameter_overrides key {key!r}={value!r} is not allow-listed by "
                            "the reviewed parameter-relaxation-bounds policy for rule "
                            f"{override.target_rule!r}"
                        ),
                    )
                )
    return issues


__all__ = ["GovernanceCatalog", "load_governance_catalog"]
