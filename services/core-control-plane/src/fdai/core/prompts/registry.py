"""Load, validate, and index prompt artifacts from ``rule-catalog/prompts/``.

The :class:`PromptRegistry` :class:`~typing.Protocol` is the seam
``core/`` consumes; :class:`FileSystemPromptRegistry` is the upstream
default that walks a catalog root on disk. A fork MAY implement its own
registry (e.g. backed by a git snapshot service) and inject it at the
composition root.

Validation is aggregate: every issue found while scanning the tree is
collected into :class:`PromptRegistryError` so a reviewer sees the full
remediation list in one exception, matching the pattern in
:mod:`fdai.rule_catalog.schema.llm_registry`.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import yaml
from jsonschema import Draft202012Validator

from fdai.core.prompts.types import PromptArtifact, PromptLayer, PromptMode

_SCHEMA_FILE = "prompt.schema.json"
_PROMPTS_DIRNAME = "prompts"
_SCHEMA_DIRNAME = "schema"
# Sibling subsystems that live under ``prompts/`` but validate against a
# different schema (their own registries handle them). Listing them here
# keeps the prompt registry's rglob from picking up peer artifacts as
# malformed prompts.
_PEER_SUBSYSTEM_DIRNAMES = frozenset({"tools", "scenarios"})


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PromptRegistryIssue:
    """One aggregate-collected failure encountered while loading the tree."""

    path: str
    message: str


class PromptRegistryError(ValueError):
    """Raised when at least one prompt artifact fails validation.

    ``issues`` carries every problem found; the exception ``str`` is a
    short preview so log lines stay bounded but the full list is still
    available for tooling.
    """

    def __init__(self, issues: list[PromptRegistryIssue]) -> None:
        self.issues: tuple[PromptRegistryIssue, ...] = tuple(issues)
        preview = "; ".join(f"{i.path}: {i.message}" for i in issues[:5])
        suffix = f" (+{len(issues) - 5} more)" if len(issues) > 5 else ""
        super().__init__(f"prompt-catalog validation failed: {preview}{suffix}")


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


class PromptRegistry(Protocol):
    """Read-only lookup surface consumed by the composition root.

    Wave 1 exposed :meth:`get_base` only; Wave 2 adds :meth:`get_packs`
    so :class:`~fdai.core.prompts.composer.DefaultPromptComposer`
    can assemble Base + Task Skill Pack layers. Later waves add lookups
    for critic / judge / tool artifacts as they land.
    """

    def get_base(self, capability_id: str) -> PromptArtifact:
        """Return the highest-version base artifact bound to ``capability_id``.

        Raises :class:`LookupError` when nothing matches - the caller
        MUST decide whether that is fatal (production) or a soft skip
        (tests wiring only a subset).
        """

    def get_packs(self, capability_id: str) -> tuple[PromptArtifact, ...]:
        """Return every task-pack artifact bound to ``capability_id``.

        Packs are optional: an empty tuple means the composer emits
        only the base layer. Duplicate ``id`` values keep the highest
        version; ties break on id so the ordering stays reproducible.
        """

    def artifacts(self) -> tuple[PromptArtifact, ...]:
        """Every artifact discovered in the tree, sorted by (id, version)."""


# ---------------------------------------------------------------------------
# File-system implementation
# ---------------------------------------------------------------------------


class FileSystemPromptRegistry(PromptRegistry):
    """Walk ``<catalog_root>/prompts/`` and index every YAML artifact.

    The constructor is doing the heavy lifting (fail-fast): every YAML
    is parsed, validated against the JSON Schema, and coerced into a
    :class:`PromptArtifact`. Any issue is collected; if the collector
    is non-empty at the end the constructor raises
    :class:`PromptRegistryError`.
    """

    def __init__(self, catalog_root: Path) -> None:
        self._root: Path = catalog_root
        prompts_dir = catalog_root / _PROMPTS_DIRNAME
        if not prompts_dir.is_dir():
            raise FileNotFoundError(f"prompt catalog directory not found at {prompts_dir!s}")
        schema_path = prompts_dir / _SCHEMA_DIRNAME / _SCHEMA_FILE
        if not schema_path.is_file():
            raise FileNotFoundError(f"prompt catalog schema not found at {schema_path!s}")
        validator = Draft202012Validator(json.loads(schema_path.read_text()))

        issues: list[PromptRegistryIssue] = []
        loaded: list[PromptArtifact] = []
        for yaml_path in _iter_prompt_files(prompts_dir):
            try:
                raw = yaml.safe_load(yaml_path.read_text())
            except yaml.YAMLError as exc:  # pragma: no cover - PyYAML detail
                issues.append(
                    PromptRegistryIssue(path=str(yaml_path), message=f"invalid YAML: {exc}")
                )
                continue
            if not isinstance(raw, dict):
                issues.append(
                    PromptRegistryIssue(
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
                        PromptRegistryIssue(
                            path=f"{yaml_path}#{pointer}",
                            message=err.message,
                        )
                    )
                continue
            filename_issue = _check_filename(yaml_path, raw)
            if filename_issue is not None:
                issues.append(filename_issue)
                continue
            loaded.append(_coerce(raw, provenance_default=str(yaml_path)))

        if issues:
            raise PromptRegistryError(issues)

        # Sorting keeps ``artifacts()`` deterministic across platforms.
        loaded.sort(key=lambda a: (a.id, a.version))
        self._artifacts: tuple[PromptArtifact, ...] = tuple(loaded)

    # -- PromptRegistry protocol ------------------------------------------------

    def get_base(self, capability_id: str) -> PromptArtifact:
        candidates = [
            art
            for art in self._artifacts
            if art.layer is PromptLayer.BASE and art.matches(capability_id)
        ]
        if not candidates:
            raise LookupError(
                f"no base prompt in {self._root!s}/{_PROMPTS_DIRNAME}/base "
                f"declares applies_to including {capability_id!r}"
            )
        # Highest version wins; tie-break by id for a deterministic pick.
        candidates.sort(key=lambda a: (a.version, a.id), reverse=True)
        return candidates[0]

    def get_packs(self, capability_id: str) -> tuple[PromptArtifact, ...]:
        # Group by id and keep the highest version so a legacy pack
        # sitting next to a bumped one does not double-inject.
        by_id: dict[str, PromptArtifact] = {}
        for art in self._artifacts:
            if art.layer is not PromptLayer.PACK:
                continue
            if not art.matches(capability_id):
                continue
            current = by_id.get(art.id)
            if current is None or art.version > current.version:
                by_id[art.id] = art
        return tuple(sorted(by_id.values(), key=lambda a: (a.id, a.version)))

    def artifacts(self) -> tuple[PromptArtifact, ...]:
        return self._artifacts


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _iter_prompt_files(prompts_dir: Path) -> Iterator[Path]:
    """Yield every YAML file under ``prompts/`` except peer subsystems.

    The schema directory holds JSON, but a defensive filter keeps a
    stray YAML there from being mistaken for an artifact. Peer
    subsystems (currently only ``tools/``) live under the same tree
    with their own schema and their own registry - excluding them here
    prevents the prompt schema validator from choking on a tool YAML.
    """

    for path in sorted(prompts_dir.rglob("*.yaml")):
        parts = path.relative_to(prompts_dir).parts
        if _SCHEMA_DIRNAME in parts:
            continue
        if parts and parts[0] in _PEER_SUBSYSTEM_DIRNAMES:
            continue
        yield path


def _check_filename(path: Path, raw: dict[str, object]) -> PromptRegistryIssue | None:
    """Enforce ``<id>.v<version>.yaml`` per the README contract."""

    expected = f"{raw['id']}.v{raw['version']}.yaml"
    if path.name != expected:
        return PromptRegistryIssue(
            path=str(path),
            message=(f"file name MUST be '{expected}' to match id+version front-matter"),
        )
    return None


def _coerce(raw: dict[str, object], *, provenance_default: str) -> PromptArtifact:
    """Turn a schema-validated mapping into a :class:`PromptArtifact`.

    ``provenance_default`` is used only when the (schema-required)
    ``provenance.source`` was ever loosened; the schema currently makes
    it mandatory, so in practice we always read it from the YAML. The
    fallback stays as a safety net so a future schema relaxation cannot
    silently drop provenance.
    """

    applies_to_raw = raw.get("applies_to") or ()
    applies_to = tuple(str(item) for item in _as_iter(applies_to_raw))
    provenance_block = raw.get("provenance") or {}
    if isinstance(provenance_block, dict):
        provenance_source = str(provenance_block.get("source") or provenance_default)
    else:
        provenance_source = provenance_default
    default_mode_raw = str(raw.get("default_mode") or PromptMode.SHADOW.value)
    token_budget_raw = raw.get("token_budget")
    return PromptArtifact(
        id=str(raw["id"]),
        version=int(raw["version"]),  # type: ignore[call-overload]
        layer=PromptLayer(str(raw["layer"])),
        body=str(raw["body"]),
        applies_to=applies_to,
        token_budget=int(token_budget_raw) if token_budget_raw is not None else None,  # type: ignore[call-overload]
        default_mode=PromptMode(default_mode_raw),
        provenance_source=provenance_source,
    )


def _as_iter(value: object) -> Iterable[object]:
    if isinstance(value, (list, tuple)):
        return value
    raise TypeError(f"expected list, got {type(value).__name__}")


__all__ = [
    "FileSystemPromptRegistry",
    "PromptRegistry",
    "PromptRegistryError",
    "PromptRegistryIssue",
]
