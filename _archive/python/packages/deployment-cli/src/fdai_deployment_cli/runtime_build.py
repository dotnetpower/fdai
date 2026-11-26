"""Assemble a complete runtime release from prebuilt, locally verified artifacts."""

from __future__ import annotations

import json
import os
import re
import stat
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from typing import cast

from fdai_deployment_cli.contracts import canonical_bytes
from fdai_deployment_cli.oci_archive import (
    validate_dependency_oci_archive,
    validate_oci_archive,
)
from fdai_deployment_cli.offline_kit import (
    _MAX_FILE_BYTES,
    _copy_verified_file,
    _sha256_nofollow,
)
from fdai_deployment_cli.private_output import (
    _open_private_parent,
    read_private_bytes,
    write_private_bytes,
)
from fdai_deployment_cli.runtime_release import (
    RUNTIME_RELEASE_PATH,
    RUNTIME_SERVICES,
    RUNTIME_SIDECARS,
    load_runtime_release,
    validate_runtime_images,
)

_SCHEMA = "fdai.runtime-release-build.v1"
_OUTPUT_SCHEMA = "fdai.runtime-release-build-result.v1"
_MAX_DESCRIPTOR_BYTES = 1024 * 1024
_COMMIT = re.compile(r"[0-9a-f]{40}")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_PLATFORMS = frozenset({"linux-x86_64", "linux-aarch64"})
_IMAGE_FIELDS = frozenset(
    {
        "archive",
        "archive_sha256",
        "sbom",
        "sbom_sha256",
        "provenance",
        "provenance_sha256",
        "image_digest",
    }
)
_ARCHIVE_FIELDS = frozenset({"archive", "archive_sha256", "sbom", "sbom_sha256"})
_ROOT_FIELDS = frozenset(
    {
        "schema_version",
        "source_commit",
        "platform_tag",
        "services",
        "sidecars",
        "console",
        "deployment_support",
    }
)
_OUTPUT_NAMES = {
    "archive": "image.oci.tar",
    "sbom": "sbom.cdx.json",
    "provenance": "provenance.jsonl",
}


