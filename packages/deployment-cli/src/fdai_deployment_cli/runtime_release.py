"""Validate local runtime inventory and complete image content without execution.

The enclosing fdai.offline-kit.v1 files map signs runtime/release.json and its
artifacts. This module does not establish production trust, contact registries,
or install anything. Catalog loading checks file hashes; validate_runtime_images
also checks OCI content for complete v2 and v3 inventories. Neither establishes SBOM or
provenance semantics, image attestation, or operational success.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Literal, cast

from fdai_deployment_cli import offline_kit
from fdai_deployment_cli.contracts import canonical_bytes, load_json_object
from fdai_deployment_cli.oci_archive import (
    VerifiedOciImage,
    validate_dependency_oci_archive,
    validate_oci_archive,
)

RUNTIME_RELEASE_PATH = "runtime/release.json"
_MAX_CATALOG_BYTES = 1024 * 1024
_LEGACY_SCHEMA = "fdai.runtime-release.v1"
_SCHEMA = "fdai.runtime-release.v2"
_LIFECYCLE_SCHEMA = "fdai.runtime-release.v3"
_COMMIT = re.compile(r"[0-9a-fA-F]{40}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_PATH = re.compile(r"runtime/[A-Za-z0-9._+/-]+")
_TOKEN = re.compile(r"[A-Za-z0-9._:/-]+")
_SEMVER = re.compile(
    r"(0|[1-9][0-9]*)\."
    r"(0|[1-9][0-9]*)\."
    r"(0|[1-9][0-9]*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"\Z",
    re.ASCII,
)
_NUMERIC = re.compile(r"0|[1-9][0-9]*\Z", re.ASCII)
_ALPHANUMERIC_NUMERIC_SUFFIX = re.compile(r"([0-9A-Za-z-]*[A-Za-z-])([0-9]+)\Z", re.ASCII)
_PLATFORMS = {"linux-x86_64", "linux-aarch64"}
RUNTIME_SERVICES = frozenset(
    {
        "core-control-plane",
        "operator-service",
        "document-ingestion-api",
        "document-processing-worker",
        "isolated-executor",
    }
)
RUNTIME_SIDECARS = frozenset({"clamav", "pgvector"})
RUNTIME_INSTALLATION_AGENTS = frozenset({"infrastructure-agent", "lifecycle-agent"})
_ARCHIVE_KEYS = {"archive", "archive_sha256", "sbom", "sbom_sha256"}
_SERVICE_KEYS = _ARCHIVE_KEYS | {"image_digest", "provenance", "provenance_sha256"}
_CATALOG_KEYS = {
    "schema_version",
    "source_commit",
    "platform_tag",
    "deployment_bundle_sha256",
    "services",
    "console",
    "deployment_support",
}
_SCHEMA_KEYS = {"target", "tolerates"}
_SCHEMA_RANGE_KEYS = {"minimum", "maximum"}
_CAPABILITY_RECORD_KEYS = {"kind", "maximum_mode"}
_CAPABILITY_KINDS = {"ActionType", "Workflow"}
_CAPABILITY_MODES = {"shadow", "enforce"}
_DOWNTIME_KEYS = {"entities"}


class RuntimeReleaseError(offline_kit.OfflineKitVerificationError):
    """Runtime release schema, compatibility, or local content is invalid."""


@dataclass(frozen=True, slots=True)
class SchemaRange:
    """Inclusive database schema revision range tolerated by one Release."""

    minimum: int
    maximum: int

    def contains(self, revision: int) -> bool:
        return self.minimum <= revision <= self.maximum


@dataclass(frozen=True, slots=True)
class ReleaseDecision:
    """Typed allow/deny result for pure release planning checks."""

    allowed: bool
    reason_code: str
    details: tuple[str, ...] = ()


RecallScope = Literal["release", "capability"]
RecallAction = Literal["recall", "lift"]


@dataclass(frozen=True, slots=True)
class RecallRecord:
    """Append-only recall fact used by local shadow-only release decisions."""

    scope: RecallScope
    target: str
    sequence: int
    notice_digest: str
    action: RecallAction = "recall"
    lifting_release_id: str | None = None

    def __post_init__(self) -> None:
        if self.scope not in {"release", "capability"}:
            raise ValueError("recall scope MUST be release or capability")
        if self.action not in {"recall", "lift"}:
            raise ValueError("recall action MUST be recall or lift")
        if type(self.sequence) is not int or self.sequence < 0:
            raise ValueError("recall sequence MUST be a non-negative integer")
        if _TOKEN.fullmatch(self.target) is None:
            raise ValueError("recall target is invalid")
        if self.scope == "release" and _release_version_parts(self.target) is None:
            raise ValueError("recall Release id is invalid")
        if _SHA256.fullmatch(self.notice_digest) is None:
            raise ValueError("recall notice digest is invalid")
        if self.action == "lift":
            if (
                self.lifting_release_id is None
                or _TOKEN.fullmatch(self.lifting_release_id) is None
                or _release_version_parts(self.lifting_release_id) is None
            ):
                raise ValueError("recall lift MUST name the lifting Release")
        elif self.lifting_release_id is not None:
            raise ValueError("recall records MUST NOT name a lifting Release")


@dataclass(frozen=True, slots=True)
class RuntimeRelease:
    """Immutable validated metadata; not a trust or execution authorization."""

    source_commit: str
    platform_tag: str
    deployment_bundle_sha256: str
    digest: str
    artifact_paths: tuple[str, ...]
    _catalog: bytes = field(repr=False)
    schema_version: str = _LEGACY_SCHEMA
    schema_target: int | None = None
    schema_range: SchemaRange | None = None
    capability_maximums: dict[str, str] = field(default_factory=dict)
    downtime_entities: tuple[str, ...] = ()
    installation_agent_images: tuple[str, ...] = ()

    def to_mapping(self) -> dict[str, object]:
        """Return a detached canonical catalog mapping, without host paths or bytes."""

        return load_json_object(self._catalog, label="runtime release")


def load_runtime_release(
    root: Path, *, expected_source_commit: str, expected_platform_tag: str
) -> RuntimeRelease:
    """Check runtime/release.json and its exact local artifact set below kit root.

    Reads are bounded by the existing offline-kit per-file and total limits.
    Revision and platform must match before artifact reads. Raises
    RuntimeReleaseError with sanitized context on any invalid or unavailable input.
    No copy, extraction, execution, network access, or production trust is implied.
    Artifact payloads are opaque; matching hashes do not validate their semantics.
    Callers must compare deployment_bundle_sha256 with the separately verified
    deployment bundle archive, and snapshot and reverify bytes before use.
    """

    try:
        _require_directory(root)
        _require_directory(root / "runtime")
        raw = offline_kit._read_regular(root / RUNTIME_RELEASE_PATH, _MAX_CATALOG_BYTES)
        release, declared = _parse_runtime_release(
            raw,
            expected_source_commit=expected_source_commit,
            expected_platform_tag=expected_platform_tag,
        )
        _verify_tree(root, {**declared, RUNTIME_RELEASE_PATH: hashlib.sha256(raw).hexdigest()})
        return release
    except RuntimeReleaseError:
        raise
    except (OSError, ValueError, TypeError, RecursionError) as exc:
        raise RuntimeReleaseError("runtime release is invalid or unavailable") from exc


def parse_runtime_release_manifest(raw: bytes) -> RuntimeRelease:
    """Validate one runtime release manifest from bytes without reading its artifacts.

    The manifest checks match load_runtime_release, but no source commit, platform, or local
    artifact tree is compared. A caller that holds no offline kit, such as a Lifecycle Hub
    catalog, uses this to read a Release it received. Raises RuntimeReleaseError on any
    invalid input. No signature, publication, or execution authority is implied.
    """

    try:
        release, _declared = _parse_runtime_release(
            raw, expected_source_commit=None, expected_platform_tag=None
        )
        return release
    except RuntimeReleaseError:
        raise
    except (ValueError, TypeError, RecursionError) as exc:
        raise RuntimeReleaseError("runtime release is invalid") from exc


def compare_release_ids(left: str, right: str) -> int:
    """Return -1, 0, or 1 by Semantic Versioning precedence of two canonical Release IDs."""

    left_parts = _release_version_parts(left)
    right_parts = _release_version_parts(right)
    if left_parts is None or right_parts is None:
        raise RuntimeReleaseError("release id is not canonical semantic version")
    return _compare_release_versions(left_parts, right_parts)


def _parse_runtime_release(
    raw: bytes,
    *,
    expected_source_commit: str | None,
    expected_platform_tag: str | None,
) -> tuple[RuntimeRelease, dict[str, str]]:
    payload = load_json_object(raw, label="runtime release", max_bytes=_MAX_CATALOG_BYTES)
    # The shared decoder currently accepts duplicate keys; reject them at every depth.
    json.loads(raw, object_pairs_hook=_unique_object)
    schema = payload.get("schema_version")
    if not isinstance(schema, str) or schema not in (
        _LEGACY_SCHEMA,
        _SCHEMA,
        _LIFECYCLE_SCHEMA,
    ):
        raise RuntimeReleaseError("runtime release schema version is unsupported")
    schema_keys = set(_CATALOG_KEYS)
    if schema in {_SCHEMA, _LIFECYCLE_SCHEMA}:
        schema_keys.add("sidecars")
    if schema == _LIFECYCLE_SCHEMA:
        schema_keys.update({"installation_agents", "schema", "capabilities", "downtime"})
    catalog = _object(payload, schema_keys)
    commit, platform = catalog["source_commit"], catalog["platform_tag"]
    if not isinstance(commit, str) or _COMMIT.fullmatch(commit) is None:
        raise RuntimeReleaseError("runtime release source commit is invalid")
    if not isinstance(platform, str) or platform not in _PLATFORMS:
        raise RuntimeReleaseError("runtime release platform is invalid")
    if expected_source_commit is not None and commit != expected_source_commit:
        raise RuntimeReleaseError("runtime release source commit does not match")
    if expected_platform_tag is not None and platform != expected_platform_tag:
        raise RuntimeReleaseError("runtime release platform does not match")
    bundle_digest = catalog["deployment_bundle_sha256"]
    if not isinstance(bundle_digest, str) or _SHA256.fullmatch(bundle_digest) is None:
        raise RuntimeReleaseError("runtime release deployment bundle digest is invalid")
    services = _object(catalog["services"], set(RUNTIME_SERVICES))
    declared: dict[str, str] = {}
    for service in sorted(RUNTIME_SERVICES):
        _declare_record(services[service], service=True, declared=declared)
    if schema == _SCHEMA:
        sidecars = _object(catalog["sidecars"], set(RUNTIME_SIDECARS))
        for sidecar in sorted(RUNTIME_SIDECARS):
            _declare_record(sidecars[sidecar], service=True, declared=declared)
    installation_agent_images: tuple[str, ...] = ()
    schema_target: int | None = None
    schema_range: SchemaRange | None = None
    capability_maximums: dict[str, str] = {}
    downtime_entities: tuple[str, ...] = ()
    if schema == _LIFECYCLE_SCHEMA:
        sidecars = _object(catalog["sidecars"], set(RUNTIME_SIDECARS))
        for sidecar in sorted(RUNTIME_SIDECARS):
            _declare_record(sidecars[sidecar], service=True, declared=declared)
        agents = _object(catalog["installation_agents"], set(RUNTIME_INSTALLATION_AGENTS))
        for agent in sorted(RUNTIME_INSTALLATION_AGENTS):
            _declare_record(agents[agent], service=True, declared=declared)
        installation_agent_images = tuple(sorted(RUNTIME_INSTALLATION_AGENTS))
        schema_target, schema_range = _release_schema(catalog["schema"])
        capability_maximums = _capability_maximums(catalog["capabilities"])
        downtime_entities = _downtime_entities(catalog["downtime"])
    for section in ("console", "deployment_support"):
        _declare_record(catalog[section], service=False, declared=declared)
    canonical = canonical_bytes(catalog)
    release = RuntimeRelease(
        source_commit=commit,
        platform_tag=platform,
        deployment_bundle_sha256=bundle_digest,
        digest=hashlib.sha256(canonical).hexdigest(),
        artifact_paths=tuple(sorted(declared)),
        _catalog=canonical,
        schema_version=schema,
        schema_target=schema_target,
        schema_range=schema_range,
        capability_maximums=capability_maximums,
        downtime_entities=downtime_entities,
        installation_agent_images=installation_agent_images,
    )
    return release, declared


def validate_runtime_images(root: Path, release: RuntimeRelease) -> dict[str, str]:
    """Validate v2 and v3 OCI images against a previously verified catalog snapshot.

    Inspect a private snapshot; callers own signature and release-eligibility checks.
    Images are inspected one at a time within the existing per-file limits; no layer
    extraction, process, registry call, provenance verification, or execution authority
    results from this check.
    """
    if release.schema_version not in {_SCHEMA, _LIFECYCLE_SCHEMA}:
        raise RuntimeReleaseError("complete preparation requires runtime release v2 or v3")
    catalog = release.to_mapping()
    digests: dict[str, str] = {}
    image: VerifiedOciImage[str] | VerifiedOciImage[None]
    sections: list[tuple[str, frozenset[str], bool]] = [
        ("services", RUNTIME_SERVICES, True),
        ("sidecars", RUNTIME_SIDECARS, False),
    ]
    if release.schema_version == _LIFECYCLE_SCHEMA:
        sections.append(("installation_agents", RUNTIME_INSTALLATION_AGENTS, True))
    for section, names, source_bound in sections:
        records = _object(catalog[section], set(names))
        for name in sorted(names):
            record = _string_record(records[name], _SERVICE_KEYS)
            path = root / record["archive"]
            expected = {
                "expected_archive_sha256": record["archive_sha256"],
                "expected_manifest_digest": record["image_digest"],
                "expected_platform_tag": release.platform_tag,
            }
            if source_bound:
                image = validate_oci_archive(
                    path, expected_source_commit=release.source_commit, **expected
                )
            else:
                image = validate_dependency_oci_archive(path, **expected)
            digests[f"{section}/{name}"] = image.manifest.digest
            del image
    return digests


def validate_schema_transition(
    *,
    current_schema_revision: int,
    candidate: RuntimeRelease,
    direction: Literal["upgrade", "rollback"],
) -> ReleaseDecision:
    """Allow only schema-compatible upgrade and roll-back candidates."""

    if type(current_schema_revision) is not int or current_schema_revision < 0:
        return ReleaseDecision(False, "schema_revision_invalid")
    if direction not in {"upgrade", "rollback"}:
        return ReleaseDecision(False, "schema_transition_direction_invalid")
    if candidate.schema_target is None or candidate.schema_range is None:
        return ReleaseDecision(False, "release_manifest_missing_schema_range")
    if not candidate.schema_range.contains(current_schema_revision):
        return ReleaseDecision(
            False,
            "schema_revision_outside_tolerated_range",
            (str(current_schema_revision),),
        )
    if direction == "upgrade" and candidate.schema_target < current_schema_revision:
        return ReleaseDecision(
            False,
            "schema_target_not_forward",
            (str(candidate.schema_target), str(current_schema_revision)),
        )
    return ReleaseDecision(True, "allowed")


def evaluate_recall_candidate(
    *,
    release_id: str,
    capability_ids: tuple[str, ...],
    recall_records: tuple[RecallRecord, ...],
) -> ReleaseDecision:
    """Deny re-promotion of active Release or capability recalls."""

    problem = _recall_record_problem(recall_records, release_id=release_id)
    if problem is not None:
        return problem
    active = _active_recalls(recall_records, candidate_release_id=release_id)
    if ("release", release_id) in active:
        return ReleaseDecision(False, "release_recalled", (release_id,))
    for capability_id in capability_ids:
        if ("capability", capability_id) in active:
            return ReleaseDecision(False, "capability_recalled", (capability_id,))
    return ReleaseDecision(True, "allowed")


def recall_target_ordering(
    *,
    release_id: str,
    capability_ids: tuple[str, ...],
    recall_records: tuple[RecallRecord, ...],
) -> tuple[str, ...]:
    """Return active recall targets in deterministic display order."""

    problem = _recall_record_problem(recall_records, release_id=release_id)
    if problem is not None:
        raise RuntimeReleaseError(problem.reason_code)
    active = _active_recalls(recall_records, candidate_release_id=release_id)
    release_priority = (
        (active[("release", release_id)], f"release:{release_id}")
        if ("release", release_id) in active
        else None
    )
    capability_priorities = [
        (active[("capability", capability_id)], f"capability:{capability_id}")
        for capability_id in capability_ids
        if ("capability", capability_id) in active
    ]
    ordered = []
    if release_priority is not None:
        ordered.append(release_priority[1])
    ordered.extend(
        item
        for _sequence, item in sorted(
            capability_priorities, key=lambda entry: (-entry[0], entry[1])
        )
    )
    return tuple(ordered)


def _recall_record_problem(
    records: tuple[RecallRecord, ...], *, release_id: str
) -> ReleaseDecision | None:
    if _release_version_parts(release_id) is None:
        return ReleaseDecision(False, "release_version_invalid", (release_id,))
    observed: set[tuple[str, str, int]] = set()
    for record in records:
        key = (record.scope, record.target, record.sequence)
        if key in observed:
            return ReleaseDecision(
                False,
                "recall_sequence_duplicate",
                (record.scope, record.target, str(record.sequence)),
            )
        observed.add(key)
        if record.action == "lift" and record.scope == "capability":
            assert record.lifting_release_id is not None
            if _release_version_parts(record.lifting_release_id) is None:
                return ReleaseDecision(
                    False,
                    "release_version_invalid",
                    (release_id, record.lifting_release_id),
                )
    return None


def _active_recalls(
    records: tuple[RecallRecord, ...], *, candidate_release_id: str
) -> dict[tuple[str, str], int]:
    active: dict[tuple[str, str], int] = {}
    for record in sorted(records, key=lambda item: (item.sequence, item.action == "recall")):
        key = (record.scope, record.target)
        if record.action == "recall":
            active[key] = record.sequence
        elif record.scope == "capability" and _release_at_or_after(
            candidate_release_id, record.lifting_release_id
        ):
            active.pop(key, None)
    return active


def _release_at_or_after(candidate: str, baseline: str | None) -> bool:
    candidate_parts = _release_version_parts(candidate)
    baseline_parts = _release_version_parts(baseline)
    return (
        candidate_parts is not None
        and baseline_parts is not None
        and _compare_release_versions(candidate_parts, baseline_parts) >= 0
    )


def _release_version_parts(
    value: str | None,
) -> tuple[int, int, int, tuple[str, ...] | None] | None:
    if value is None:
        return None
    match = _SEMVER.fullmatch(value)
    if match is None:
        return None
    major, minor, patch, prerelease = match.groups()
    prerelease_parts: tuple[str, ...] | None = None
    if prerelease is not None:
        prerelease_parts = tuple(prerelease.split("."))
        if any(part.isdigit() and _NUMERIC.fullmatch(part) is None for part in prerelease_parts):
            return None
    return int(major), int(minor), int(patch), prerelease_parts


def _compare_release_versions(
    left: tuple[int, int, int, tuple[str, ...] | None],
    right: tuple[int, int, int, tuple[str, ...] | None],
) -> int:
    left_core, right_core = left[:3], right[:3]
    if left_core != right_core:
        return 1 if left_core > right_core else -1
    left_prerelease, right_prerelease = left[3], right[3]
    if left_prerelease is None and right_prerelease is None:
        return 0
    if left_prerelease is None:
        return 1
    if right_prerelease is None:
        return -1
    return _compare_prerelease(left_prerelease, right_prerelease)


def _compare_prerelease(left: tuple[str, ...], right: tuple[str, ...]) -> int:
    for left_part, right_part in zip(left, right, strict=False):
        left_numeric, right_numeric = left_part.isdigit(), right_part.isdigit()
        if left_numeric and right_numeric:
            left_number, right_number = int(left_part), int(right_part)
            if left_number != right_number:
                return 1 if left_number > right_number else -1
        elif left_numeric != right_numeric:
            return -1 if left_numeric else 1
        elif (numeric_suffix_order := _compare_numeric_suffix(left_part, right_part)) is not None:
            return numeric_suffix_order
        elif left_part != right_part:
            return 1 if left_part > right_part else -1
    if len(left) == len(right):
        return 0
    return 1 if len(left) > len(right) else -1


def _compare_numeric_suffix(left: str, right: str) -> int | None:
    left_match = _ALPHANUMERIC_NUMERIC_SUFFIX.fullmatch(left)
    right_match = _ALPHANUMERIC_NUMERIC_SUFFIX.fullmatch(right)
    if left_match is None or right_match is None or left_match.group(1) != right_match.group(1):
        return None
    left_number, right_number = int(left_match.group(2)), int(right_match.group(2))
    if left_number == right_number:
        return 0
    return 1 if left_number > right_number else -1


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise RuntimeReleaseError("runtime release contains duplicate JSON keys")
        result[key] = value
    return result


def _release_schema(value: object) -> tuple[int, SchemaRange]:
    metadata = _object(value, _SCHEMA_KEYS)
    target = _schema_revision(metadata["target"])
    tolerated = _object(metadata["tolerates"], _SCHEMA_RANGE_KEYS)
    minimum = _schema_revision(tolerated["minimum"])
    maximum = _schema_revision(tolerated["maximum"])
    if minimum > maximum:
        raise RuntimeReleaseError("runtime release schema range is invalid")
    if not minimum <= target <= maximum:
        raise RuntimeReleaseError("runtime release schema target is outside its tolerated range")
    return target, SchemaRange(minimum=minimum, maximum=maximum)


def _schema_revision(value: object) -> int:
    if type(value) is not int or value < 0:
        raise RuntimeReleaseError("runtime release schema revision is invalid")
    return value


def _capability_maximums(value: object) -> dict[str, str]:
    if not isinstance(value, dict) or not value:
        raise RuntimeReleaseError("runtime release capability maximums are invalid")
    result: dict[str, str] = {}
    for raw_name, raw_record in value.items():
        if not isinstance(raw_name, str) or _TOKEN.fullmatch(raw_name) is None:
            raise RuntimeReleaseError("runtime release capability identifier is invalid")
        record = _object(raw_record, _CAPABILITY_RECORD_KEYS)
        kind, maximum_mode = record["kind"], record["maximum_mode"]
        if kind not in _CAPABILITY_KINDS or maximum_mode not in _CAPABILITY_MODES:
            raise RuntimeReleaseError("runtime release capability maximum is invalid")
        result[raw_name] = maximum_mode
    return dict(sorted(result.items()))


def _downtime_entities(value: object) -> tuple[str, ...]:
    record = _object(value, _DOWNTIME_KEYS)
    entities = record["entities"]
    if not isinstance(entities, list):
        raise RuntimeReleaseError("runtime release downtime entities are invalid")
    result: list[str] = []
    observed: set[str] = set()
    for entity in entities:
        if not isinstance(entity, str) or _TOKEN.fullmatch(entity) is None:
            raise RuntimeReleaseError("runtime release downtime entity is invalid")
        if entity in observed:
            raise RuntimeReleaseError("runtime release downtime entities are duplicated")
        observed.add(entity)
        result.append(entity)
    return tuple(result)


def _object(value: object, keys: set[str]) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != keys:
        raise RuntimeReleaseError("runtime release fields do not match the schema")
    return cast(dict[str, object], value)


def _declare_record(value: object, *, service: bool, declared: dict[str, str]) -> None:
    fields = _string_record(value, _SERVICE_KEYS if service else _ARCHIVE_KEYS)
    if service and re.fullmatch(r"sha256:[0-9a-f]{64}", fields["image_digest"]) is None:
        raise RuntimeReleaseError("runtime release image digest is invalid")
    for key in ("archive", "sbom", "provenance") if service else ("archive", "sbom"):
        path, digest = fields[key], fields[f"{key}_sha256"]
        if _PATH.fullmatch(path) is None or any(
            part in {"", ".", ".."} for part in path.split("/")
        ):
            raise RuntimeReleaseError("runtime release artifact path is invalid")
        if path == RUNTIME_RELEASE_PATH or path in declared:
            raise RuntimeReleaseError(
                "runtime release artifact path is duplicated or self-referencing"
            )
        if _SHA256.fullmatch(digest) is None:
            raise RuntimeReleaseError("runtime release artifact digest is invalid")
        declared[path] = digest


def _string_record(value: object, keys: set[str]) -> dict[str, str]:
    record = _object(value, keys)
    if not all(isinstance(item, str) for item in record.values()):
        raise RuntimeReleaseError("runtime release artifact fields MUST be strings")
    return cast(dict[str, str], record)


def _require_directory(path: Path) -> None:
    """Reject directory symlinks, including supplied-root ancestors, without resolving them."""

    if ".." in path.parts:
        raise RuntimeReleaseError("runtime release root MUST NOT traverse parent directories")
    for component in (path, *path.parents):
        if not stat.S_ISDIR(component.lstat().st_mode):
            raise RuntimeReleaseError("runtime release directories MUST NOT be symlinks")


def _walk_error(error: OSError) -> None:
    raise RuntimeReleaseError("runtime release directory is unavailable") from error


def _verify_tree(root: Path, declared: dict[str, str]) -> None:
    """Enforce the runtime-only exact set using the shared no-follow digest reader."""

    directories = {
        parent.as_posix()
        for path in declared
        for parent in PurePosixPath(path).parents
        if parent.as_posix() != "."
    }
    observed: set[str] = set()
    total = 0
    for directory, children, names in os.walk(
        root / "runtime", followlinks=False, onerror=_walk_error
    ):
        base = Path(directory)
        for name in children:
            child = base / name
            if child.relative_to(root).as_posix() not in directories or not stat.S_ISDIR(
                child.lstat().st_mode
            ):
                raise RuntimeReleaseError("runtime release contains extra or symlinked directories")
        for name in names:
            candidate = base / name
            relative = candidate.relative_to(root).as_posix()
            if relative not in declared or relative in observed:
                raise RuntimeReleaseError("runtime release exact file set does not match")
            details = candidate.lstat()
            if not stat.S_ISREG(details.st_mode):
                raise RuntimeReleaseError("runtime release artifacts MUST be regular files")
            if details.st_size > offline_kit._MAX_FILE_BYTES:
                raise RuntimeReleaseError("runtime release artifact exceeds its size limit")
            total += details.st_size
            if total > offline_kit._MAX_TOTAL_BYTES:
                raise RuntimeReleaseError("runtime release exceeds its total size limit")
            if offline_kit._sha256_nofollow(candidate, expected=details) != declared[relative]:
                raise RuntimeReleaseError("runtime release artifact digest does not match")
            observed.add(relative)
    if observed != set(declared):
        raise RuntimeReleaseError("runtime release exact file set does not match")
