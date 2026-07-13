"""Load and cross-reference declarative process ViewSpecs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from fdai.core.views.models import ViewAppliesTo, ViewRegion, ViewSpec

_DEFAULT_SCHEMA = (
    Path(__file__).resolve().parents[4]
    / "rule-catalog"
    / "views"
    / "schema"
    / "view.schema.json"
)


@dataclass(frozen=True, slots=True)
class ViewCatalogIssue:
    origin: str
    message: str


class ViewCatalogError(ValueError):
    def __init__(self, issues: Sequence[ViewCatalogIssue]) -> None:
        self.issues = tuple(issues)
        preview = "; ".join(f"{issue.origin}: {issue.message}" for issue in issues[:5])
        super().__init__(f"view catalog validation failed: {preview}")


def load_view_catalog(
    root: Path,
    *,
    report_ids: set[str],
    workflow_names: set[str],
    schema_path: Path | None = None,
) -> tuple[ViewSpec, ...]:
    if not root.exists():
        return ()
    schema = yaml.safe_load((schema_path or _DEFAULT_SCHEMA).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    specs: list[ViewSpec] = []
    issues: list[ViewCatalogIssue] = []
    seen_ids: set[str] = set()
    seen_workflows: set[str] = set()
    for path in sorted(root.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, Mapping):
            issues.append(ViewCatalogIssue(path.name, "top-level MUST be a mapping"))
            continue
        file_issues = [
            ViewCatalogIssue(
                path.name,
                f"{'/'.join(str(part) for part in error.absolute_path) or '<root>'}: "
                f"{error.message}",
            )
            for error in sorted(validator.iter_errors(dict(raw)), key=lambda err: list(err.path))
        ]
        if file_issues:
            issues.extend(file_issues)
            continue
        spec = _spec(raw)
        if spec.id in seen_ids:
            issues.append(ViewCatalogIssue(path.name, f"duplicate view id {spec.id!r}"))
        if spec.applies_to.workflow_ref in seen_workflows:
            issues.append(
                ViewCatalogIssue(
                    path.name,
                    f"duplicate workflow view {spec.applies_to.workflow_ref!r}",
                )
            )
        if spec.applies_to.workflow_ref not in workflow_names:
            issues.append(
                ViewCatalogIssue(
                    path.name,
                    f"unknown workflow_ref {spec.applies_to.workflow_ref!r}",
                )
            )
        for region in spec.regions:
            if region.report_ref not in report_ids:
                issues.append(
                    ViewCatalogIssue(path.name, f"unknown report_ref {region.report_ref!r}")
                )
        seen_ids.add(spec.id)
        seen_workflows.add(spec.applies_to.workflow_ref)
        specs.append(spec)
    if issues:
        raise ViewCatalogError(issues)
    return tuple(specs)


def _spec(raw: Mapping[str, Any]) -> ViewSpec:
    applies = raw["applies_to"]
    regions = raw["regions"]
    if not isinstance(applies, Mapping):  # pragma: no cover - schema precondition
        raise ValueError("applies_to MUST be a mapping")
    if not isinstance(regions, Sequence):  # pragma: no cover - schema precondition
        raise ValueError("regions MUST be a sequence")
    return ViewSpec(
        id=str(raw["id"]),
        version=str(raw["version"]),
        name=str(raw["name"]),
        description=str(raw.get("description", "")),
        route=str(raw["route"]),
        applies_to=ViewAppliesTo(workflow_ref=str(applies["workflow_ref"])),
        regions=tuple(
            ViewRegion(
                id=str(region["id"]),
                report_ref=str(region["report_ref"]),
                column_span=int(region.get("column_span", 12)),
            )
            for region in regions
            if isinstance(region, Mapping)
        ),
    )


__all__ = ["ViewCatalogError", "ViewCatalogIssue", "load_view_catalog"]
