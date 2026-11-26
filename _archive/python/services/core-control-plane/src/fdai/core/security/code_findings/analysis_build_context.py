"""Deterministic build-context identity for owned code analysis."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

_CONFIG_NAMES = frozenset(
    {
        "build.gradle",
        "build.gradle.kts",
        "package.json",
        "pom.xml",
        "pyproject.toml",
        "setup.cfg",
        "tsconfig.json",
    }
)
_CONFIG_SUFFIXES = (".csproj", ".fsproj", ".props", ".targets")
_LANGUAGE_SUFFIXES = {
    "csharp": (".cs",),
    "java": (".java",),
    "python": (".py",),
    "typescript": (".cts", ".mts", ".ts", ".tsx"),
}


class AnalysisBuildContext(BaseModel):
    """Configuration inputs that can change frontend or framework semantics."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0.0"]
    language_roots: dict[str, tuple[str, ...]]
    configuration_digests: dict[str, str]
    generated_code_policy: Literal["include"] = "include"
    excluded_directories: tuple[str, ...] = (".git", ".fdai")

    def canonical_bytes(self) -> bytes:
        return json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")

    def digest(self) -> str:
        return f"sha256:{hashlib.sha256(self.canonical_bytes()).hexdigest()}"


def _bounded_digest(path: Path, limit: int) -> str:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > limit:
            raise ValueError("analysis build configuration is not a bounded regular file")
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            content = handle.read(limit + 1)
        if len(content) > limit:
            raise ValueError("analysis build configuration exceeds the byte limit")
        return f"sha256:{hashlib.sha256(content).hexdigest()}"
    finally:
        os.close(descriptor)


def build_analysis_context(
    root: Path,
    *,
    max_files: int = 500,
    max_file_bytes: int = 1_000_000,
) -> AnalysisBuildContext:
    """Return bounded language roots and build-configuration digests under ``root``."""
    base = root.resolve(strict=True)
    if root.is_symlink() or not base.is_dir():
        raise ValueError("analysis build-context root must be a non-symlink directory")
    language_roots: dict[str, set[str]] = {language: set() for language in _LANGUAGE_SUFFIXES}
    configurations: list[Path] = []
    for directory, directories, names in os.walk(base, followlinks=False):
        directories[:] = sorted(
            name
            for name in directories
            if name not in {".fdai", ".git"} and not (Path(directory) / name).is_symlink()
        )
        current = Path(directory)
        relative_root = current.relative_to(base).as_posix() or "."
        for name in sorted(names):
            path = current / name
            for language, suffixes in _LANGUAGE_SUFFIXES.items():
                if name.endswith(suffixes):
                    language_roots[language].add(relative_root)
            if name in _CONFIG_NAMES or name.endswith(_CONFIG_SUFFIXES):
                if path.is_symlink():
                    raise ValueError("analysis build configuration cannot be a symlink")
                configurations.append(path)
                if len(configurations) > max_files:
                    raise ValueError("analysis build-context file limit exceeded")
    digests = {
        path.relative_to(base).as_posix(): _bounded_digest(path, max_file_bytes)
        for path in sorted(configurations)
    }
    return AnalysisBuildContext(
        schema_version="1.0.0",
        language_roots={
            language: tuple(sorted(roots))
            for language, roots in sorted(language_roots.items())
            if roots
        },
        configuration_digests=digests,
    )


__all__ = ["AnalysisBuildContext", "build_analysis_context"]
