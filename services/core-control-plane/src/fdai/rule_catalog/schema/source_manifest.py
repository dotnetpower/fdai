"""SourceManifest model + fail-fast loader.

Mirror of ``rule-catalog/schema/source_manifest.schema.json``. The JSON
Schema is authoritative at the boundary; this pydantic model layers the
enum invariants + revision-pin discipline required by the collector
pipeline (see ``docs/roadmap/rules-and-detection/rule-catalog-collection.md`` § Collector
Architecture).

Every source is one YAML file under
``rule-catalog/sources/<id>/manifest.yaml``. The pipeline reads that
manifest, dispatches on ``fetch.kind`` to a Fetcher, verifies the
resolved artifact, and writes the snapshot under
``rule-catalog/sources/<id>/<revision>/``. Rules never land in the T0
catalog directly - a separate normalization step (out of scope here)
translates parsed snapshots into normalized rule YAML.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from importlib import resources
from pathlib import Path
from typing import Annotated, Any

import yaml
from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict, Field, model_validator

_SCHEMA_PACKAGE = "fdai.rule_catalog.schema"
_SCHEMA_FILE = "source_manifest.schema.json"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ManifestIssue:
    key: str
    message: str


class ManifestError(ValueError):
    """Aggregate error surfaced at the manifest-load boundary."""

    def __init__(self, issues: list[ManifestIssue]) -> None:
        self.issues = issues
        preview = "; ".join(f"{i.key}: {i.message}" for i in issues[:5])
        suffix = f" (+{len(issues) - 5} more)" if len(issues) > 5 else ""
        super().__init__(f"source manifest validation failed: {preview}{suffix}")


# ---------------------------------------------------------------------------
# Enums + model
# ---------------------------------------------------------------------------


class FetchKind(StrEnum):
    GIT = "git"
    HTTP = "http"
    LOCAL = "local"


class Redistribution(StrEnum):
    EMBEDDABLE = "embeddable"
    REFERENCE_ONLY = "reference-only"


class Cadence(StrEnum):
    ON_DEMAND = "on-demand"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class FetchConfig(BaseModel):
    """Per-kind fetch parameters - validated per-kind via ``model_validator``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: FetchKind
    repo: str | None = None
    revision: str | None = None
    subpath: str | None = None
    url: str | None = None
    expected_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")] | None = None
    path: str | None = None

    @model_validator(mode="after")
    def _require_per_kind_fields(self) -> FetchConfig:
        if self.kind is FetchKind.GIT:
            if not self.repo or not self.revision:
                raise ValueError("fetch.kind='git' requires repo + revision")
            if self.revision.strip() in ("main", "master", "HEAD", "trunk", "latest"):
                raise ValueError(
                    "fetch.revision MUST be an immutable commit sha, not a "
                    f"mutable ref: {self.revision!r}"
                )
        elif self.kind is FetchKind.HTTP:
            if not self.url or not self.expected_sha256:
                raise ValueError("fetch.kind='http' requires url + expected_sha256")
        elif self.kind is FetchKind.LOCAL:
            if not self.path:
                raise ValueError("fetch.kind='local' requires path")
        return self


class SourceManifest(BaseModel):
    """One rule-catalog source manifest."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
        validate_default=True,
    )

    schema_version: Annotated[str, Field(pattern=r"^\d+\.\d+\.\d+$")]
    id: Annotated[str, Field(pattern=r"^[a-z][a-z0-9._-]{1,63}$")]
    name: Annotated[str, Field(min_length=1, max_length=256)]
    url_prefix: str | None = None
    license: Annotated[str, Field(min_length=1)]
    redistribution: Redistribution
    fetch: FetchConfig
    parser: Annotated[str, Field(min_length=1)]
    cadence: Cadence = Cadence.ON_DEMAND


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def _load_json_schema() -> dict[str, Any]:
    raw = resources.files(_SCHEMA_PACKAGE).joinpath(_SCHEMA_FILE).read_text(encoding="utf-8")
    return json.loads(raw)  # type: ignore[no-any-return]


def load_source_manifest_from_mapping(raw: Mapping[str, Any]) -> SourceManifest:
    """Validate ``raw`` against JSON Schema + pydantic, return the model."""
    issues: list[ManifestIssue] = []

    schema = _load_json_schema()
    validator = Draft202012Validator(schema)
    for err in sorted(validator.iter_errors(dict(raw)), key=lambda e: list(e.path)):
        path = ".".join(str(p) for p in err.absolute_path) or "<root>"
        issues.append(ManifestIssue(key=path, message=err.message))

    if issues:
        raise ManifestError(issues)

    try:
        return SourceManifest.model_validate(raw)
    except ValueError as exc:
        errors = getattr(exc, "errors", None)
        if callable(errors):
            for e in errors():
                loc = ".".join(str(p) for p in e.get("loc", ()))
                issues.append(ManifestIssue(key=loc or "<root>", message=e["msg"]))
        else:
            issues.append(ManifestIssue(key="<root>", message=str(exc)))
        raise ManifestError(issues) from exc


def load_source_manifest_from_yaml(path: Path) -> SourceManifest:
    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    if not isinstance(raw, Mapping):
        raise ManifestError(
            [ManifestIssue(key="<root>", message=f"{path}: manifest MUST be a YAML mapping")]
        )
    return load_source_manifest_from_mapping(raw)


__all__ = [
    "Cadence",
    "FetchConfig",
    "FetchKind",
    "ManifestError",
    "ManifestIssue",
    "Redistribution",
    "SourceManifest",
    "load_source_manifest_from_mapping",
    "load_source_manifest_from_yaml",
]
