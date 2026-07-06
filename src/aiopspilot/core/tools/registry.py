"""Load, validate, and index tool artifacts from ``rule-catalog/prompts/tools/``.

Mirrors the aggregate-error / fail-fast pattern of
:mod:`aiopspilot.core.prompts.registry` so the developer sees every
malformed tool YAML in one exception rather than fixing them one at a
time.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Protocol

import yaml
from jsonschema import Draft202012Validator

from aiopspilot.core.prompts.types import PromptMode
from aiopspilot.core.tools.types import CapabilityGate, ToolArtifact

_SCHEMA_FILE: Final[str] = "tool.schema.json"
_TOOLS_DIRNAME: Final[str] = "tools"
_PROMPTS_DIRNAME: Final[str] = "prompts"
_SCHEMA_DIRNAME: Final[str] = "schema"
_UNTRUSTED_MARKER: Final[str] = 'trusted="false"'


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ToolRegistryIssue:
    """One aggregate-collected failure encountered while loading the tree."""

    path: str
    message: str


class ToolRegistryError(ValueError):
    """Raised when at least one tool artifact fails validation."""

    def __init__(self, issues: list[ToolRegistryIssue]) -> None:
        self.issues: tuple[ToolRegistryIssue, ...] = tuple(issues)
        preview = "; ".join(f"{i.path}: {i.message}" for i in issues[:5])
        suffix = f" (+{len(issues) - 5} more)" if len(issues) > 5 else ""
        super().__init__(f"tool-catalog validation failed: {preview}{suffix}")


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


class ToolRegistry(Protocol):
    """Read-only lookup surface consumed by the composer and executor.

    Wave 2.5-A ships :meth:`get` and :meth:`artifacts`; the Wave 2.5-B
    executor adds an ``eligible_for(role_capability_id)`` helper that
    applies the tool's :class:`CapabilityGate` at dispatch time.
    """

    def get(self, tool_id: str) -> ToolArtifact:
        """Return the highest-version tool artifact with ``tool_id``.

        Raises :class:`LookupError` when nothing matches.
        """

    def artifacts(self) -> tuple[ToolArtifact, ...]:
        """Every tool discovered in the tree, sorted by (id, version)."""


# ---------------------------------------------------------------------------
# File-system implementation
# ---------------------------------------------------------------------------


class FileSystemToolRegistry(ToolRegistry):
    """Walk ``<catalog_root>/prompts/tools/`` and index every YAML tool.

    The constructor is fail-fast: every YAML is parsed, validated
    against the JSON Schema, and coerced into a :class:`ToolArtifact`.
    Wave 2.5-A ships with an empty ``catalog/`` directory - the tests
    exercise the full validation surface via ``tmp_path`` fixtures.
    """

    def __init__(self, catalog_root: Path) -> None:
        self._root: Final[Path] = catalog_root
        tools_dir = catalog_root / _PROMPTS_DIRNAME / _TOOLS_DIRNAME
        if not tools_dir.is_dir():
            raise FileNotFoundError(f"tool catalog directory not found at {tools_dir!s}")
        schema_path = tools_dir / _SCHEMA_DIRNAME / _SCHEMA_FILE
        if not schema_path.is_file():
            raise FileNotFoundError(f"tool catalog schema not found at {schema_path!s}")
        validator = Draft202012Validator(json.loads(schema_path.read_text()))

        issues: list[ToolRegistryIssue] = []
        loaded: list[ToolArtifact] = []
        for yaml_path in _iter_tool_files(tools_dir):
            try:
                raw = yaml.safe_load(yaml_path.read_text())
            except yaml.YAMLError as exc:  # pragma: no cover - PyYAML detail
                issues.append(
                    ToolRegistryIssue(path=str(yaml_path), message=f"invalid YAML: {exc}")
                )
                continue
            if not isinstance(raw, dict):
                issues.append(
                    ToolRegistryIssue(
                        path=str(yaml_path),
                        message="top-level YAML MUST be a mapping",
                    )
                )
                continue
            schema_errors = sorted(validator.iter_errors(raw), key=lambda e: list(e.absolute_path))
            if schema_errors:
                for err in schema_errors:
                    pointer = "/".join(str(p) for p in err.absolute_path) or "<root>"
                    issues.append(
                        ToolRegistryIssue(
                            path=f"{yaml_path}#{pointer}",
                            message=err.message,
                        )
                    )
                continue
            filename_issue = _check_filename(yaml_path, raw)
            if filename_issue is not None:
                issues.append(filename_issue)
                continue
            wrapper_issue = _check_output_wrapper(yaml_path, raw)
            if wrapper_issue is not None:
                issues.append(wrapper_issue)
                continue
            loaded.append(_coerce(raw))

        if issues:
            raise ToolRegistryError(issues)

        loaded.sort(key=lambda a: (a.id, a.version))
        self._artifacts: Final[tuple[ToolArtifact, ...]] = tuple(loaded)

    def get(self, tool_id: str) -> ToolArtifact:
        candidates = [a for a in self._artifacts if a.id == tool_id]
        if not candidates:
            raise LookupError(
                f"no tool with id {tool_id!r} under "
                f"{self._root!s}/{_PROMPTS_DIRNAME}/{_TOOLS_DIRNAME}"
            )
        candidates.sort(key=lambda a: a.version, reverse=True)
        return candidates[0]

    def artifacts(self) -> tuple[ToolArtifact, ...]:
        return self._artifacts


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _iter_tool_files(tools_dir: Path) -> Iterator[Path]:
    for path in sorted(tools_dir.rglob("*.yaml")):
        if _SCHEMA_DIRNAME in path.relative_to(tools_dir).parts:
            continue
        yield path


def _check_filename(path: Path, raw: dict[str, object]) -> ToolRegistryIssue | None:
    expected = f"{raw['id']}.v{raw['version']}.yaml"
    if path.name != expected:
        return ToolRegistryIssue(
            path=str(path),
            message=f"file name MUST be '{expected}' to match id+version front-matter",
        )
    return None


def _check_output_wrapper(path: Path, raw: dict[str, object]) -> ToolRegistryIssue | None:
    """Enforce the ``trusted="false"`` invariant on any populated wrapper.

    Wrappers without the untrusted marker collapse a critical safety
    invariant from the design doc (tool output MUST be treated as data,
    not instructions). Absent wrapper is fine - the Wave 2.5-B executor
    will inject a canonical wrapper when the tool YAML leaves it off.
    """

    wrapper = raw.get("output_wrapper")
    if wrapper is None:
        return None
    if not isinstance(wrapper, str) or _UNTRUSTED_MARKER not in wrapper:
        return ToolRegistryIssue(
            path=str(path),
            message=(
                "output_wrapper MUST include 'trusted=\"false\"' so the model "
                "treats tool output as data, not instructions"
            ),
        )
    return None


def _coerce(raw: dict[str, Any]) -> ToolArtifact:
    """Turn a schema-validated mapping into a :class:`ToolArtifact`."""

    provenance_block = raw.get("provenance") or {}
    if not isinstance(provenance_block, Mapping):  # pragma: no cover - schema-guarded
        provenance_source = "<unknown>"
    else:
        provenance_source = str(provenance_block.get("source") or "<unknown>")
    gate_raw = raw.get("capability_gate") or {}
    if not isinstance(gate_raw, Mapping):  # pragma: no cover - schema-guarded
        gate_raw = {}
    gate = CapabilityGate(
        requires_tier=(str(gate_raw["requires_tier"]) if "requires_tier" in gate_raw else None),
        requires_novelty_score=(
            str(gate_raw["requires_novelty_score"])
            if "requires_novelty_score" in gate_raw
            else None
        ),
        cost_budget_usd_per_call=(
            float(gate_raw["cost_budget_usd_per_call"])
            if "cost_budget_usd_per_call" in gate_raw
            else None
        ),
    )
    default_mode_raw = str(raw.get("default_mode") or PromptMode.SHADOW.value)
    return ToolArtifact(
        id=str(raw["id"]),
        version=int(raw["version"]),
        description=str(raw["description"]),
        input_schema=dict(raw["input_schema"]),
        capability_gate=gate,
        allowlist=dict(raw["allowlist"]) if "allowlist" in raw else None,
        output_wrapper=str(raw["output_wrapper"]) if "output_wrapper" in raw else None,
        default_mode=PromptMode(default_mode_raw),
        provider=str(raw["provider"]) if "provider" in raw else None,
        provenance_source=provenance_source,
    )


__all__ = [
    "FileSystemToolRegistry",
    "ToolRegistry",
    "ToolRegistryError",
    "ToolRegistryIssue",
]
