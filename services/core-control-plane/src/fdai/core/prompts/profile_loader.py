"""Load exact prompt profiles and validate their artifact references."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from fdai.core.prompts.profiles import (
    PromptArtifactRef,
    PromptProfile,
    PromptProfileMode,
)
from fdai.core.prompts.types import PromptArtifact, PromptLayer

_PROFILE_CATALOG = "catalog.yaml"
_DYNAMIC_SCHEMA_VERSION = "1.1.0"
_PROFILE_SCHEMA = "prompt-profile.schema.json"
_PROFILES_DIR = "profiles"
_SCHEMA_DIR = "schema"
_ROOT_LAYERS = frozenset(
    {
        PromptLayer.BASE,
        PromptLayer.CRITIC,
        PromptLayer.JUDGE,
        PromptLayer.ROLE_HEADER,
        PromptLayer.RUBRIC,
    }
)


@dataclass(frozen=True, slots=True)
class PromptProfileIssue:
    """One bounded prompt-profile validation failure."""

    path: str
    message: str


def load_prompt_profiles(
    prompts_dir: Path,
    artifacts: tuple[PromptArtifact, ...],
) -> tuple[tuple[PromptProfile, ...], tuple[PromptProfileIssue, ...]]:
    """Load the optional exact-selection catalog and return all issues."""

    profiles_dir = prompts_dir / _PROFILES_DIR
    if not profiles_dir.exists():
        return (), ()
    catalog_path = profiles_dir / _PROFILE_CATALOG
    schema_path = profiles_dir / _SCHEMA_DIR / _PROFILE_SCHEMA
    missing = [
        PromptProfileIssue(str(path), "required prompt profile file is missing")
        for path in (catalog_path, schema_path)
        if not path.is_file()
    ]
    if missing:
        return (), tuple(missing)
    try:
        schema = json.loads(schema_path.read_text())
        raw = yaml.safe_load(catalog_path.read_text())
    except (json.JSONDecodeError, yaml.YAMLError) as exc:
        return (), (PromptProfileIssue(str(catalog_path), f"invalid profile catalog: {exc}"),)
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        return (), (
            PromptProfileIssue(str(schema_path), f"invalid prompt profile schema: {exc.message}"),
        )
    validator = Draft202012Validator(schema)
    schema_errors = sorted(validator.iter_errors(raw), key=lambda error: list(error.absolute_path))
    if schema_errors:
        return (), tuple(
            PromptProfileIssue(
                f"{catalog_path}#{'/'.join(str(part) for part in error.absolute_path) or '<root>'}",
                error.message,
            )
            for error in schema_errors
        )
    if not isinstance(raw, Mapping):
        return (), (PromptProfileIssue(str(catalog_path), "profile catalog MUST be a mapping"),)
    profiles: list[PromptProfile] = []
    coercion_issues: list[PromptProfileIssue] = []
    for index, item in enumerate(raw["profiles"]):
        try:
            profile = _coerce_profile(item)
            if profile.dynamic and raw["schema_version"] != _DYNAMIC_SCHEMA_VERSION:
                raise ValueError(
                    f"conditional prompt packs require schema_version {_DYNAMIC_SCHEMA_VERSION}"
                )
            profiles.append(profile)
        except (TypeError, ValueError) as exc:
            coercion_issues.append(
                PromptProfileIssue(
                    f"{catalog_path}#profiles/{index}",
                    str(exc),
                )
            )
    if coercion_issues:
        return (), tuple(coercion_issues)
    resolved = tuple(profiles)
    issues = _validate_profiles(catalog_path, resolved, artifacts)
    return resolved, issues


def _coerce_profile(raw: Mapping[str, object]) -> PromptProfile:
    provenance = raw["provenance"]
    if not isinstance(provenance, Mapping):
        raise TypeError("prompt profile provenance MUST be a mapping")
    packs = raw["packs"]
    promotion_evidence = raw["promotion_evidence"]
    if not isinstance(packs, list):
        raise TypeError("prompt profile packs MUST be a list")
    if not isinstance(promotion_evidence, list):
        raise TypeError("prompt profile promotion_evidence MUST be a list")
    return PromptProfile(
        id=str(raw["id"]),
        version=int(raw["version"]),  # type: ignore[call-overload]
        capability_id=str(raw["capability_id"]),
        mode=PromptProfileMode(str(raw["mode"])),
        root=_coerce_ref(raw["root"]),
        packs=tuple(_coerce_ref(item) for item in packs),
        system_token_budget=int(raw["system_token_budget"]),  # type: ignore[call-overload]
        request_token_budget=int(raw["request_token_budget"]),  # type: ignore[call-overload]
        reserved_output_tokens=int(raw["reserved_output_tokens"]),  # type: ignore[call-overload]
        promotion_evidence=tuple(str(item) for item in promotion_evidence),
        provenance_source=str(provenance["source"]),
    )


def _coerce_ref(raw: object) -> PromptArtifactRef:
    if not isinstance(raw, Mapping):
        raise TypeError("prompt artifact reference MUST be a mapping")
    return PromptArtifactRef(
        id=str(raw["id"]),
        version=int(raw["version"]),
        layer=PromptLayer(str(raw["layer"])),
        when_any=_assembly_keys(raw.get("when_any")),
        covers=_assembly_keys(raw.get("covers")),
    )


def _assembly_keys(raw: object) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list) or any(not isinstance(item, str) for item in raw):
        raise TypeError("prompt assembly keys MUST be a list of strings")
    return tuple(raw)


def _validate_profiles(
    catalog_path: Path,
    profiles: tuple[PromptProfile, ...],
    artifacts: tuple[PromptArtifact, ...],
) -> tuple[PromptProfileIssue, ...]:
    issues: list[PromptProfileIssue] = []
    id_counts = Counter(profile.id for profile in profiles)
    active_counts = Counter(
        profile.capability_id for profile in profiles if profile.mode is PromptProfileMode.ACTIVE
    )
    capability_counts = Counter(profile.capability_id for profile in profiles)
    artifact_index = {(item.id, item.version, item.layer): item for item in artifacts}
    for capability_id in sorted(capability_counts):
        if active_counts[capability_id] != 1:
            issues.append(
                PromptProfileIssue(
                    f"{catalog_path}#capabilities/{capability_id}",
                    "capability MUST declare exactly one active profile",
                )
            )
    for profile in profiles:
        location = f"{catalog_path}#profiles/{profile.id}"
        if id_counts[profile.id] > 1:
            issues.append(PromptProfileIssue(location, "profile id MUST be unique"))
        if profile.mode is PromptProfileMode.ACTIVE and not profile.promotion_evidence:
            issues.append(
                PromptProfileIssue(location, "active profile requires promotion evidence")
            )
        if profile.root.layer not in _ROOT_LAYERS:
            issues.append(
                PromptProfileIssue(location, "profile root MUST use a protected role layer")
            )
        _validate_ref(
            issues,
            artifact_index,
            profile,
            profile.root,
            location=f"{location}/root",
        )
        for index, ref in enumerate(profile.packs):
            if ref.layer is not PromptLayer.PACK:
                issues.append(
                    PromptProfileIssue(
                        f"{location}/packs/{index}",
                        "profile packs MUST use the pack layer",
                    )
                )
            _validate_ref(
                issues,
                artifact_index,
                profile,
                ref,
                location=f"{location}/packs/{index}",
            )
    return tuple(issues)


def _validate_ref(
    issues: list[PromptProfileIssue],
    artifact_index: Mapping[tuple[str, int, PromptLayer], PromptArtifact],
    profile: PromptProfile,
    ref: PromptArtifactRef,
    *,
    location: str,
) -> None:
    artifact = artifact_index.get((ref.id, ref.version, ref.layer))
    if artifact is None:
        issues.append(PromptProfileIssue(location, "profile references an unknown artifact"))
        return
    if not artifact.matches(profile.capability_id):
        issues.append(
            PromptProfileIssue(location, "profile artifact does not match its capability")
        )


__all__ = ["PromptProfileIssue", "load_prompt_profiles"]
