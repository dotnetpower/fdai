"""Load and validate chaos scenarios from `rule-catalog/chaos-scenarios/`.

Reads YAML scenarios out of `promoted/`, `collected/`, and (in a fork)
the `chaos-scenarios-custom/` / `chaos-scenarios-overrides/` overlay,
validates each against `schema/chaos-scenario.schema.json`, and turns
the result into a list of catalog entries suitable for indexing.

The loader is intentionally UI-agnostic and never imports from
`fdai.delivery.*`. It only depends on the signal registry to reject
scenarios whose `expected_signal` is not registered.

Two entry points:

    load_promoted(root=DEFAULT_ROOT) -> list[CatalogEntry]
        For runtime: only scenarios that already cleared shadow (and
        therefore live in `promoted/`) plus fork additions from
        `chaos-scenarios-custom/`, with `chaos-scenarios-overrides/`
        applied on top.

    load_all(root=DEFAULT_ROOT) -> list[CatalogEntry]
        For tooling: everything under `promoted/` and `collected/**` too;
        used by the deterministic combinator and CI validators.

Both entry points fail hard on schema violation or unknown signal - a
malformed catalog file must never silently load into the trust router.
"""

from __future__ import annotations

import json
import pathlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import jsonschema
import yaml

from fdai.core.detection.signals import is_known_signal

_HERE = pathlib.Path(__file__).resolve()
_REPO_ROOT = _HERE.parents[4]

DEFAULT_ROOT: pathlib.Path = _REPO_ROOT / "rule-catalog" / "chaos-scenarios"
_SCHEMA_PATH: pathlib.Path = DEFAULT_ROOT / "schema" / "chaos-scenario.schema.json"

# Forks add / override in these siblings of `chaos-scenarios/`.
_FORK_CUSTOM_DIR = "chaos-scenarios-custom"
_FORK_OVERRIDES_DIR = "chaos-scenarios-overrides"


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    """One loaded, validated scenario.

    The raw YAML body is preserved verbatim in ``spec`` (immutable view
    via dict copy) so downstream tools can consume any field without
    needing the loader to enumerate every field on the dataclass.
    """

    id: str
    source_path: pathlib.Path
    spec: Mapping[str, Any] = field(default_factory=dict)

    @property
    def expected_signal(self) -> str:
        return str(self.spec["expected_signal"])

    @property
    def category(self) -> str:
        return str(self.spec["category"])

    @property
    def gpu_domain(self) -> str | None:
        v = self.spec.get("gpu_domain")
        return str(v) if v else None

    @property
    def requires_hardware(self) -> bool:
        return bool(self.spec.get("requires_hardware", False))

    @property
    def shadow_status(self) -> str:
        return str(self.spec["gates"]["shadow_status"])

    @property
    def enforce_status(self) -> str | None:
        v = self.spec["gates"].get("enforce_status")
        return str(v) if v else None


class ScenarioCatalogError(Exception):
    """Loader / validator failure. Raised from a bad YAML, a schema
    violation, an unknown signal, or an id collision."""


def _load_schema() -> Mapping[str, Any]:
    with _SCHEMA_PATH.open("r", encoding="utf-8") as f:
        schema: Mapping[str, Any] = json.load(f)
    return schema


def _iter_yaml_files(root: pathlib.Path) -> list[pathlib.Path]:
    if not root.exists():
        return []
    out = sorted(p for p in root.rglob("*.yaml"))
    out += sorted(p for p in root.rglob("*.yml"))
    return sorted(set(out))


