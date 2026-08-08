"""Strict canonical manifest for governed multi-skill composition bundles."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

_ID_PATTERN = re.compile(r"^[a-z][a-z0-9.-]{2,127}$")
_VERSION_PATTERN = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
_CONSTRAINT_PATTERN = re.compile(r"^==(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
_DIGEST_PATTERN = re.compile(r"^[a-f0-9]{64}$")
_MAX_MANIFEST_BYTES = 64 * 1024
_MAX_MEMBERS = 16
_MAX_INSTRUCTION_CHARS = 8 * 1024
_MANIFEST_KEYS = frozenset(
    {
        "allowed_agents",
        "description",
        "digest",
        "instruction",
        "members",
        "name",
        "required_tools",
        "source",
        "version",
    }
)
_MEMBER_KEYS = frozenset({"name", "version"})


class SkillBundleManifestError(ValueError):
    """A governed skill bundle manifest is malformed or non-canonical."""


@dataclass(frozen=True, slots=True)
class SkillBundleMember:
    name: str
    version: str

    def __post_init__(self) -> None:
        if _ID_PATTERN.fullmatch(self.name) is None:
            raise SkillBundleManifestError("bundle member name MUST be lowercase ASCII")
        if _CONSTRAINT_PATTERN.fullmatch(self.version) is None:
            raise SkillBundleManifestError(
                "bundle member version MUST use an exact ==MAJOR.MINOR.PATCH constraint"
            )

    @property
    def exact_version(self) -> str:
        return self.version.removeprefix("==")


@dataclass(frozen=True, slots=True)
class SkillBundleManifest:
    name: str
    version: str
    description: str
    source: str
    members: tuple[SkillBundleMember, ...]
    allowed_agents: tuple[str, ...]
    required_tools: tuple[str, ...]
    instruction: str | None
    digest: str

    def __post_init__(self) -> None:
        if _ID_PATTERN.fullmatch(self.name) is None:
            raise SkillBundleManifestError("skill bundle name MUST be lowercase ASCII")
        if _VERSION_PATTERN.fullmatch(self.version) is None:
            raise SkillBundleManifestError("skill bundle version MUST use MAJOR.MINOR.PATCH")
        if not self.description.strip() or not self.source.strip():
            raise SkillBundleManifestError("skill bundle description and source MUST be non-empty")
        if not self.members or len(self.members) > _MAX_MEMBERS:
            raise SkillBundleManifestError("skill bundle MUST contain between 1 and 16 members")
        member_names = tuple(member.name for member in self.members)
        if len(set(member_names)) != len(member_names):
            raise SkillBundleManifestError("skill bundle members MUST NOT contain duplicates")
        _require_unique_strings("allowed_agents", self.allowed_agents)
        _require_unique_strings("required_tools", self.required_tools)
        if self.instruction is not None:
            if not self.instruction.strip():
                raise SkillBundleManifestError("skill bundle instruction MUST be non-empty")
            if len(self.instruction) > _MAX_INSTRUCTION_CHARS:
                raise SkillBundleManifestError("skill bundle instruction exceeds 8 KiB")
        if _DIGEST_PATTERN.fullmatch(self.digest) is None:
            raise SkillBundleManifestError("skill bundle digest MUST be lowercase SHA-256")


@dataclass(frozen=True, slots=True)
class RuntimeSkillBundle:
    manifest: SkillBundleManifest
    raw_manifest: bytes
    enabled: bool = False


class SkillBundleTrustVerifier(Protocol):
    """Verify detached publisher trust for one governed bundle manifest."""

    def verify(self, bundle: RuntimeSkillBundle, raw_manifest: bytes) -> bool: ...


def parse_skill_bundle_manifest(raw_manifest: bytes) -> RuntimeSkillBundle:
    """Parse one canonical JSON manifest and verify its self-digest."""
    if not raw_manifest or len(raw_manifest) > _MAX_MANIFEST_BYTES:
        raise SkillBundleManifestError("skill bundle manifest MUST be non-empty and <= 64 KiB")
    try:
        decoded = json.loads(raw_manifest.decode("utf-8"), object_pairs_hook=_unique_object)
    except UnicodeDecodeError as exc:
        raise SkillBundleManifestError("skill bundle manifest MUST be UTF-8 JSON") from exc
    except json.JSONDecodeError as exc:
        raise SkillBundleManifestError("skill bundle manifest MUST be valid JSON") from exc
    if not isinstance(decoded, dict):
        raise SkillBundleManifestError("skill bundle manifest root MUST be an object")
    _require_exact_keys(decoded, _MANIFEST_KEYS, "skill bundle manifest")
    members_raw = decoded["members"]
    if not isinstance(members_raw, list):
        raise SkillBundleManifestError("skill bundle members MUST be an array")
    members: list[SkillBundleMember] = []
    for value in members_raw:
        if not isinstance(value, dict):
            raise SkillBundleManifestError("skill bundle member MUST be an object")
        _require_exact_keys(value, _MEMBER_KEYS, "skill bundle member")
        members.append(
            SkillBundleMember(
                name=_required_string(value, "name"),
                version=_required_string(value, "version"),
            )
        )
    manifest = SkillBundleManifest(
        name=_required_string(decoded, "name"),
        version=_required_string(decoded, "version"),
        description=_required_string(decoded, "description"),
        source=_required_string(decoded, "source"),
        members=tuple(members),
        allowed_agents=_string_tuple(decoded, "allowed_agents"),
        required_tools=_string_tuple(decoded, "required_tools"),
        instruction=_optional_string(decoded, "instruction"),
        digest=_required_string(decoded, "digest"),
    )
    if manifest.digest != skill_bundle_manifest_digest(decoded):
        raise SkillBundleManifestError("skill bundle manifest digest mismatch")
    canonical = json.dumps(decoded, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if canonical != raw_manifest:
        raise SkillBundleManifestError("skill bundle manifest MUST use canonical JSON")
    return RuntimeSkillBundle(manifest=manifest, raw_manifest=bytes(raw_manifest))


def skill_bundle_manifest_digest(document: Mapping[str, Any]) -> str:
    """Hash canonical manifest fields while excluding the self-digest slot."""
    payload = {str(key): value for key, value in document.items() if key != "digest"}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def encode_skill_bundle_manifest(document: Mapping[str, Any]) -> bytes:
    """Return canonical bytes after replacing the document's digest."""
    snapshot = {str(key): value for key, value in document.items() if key != "digest"}
    snapshot["digest"] = skill_bundle_manifest_digest(snapshot)
    return json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for key, value in pairs:
        if key in values:
            raise SkillBundleManifestError(f"skill bundle JSON contains duplicate key: {key!r}")
        values[key] = value
    return values