def build_runtime_release(
    source_root: Path,
    descriptor_path: Path,
    deployment_bundle: Path,
    output_root: Path,
) -> dict[str, object]:
    """Build one exact runtime v2 tree without network access or artifact execution.

    The private descriptor names only relative files below ``source_root``. Every
    payload is copied through no-follow digest checks into a new private output.
    Service OCI archives must carry the declared FDAI revision; the ClamAV archive
    is revision-neutral. This function does not sign artifacts, attest provenance,
    publish an image, or authorize deployment.
    """

    descriptor = _load_descriptor(
        read_private_bytes(descriptor_path, max_bytes=_MAX_DESCRIPTOR_BYTES)
    )
    source_commit = _text(descriptor, "source_commit")
    platform_tag = _text(descriptor, "platform_tag")
    if _COMMIT.fullmatch(source_commit) is None:
        raise ValueError("runtime build source_commit is invalid")
    if platform_tag not in _PLATFORMS:
        raise ValueError("runtime build platform_tag is unsupported")
    _require_source_root(source_root)
    if not output_root.is_absolute():
        raise ValueError("runtime release output MUST be an absolute path")
    parent = _open_private_parent(output_root)
    os.close(parent)
    if output_root.exists() or output_root.is_symlink():
        raise ValueError("runtime release output already exists")
    bundle_digest = _regular_digest(deployment_bundle, label="deployment bundle")

    with TemporaryDirectory(prefix=".runtime-release-", dir=output_root.parent) as temporary:
        temporary_root = Path(temporary)
        temporary_root.chmod(0o700)
        staging = temporary_root / "release"
        staging.mkdir(mode=0o700)
        services = _build_image_group(
            source_root,
            staging,
            descriptor.get("services"),
            section="services",
            expected_names=RUNTIME_SERVICES,
            source_commit=source_commit,
            platform_tag=platform_tag,
        )
        sidecars = _build_image_group(
            source_root,
            staging,
            descriptor.get("sidecars"),
            section="sidecars",
            expected_names=RUNTIME_SIDECARS,
            source_commit=None,
            platform_tag=platform_tag,
        )
        console = _build_archive_record(
            source_root,
            staging,
            descriptor.get("console"),
            section="console",
            archive_name="console.tar.gz",
        )
        support = _build_archive_record(
            source_root,
            staging,
            descriptor.get("deployment_support"),
            section="deployment-support",
            archive_name="deployment-support.tar.gz",
        )
        catalog = {
            "schema_version": "fdai.runtime-release.v2",
            "source_commit": source_commit,
            "platform_tag": platform_tag,
            "deployment_bundle_sha256": bundle_digest,
            "services": services,
            "sidecars": sidecars,
            "console": console,
            "deployment_support": support,
        }
        write_private_bytes(staging / RUNTIME_RELEASE_PATH, canonical_bytes(catalog))
        release = load_runtime_release(
            staging,
            expected_source_commit=source_commit,
            expected_platform_tag=platform_tag,
        )
        image_digests = validate_runtime_images(staging, release)

        marker = staging / "runtime/.fdai-incomplete"
        write_private_bytes(marker, b"fdai-runtime-release-build-v1\n")
        os.mkdir(output_root, 0o700)
        try:
            os.rename(staging / "runtime", output_root / "runtime")
        except BaseException:
            os.rmdir(output_root)
            raise
        marker = output_root / "runtime/.fdai-incomplete"
        try:
            marker.unlink()
        except OSError as exc:
            raise ValueError(
                "runtime release publication is incomplete; remove the marked output after review"
            ) from exc

    return {
        "schema_version": _OUTPUT_SCHEMA,
        "runtime_release_digest": release.digest,
        "deployment_bundle_sha256": bundle_digest,
        "source_commit": source_commit,
        "platform_tag": platform_tag,
        "artifact_count": len(release.artifact_paths),
        "image_content_digests": image_digests,
        "azure_mutation_performed": False,
        "production_release_eligibility": "unverified",
    }


