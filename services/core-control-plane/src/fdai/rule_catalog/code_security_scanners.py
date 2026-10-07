"""Strict loader for the deterministic-lane scanner catalog (``scanners.yaml``).

Each entry names the SARIF producer a scanner reports as, an argv template whose only
placeholders are ``{source}``, ``{rules}``, and ``{cache}``, the read-only mounts it needs, its
success exit codes, and its time and output bounds. Loading fails closed on any unknown key,
placeholder, or mount.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from fdai.rule_catalog.code_security import CodeSecurityCatalogError

_PLACEHOLDER = re.compile(r"\{([^{}]*)\}")
_ALLOWED = {"source", "rules", "cache"}


class ScannerSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    producer: Annotated[str, Field(min_length=2, max_length=64)]
    argv: Annotated[tuple[str, ...], Field(min_length=1, max_length=64)]
    mounts: tuple[Literal["rules", "cache"], ...] = ()
    cache_env: Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9_]{1,63}$")] | None = None
    success_exit_codes: Annotated[tuple[int, ...], Field(min_length=1)]
    timeout_seconds: Annotated[int, Field(ge=10, le=3600)]
    max_output_bytes: Annotated[int, Field(ge=1_000, le=50_000_000)]

    @model_validator(mode="after")
    def _placeholders(self) -> ScannerSpec:
        used: set[str] = set()
        for value in self.argv:
            if not value or "\x00" in value:
                raise ValueError("argv entries must be non-empty and NUL-free")
            names = set(_PLACEHOLDER.findall(value))
            if names - _ALLOWED:
                raise ValueError(f"unknown argv placeholders: {sorted(names - _ALLOWED)}")
            used |= names
        if "source" not in used:
            raise ValueError("argv must reference {source}")
        for mount in ("rules", "cache"):
            if mount in used and mount not in self.mounts:
                raise ValueError(f"argv uses {{{mount}}} without declaring the mount")
        if self.cache_env and "cache" not in self.mounts:
            raise ValueError("cache_env requires the cache mount")
        return self


class ScannerCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1]
    catalog_id: Annotated[str, Field(min_length=3, max_length=128)]
    version: Annotated[str, Field(pattern=r"^\d+\.\d+\.\d+$")]
    scanners: dict[Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]{1,31}$")], ScannerSpec]


def load_scanner_catalog(root: Path) -> ScannerCatalog:
    """Load ``scanners.yaml`` from the code-security catalog root, failing closed."""
    path = root / "scanners.yaml"
    try:
        return ScannerCatalog.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    except FileNotFoundError as exc:
        raise CodeSecurityCatalogError("missing code-security catalog file: scanners.yaml") from exc
    except (yaml.YAMLError, ValidationError) as exc:
        raise CodeSecurityCatalogError(f"invalid scanner catalog: {exc}") from exc


def resolve_argv(spec: ScannerSpec, mounts: dict[str, str]) -> tuple[str, ...]:
    """Substitute sandbox mount paths for placeholders; every used placeholder must resolve."""
    resolved = []
    for value in spec.argv:
        for name in _PLACEHOLDER.findall(value):
            if name not in mounts:
                raise CodeSecurityCatalogError(f"no sandbox path for {{{name}}}")
            value = value.replace("{" + name + "}", mounts[name])
        resolved.append(value)
    return tuple(resolved)


__all__ = ["ScannerCatalog", "ScannerSpec", "load_scanner_catalog", "resolve_argv"]