def _require_exact_keys(values: Mapping[str, Any], expected: frozenset[str], label: str) -> None:
    keys = set(values)
    if keys != expected:
        raise SkillBundleManifestError(
            f"{label} keys mismatch: missing={sorted(expected - keys)}, "
            f"unknown={sorted(keys - expected)}"
        )


def _required_string(values: Mapping[str, Any], key: str) -> str:
    value = values[key]
    if not isinstance(value, str) or not value.strip():
        raise SkillBundleManifestError(f"skill bundle {key} MUST be a non-empty string")
    return value


def _optional_string(values: Mapping[str, Any], key: str) -> str | None:
    value = values[key]
    if value is None:
        return None
    if not isinstance(value, str):
        raise SkillBundleManifestError(f"skill bundle {key} MUST be a string or null")
    return value


def _string_tuple(values: Mapping[str, Any], key: str) -> tuple[str, ...]:
    value = values[key]
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise SkillBundleManifestError(f"skill bundle {key} MUST be a string array")
    return tuple(value)


def _require_unique_strings(label: str, values: tuple[str, ...]) -> None:
    if any(not value or value != value.strip() or len(value) > 128 for value in values):
        raise SkillBundleManifestError(f"skill bundle {label} values MUST be bounded strings")
    if len(set(values)) != len(values):
        raise SkillBundleManifestError(f"skill bundle {label} MUST NOT contain duplicates")


__all__ = [
    "RuntimeSkillBundle",
    "SkillBundleManifest",
    "SkillBundleManifestError",
    "SkillBundleMember",
    "SkillBundleTrustVerifier",
    "encode_skill_bundle_manifest",
    "parse_skill_bundle_manifest",
    "skill_bundle_manifest_digest",
]
