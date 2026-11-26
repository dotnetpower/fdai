"""Derive bounded source snapshots for one service image build."""

from __future__ import annotations

import os
import shlex
from pathlib import PurePosixPath

from fdai_deployment_cli.runtime_release import RUNTIME_SERVICES
from fdai_deployment_cli.source_input import SourceDeploymentInput, _git, _read_tracked

_SUPPORT_FILES = frozenset(
    {
        ".dockerignore",
        "scripts/automation/run-bounded-command.py",
        "scripts/deployment/azure/genesis_checks.py",
        "scripts/deployment/azure/genesis_subprocess.py",
        "scripts/deployment/azure/source_image_build.py",
    }
)


def service_source_projection(
    source: SourceDeploymentInput,
    service: str,
) -> tuple[str, ...]:
    """Return the exact tracked files needed to build one baseline service image.

    The Dockerfile remains the source of its copy inputs. Unsupported Dockerfile
    syntax fails closed instead of broadening the projection to the repository.
    """
    if service not in RUNTIME_SERVICES:
        raise ValueError("source projection service is outside the baseline inventory")
    entries = _tracked_entries(source)
    dockerfile = f"services/{service}/docker/Dockerfile"
    if dockerfile not in entries:
        raise ValueError("source projection Dockerfile is unavailable")
    content = _read_tracked(source.root, dockerfile, mode=entries[dockerfile]).decode("utf-8")
    selected = set(_SUPPORT_FILES)
    explicit_filtered: set[str] = set()
    selected.add(dockerfile)
    for item in _docker_copy_sources(content):
        expanded = _expand_tracked_source(item, entries)
        selected.update(expanded)
        if _explicit_filtered_source(item):
            explicit_filtered.update(expanded)
    missing = selected - entries.keys()
    if missing:
        raise ValueError("source projection requires unavailable tracked inputs")
    selected = {
        path for path in selected if path in explicit_filtered or _included_build_input(path)
    }
    _include_symlink_targets(source, selected, entries)
    return tuple(sorted(selected))


def _tracked_entries(source: SourceDeploymentInput) -> dict[str, str]:
    entries: dict[str, str] = {}
    for entry in _git(source.root, "ls-tree", "-rz", "--full-tree", source.commit).split(b"\0"):
        if not entry:
            continue
        metadata, raw_path = entry.split(b"\t", 1)
        mode, kind, _blob = metadata.decode("ascii").split()
        if kind != "blob" or mode not in {"100644", "100755", "120000"}:
            raise ValueError("source projection contains an unsupported tracked input")
        entries[raw_path.decode("utf-8")] = mode
    return entries


def _docker_copy_sources(content: str) -> tuple[str, ...]:
    logical: list[str] = []
    pending = ""
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        pending = f"{pending} {line}".strip()
        if pending.endswith("\\"):
            pending = pending[:-1].rstrip()
            continue
        logical.append(pending)
        pending = ""
    if pending:
        raise ValueError("source projection Dockerfile has an incomplete instruction")

    sources: list[str] = []
    for instruction in logical:
        parts = shlex.split(instruction)
        if not parts:
            continue
        if parts[0].upper() == "ADD":
            raise ValueError("source projection does not accept Docker ADD inputs")
        if parts[0].upper() != "COPY":
            continue
        if any(part.startswith("--from=") for part in parts[1:]):
            continue
        operands = [part for part in parts[1:] if not part.startswith("--")]
        if len(operands) < 2:
            raise ValueError("source projection COPY instruction is invalid")
        for value in operands[:-1]:
            if any(character in value for character in "*?[") or value.startswith("$"):
                raise ValueError("source projection does not accept dynamic COPY inputs")
            path = PurePosixPath(value)
            if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
                raise ValueError("source projection COPY input is invalid")
            sources.append(path.as_posix())
    if not sources:
        raise ValueError("source projection Dockerfile has no local COPY inputs")
    return tuple(sources)


def _expand_tracked_source(value: str, entries: dict[str, str]) -> set[str]:
    if value in entries:
        return {value}
    prefix = value.rstrip("/") + "/"
    matches = {path for path in entries if path.startswith(prefix)}
    if not matches:
        raise ValueError("source projection COPY input is unavailable")
    return matches


def _included_build_input(path: str) -> bool:
    if "/tests/" in path and not path.startswith("services/core-control-plane/tests/scenarios/"):
        return False
    if path.endswith(".md") and path not in {
        "README.md",
        "rule-catalog/README.md",
        "extensions/cost-governance/README.md",
        "extensions/cost-governance/README-ko.md",
    }:
        return False
    parts = PurePosixPath(path).parts
    return not (
        "__pycache__" in parts
        or "node_modules" in parts
        or "dist" in parts
        or path.endswith(".pyc")
    )


def _explicit_filtered_source(path: str) -> bool:
    parts = PurePosixPath(path).parts
    return "tests" in parts or "docs" in parts or path.endswith(".md")


def _include_symlink_targets(
    source: SourceDeploymentInput,
    selected: set[str],
    entries: dict[str, str],
) -> None:
    pending = [path for path in selected if entries[path] == "120000"]
    while pending:
        relative = pending.pop()
        target = os.fsdecode(_read_tracked(source.root, relative, mode="120000"))
        resolved = PurePosixPath(relative).parent / target
        if resolved.is_absolute() or ".." in resolved.parts:
            raise ValueError("source projection link leaves the tracked file set")
        normalized = resolved.as_posix()
        if normalized not in entries:
            raise ValueError("source projection link target is unavailable")
        if normalized not in selected:
            selected.add(normalized)
            if entries[normalized] == "120000":
                pending.append(normalized)
