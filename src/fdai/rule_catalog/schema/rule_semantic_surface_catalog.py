"""Strict Git catalog loader for promoted Rule semantic surfaces."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from fdai.rule_catalog.schema.rule_semantic_retrieval import (
    RuleSemanticManifest,
    RuleSemanticSurface,
    SurfaceOrigin,
    SurfaceState,
)

_SCHEMA_FILE = "rule_semantic_surface.schema.json"


@dataclass(frozen=True, slots=True)
class SemanticSurfaceCatalogIssue:
    key: str
    message: str


class SemanticSurfaceCatalogError(ValueError):
    """Aggregate promoted-surface load failure."""

    def __init__(self, issues: list[SemanticSurfaceCatalogIssue]) -> None:
        self.issues = tuple(issues)
        preview = "; ".join(f"{item.key}: {item.message}" for item in issues[:5])
        suffix = f" (+{len(issues) - 5} more)" if len(issues) > 5 else ""
        super().__init__(f"semantic surface catalog load failed: {preview}{suffix}")


def load_promoted_semantic_surfaces(
    root: Path,
    *,
    manifests: Mapping[str, RuleSemanticManifest],
) -> tuple[RuleSemanticSurface, ...]:
    """Load reviewed surfaces and verify exact manifest membership."""

    if not root.is_dir():
        return ()
    validator = Draft202012Validator(_schema())
    issues: list[SemanticSurfaceCatalogIssue] = []
    loaded: list[RuleSemanticSurface] = []
    seen_ids: dict[str, str] = {}
    known_manifests = {item.digest for item in manifests.values()}
    for path in sorted((*root.glob("*.yaml"), *root.glob("*.yml"))):
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
            issues.append(SemanticSurfaceCatalogIssue(path.name, f"invalid YAML: {exc}"))
            continue
        if not isinstance(raw, Mapping):
            issues.append(SemanticSurfaceCatalogIssue(path.name, "not a YAML mapping"))
            continue
        schema_issues = sorted(validator.iter_errors(dict(raw)), key=lambda item: list(item.path))
        if schema_issues:
            issues.extend(
                SemanticSurfaceCatalogIssue(
                    f"{path.name}:{'/'.join(str(value) for value in item.path) or '<root>'}",
                    item.message,
                )
                for item in schema_issues
            )
            continue
        try:
            surface = _surface_from_mapping(raw)
        except ValueError as exc:
            issues.append(SemanticSurfaceCatalogIssue(path.name, str(exc)))
            continue
        prior = seen_ids.get(surface.surface_id)
        if prior is not None:
            issues.append(
                SemanticSurfaceCatalogIssue(
                    path.name,
                    f"duplicate surface_id {surface.surface_id!r} (also in {prior})",
                )
            )
        else:
            seen_ids[surface.surface_id] = path.name
        if surface.manifest_digest not in known_manifests:
            issues.append(
                SemanticSurfaceCatalogIssue(
                    path.name,
                    f"unknown manifest_digest {surface.manifest_digest!r}",
                )
            )
        loaded.append(surface)
    if issues:
        raise SemanticSurfaceCatalogError(issues)
    return tuple(sorted(loaded, key=lambda item: item.surface_id))


def _surface_from_mapping(raw: Mapping[str, Any]) -> RuleSemanticSurface:
    prompt_digest = raw.get("prompt_digest")
    return RuleSemanticSurface(
        schema_version=str(raw["schema_version"]),
        surface_id=str(raw["surface_id"]),
        manifest_digest=str(raw["manifest_digest"]),
        locale=str(raw["locale"]),
        origin=SurfaceOrigin(str(raw["origin"])),
        intent_ids=tuple(sorted(str(item) for item in raw["intent_ids"])),
        concept_refs=tuple(sorted(str(item) for item in raw["concept_refs"])),
        aliases=tuple(sorted(str(item) for item in raw["aliases"])),
        training_queries=tuple(sorted(str(item) for item in raw["training_queries"])),
        hard_negative_queries=tuple(sorted(str(item) for item in raw["hard_negative_queries"])),
        producer_ref=str(raw["producer_ref"]),
        evidence_refs=tuple(sorted(str(item) for item in raw["evidence_refs"])),
        state=SurfaceState(str(raw["state"])),
        prompt_digest=str(prompt_digest) if prompt_digest is not None else None,
        validation_receipt_digest=str(raw["validation_receipt_digest"]),
    )


def _schema() -> dict[str, Any]:
    raw = (
        resources.files("fdai.rule_catalog.schema")
        .joinpath(_SCHEMA_FILE)
        .read_text(encoding="utf-8")
    )
    return json.loads(raw)  # type: ignore[no-any-return]


__all__ = [
    "SemanticSurfaceCatalogError",
    "SemanticSurfaceCatalogIssue",
    "load_promoted_semantic_surfaces",
]
