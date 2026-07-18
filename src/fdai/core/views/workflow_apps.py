"""Load read-only WorkflowApp manifests for Operations discovery."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

_DEFAULT_SCHEMA = (
    Path(__file__).resolve().parents[4]
    / "rule-catalog"
    / "operator-console"
    / "schema"
    / "workflow-app.schema.json"
)


@dataclass(frozen=True, slots=True)
class LocalizedWorkflowAppText:
    en: str
    ko: str


@dataclass(frozen=True, slots=True)
class WorkflowAppManifest:
    schema_version: str
    id: str
    workflow_ref: str
    view_ref: str
    lifecycle: str
    audience: str
    label: LocalizedWorkflowAppText
    description: LocalizedWorkflowAppText
    exposure: str
    group: str
    order: int

    @property
    def route(self) -> str:
        return f"/workflow-apps/{self.id}"

    @property
    def is_hub_visible(self) -> bool:
        return self.lifecycle == "published" and self.exposure == "hub"

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "workflow_ref": self.workflow_ref,
            "view_ref": self.view_ref,
            "lifecycle": self.lifecycle,
            "audience": self.audience,
            "label": {"en": self.label.en, "ko": self.label.ko},
            "description": {"en": self.description.en, "ko": self.description.ko},
            "route": self.route,
            "group": self.group,
            "order": self.order,
        }


@dataclass(frozen=True, slots=True)
class WorkflowAppCatalogIssue:
    origin: str
    message: str


class WorkflowAppCatalogError(ValueError):
    def __init__(self, issues: Sequence[WorkflowAppCatalogIssue]) -> None:
        self.issues = tuple(issues)
        preview = "; ".join(f"{issue.origin}: {issue.message}" for issue in issues[:5])
        super().__init__(f"workflow app catalog validation failed: {preview}")


def load_workflow_app_catalog(
    root: Path,
    *,
    workflow_names: set[str],
    view_workflows: Mapping[str, str],
    schema_path: Path | None = None,
) -> tuple[WorkflowAppManifest, ...]:
    if not root.exists():
        return ()
    schema = yaml.safe_load((schema_path or _DEFAULT_SCHEMA).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    manifests: list[WorkflowAppManifest] = []
    issues: list[WorkflowAppCatalogIssue] = []
    seen_ids: set[str] = set()
    seen_workflows: set[str] = set()
    for path in sorted(root.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, Mapping):
            issues.append(WorkflowAppCatalogIssue(path.name, "top-level MUST be a mapping"))
            continue
        file_issues = [
            WorkflowAppCatalogIssue(
                path.name,
                f"{'/'.join(str(part) for part in error.absolute_path) or '<root>'}: "
                f"{error.message}",
            )
            for error in sorted(validator.iter_errors(dict(raw)), key=lambda item: list(item.path))
        ]
        if file_issues:
            issues.extend(file_issues)
            continue
        manifest = _manifest(raw)
        if manifest.id in seen_ids:
            issues.append(WorkflowAppCatalogIssue(path.name, f"duplicate app id {manifest.id!r}"))
        if manifest.workflow_ref in seen_workflows:
            issues.append(
                WorkflowAppCatalogIssue(
                    path.name,
                    f"duplicate workflow app {manifest.workflow_ref!r}",
                )
            )
        if manifest.workflow_ref not in workflow_names:
            issues.append(
                WorkflowAppCatalogIssue(
                    path.name,
                    f"unknown workflow_ref {manifest.workflow_ref!r}",
                )
            )
        view_workflow = view_workflows.get(manifest.view_ref)
        if view_workflow is None:
            issues.append(
                WorkflowAppCatalogIssue(path.name, f"unknown view_ref {manifest.view_ref!r}")
            )
        elif view_workflow != manifest.workflow_ref:
            issues.append(
                WorkflowAppCatalogIssue(
                    path.name,
                    "view_ref and workflow_ref MUST resolve to the same workflow",
                )
            )
        seen_ids.add(manifest.id)
        seen_workflows.add(manifest.workflow_ref)
        manifests.append(manifest)
    if issues:
        raise WorkflowAppCatalogError(issues)
    return tuple(sorted(manifests, key=lambda item: (item.order, item.id)))


def _manifest(raw: Mapping[str, Any]) -> WorkflowAppManifest:
    label = raw["label"]
    description = raw["description"]
    navigation = raw["navigation"]
    if not isinstance(label, Mapping):  # pragma: no cover - schema precondition
        raise ValueError("label MUST be a mapping")
    if not isinstance(description, Mapping):  # pragma: no cover - schema precondition
        raise ValueError("description MUST be a mapping")
    if not isinstance(navigation, Mapping):  # pragma: no cover - schema precondition
        raise ValueError("navigation MUST be a mapping")
    return WorkflowAppManifest(
        schema_version=str(raw["schema_version"]),
        id=str(raw["id"]),
        workflow_ref=str(raw["workflow_ref"]),
        view_ref=str(raw["view_ref"]),
        lifecycle=str(raw["lifecycle"]),
        audience=str(raw["audience"]),
        label=LocalizedWorkflowAppText(en=str(label["en"]), ko=str(label["ko"])),
        description=LocalizedWorkflowAppText(
            en=str(description["en"]),
            ko=str(description["ko"]),
        ),
        exposure=str(navigation["exposure"]),
        group=str(navigation["group"]),
        order=int(navigation["order"]),
    )


__all__ = [
    "LocalizedWorkflowAppText",
    "WorkflowAppCatalogError",
    "WorkflowAppCatalogIssue",
    "WorkflowAppManifest",
    "load_workflow_app_catalog",
]
