"""Directory loader and cross-reference validator for best practices."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

import yaml

from fdai.rule_catalog.schema.best_practice_loader import (
    BestPracticeLoadError,
    load_best_practice_from_mapping,
)
from fdai.shared.contracts.models import BestPractice, RequirementKind


@dataclass(frozen=True, slots=True)
class BestPracticeCatalogIssue:
    key: str
    message: str


class BestPracticeCatalogError(ValueError):
    """Aggregate error for malformed or incompletely grounded controls."""

    def __init__(self, issues: list[BestPracticeCatalogIssue]) -> None:
        self.issues = tuple(issues)
        preview = "; ".join(f"{issue.key}: {issue.message}" for issue in issues[:5])
        suffix = f" (+{len(issues) - 5} more)" if len(issues) > 5 else ""
        super().__init__(f"best-practice catalog load failed: {preview}{suffix}")


def load_best_practice_catalog(
    root: Path,
    *,
    known_refs: Mapping[RequirementKind, Iterable[str]] | None = None,
    strict: bool = True,
) -> tuple[BestPractice, ...]:
    """Load all checklist controls and validate every typed reference.

    Strict mode requires a registry for every requirement kind used by a
    control. Authoring and preview tools can opt into ``strict=False`` while
    still receiving schema, identity, and duplicate validation.
    """

    if not root.is_dir():
        raise FileNotFoundError(f"best-practice catalog root not a directory: {root}")

    registries = {kind: frozenset(refs) for kind, refs in (known_refs or {}).items()}
    issues: list[BestPracticeCatalogIssue] = []
    loaded: list[BestPractice] = []
    seen_ids: dict[str, str] = {}
    seen_controls: dict[tuple[str, str], str] = {}

    paths = sorted([*root.glob("*.yaml"), *root.glob("*.yml")])
    for path in paths:
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            issues.append(BestPracticeCatalogIssue(path.name, f"invalid YAML: {exc}"))
            continue
        except UnicodeDecodeError as exc:
            issues.append(BestPracticeCatalogIssue(path.name, f"not UTF-8 text: {exc}"))
            continue
        if not isinstance(raw, Mapping):
            issues.append(BestPracticeCatalogIssue(path.name, "not a YAML mapping"))
            continue
        try:
            control = load_best_practice_from_mapping(raw)
        except BestPracticeLoadError as exc:
            issues.extend(
                BestPracticeCatalogIssue(f"{path.name}:{issue.key}", issue.message)
                for issue in exc.issues
            )
            continue

        if path.stem != control.id:
            issues.append(
                BestPracticeCatalogIssue(
                    path.name,
                    f"file stem MUST equal best-practice id {control.id!r}",
                )
            )
        prior_id = seen_ids.get(control.id)
        if prior_id is not None:
            issues.append(
                BestPracticeCatalogIssue(
                    path.name,
                    f"duplicate id {control.id!r} (also in {prior_id})",
                )
            )
        else:
            seen_ids[control.id] = path.name

        control_key = (control.framework, control.control_id)
        prior_control = seen_controls.get(control_key)
        if prior_control is not None:
            issues.append(
                BestPracticeCatalogIssue(
                    path.name,
                    f"duplicate framework control {control_key!r} (also in {prior_control})",
                )
            )
        else:
            seen_controls[control_key] = path.name

        issues.extend(_reference_issues(control, path.name, registries=registries, strict=strict))
        loaded.append(control)

    if issues:
        raise BestPracticeCatalogError(issues)
    return tuple(loaded)


def _reference_issues(
    control: BestPractice,
    origin: str,
    *,
    registries: Mapping[RequirementKind, frozenset[str]],
    strict: bool,
) -> list[BestPracticeCatalogIssue]:
    issues: list[BestPracticeCatalogIssue] = []
    for index, requirement in enumerate(control.requirements):
        registry = registries.get(requirement.kind)
        key = f"{origin}:requirements/{index}/ref"
        if registry is None:
            if strict:
                issues.append(
                    BestPracticeCatalogIssue(
                        key,
                        f"no known-reference registry supplied for {requirement.kind.value!r}",
                    )
                )
            continue
        if requirement.ref not in registry:
            issues.append(
                BestPracticeCatalogIssue(
                    key,
                    f"unknown {requirement.kind.value} reference {requirement.ref!r}",
                )
            )
    return issues


__all__ = [
    "BestPracticeCatalogError",
    "BestPracticeCatalogIssue",
    "load_best_practice_catalog",
]
