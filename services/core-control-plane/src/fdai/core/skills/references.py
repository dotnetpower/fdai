"""Immutable content-addressed support references for runtime skills."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath

from fdai.core.skills.errors import SkillCatalogError

_SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")
_MEDIA_TYPE_PATTERN = re.compile(
    r"^[a-z0-9][a-z0-9!#$&^_.+-]{0,62}/[a-z0-9][a-z0-9!#$&^_.+-]{0,62}$"
)
_PATH_SEGMENT_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
MAX_REFERENCE_COUNT = 16
MAX_REFERENCE_BYTES = 256 * 1024
MAX_REFERENCE_TOTAL_BYTES = 1024 * 1024
_MAX_REFERENCE_PATH_CHARS = 255


@dataclass(frozen=True, slots=True)
class SkillReferenceManifest:
    path: str
    sha256: str
    size_bytes: int
    media_type: str


@dataclass(frozen=True, slots=True)
class SkillReferenceArtifact:
    manifest: SkillReferenceManifest
    content: bytes


def validate_reference_manifest(references: tuple[SkillReferenceManifest, ...]) -> None:
    paths = tuple(reference.path for reference in references)
    if len(set(paths)) != len(paths):
        raise ValueError("skill references MUST NOT contain duplicate paths")
    if len(references) > MAX_REFERENCE_COUNT:
        raise ValueError("skill references MUST NOT contain more than 16 entries")
    if sum(reference.size_bytes for reference in references) > MAX_REFERENCE_TOTAL_BYTES:
        raise ValueError("skill references exceed the 1 MiB total limit")


def validate_reference_declaration(
    *,
    path: str,
    sha256: str,
    size_bytes: int,
    media_type: str,
) -> None:
    parts = path.split("/")
    if (
        len(path) > _MAX_REFERENCE_PATH_CHARS
        or "\\" in path
        or PurePosixPath(path).is_absolute()
        or len(parts) < 2
        or parts[0] != "references"
        or any(part in {"", ".", ".."} for part in parts)
        or any(_PATH_SEGMENT_PATTERN.fullmatch(part) is None for part in parts)
    ):
        raise ValueError("skill reference path MUST be a safe path under references/")
    if _SHA256_PATTERN.fullmatch(sha256) is None:
        raise ValueError("skill reference sha256 MUST be a lowercase SHA-256 digest")
    if size_bytes < 0 or size_bytes > MAX_REFERENCE_BYTES:
        raise ValueError("skill reference size_bytes MUST be between 0 and 256 KiB")
    if len(media_type) > 127 or _MEDIA_TYPE_PATTERN.fullmatch(media_type) is None:
        raise ValueError("skill reference media_type MUST be a bounded lowercase media type")


def build_reference_artifacts(
    declarations: tuple[SkillReferenceManifest, ...],
    references: Mapping[str, bytes],
) -> tuple[SkillReferenceArtifact, ...]:
    declared_paths = {declaration.path for declaration in declarations}
    provided_paths = set(references)
    missing = declared_paths - provided_paths
    if missing:
        raise SkillCatalogError(f"skill bundle is missing references: {sorted(missing)}")
    extra = provided_paths - declared_paths
    if extra:
        raise SkillCatalogError(f"skill bundle has undeclared references: {sorted(extra)}")
    artifacts: list[SkillReferenceArtifact] = []
    for declaration in declarations:
        content = references[declaration.path]
        if not isinstance(content, bytes):
            raise SkillCatalogError("skill reference content MUST be immutable bytes")
        if len(content) != declaration.size_bytes:
            raise SkillCatalogError(
                f"skill reference {declaration.path!r} size does not match front matter"
            )
        if hashlib.sha256(content).hexdigest() != declaration.sha256:
            raise SkillCatalogError(
                f"skill reference {declaration.path!r} digest does not match front matter"
            )
        artifacts.append(SkillReferenceArtifact(manifest=declaration, content=content))
    return tuple(artifacts)


def verify_reference_artifacts(
    declarations: tuple[SkillReferenceManifest, ...],
    artifacts: tuple[SkillReferenceArtifact, ...],
) -> None:
    paths = tuple(artifact.manifest.path for artifact in artifacts)
    if len(set(paths)) != len(paths):
        raise SkillCatalogError("stored skill references contain duplicate paths")
    supplied = {artifact.manifest.path: artifact.content for artifact in artifacts}
    rebuilt = build_reference_artifacts(declarations, supplied)
    if tuple(artifact.manifest for artifact in rebuilt) != tuple(
        artifact.manifest for artifact in artifacts
    ):
        raise SkillCatalogError("stored skill reference metadata does not match front matter")


__all__ = [
    "MAX_REFERENCE_COUNT",
    "SkillReferenceArtifact",
    "SkillReferenceManifest",
    "build_reference_artifacts",
    "validate_reference_declaration",
    "validate_reference_manifest",
    "verify_reference_artifacts",
]
