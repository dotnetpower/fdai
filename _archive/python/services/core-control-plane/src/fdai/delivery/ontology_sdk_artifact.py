"""Content-addressed publication of scoped proposal-only ontology SDK artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from fdai.core.ontology_platform.sdk_codegen import GeneratedOntologySdk
from fdai.shared.contracts.models import CeilingRole

_SCOPE_ID = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
_PURPOSE = re.compile(r"^[a-z][a-z0-9._-]{0,63}$")
_DECLARATION_KEYS = ("object_types", "action_types", "functions")


@dataclass(frozen=True, slots=True)
class OntologySdkPublicationScope:
    """Server-owned audience scope attached to one immutable SDK artifact."""

    scope_id: str
    purposes: tuple[str, ...]
    max_role: CeilingRole

    def __post_init__(self) -> None:
        if _SCOPE_ID.fullmatch(self.scope_id) is None:
            raise ValueError("SDK scope_id is invalid")
        if not self.purposes or len(self.purposes) > 32:
            raise ValueError("SDK purposes MUST contain 1..32 entries")
        if any(_PURPOSE.fullmatch(item) is None for item in self.purposes):
            raise ValueError("SDK purpose is invalid")
        if len(set(self.purposes)) != len(self.purposes):
            raise ValueError("SDK purposes MUST be unique")


@dataclass(frozen=True, slots=True)
class PublishedOntologySdk:
    """Verified immutable publication location and manifest digest."""

    path: Path
    manifest_digest: str
    created: bool


def publish_ontology_sdk(
    *,
    sdk: GeneratedOntologySdk,
    scope: OntologySdkPublicationScope,
    root: Path,
    previous_manifest: Mapping[str, object] | None = None,
    migration_ref: str | None = None,
) -> PublishedOntologySdk:
    """Publish one immutable artifact or verify an identical existing publication."""

    sdk_manifest = _sdk_manifest(sdk)
    _validate_compatibility(
        previous_manifest=previous_manifest,
        current_sdk_manifest=sdk_manifest,
        migration_ref=migration_ref,
    )
    manifest = _publication_manifest(
        sdk=sdk,
        sdk_manifest=sdk_manifest,
        scope=scope,
        migration_ref=migration_ref,
    )
    manifest_bytes = _canonical_json(manifest)
    manifest_digest = _sha256(manifest_bytes)
    target = root / scope.scope_id / sdk.release_digest.removeprefix("sha256:")
    files = {
        "ontology_sdk.py": sdk.python.encode("utf-8"),
        "ontology_sdk.ts": sdk.typescript.encode("utf-8"),
        "manifest.json": manifest_bytes,
    }
    if target.exists():
        _verify_existing(target, files)
        return PublishedOntologySdk(
            path=target,
            manifest_digest=manifest_digest,
            created=False,
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".ontology-sdk-", dir=target.parent))
    try:
        for name, content in files.items():
            (temporary / name).write_bytes(content)
        os.replace(temporary, target)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return PublishedOntologySdk(path=target, manifest_digest=manifest_digest, created=True)


def _sdk_manifest(sdk: GeneratedOntologySdk) -> dict[str, object]:
    try:
        parsed = json.loads(sdk.manifest_json)
    except json.JSONDecodeError as exc:
        raise ValueError("generated SDK manifest is invalid JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError("generated SDK manifest MUST be an object")
    if parsed.get("release_digest") != sdk.release_digest:
        raise ValueError("generated SDK manifest release digest mismatch")
    if parsed.get("write_surface") != "proposal_only":
        raise ValueError("ontology SDK publication requires proposal_only write surface")
    return parsed


def _publication_manifest(
    *,
    sdk: GeneratedOntologySdk,
    sdk_manifest: Mapping[str, object],
    scope: OntologySdkPublicationScope,
    migration_ref: str | None,
) -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "release_digest": sdk.release_digest,
        "scope": {
            "id": scope.scope_id,
            "purposes": sorted(scope.purposes),
            "max_role": scope.max_role.value,
        },
        "write_surface": "proposal_only",
        "migration_ref": migration_ref,
        "artifacts": {
            "python": _sha256(sdk.python.encode("utf-8")),
            "typescript": _sha256(sdk.typescript.encode("utf-8")),
        },
        "sdk_manifest": dict(sdk_manifest),
    }


def _validate_compatibility(
    *,
    previous_manifest: Mapping[str, object] | None,
    current_sdk_manifest: Mapping[str, object],
    migration_ref: str | None,
) -> None:
    if migration_ref is not None and (not migration_ref.strip() or len(migration_ref) > 256):
        raise ValueError("migration_ref MUST be 1..256 characters when supplied")
    if previous_manifest is None:
        return
    prior_sdk = previous_manifest.get("sdk_manifest")
    if not isinstance(prior_sdk, Mapping):
        raise ValueError("previous SDK publication manifest is malformed")
    removed: list[str] = []
    for key in _DECLARATION_KEYS:
        prior_names = _manifest_names(prior_sdk, key)
        current_names = _manifest_names(current_sdk_manifest, key)
        removed.extend(f"{key}:{name}" for name in sorted(prior_names - current_names))
    prior_interfaces = prior_sdk.get("interfaces")
    current_interfaces = current_sdk_manifest.get("interfaces")
    if not isinstance(prior_interfaces, Mapping) or not isinstance(current_interfaces, Mapping):
        raise ValueError("SDK interface manifests are malformed")
    removed.extend(
        f"interfaces:{name}" for name in sorted(set(prior_interfaces) - set(current_interfaces))
    )
    if removed and migration_ref is None:
        raise ValueError(
            "breaking SDK declaration removal requires migration_ref: " + ", ".join(removed)
        )


def _manifest_names(manifest: Mapping[str, object], key: str) -> set[str]:
    value = manifest.get(key)
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"SDK manifest {key} is malformed")
    return set(value)


def _verify_existing(target: Path, expected: Mapping[str, bytes]) -> None:
    if not target.is_dir():
        raise ValueError("ontology SDK publication target is not a directory")
    for name, content in expected.items():
        path = target / name
        if not path.is_file() or path.read_bytes() != content:
            raise ValueError(f"existing ontology SDK artifact differs: {name}")


def _canonical_json(value: Mapping[str, object]) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


__all__ = [
    "OntologySdkPublicationScope",
    "PublishedOntologySdk",
    "publish_ontology_sdk",
]
