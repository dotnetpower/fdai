"""Validate one OCI image without extracting layers or granting provenance trust.

Only uncompressed, regular USTAR-compatible OCI layout archives are supported.
The bounded archive is retained as immutable private process memory; streaming
never reopens its original path. No snapshot, layer, or credential is written.
"""

from __future__ import annotations

import hashlib
import json
import re
import tarfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

from fdai_deployment_cli import offline_kit

OCI_MANIFEST = "application/vnd.oci.image.manifest.v1+json"
OCI_CONFIG = "application/vnd.oci.image.config.v1+json"
OCI_INDEX = "application/vnd.oci.image.index.v1+json"
_LAYERS = {
    "application/vnd.oci.image.layer.v1.tar",
    "application/vnd.oci.image.layer.v1.tar+gzip",
    "application/vnd.oci.image.layer.v1.tar+zstd",
}
_PLATFORMS = {"linux-x86_64": "amd64", "linux-aarch64": "arm64"}
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_BLOB = re.compile(r"blobs/sha256/[0-9a-f]{64}")
_REVISION = "org.opencontainers.image.revision"
_CHUNK = 1024 * 1024


class OciArchiveError(ValueError):
    """Sanitized structural-validation failure; stage and status are stable codes."""

    def __init__(self, stage: str, status: str = "invalid") -> None:
        self.stage = stage
        self.status = status
        super().__init__(f"OCI archive {stage}: {status}")


@dataclass(frozen=True, slots=True)
class OciDescriptor:
    """A hash-checked blob's media type, size, archive path, and byte offset."""

    digest: str
    size: int
    media_type: str
    path: str
    offset: int


@dataclass(frozen=True, slots=True)
class VerifiedOciImage:
    """Content validation, not attestation or authority; retains a bounded snapshot."""

    manifest: OciDescriptor
    config: OciDescriptor
    layers: tuple[OciDescriptor, ...]
    source_commit: str
    platform_tag: str
    archive_sha256: str
    _snapshot: bytes = field(repr=False, compare=False)

    def iter_bytes(self, descriptor: OciDescriptor, *, chunk_size: int = _CHUNK) -> Iterator[bytes]:
        """Stream only a verified descriptor, in at most one-MiB immutable chunks."""

        _require(descriptor in (self.manifest, self.config, *self.layers), "descriptor")
        _require(type(chunk_size) is int and 0 < chunk_size <= _CHUNK, "descriptor")
        end = descriptor.offset + descriptor.size
        for start in range(descriptor.offset, end, chunk_size):
            yield self._snapshot[start : min(end, start + chunk_size)]


