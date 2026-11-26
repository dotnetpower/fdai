"""Canonical bounded persistence codec for trusted skill bundles."""

from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from fdai.core.skills import SkillCatalogError, parse_skill_markdown
from fdai.core.skills.references import (
    MAX_REFERENCE_COUNT,
    MAX_REFERENCE_TOTAL_BYTES,
    build_reference_artifacts,
)

SKILL_BUNDLE_KIND = "fdai.skill-bundle"
SKILL_BUNDLE_VERSION = 1
MAX_ENCODED_SKILL_BUNDLE_BYTES = 2 * 1024 * 1024
MAX_SKILL_MARKDOWN_BYTES = 64 * 1024

_BUNDLE_KEYS = frozenset({"kind", "markdown", "references", "version"})
_REFERENCE_KEYS = frozenset({"content", "path"})


class SkillBundleCodecError(ValueError):
    """A durable skill bundle is malformed, non-canonical, or out of bounds."""


@dataclass(frozen=True, slots=True)
class DecodedSkillBundle:
    raw_markdown: bytes
    references: Mapping[str, bytes]


def encode_skill_bundle(raw_markdown: bytes, references: Mapping[str, bytes]) -> bytes:
    """Encode one validated skill bundle as deterministic canonical JSON bytes."""
    bundle = _validate_bundle(raw_markdown, references)
    document = {
        "kind": SKILL_BUNDLE_KIND,
        "markdown": bundle.raw_markdown.decode("utf-8"),
        "references": [
            {
                "content": base64.b64encode(content).decode("ascii"),
                "path": path,
            }
            for path, content in sorted(bundle.references.items())
        ],
        "version": SKILL_BUNDLE_VERSION,
    }
    encoded = json.dumps(
        document,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(encoded) > MAX_ENCODED_SKILL_BUNDLE_BYTES:
        raise SkillBundleCodecError("encoded skill bundle exceeds the 2 MiB limit")
    return encoded


def decode_skill_bundle(artifact: bytes) -> DecodedSkillBundle:
    """Decode canonical JSON, or a legacy reference-free raw Markdown artifact."""
    if len(artifact) > MAX_ENCODED_SKILL_BUNDLE_BYTES:
        raise SkillBundleCodecError("encoded skill bundle exceeds the 2 MiB limit")
    if artifact.startswith(b"---\n"):
        return _validate_bundle(artifact, {})
    try:
        text = artifact.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SkillBundleCodecError("skill bundle MUST be UTF-8 JSON") from exc
    try:
        decoded: object = json.loads(text, object_pairs_hook=_unique_object)
    except json.JSONDecodeError as exc:
        raise SkillBundleCodecError("skill bundle MUST be valid JSON") from exc
    if not isinstance(decoded, dict):
        raise SkillBundleCodecError("skill bundle root MUST be an object")
    _require_exact_keys(decoded, _BUNDLE_KEYS, "skill bundle")
    if decoded["kind"] != SKILL_BUNDLE_KIND:
        raise SkillBundleCodecError("skill bundle kind is unsupported")
    if type(decoded["version"]) is not int or decoded["version"] != SKILL_BUNDLE_VERSION:
        raise SkillBundleCodecError("skill bundle version is unsupported")
    markdown = decoded["markdown"]
    if not isinstance(markdown, str):
        raise SkillBundleCodecError("skill bundle markdown MUST be a string")
    try:
        raw_markdown = markdown.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise SkillBundleCodecError("skill bundle markdown MUST be valid UTF-8") from exc
    raw_references = decoded["references"]
    if not isinstance(raw_references, list):
        raise SkillBundleCodecError("skill bundle references MUST be an array")
    if len(raw_references) > MAX_REFERENCE_COUNT:
        raise SkillBundleCodecError("skill bundle references exceed the 16 entry limit")
    references: dict[str, bytes] = {}
    reference_bytes = 0
    for raw_reference in raw_references:
        if not isinstance(raw_reference, dict):
            raise SkillBundleCodecError("skill bundle reference MUST be an object")
        _require_exact_keys(raw_reference, _REFERENCE_KEYS, "skill bundle reference")
        path = raw_reference["path"]
        content = raw_reference["content"]
        if not isinstance(path, str) or not isinstance(content, str):
            raise SkillBundleCodecError("skill bundle reference fields MUST be strings")
        if path in references:
            raise SkillBundleCodecError("skill bundle contains duplicate reference paths")
        try:
            decoded_content = base64.b64decode(content.encode("ascii"), validate=True)
        except (UnicodeEncodeError, binascii.Error) as exc:
            raise SkillBundleCodecError("skill bundle reference content MUST be base64") from exc
        reference_bytes += len(decoded_content)
        if reference_bytes > MAX_REFERENCE_TOTAL_BYTES:
            raise SkillBundleCodecError("skill bundle references exceed the 1 MiB total limit")
        references[path] = decoded_content
    bundle = _validate_bundle(raw_markdown, references)
    if encode_skill_bundle(bundle.raw_markdown, bundle.references) != artifact:
        raise SkillBundleCodecError("skill bundle bytes MUST use canonical encoding")
    return bundle


def _validate_bundle(
    raw_markdown: bytes,
    references: Mapping[str, bytes],
) -> DecodedSkillBundle:
    if len(raw_markdown) > MAX_SKILL_MARKDOWN_BYTES:
        raise SkillBundleCodecError("skill bundle markdown exceeds the 64 KiB limit")
    try:
        skill = parse_skill_markdown(raw_markdown)
        build_reference_artifacts(skill.manifest.references, references)
    except SkillCatalogError as exc:
        raise SkillBundleCodecError(str(exc)) from exc
    return DecodedSkillBundle(
        raw_markdown=bytes(raw_markdown),
        references=MappingProxyType(dict(references)),
    )


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise SkillBundleCodecError(f"skill bundle JSON contains duplicate key: {key!r}")
        value[key] = item
    return value


def _require_exact_keys(
    value: Mapping[str, object],
    expected: frozenset[str],
    label: str,
) -> None:
    unknown = set(value) - expected
    if unknown:
        raise SkillBundleCodecError(f"{label} has unknown keys: {sorted(unknown)}")
    missing = expected - set(value)
    if missing:
        raise SkillBundleCodecError(f"{label} is missing keys: {sorted(missing)}")


__all__ = [
    "DecodedSkillBundle",
    "MAX_ENCODED_SKILL_BUNDLE_BYTES",
    "MAX_SKILL_MARKDOWN_BYTES",
    "SKILL_BUNDLE_KIND",
    "SKILL_BUNDLE_VERSION",
    "SkillBundleCodecError",
    "decode_skill_bundle",
    "encode_skill_bundle",
]
