"""Probe manifest loader (M1 groundwork).

Loads YAML declarations under ``rule-catalog/probes/`` and validates
each against the shipped JSON Schema. This is the lightweight, no-I/O
half of the live-blast probe subsystem described in
[execution-model.md § 4](../../../../docs/roadmap/decisioning/execution-model.md).
The heavyweight half (Azure Monitor adapter that turns a manifest into
a runtime probe result) lands in Wave M1; this module is what
`ActionType.live_probe_ref` resolves against at catalog load so a
misspelled reference is a fatal load error, not a runtime surprise.

Design points:

- Pure data. No adapter is invoked; no HTTP; no cloud SDK.
- Fail closed. A file with an invalid schema or a duplicate ``id``
  raises :class:`ProbeCatalogError` collecting every issue.
- Idempotent. Re-loading yields the same tuple.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator


@dataclass(frozen=True)
class ProbeIssue:
    """One error collected during probe-catalog load."""

    key: str
    message: str


class ProbeCatalogError(ValueError):
    """Raised when one or more probe manifests fail schema / uniqueness."""

    def __init__(self, issues: list[ProbeIssue]) -> None:
        super().__init__(
            "probe catalog load failed: " + "; ".join(f"{i.key}: {i.message}" for i in issues)
        )
        self.issues = tuple(issues)


@dataclass(frozen=True)
class ProbeManifest:
    """One live-blast probe declaration."""

    id: str
    description: str
    adapter_ref: str
    adapter_payload: Mapping[str, Any]
    interpretation: Mapping[str, str]
    timeout_seconds: int
    cache_ttl_seconds: int

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> ProbeManifest:
        return cls(
            id=str(raw["id"]),
            description=str(raw["description"]),
            adapter_ref=str(raw["adapter_ref"]),
            adapter_payload=dict(raw.get("adapter_payload") or {}),
            interpretation={k: str(v) for k, v in dict(raw["interpretation"]).items()},
            timeout_seconds=int(raw["timeout_seconds"]),
            cache_ttl_seconds=int(raw["cache_ttl_seconds"]),
        )


def _iter_probe_files(root: Path) -> Iterator[Path]:
    yield from sorted(root.glob("*.yaml"))


def _load_schema(schema_path: Path) -> dict[str, Any]:
    with schema_path.open() as f:
        loaded = json.load(f)
    if not isinstance(loaded, dict):
        raise ValueError(f"probe schema at {schema_path} must be a JSON object")
    return loaded


def load_probe_catalog(root: Path) -> tuple[ProbeManifest, ...]:
    """Load every probe YAML under ``root``.

    Silently returns an empty tuple when ``root`` has no probe YAML
    files (only ``README.md`` present) - matching the Day-1 contract
    that ``rule-catalog/probes/`` is a placeholder until Month 1. A
    missing schema file is a hard error.
    """

    if not root.is_dir():
        raise FileNotFoundError(f"probe catalog root not a directory: {root}")

    schema_path = root / "probe.schema.json"
    if not schema_path.is_file():
        # Placeholder mode: catalog exists but schema not yet added.
        # Return empty rather than crashing so pre-M1 startup works.
        return ()

    schema = _load_schema(schema_path)
    validator = Draft202012Validator(schema)

    issues: list[ProbeIssue] = []
    loaded: list[ProbeManifest] = []
    seen_ids: dict[str, str] = {}

    for path in _iter_probe_files(root):
        try:
            with path.open() as f:
                raw = yaml.safe_load(f)
        except yaml.YAMLError as exc:
            issues.append(ProbeIssue(key=path.name, message=f"invalid YAML: {exc}"))
            continue
        if not isinstance(raw, dict):
            issues.append(ProbeIssue(key=path.name, message="top-level must be a mapping"))
            continue
        errors = list(validator.iter_errors(raw))
        if errors:
            for err in errors:
                loc = ".".join(str(p) for p in err.absolute_path) or "<root>"
                issues.append(ProbeIssue(key=f"{path.name}:{loc}", message=err.message))
            continue
        try:
            manifest = ProbeManifest.from_mapping(raw)
        except (KeyError, TypeError, ValueError) as exc:
            issues.append(ProbeIssue(key=path.name, message=str(exc)))
            continue
        prior = seen_ids.get(manifest.id)
        if prior is not None:
            issues.append(
                ProbeIssue(
                    key=path.name,
                    message=f"duplicate probe id {manifest.id!r} (also in {prior})",
                )
            )
            continue
        seen_ids[manifest.id] = path.name
        loaded.append(manifest)

    if issues:
        raise ProbeCatalogError(issues)
    return tuple(loaded)


def probe_ids(catalog: Iterable[ProbeManifest]) -> set[str]:
    return {p.id for p in catalog}


__all__ = [
    "ProbeCatalogError",
    "ProbeIssue",
    "ProbeManifest",
    "load_probe_catalog",
    "probe_ids",
]