def _load_descriptor(raw: bytes) -> dict[str, object]:
    try:
        value = json.loads(raw, object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("runtime build descriptor is not valid JSON") from exc
    if not isinstance(value, dict) or set(value) != _ROOT_FIELDS:
        raise ValueError("runtime build descriptor fields do not match the schema")
    result = cast(dict[str, object], value)
    if result["schema_version"] != _SCHEMA:
        raise ValueError("runtime build descriptor schema_version is unsupported")
    return result


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("runtime build descriptor contains duplicate JSON keys")
        result[key] = value
    return result


def _build_image_group(
    source_root: Path,
    staging: Path,
    value: object,
    *,
    section: str,
    expected_names: frozenset[str],
    source_commit: str | None,
    platform_tag: str,
) -> dict[str, object]:
    records = _object(value, set(expected_names), label=section)
    result: dict[str, object] = {}
    for name in sorted(expected_names):
        record = _string_record(records[name], _IMAGE_FIELDS, label=f"{section} record")
        image_digest = record["image_digest"]
        if _DIGEST.fullmatch(image_digest) is None:
            raise ValueError("runtime build image digest is invalid")
        output: dict[str, str] = {"image_digest": image_digest}
        for field in ("archive", "sbom", "provenance"):
            relative = f"runtime/{section}/{name}/{_OUTPUT_NAMES[field]}"
            digest = _copy_source(
                source_root,
                record[field],
                staging / relative,
                output_root=staging,
                expected_digest=record[f"{field}_sha256"],
                label=f"{section} {field}",
            )
            output[field] = relative
            output[f"{field}_sha256"] = digest
        arguments = {
            "expected_archive_sha256": output["archive_sha256"],
            "expected_manifest_digest": image_digest,
            "expected_platform_tag": platform_tag,
        }
        archive = staging / output["archive"]
        if source_commit is None:
            validate_dependency_oci_archive(archive, **arguments)
        else:
            validate_oci_archive(
                archive,
                expected_source_commit=source_commit,
                **arguments,
            )
        result[name] = output
    return result


def _build_archive_record(
    source_root: Path,
    staging: Path,
    value: object,
    *,
    section: str,
    archive_name: str,
) -> dict[str, str]:
    record = _string_record(value, _ARCHIVE_FIELDS, label=f"{section} record")
    output: dict[str, str] = {}
    names = {"archive": archive_name, "sbom": "sbom.cdx.json"}
    for field in ("archive", "sbom"):
        relative = f"runtime/{section}/{names[field]}"
        digest = _copy_source(
            source_root,
            record[field],
            staging / relative,
            output_root=staging,
            expected_digest=record[f"{field}_sha256"],
            label=f"{section} {field}",
        )
        output[field] = relative
        output[f"{field}_sha256"] = digest
    return output


def _copy_source(
    source_root: Path,
    relative: str,
    target: Path,
    *,
    output_root: Path,
    expected_digest: str,
    label: str,
) -> str:
    if _SHA256.fullmatch(expected_digest) is None:
        raise ValueError(f"runtime build {label} digest is invalid")
    try:
        source = _source_path(source_root, relative)
        details = source.lstat()
    except OSError as exc:
        raise ValueError(f"runtime build {label} is unavailable") from exc
    if not stat.S_ISREG(details.st_mode) or not 0 < details.st_size <= _MAX_FILE_BYTES:
        raise ValueError(f"runtime build {label} MUST be a non-empty bounded regular file")
    digest = _sha256_nofollow(source, expected=details)
    if digest != expected_digest:
        raise ValueError(f"runtime build {label} digest does not match")
    _ensure_private_parent(target, root=output_root)
    _copy_verified_file(
        source,
        target,
        expected_digest=digest,
        expected_size=details.st_size,
    )
    return digest


def _ensure_private_parent(path: Path, *, root: Path) -> None:
    current = root
    for part in path.parent.relative_to(root).parts:
        current /= part
        try:
            os.mkdir(current, 0o700)
        except FileExistsError:
            details = current.lstat()
            if not stat.S_ISDIR(details.st_mode):
                raise ValueError(
                    "runtime release output directories MUST NOT be symlinks"
                ) from None
        current.chmod(0o700)


def _source_path(root: Path, value: str) -> Path:
    path = PurePosixPath(value)
    if (
        not value
        or value.startswith("/")
        or "\\" in value
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError("runtime build source path is invalid")
    current = root
    for part in path.parts[:-1]:
        current /= part
        if not stat.S_ISDIR(current.lstat().st_mode):
            raise ValueError("runtime build source directories MUST NOT be symlinks")
    return root / path.as_posix()


def _require_source_root(path: Path) -> None:
    if not path.is_absolute() or not stat.S_ISDIR(path.lstat().st_mode):
        raise ValueError("runtime build source root MUST be an absolute real directory")


def _regular_digest(path: Path, *, label: str) -> str:
    if not path.is_absolute():
        raise ValueError(f"{label} path MUST be absolute")
    try:
        details = path.lstat()
    except OSError as exc:
        raise ValueError(f"{label} is unavailable") from exc
    if not stat.S_ISREG(details.st_mode) or not 0 < details.st_size <= _MAX_FILE_BYTES:
        raise ValueError(f"{label} MUST be a non-empty bounded regular file")
    return _sha256_nofollow(path, expected=details)


def _object(value: object, fields: set[str], *, label: str) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError(f"runtime build {label} fields do not match the schema")
    return cast(dict[str, object], value)


def _string_record(value: object, fields: frozenset[str], *, label: str) -> dict[str, str]:
    record = _object(value, set(fields), label=label)
    if not all(isinstance(item, str) for item in record.values()):
        raise ValueError(f"runtime build {label} values MUST be strings")
    return cast(dict[str, str], record)


def _text(value: dict[str, object], field: str) -> str:
    item = value[field]
    if not isinstance(item, str):
        raise TypeError(f"runtime build {field} MUST be a string")
    return item


__all__ = ["build_runtime_release"]
