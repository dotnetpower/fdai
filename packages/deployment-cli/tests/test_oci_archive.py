from __future__ import annotations

import hashlib
import io
import json
import os
import tarfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from fdai_deployment_cli import offline_kit
from fdai_deployment_cli.oci_archive import (
    OCI_CONFIG,
    OCI_INDEX,
    OCI_MANIFEST,
    OciArchiveError,
    validate_oci_archive,
)

COMMIT = "a" * 40
PLATFORM = "linux-x86_64"


def _json(value: object) -> bytes:
    return json.dumps(value, separators=(",", ":")).encode()


def _digest(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def write_archive(
    path: Path,
    entries: Mapping[str, bytes],
    *,
    extras: Sequence[tuple[tarfile.TarInfo, bytes]] = (),
) -> None:
    """Create synthetic USTAR bytes only; never extract or run layer content."""

    with tarfile.open(path, "w", format=tarfile.USTAR_FORMAT) as archive:
        for name, content in entries.items():
            member = tarfile.TarInfo(name)
            member.size = len(content)
            archive.addfile(member, io.BytesIO(content))
        for member, content in extras:
            archive.addfile(member, io.BytesIO(content) if content else None)


@dataclass
class ArchiveFixture:
    path: Path
    entries: dict[str, bytes]
    manifest_digest: str

    def expectations(self) -> dict[str, str]:
        return {
            "expected_archive_sha256": hashlib.sha256(self.path.read_bytes()).hexdigest(),
            "expected_manifest_digest": self.manifest_digest,
            "expected_source_commit": COMMIT,
            "expected_platform_tag": PLATFORM,
        }

    @property
    def manifest_bytes(self) -> bytes:
        return self.entries["blobs/sha256/" + self.manifest_digest[7:]]


def make_archive(
    path: Path,
    *,
    config_updates: Mapping[str, Any] | None = None,
    manifest_updates: Mapping[str, Any] | None = None,
    descriptor_updates: Mapping[str, Any] | None = None,
    index_updates: Mapping[str, Any] | None = None,
) -> ArchiveFixture:
    """Shared synthetic fixture for validator and recording-transport tests."""

    layer_stream = io.BytesIO()
    with tarfile.open(fileobj=layer_stream, mode="w", format=tarfile.USTAR_FORMAT) as layer_tar:
        member = tarfile.TarInfo("hello.txt")
        member.size = 5
        layer_tar.addfile(member, io.BytesIO(b"hello"))
    layer = layer_stream.getvalue()
    config = {
        "os": "linux",
        "architecture": "amd64",
        "config": {"Labels": {"org.opencontainers.image.revision": COMMIT}},
        "rootfs": {"type": "layers", "diff_ids": [_digest(layer)]},
        **(config_updates or {}),
    }
    entries = {"oci-layout": _json({"imageLayoutVersion": "1.0.0"})}

    def descriptor(content: bytes, media_type: str) -> dict[str, Any]:
        digest = _digest(content)
        entries["blobs/sha256/" + digest[7:]] = content
        return {"digest": digest, "size": len(content), "mediaType": media_type}

    config_descriptor = descriptor(_json(config), OCI_CONFIG)
    layer_descriptor = descriptor(layer, "application/vnd.oci.image.layer.v1.tar")
    manifest = _json(
        {
            "schemaVersion": 2,
            "mediaType": OCI_MANIFEST,
            "config": config_descriptor,
            "layers": [layer_descriptor],
            **(manifest_updates or {}),
        }
    )
    selected = {**descriptor(manifest, OCI_MANIFEST), **(descriptor_updates or {})}
    entries["index.json"] = _json(
        {
            "schemaVersion": 2,
            "mediaType": OCI_INDEX,
            "manifests": [selected],
            **(index_updates or {}),
        }
    )
    write_archive(path, entries)
    return ArchiveFixture(path, entries, _digest(manifest))


@pytest.mark.parametrize(
    ("architecture", "platform"),
    [
        ("amd64", PLATFORM),
        ("arm64", "linux-aarch64"),
    ],
)
def test_valid_image_retains_immutable_streaming_snapshot(
    tmp_path: Path,
    architecture: str,
    platform: str,
) -> None:
    fixture = make_archive(tmp_path / "image.tar", config_updates={"architecture": architecture})
    expectations = {**fixture.expectations(), "expected_platform_tag": platform}
    image = validate_oci_archive(fixture.path, **expectations)
    fixture.path.write_bytes(b"replaced after verification")
    for descriptor in (image.manifest, image.config, *image.layers):
        chunks = list(image.iter_bytes(descriptor, chunk_size=17))
        assert all(len(chunk) <= 17 for chunk in chunks)
        assert b"".join(chunks) == fixture.entries[descriptor.path]
        assert _digest(b"".join(chunks)) == descriptor.digest
    assert image.manifest.digest == fixture.manifest_digest
    assert image.source_commit == COMMIT
    assert image.platform_tag == platform
    assert "hello.txt" not in repr(image)
    assert not (tmp_path / "hello.txt").exists()
    with pytest.raises(OciArchiveError, match="descriptor"):
        list(image.iter_bytes(image.manifest, chunk_size=0))


@pytest.mark.parametrize(
    ("key", "value", "stage"),
    [
        ("expected_archive_sha256", "b" * 64, "archive"),
        ("expected_manifest_digest", "sha256:" + "b" * 64, "manifest"),
        ("expected_source_commit", "b" * 40, "revision"),
        ("expected_platform_tag", "linux-aarch64", "platform"),
        ("expected_platform_tag", "windows-amd64", "platform"),
    ],
)
def test_explicit_assertions_never_select_another_image(
    tmp_path: Path,
    key: str,
    value: str,
    stage: str,
) -> None:
    fixture = make_archive(tmp_path / "image.tar")
    with pytest.raises(OciArchiveError) as failure:
        validate_oci_archive(fixture.path, **{**fixture.expectations(), key: value})
    assert failure.value.stage == stage


@pytest.mark.parametrize(
    "config_updates",
    [
        {"architecture": "riscv64"},
        {"os": "windows"},
        {"variant": "v7"},
        {"config": {}},
        {"config": {"Labels": {"org.opencontainers.image.revision": "b" * 40}}},
        {"rootfs": {"type": "layers", "diff_ids": []}},
    ],
)
def test_config_revision_platform_and_rootfs_are_checked(
    tmp_path: Path,
    config_updates: dict[str, Any],
) -> None:
    fixture = make_archive(tmp_path / "image.tar", config_updates=config_updates)
    with pytest.raises(OciArchiveError):
        validate_oci_archive(fixture.path, **fixture.expectations())


def test_manifest_annotation_can_supply_revision_but_cannot_override_conflict(
    tmp_path: Path,
) -> None:
    annotation = {"annotations": {"org.opencontainers.image.revision": COMMIT}}
    fixture = make_archive(
        tmp_path / "image.tar", config_updates={"config": {}}, manifest_updates=annotation
    )
    assert validate_oci_archive(fixture.path, **fixture.expectations()).source_commit == COMMIT
    fixture = make_archive(
        tmp_path / "image.tar",
        manifest_updates={
            "annotations": {"org.opencontainers.image.revision": "b" * 40},
        },
    )
    with pytest.raises(OciArchiveError, match="revision"):
        validate_oci_archive(fixture.path, **fixture.expectations())


@pytest.mark.parametrize(
    "updates",
    [
        {"mediaType": OCI_INDEX},
        {"size": True},
        {"size": 1},
        {"urls": ["https://example.com/foreign"]},
        {"platform": {"os": "linux", "architecture": "arm64"}},
    ],
)
def test_invalid_or_nested_descriptor_is_refused(tmp_path: Path, updates: dict[str, Any]) -> None:
    fixture = make_archive(tmp_path / "image.tar", descriptor_updates=updates)
    with pytest.raises(OciArchiveError):
        validate_oci_archive(fixture.path, **fixture.expectations())


@pytest.mark.parametrize("count", [0, 2])
def test_no_empty_or_multiplatform_index(tmp_path: Path, count: int) -> None:
    fixture = make_archive(tmp_path / "image.tar")
    index = json.loads(fixture.entries["index.json"])
    index["manifests"] *= count
    fixture.entries["index.json"] = _json(index)
    write_archive(fixture.path, fixture.entries)
    with pytest.raises(OciArchiveError, match="index: unsupported"):
        validate_oci_archive(fixture.path, **fixture.expectations())


def test_index_digest_is_not_accepted_as_manifest_digest(tmp_path: Path) -> None:
    fixture = make_archive(tmp_path / "image.tar")
    with pytest.raises(OciArchiveError, match="manifest: digest-mismatch"):
        validate_oci_archive(
            fixture.path,
            **{
                **fixture.expectations(),
                "expected_manifest_digest": _digest(fixture.entries["index.json"]),
            },
        )


@pytest.mark.parametrize("role", ["manifest", "config", "layer"])
def test_every_blob_is_hash_checked(tmp_path: Path, role: str) -> None:
    fixture = make_archive(tmp_path / "image.tar")
    image = validate_oci_archive(fixture.path, **fixture.expectations())
    descriptor = {"manifest": image.manifest, "config": image.config, "layer": image.layers[0]}[
        role
    ]
    fixture.entries[descriptor.path] = b"x" * descriptor.size
    write_archive(fixture.path, fixture.entries)
    with pytest.raises(OciArchiveError, match="blob: digest-mismatch"):
        validate_oci_archive(fixture.path, **fixture.expectations())


@pytest.mark.parametrize(
    ("name", "kind"),
    [
        ("../escaped", tarfile.REGTYPE),
        ("/absolute", tarfile.REGTYPE),
        ("blobs/sha256/../escaped", tarfile.REGTYPE),
        ("./index.json", tarfile.REGTYPE),
        ("extra", tarfile.REGTYPE),
        ("oci-layout", tarfile.REGTYPE),
        ("blobs", tarfile.SYMTYPE),
        ("blobs", tarfile.LNKTYPE),
        ("blobs", tarfile.FIFOTYPE),
        ("blobs", tarfile.CHRTYPE),
        ("blobs", tarfile.BLKTYPE),
        ("blobs", tarfile.GNUTYPE_SPARSE),
        ("pax", tarfile.XHDTYPE),
        ("unexpected", tarfile.DIRTYPE),
    ],
)
def test_rejects_unsafe_physical_tar_members(tmp_path: Path, name: str, kind: bytes) -> None:
    fixture = make_archive(tmp_path / "image.tar")
    member = tarfile.TarInfo(name)
    member.type = kind
    if kind in {tarfile.SYMTYPE, tarfile.LNKTYPE}:
        member.linkname = "../foreign"
    write_archive(fixture.path, fixture.entries, extras=[(member, b"")])
    with pytest.raises(OciArchiveError):
        validate_oci_archive(fixture.path, **fixture.expectations())
    assert not (tmp_path / "escaped").exists()


@pytest.mark.parametrize("corruption", ["json", "duplicate-json", "truncated", "tail", "header"])
def test_rejects_malformed_metadata_and_tar(tmp_path: Path, corruption: str) -> None:
    fixture = make_archive(tmp_path / "image.tar")
    if corruption in {"json", "duplicate-json"}:
        fixture.entries["index.json"] = (
            b"{" if corruption == "json" else b'{"schemaVersion":2,"schemaVersion":2}'
        )
        write_archive(fixture.path, fixture.entries)
    else:
        raw = fixture.path.read_bytes()
        fixture.path.write_bytes(
            {
                "truncated": raw[:900],
                "tail": raw + b"x" * 512,
                "header": b"x" * 512 + raw[512:],
            }[corruption]
        )
    with pytest.raises(OciArchiveError):
        validate_oci_archive(fixture.path, **fixture.expectations())


def test_member_oversize_is_rejected_before_reading_content(tmp_path: Path) -> None:
    fixture = make_archive(tmp_path / "image.tar")
    oversized = tarfile.TarInfo("blobs/sha256/" + "b" * 64)
    oversized.size = offline_kit._MAX_FILE_BYTES + 1
    with tarfile.open(fixture.path, "r:") as source:
        terminator = max(
            member.offset_data + ((member.size + 511) // 512) * 512
            for member in source.getmembers()
        )
    archive = fixture.path.read_bytes()
    fixture.path.write_bytes(
        archive[:terminator] + oversized.tobuf(format=tarfile.USTAR_FORMAT) + bytes(1024)
    )
    with pytest.raises(OciArchiveError, match="limit"):
        validate_oci_archive(fixture.path, **fixture.expectations())


@pytest.mark.parametrize(
    ("limit", "maximum"),
    [
        ("_MAX_FILE_BYTES", 32),
        ("_MAX_FILES", 2),
        ("_MAX_TOTAL_BYTES", 32),
        ("_MAX_MANIFEST_BYTES", 2),
    ],
)
def test_inherits_offline_kit_bounds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    limit: str,
    maximum: int,
) -> None:
    fixture = make_archive(tmp_path / "image.tar")
    monkeypatch.setattr(offline_kit, limit, maximum)
    with pytest.raises(OciArchiveError):
        validate_oci_archive(fixture.path, **fixture.expectations())


def test_extra_hash_valid_blob_is_rejected(tmp_path: Path) -> None:
    fixture = make_archive(tmp_path / "image.tar")
    fixture.entries["blobs/sha256/" + _digest(b"unreferenced")[7:]] = b"unreferenced"
    write_archive(fixture.path, fixture.entries)
    with pytest.raises(OciArchiveError, match="extra-content"):
        validate_oci_archive(fixture.path, **fixture.expectations())


@pytest.mark.parametrize("kind", ["symlink", "fifo"])
def test_archive_source_rejects_links_and_nonregular_files(tmp_path: Path, kind: str) -> None:
    fixture = make_archive(tmp_path / "image.tar")
    source = tmp_path / "unsafe"
    if kind == "symlink":
        source.symlink_to(fixture.path)
    else:
        os.mkfifo(source)
    with pytest.raises(OciArchiveError):
        validate_oci_archive(source, **fixture.expectations())
