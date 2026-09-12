"""Acquire and authenticate one complete online or artifact-offline deployment kit."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import platform
import re
import shutil
import stat
import tarfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import IO, BinaryIO, Final

from fdai_deployment_cli.__about__ import __version__
from fdai_deployment_cli.bundle import extract_bundle_archive, verify_bundle
from fdai_deployment_cli.offline_kit import (
    OfflineKitVerification,
    materialize_verified_artifacts,
    verify_offline_kit,
)
from fdai_deployment_cli.private_output import read_private_bytes, write_private_output
from fdai_deployment_cli.runtime_release import (
    RuntimeRelease,
    load_runtime_release,
    validate_runtime_images,
)
from fdai_deployment_cli.trust_roots import (
    deployment_bundle_root_pem,
    deployment_release_root_pem,
)

_MAX_ARCHIVE_BYTES: Final = 8 * 1024 * 1024 * 1024
_MAX_ARCHIVE_FILES: Final = 20_000
_MAX_MEMBER_BYTES: Final = 512 * 1024 * 1024
_BUFFER_BYTES: Final = 1024 * 1024
_COMMIT = re.compile(r"[0-9a-f]{40}")
_DIGEST = re.compile(r"[0-9a-f]{64}")
_SAFE_ONLINE_HOSTS = frozenset(
    {"github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com"}
)


@dataclass(frozen=True, slots=True)
class DeploymentKit:
    """Verified complete deployment bytes and their immutable source binding."""

    root: Path
    materialized_root: Path
    bundle_root: Path
    verification: OfflineKitVerification
    runtime: RuntimeRelease
    bundle_manifest_digest: str

    @property
    def source_commit(self) -> str:
        """Return the source revision authenticated by the complete runtime release."""

        return self.runtime.source_commit


def default_online_kit_url() -> str:
    """Return the versioned upstream kit URL for the current package and platform."""

    platform_tag = runtime_platform_tag()
    return (
        "https://github.com/dotnetpower/fdai/releases/download/"
        f"deployment-v{__version__}/fdai-deployment-kit-{__version__}-{platform_tag}.tar.gz"
    )


def acquire_deployment_kit(
    *,
    work_dir: Path,
    online: bool,
    offline_kit: Path | None,
    online_url: str | None = None,
) -> DeploymentKit:
    """Acquire exactly one source and verify all executable content before use.

    Online mode downloads one archive from the configured HTTPS release location. Artifact-offline
    mode accepts only the supplied local directory or archive and performs no network fallback.
    The release and bundle public roots always come from the installed package.
    """

    if online == (offline_kit is not None):
        raise ValueError("select exactly one of online mode or an offline kit")
    _require_private_directory(work_dir)
    kit_root = work_dir / "kit"
    if online:
        archive = work_dir / "downloaded-kit.tar.gz"
        if archive.exists() or archive.is_symlink():
            _sha256_private_file(archive)
        else:
            if kit_root.exists() or kit_root.is_symlink():
                raise ValueError("online deployment kit acquisition is incomplete")
            _download(online_url or default_online_kit_url(), archive)
        if kit_root.exists() or kit_root.is_symlink():
            _require_private_directory(kit_root)
        else:
            _extract_kit_archive(archive, kit_root)
    else:
        assert offline_kit is not None
        source = offline_kit if offline_kit.is_absolute() else Path.cwd() / offline_kit
        details = source.lstat()
        if stat.S_ISDIR(details.st_mode):
            kit_root = source
        elif stat.S_ISREG(details.st_mode):
            if kit_root.exists() or kit_root.is_symlink():
                _require_private_directory(kit_root)
            else:
                _extract_kit_archive(source, kit_root)
        else:
            raise ValueError("offline kit must be a regular archive or directory")
    verification = verify_offline_kit(
        kit_root,
        release_root_pem=deployment_release_root_pem(),
        cli_version=__version__,
        platform_tag=runtime_platform_tag(),
    )
    files = dict(verification.file_digests)
    if "runtime/release.json" not in files:
        raise ValueError("complete deployment kit requires a runtime v2 release")
    if "support/python/inventory.json" not in files or not any(
        name.startswith("support/python/wheels/") and name.endswith(".whl") for name in files
    ):
        raise ValueError("complete deployment kit requires runtime migration support wheels")
    materialized = work_dir / "verified"
    _reset_private_derived_directory(materialized)
    artifacts = materialize_verified_artifacts(
        kit_root,
        verification,
        materialized,
        include_all=True,
    )
    runtime_source = _runtime_source_commit(materialized)
    runtime = load_runtime_release(
        materialized,
        expected_source_commit=runtime_source,
        expected_platform_tag=runtime_platform_tag(),
    )
    if (
        runtime.schema_version != "fdai.runtime-release.v2"
        or _COMMIT.fullmatch(runtime.source_commit) is None
    ):
        raise ValueError("complete deployment kit runtime source is invalid")
    validate_runtime_images(materialized, runtime)
    _reset_private_derived_directory(work_dir / "bundle")
    bundle_root = extract_bundle_archive(
        artifacts.deployment_bundle,
        work_dir / "bundle",
    )
    bundle = verify_bundle(
        bundle_root,
        public_key_pem=deployment_bundle_root_pem(),
        cli_version=__version__,
    )
    if (
        bundle.bundle_version != verification.bundle_version
        or runtime.deployment_bundle_sha256 != files[verification.deployment_bundle]
    ):
        raise ValueError("deployment kit bundle binding is invalid")
    return DeploymentKit(
        root=kit_root,
        materialized_root=materialized,
        bundle_root=bundle_root,
        verification=verification,
        runtime=runtime,
        bundle_manifest_digest=bundle.manifest_digest,
    )


def runtime_platform_tag() -> str:
    """Return the supported package platform identity."""

    architecture = {
        "x86_64": "x86_64",
        "amd64": "x86_64",
    }.get(platform.machine().casefold())
    if os.name != "posix" or architecture is None:
        raise ValueError("standalone deployment currently supports Linux x86_64")
    return f"linux-{architecture}"


def archive_verified_kit(kit: DeploymentKit, destination: Path) -> str:
    """Write one private archive while rechecking every signed source file."""

    expected = dict(kit.verification.file_digests)
    if destination.exists() or destination.is_symlink():
        digest = _sha256_private_file(destination)
        if _archive_binding(destination) != _expected_archive_binding(kit, digest):
            raise ValueError("existing deployment kit transport archive is invalid")
        return digest
    descriptor = os.open(
        destination,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600,
    )
    try:
        with (
            os.fdopen(descriptor, "wb") as raw,
            gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=0) as zipped,
            tarfile.open(fileobj=zipped, mode="w", format=tarfile.GNU_FORMAT) as archive,
        ):
            for relative, digest in sorted(expected.items()):
                source = kit.root / relative
                _add_verified_member(
                    archive,
                    source,
                    f"kit/{relative}",
                    expected_digest=digest,
                )
            for name in ("offline-kit.json", "offline-kit.json.sig"):
                if name in expected:
                    continue
                source = kit.root / name
                details = source.lstat()
                if not stat.S_ISREG(details.st_mode) or details.st_size > _MAX_MEMBER_BYTES:
                    raise ValueError("deployment kit signature material is invalid")
                info = tarfile.TarInfo(f"kit/{name}")
                info.size = details.st_size
                info.mode = 0o600
                info.mtime = 0
                info.uid = 0
                info.gid = 0
                info.uname = ""
                info.gname = ""
                with source.open("rb") as stream:
                    archive.addfile(info, stream)
            raw.flush()
            os.fsync(raw.fileno())
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
    digest = _sha256_file(destination)
    sidecar = destination.with_suffix(destination.suffix + ".sha256")
    write_private_output(
        sidecar,
        json.dumps(
            _expected_archive_binding(kit, digest),
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
    )
    return digest


def _download(url: str, destination: Path) -> None:
    parsed = urllib.parse.urlparse(url)
    if not _approved_online_url(parsed):
        raise ValueError("online deployment kit URL is not an approved HTTPS release host")
    request = urllib.request.Request(url, headers={"User-Agent": f"fdaictl/{__version__}"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            final = urllib.parse.urlparse(response.geturl())
            if not _approved_online_url(final):
                raise ValueError("online deployment kit redirect is not approved")
            _write_bounded_stream(response, destination)
    except (OSError, urllib.error.URLError) as exc:
        raise ValueError("online deployment kit download failed") from exc


def _approved_online_url(value: urllib.parse.ParseResult) -> bool:
    try:
        port = value.port
    except ValueError:
        return False
    return (
        value.scheme == "https"
        and value.hostname in _SAFE_ONLINE_HOSTS
        and port in {None, 443}
        and value.username is None
        and value.password is None
    )


def _write_bounded_stream(source: BinaryIO, destination: Path) -> None:
    descriptor = os.open(
        destination,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600,
    )
    total = 0
    try:
        with os.fdopen(descriptor, "wb") as stream:
            while chunk := source.read(_BUFFER_BYTES):
                total += len(chunk)
                if total > _MAX_ARCHIVE_BYTES:
                    raise ValueError("deployment kit archive exceeds its byte limit")
                stream.write(chunk)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
    if total == 0:
        destination.unlink(missing_ok=True)
        raise ValueError("deployment kit archive is empty")


def _extract_kit_archive(archive: Path, destination: Path) -> None:
    if destination.exists() or destination.is_symlink():
        raise ValueError("deployment kit destination already exists")
    temporary = destination.parent / f".{destination.name}.extract-{os.getpid()}"
    if temporary.exists() or temporary.is_symlink():
        raise ValueError("deployment kit temporary destination already exists")
    temporary.mkdir(mode=0o700)
    total = 0
    count = 0
    try:
        with tarfile.open(archive, mode="r:gz") as stream:
            for member in stream:
                count += 1
                path = PurePosixPath(member.name)
                if (
                    count > _MAX_ARCHIVE_FILES
                    or path.is_absolute()
                    or not path.parts
                    or path.parts[0] != "kit"
                    or any(part in {"", ".", ".."} for part in path.parts)
                    or member.issym()
                    or member.islnk()
                    or member.isdev()
                    or member.isfifo()
                    or not (member.isdir() or member.isfile())
                ):
                    raise ValueError("deployment kit archive member is invalid")
                if member.size < 0 or member.size > _MAX_MEMBER_BYTES:
                    raise ValueError("deployment kit archive member exceeds its byte limit")
                total += member.size
                if total > _MAX_ARCHIVE_BYTES:
                    raise ValueError("deployment kit archive exceeds its expanded byte limit")
                relative = Path(*path.parts[1:])
                target = temporary / relative
                if member.isdir():
                    target.mkdir(mode=0o700, parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                extracted = stream.extractfile(member)
                if extracted is None:
                    raise ValueError("deployment kit archive file is unreadable")
                _write_bounded_member(extracted, target, member.size)
        if count == 0:
            raise ValueError("deployment kit archive is empty")
        temporary.rename(destination)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def _write_bounded_member(source: IO[bytes], destination: Path, expected_size: int) -> None:
    descriptor = os.open(
        destination,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600,
    )
    total = 0
    with os.fdopen(descriptor, "wb") as stream:
        while chunk := source.read(_BUFFER_BYTES):
            total += len(chunk)
            if total > expected_size:
                raise ValueError("deployment kit archive member changed size")
            stream.write(chunk)
        stream.flush()
        os.fsync(stream.fileno())
    if total != expected_size:
        raise ValueError("deployment kit archive member is truncated")


def _add_verified_member(
    archive: tarfile.TarFile,
    source: Path,
    member_name: str,
    *,
    expected_digest: str,
) -> None:
    descriptor = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    digest = hashlib.sha256()

    class DigestingReader:
        def __init__(self, stream: BinaryIO) -> None:
            self.stream = stream

        def read(self, size: int = -1) -> bytes:
            chunk = self.stream.read(size)
            digest.update(chunk)
            return chunk

    with os.fdopen(descriptor, "rb") as stream:
        details = os.fstat(stream.fileno())
        if not stat.S_ISREG(details.st_mode) or not 0 < details.st_size <= _MAX_MEMBER_BYTES:
            raise ValueError("deployment kit changed before transport")
        info = tarfile.TarInfo(member_name)
        info.size = details.st_size
        info.mode = 0o600
        info.mtime = 0
        info.uid = 0
        info.gid = 0
        info.uname = ""
        info.gname = ""
        archive.addfile(info, DigestingReader(stream))
        after = os.fstat(stream.fileno())
    if (
        digest.hexdigest() != expected_digest
        or after.st_dev != details.st_dev
        or after.st_ino != details.st_ino
        or after.st_size != details.st_size
        or after.st_mtime_ns != details.st_mtime_ns
        or after.st_ctime_ns != details.st_ctime_ns
    ):
        raise ValueError("deployment kit changed before transport")


def _runtime_source_commit(root: Path) -> str:
    try:
        value = json.loads((root / "runtime/release.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("complete deployment kit runtime catalog is unavailable") from exc
    source = value.get("source_commit") if isinstance(value, dict) else None
    if not isinstance(source, str) or _COMMIT.fullmatch(source) is None:
        raise ValueError("complete deployment kit runtime source is invalid")
    return source


def _reset_private_derived_directory(path: Path) -> None:
    """Remove one current-UID private derived snapshot before authenticated recreation."""

    if not path.exists() and not path.is_symlink():
        return
    _require_private_directory(path)
    retired = path.parent / f".{path.name}.retired-{os.getpid()}"
    if retired.exists() or retired.is_symlink():
        raise ValueError("deployment kit retired snapshot already exists")
    path.rename(retired)
    shutil.rmtree(retired)


def _require_private_directory(path: Path) -> None:
    details = path.lstat()
    if (
        not path.is_absolute()
        or not stat.S_ISDIR(details.st_mode)
        or stat.S_IMODE(details.st_mode) != 0o700
        or details.st_uid != os.geteuid()
    ):
        raise PermissionError("deployment work directory must be current-UID mode 0700")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(_BUFFER_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_private_file(path: Path) -> str:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    digest = hashlib.sha256()
    with os.fdopen(descriptor, "rb") as stream:
        details = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(details.st_mode)
            or stat.S_IMODE(details.st_mode) != 0o600
            or details.st_uid != os.geteuid()
            or details.st_nlink != 1
        ):
            raise ValueError("existing deployment kit transport archive is invalid")
        for chunk in iter(lambda: stream.read(_BUFFER_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _archive_binding(path: Path) -> dict[str, str]:
    sidecar = path.with_suffix(path.suffix + ".sha256")
    try:
        value = json.loads(read_private_bytes(sidecar, max_bytes=4096))
    except json.JSONDecodeError as exc:
        raise ValueError("deployment kit transport binding is invalid") from exc
    expected = {
        "schema_version",
        "archive_sha256",
        "kit_manifest_digest",
        "bundle_manifest_digest",
        "runtime_release_digest",
    }
    if (
        not isinstance(value, dict)
        or set(value) != expected
        or value.get("schema_version") != "fdai.standalone-kit-transport.v1"
        or any(
            not isinstance(value.get(key), str) or _DIGEST.fullmatch(str(value[key])) is None
            for key in expected - {"schema_version"}
        )
    ):
        raise ValueError("deployment kit transport binding is invalid")
    return {str(key): str(item) for key, item in value.items()}


def _expected_archive_binding(kit: DeploymentKit, digest: str) -> dict[str, str]:
    return {
        "schema_version": "fdai.standalone-kit-transport.v1",
        "archive_sha256": digest,
        "kit_manifest_digest": kit.verification.manifest_digest,
        "bundle_manifest_digest": kit.bundle_manifest_digest,
        "runtime_release_digest": kit.runtime.digest,
    }