def _load_one(path: pathlib.Path, validator: jsonschema.Draft202012Validator) -> CatalogEntry:
    with path.open("r", encoding="utf-8") as f:
        body = yaml.safe_load(f)
    if not isinstance(body, dict):
        raise ScenarioCatalogError(f"{path}: top-level YAML must be a mapping")
    errors = sorted(validator.iter_errors(body), key=lambda e: list(e.absolute_path))
    if errors:
        joined = "; ".join(f"{list(e.absolute_path)}: {e.message}" for e in errors)
        raise ScenarioCatalogError(f"{path}: schema validation failed - {joined}")
    signal = body["expected_signal"]
    if not is_known_signal(signal):
        raise ScenarioCatalogError(
            f"{path}: expected_signal {signal!r} is not registered in "
            f"fdai.core.detection.signals. Register the SignalSpec first."
        )
    if body["injector"] in {"needs-injector", "cross-csp-reference"} and str(path.parent).endswith(
        "promoted"
    ):
        raise ScenarioCatalogError(
            f"{path}: injector {body['injector']!r} is not allowed in "
            f"promoted/; leave the file in collected/ until an executable "
            f"injector is wired."
        )
    return CatalogEntry(id=str(body["id"]), source_path=path, spec=dict(body))


def _apply_overrides(
    entries: list[CatalogEntry], overrides_dir: pathlib.Path
) -> list[CatalogEntry]:
    """Merge override YAMLs onto matching entries by id.

    An override file must be a mapping with `id` matching an existing
    entry; any other top-level field replaces (for scalars) or merges
    (for `params` / `gates`) the base value. Overrides that do not
    match any base entry are ignored (a fork may over-scope its
    overrides file to survive an upstream retirement without breaking
    the loader).
    """
    if not overrides_dir.exists():
        return entries
    by_id = {e.id: e for e in entries}
    for path in _iter_yaml_files(overrides_dir):
        with path.open("r", encoding="utf-8") as f:
            body = yaml.safe_load(f)
        if not isinstance(body, dict) or "id" not in body:
            raise ScenarioCatalogError(f"{path}: override must be a mapping with an `id` key")
        target = by_id.get(body["id"])
        if target is None:
            continue
        merged: dict[str, Any] = dict(target.spec)
        for key, value in body.items():
            if key == "id":
                continue
            if (
                key in {"params", "gates"}
                and isinstance(value, dict)
                and isinstance(merged.get(key), dict)
            ):
                new_sub = dict(merged[key])
                new_sub.update(value)
                merged[key] = new_sub
            else:
                merged[key] = value
        by_id[target.id] = CatalogEntry(id=target.id, source_path=target.source_path, spec=merged)
    return list(by_id.values())


def _dedupe_by_id(entries: list[CatalogEntry], scope: str) -> list[CatalogEntry]:
    seen: dict[str, pathlib.Path] = {}
    for e in entries:
        if e.id in seen and seen[e.id] != e.source_path:
            raise ScenarioCatalogError(
                f"duplicate scenario id {e.id!r} in {scope}: {seen[e.id]} and {e.source_path}"
            )
        seen[e.id] = e.source_path
    return entries


def _load_from(directories: list[pathlib.Path]) -> list[CatalogEntry]:
    schema = _load_schema()
    validator = jsonschema.Draft202012Validator(schema)
    entries: list[CatalogEntry] = []
    for d in directories:
        for path in _iter_yaml_files(d):
            entries.append(_load_one(path, validator))
    return entries


def load_promoted(root: pathlib.Path = DEFAULT_ROOT) -> list[CatalogEntry]:
    """Runtime path: promoted upstream + fork custom + fork overrides."""
    dirs = [root / "promoted"]
    fork_custom = root.parent / _FORK_CUSTOM_DIR
    if fork_custom.exists():
        dirs.append(fork_custom)
    entries = _dedupe_by_id(_load_from(dirs), scope="promoted+custom")
    fork_overrides = root.parent / _FORK_OVERRIDES_DIR
    return _apply_overrides(entries, fork_overrides)


def load_all(root: pathlib.Path = DEFAULT_ROOT) -> list[CatalogEntry]:
    """Tooling path: everything, including collected/**."""
    dirs = [root / "promoted", root / "collected"]
    fork_custom = root.parent / _FORK_CUSTOM_DIR
    if fork_custom.exists():
        dirs.append(fork_custom)
    entries = _dedupe_by_id(_load_from(dirs), scope="all")
    fork_overrides = root.parent / _FORK_OVERRIDES_DIR
    return _apply_overrides(entries, fork_overrides)


__all__ = [
    "DEFAULT_ROOT",
    "CatalogEntry",
    "ScenarioCatalogError",
    "load_all",
    "load_promoted",
]