def validate_oci_archive(
    path: Path,
    *,
    expected_archive_sha256: str,
    expected_manifest_digest: str,
    expected_source_commit: str,
    expected_platform_tag: str,
) -> VerifiedOciImage:
    """Bind an immutable image snapshot to the caller's four explicit assertions.

    Archive, member, count, and total limits inherit offline-kit ceilings. The
    archive itself is at most the offline-kit per-file limit (512 MiB today).
    Every blob is SHA-256 checked; compressed layer contents and rootfs diff_ids
    are not interpreted. Nested indexes, multiple images, foreign layers, links,
    extensions, duplicate paths/JSON keys, and extra blobs fail closed.
    Source labels are content assertions, not independently trusted provenance.
    Raises OciArchiveError without including paths or untrusted payloads.
    """

    try:
        _require(bool(re.fullmatch(r"[0-9a-f]{64}", expected_archive_sha256)), "archive")
        _require(bool(_DIGEST.fullmatch(expected_manifest_digest)), "manifest")
        _require(bool(re.fullmatch(r"[0-9a-fA-F]{40}", expected_source_commit)), "revision")
        _require(expected_platform_tag in _PLATFORMS, "platform", "unsupported")
        snapshot = offline_kit._read_regular(path, offline_kit._MAX_FILE_BYTES)
        _require(len(snapshot) <= offline_kit._MAX_FILE_BYTES, "archive", "limit")
        _require(
            hashlib.sha256(snapshot).hexdigest() == expected_archive_sha256,
            "archive",
            "digest-mismatch",
        )
        entries = _scan(snapshot)
        layout = _json(snapshot, entries["oci-layout"])
        _require(layout == {"imageLayoutVersion": "1.0.0"}, "layout", "unsupported")
        index = _json(snapshot, entries["index.json"])
        _schema(index, OCI_INDEX, "index")
        manifests = index.get("manifests")
        _require(isinstance(manifests, list) and len(manifests) == 1, "index", "unsupported")
        selected = _object(cast(list[object], manifests)[0])
        manifest = _descriptor(selected, entries, {OCI_MANIFEST}, "manifest")
        _require(manifest.digest == expected_manifest_digest, "manifest", "digest-mismatch")
        image = _json(snapshot, (manifest.offset, manifest.size))
        _schema(image, OCI_MANIFEST, "manifest")
        config = _descriptor(image.get("config"), entries, {OCI_CONFIG}, "config")
        layer_values = image.get("layers")
        _require(isinstance(layer_values, list), "layers")
        layers = tuple(
            _descriptor(value, entries, _LAYERS, "layer")
            for value in cast(list[object], layer_values)
        )
        configuration = _json(snapshot, (config.offset, config.size))
        architecture = _PLATFORMS[expected_platform_tag]
        _platform(configuration, architecture)
        if "platform" in selected:
            _platform(_object(selected["platform"]), architecture)
        rootfs = _object(configuration.get("rootfs"))
        diff_ids = rootfs.get("diff_ids")
        _require(rootfs.get("type") == "layers" and isinstance(diff_ids, list), "config")
        _require(len(cast(list[object], diff_ids)) == len(layers), "config")
        for digest in cast(list[object], diff_ids):
            _require(isinstance(digest, str) and bool(_DIGEST.fullmatch(digest)), "config")
        labels = _object(configuration.get("config", {})).get("Labels", {})
        _revision(
            (
                labels,
                selected.get("annotations", {}),
                image.get("annotations", {}),
                index.get("annotations", {}),
            ),
            expected_source_commit,
        )
        expected_paths = {"oci-layout", "index.json", manifest.path, config.path}
        expected_paths.update(layer.path for layer in layers)
        _require(set(entries) == expected_paths, "archive", "extra-content")
        return VerifiedOciImage(
            manifest,
            config,
            layers,
            expected_source_commit,
            expected_platform_tag,
            expected_archive_sha256,
            snapshot,
        )
    except OciArchiveError:
        raise
    except (OSError, ValueError, TypeError, KeyError, RecursionError, tarfile.TarError):
        raise OciArchiveError("archive", "invalid-or-unavailable") from None


def _require(condition: bool, stage: str, status: str = "invalid") -> None:
    if not condition:
        raise OciArchiveError(stage, status)


def _scan(snapshot: bytes) -> dict[str, tuple[int, int]]:
    """Parse physical headers, not TarFile's extension-skipping logical members."""

    _require(len(snapshot) % 512 == 0, "archive")
    entries: dict[str, tuple[int, int]] = {}
    seen: set[str] = set()
    position = total = 0
    while position + 512 <= len(snapshot):
        header = snapshot[position : position + 512]
        if header == bytes(512):
            _require(len(snapshot) - position >= 1024, "archive")
            _require(not any(memoryview(snapshot)[position:]), "archive", "trailing-content")
            _require({"oci-layout", "index.json"} <= entries.keys(), "layout")
            return entries
        member = tarfile.TarInfo.frombuf(header, encoding="ascii", errors="strict")
        _require(
            member.type in {tarfile.REGTYPE, tarfile.AREGTYPE, tarfile.DIRTYPE},
            "archive",
            "unsupported-member",
        )
        _require(not member.linkname and member.sparse is None, "archive", "unsupported-member")
        name = member.name
        _require(name not in seen, "archive", "duplicate-path")
        seen.add(name)
        _require(len(seen) <= offline_kit._MAX_FILES, "archive", "limit")
        _require(0 <= member.size <= offline_kit._MAX_FILE_BYTES, "archive", "limit")
        if member.isdir():
            _require(name in {"blobs", "blobs/sha256"} and member.size == 0, "archive")
        else:
            _require(
                name in {"oci-layout", "index.json"} or bool(_BLOB.fullmatch(name)),
                "archive",
                "invalid-path",
            )
            entries[name] = (position + 512, member.size)
        total += member.size
        _require(total <= offline_kit._MAX_TOTAL_BYTES, "archive", "limit")
        start = position + 512
        end = start + member.size
        position = start + ((member.size + 511) // 512) * 512
        _require(position <= len(snapshot), "archive", "truncated")
        _require(not any(memoryview(snapshot)[end:position]), "archive", "invalid-padding")
        if _BLOB.fullmatch(name):
            digest = hashlib.sha256(memoryview(snapshot)[start:end]).hexdigest()
            _require(digest == name.rsplit("/", 1)[1], "blob", "digest-mismatch")
    raise OciArchiveError("archive", "missing-terminator")


def _object(value: object) -> dict[str, object]:
    _require(isinstance(value, dict), "metadata")
    return cast(dict[str, object], value)


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        _require(key not in result, "metadata", "duplicate-key")
        result[key] = value
    return result


def _invalid_constant(value: str) -> object:
    raise OciArchiveError("metadata")


def _json(snapshot: bytes, entry: tuple[int, int]) -> dict[str, object]:
    start, size = entry
    _require(size <= offline_kit._MAX_MANIFEST_BYTES, "metadata", "limit")
    return _object(
        json.loads(
            snapshot[start : start + size],
            object_pairs_hook=_unique,
            parse_constant=_invalid_constant,
        )
    )


def _schema(value: dict[str, object], media_type: str, stage: str) -> None:
    _require(type(value.get("schemaVersion")) is int and value["schemaVersion"] == 2, stage)
    _require(value.get("mediaType", media_type) == media_type, stage, "unsupported")
    _require(not ({"artifactType", "subject"} & value.keys()), stage, "unsupported")


def _descriptor(
    value: object,
    entries: dict[str, tuple[int, int]],
    media_types: set[str],
    stage: str,
) -> OciDescriptor:
    descriptor = _object(value)
    digest, size, media_type = (
        descriptor.get("digest"),
        descriptor.get("size"),
        descriptor.get("mediaType"),
    )
    _require(isinstance(digest, str) and bool(_DIGEST.fullmatch(digest)), stage)
    _require(type(size) is int and 0 <= size <= offline_kit._MAX_FILE_BYTES, stage, "limit")
    _require(isinstance(media_type, str) and media_type in media_types, stage, "unsupported")
    _require(not ({"urls", "data", "artifactType"} & descriptor.keys()), stage, "unsupported")
    path = "blobs/sha256/" + cast(str, digest)[7:]
    _require(path in entries and entries[path][1] == size, stage, "size-or-path-mismatch")
    return OciDescriptor(
        cast(str, digest), cast(int, size), cast(str, media_type), path, entries[path][0]
    )


def _platform(value: dict[str, object], architecture: str) -> None:
    _require(
        value.get("os") == "linux" and value.get("architecture") == architecture,
        "platform",
        "mismatch",
    )
    variants = {"", "v8"} if architecture == "arm64" else {""}
    _require(value.get("variant", "") in variants, "platform", "unsupported")
    _require(
        not value.get("os.features") and not value.get("os.version"), "platform", "unsupported"
    )


def _revision(sources: tuple[object, ...], expected: str) -> None:
    revisions: list[str] = []
    for source in sources:
        mapping = _object(source)
        _require(all(isinstance(value, str) for value in mapping.values()), "revision")
        if _REVISION in mapping:
            revisions.append(cast(str, mapping[_REVISION]))
    _require(
        bool(revisions) and all(value == expected for value in revisions), "revision", "mismatch"
    )
