"""Build one exact private execution bundle for a governed host transport."""

from __future__ import annotations

import gzip
import hashlib
import io
import os
import re
import stat
import tarfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from fdai_deployment_cli.contracts import canonical_bytes, canonical_digest, load_json_object
from fdai_deployment_cli.private_output import read_private_bytes, write_private_bytes

_OPERATION_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,127}")
_ALLOWED_SECTIONS = frozenset({"artifact", "evidence", "toolchain"})
_MAX_FILE_BYTES = 512 * 1024 * 1024
_MAX_TOTAL_BYTES = 2 * 1024 * 1024 * 1024
_MAX_FILES = 20_000
_ARCHIVE = "execution-bundle.tar.gz"
_RECEIPT = "execution-bundle-receipt.json"
_RECEIVER = "run-command-receiver.pyz"
_RECEIVER_MODULES = (
    "__init__",
    "__about__",
    "contracts",
    "private_output",
    "run_command_receiver",
)
_RECEIVER_ENTRY = (
    b"from fdai_deployment_cli.run_command_receiver import main\nraise SystemExit(main())\n"
)
_MAX_RECEIVER_BYTES = 4 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class ExecutionBundleSource:
    """Map one private regular file or directory into an allowlisted bundle section."""

    source: Path
    destination: str


@dataclass(frozen=True, slots=True)
class _File:
    root_descriptor: int
    relative_parts: tuple[str, ...]
    destination: str
    sha256: str
    mode: str
    size: int


def prepare_execution_bundle(
    sources: tuple[ExecutionBundleSource, ...],
    work_dir: Path,
    *,
    operation_id: str,
) -> dict[str, object]:
    """Create or reverify one deterministic bundle without granting execution authority."""

    if not sources or _OPERATION_ID.fullmatch(operation_id) is None:
        raise ValueError("execution bundle operation or source inventory is invalid")
    details = work_dir.lstat()
    if (
        not stat.S_ISDIR(details.st_mode)
        or stat.S_IMODE(details.st_mode) != 0o700
        or details.st_uid != os.geteuid()
    ):
        raise PermissionError("execution bundle work directory must be current-UID mode 0700")
    files, source_descriptors = _inventory(sources)
    try:
        return _prepare_execution_bundle_files(files, work_dir, operation_id=operation_id)
    finally:
        for source_descriptor in source_descriptors:
            os.close(source_descriptor)


def _prepare_execution_bundle_files(
    files: tuple[_File, ...], work_dir: Path, *, operation_id: str
) -> dict[str, object]:
    inventory = {item.destination: {"sha256": item.sha256, "mode": item.mode} for item in files}
    inventory_digest = canonical_digest({"files": inventory})
    archive = work_dir / _ARCHIVE
    receipt_path = work_dir / _RECEIPT
    if (
        archive.exists()
        or archive.is_symlink()
        or receipt_path.exists()
        or receipt_path.is_symlink()
    ):
        if not archive.is_file() or not receipt_path.is_file():
            raise ValueError("execution bundle retained state is incomplete")
        retained = load_json_object(
            read_private_bytes(receipt_path, max_bytes=65_536),
            label="execution bundle receipt",
            max_bytes=65_536,
        )
        digest = _file_digest(archive, maximum=_MAX_FILE_BYTES)
        expected = _receipt(
            operation_id=operation_id,
            bundle_digest=digest,
            bundle_size=archive.stat().st_size,
            file_count=len(files),
            inventory_digest=inventory_digest,
        )
        if retained != expected:
            raise ValueError("execution bundle retained receipt differs")
        return expected

    manifest = {
        "schema_version": "fdai.execution-bundle-manifest.v1",
        "operation_id": operation_id,
        "files": inventory,
    }
    temporary = work_dir / f".{_ARCHIVE}.partial-{os.getpid()}"
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600,
    )
    published = False
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as raw:
            with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
                with tarfile.open(
                    fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT
                ) as stream:
                    _add(stream, "fdai-execution/manifest.json", canonical_bytes(manifest), 0o600)
                    for item in files:
                        _add(
                            stream,
                            f"fdai-execution/{item.destination}",
                            _read_exact(item),
                            int(item.mode, 8),
                        )
            raw.flush()
            os.fsync(raw.fileno())
        os.close(descriptor)
        descriptor = -1
        if temporary.stat().st_size > _MAX_FILE_BYTES:
            raise ValueError("execution bundle archive exceeds its size limit")
        os.rename(temporary, archive)
        published = True
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if not published:
            temporary.unlink(missing_ok=True)
    digest = _file_digest(archive, maximum=_MAX_FILE_BYTES)
    receipt = _receipt(
        operation_id=operation_id,
        bundle_digest=digest,
        bundle_size=archive.stat().st_size,
        file_count=len(files),
        inventory_digest=inventory_digest,
    )
    write_private_bytes(receipt_path, canonical_bytes(receipt))
    return receipt


def prepare_run_command_receiver(work_dir: Path) -> str:
    """Build or reverify the fixed dependency-free WSL receiver zipapp."""

    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w", compression=zipfile.ZIP_STORED) as archive:
        _zip_add(archive, "__main__.py", _RECEIVER_ENTRY)
        module_root = Path(__file__).parent
        for module in _RECEIVER_MODULES:
            content = _module_content(module_root / f"{module}.py")
            if payload.tell() + len(content) > _MAX_RECEIVER_BYTES:
                raise ValueError("run command receiver exceeds its size limit")
            _zip_add(archive, f"fdai_deployment_cli/{module}.py", content)
    content = payload.getvalue()
    if not 0 < len(content) <= _MAX_RECEIVER_BYTES:
        raise ValueError("run command receiver size is invalid")
    destination = work_dir / _RECEIVER
    if destination.exists() or destination.is_symlink():
        if read_private_bytes(destination, max_bytes=_MAX_RECEIVER_BYTES) != content:
            raise ValueError("retained run command receiver differs")
    else:
        write_private_bytes(destination, content)
    return hashlib.sha256(content).hexdigest()


def _inventory(
    sources: tuple[ExecutionBundleSource, ...],
) -> tuple[tuple[_File, ...], tuple[int, ...]]:
    selected: dict[str, tuple[int, tuple[str, ...], os.stat_result]] = {}
    source_descriptors: list[int] = []
    try:
        for selected_source in sources:
            destination = _destination(selected_source.destination)
            source = selected_source.source.absolute()
            if source.resolve(strict=True) != source or source.is_symlink():
                raise ValueError("execution bundle source must be a regular single-link file")
            if source.is_dir():
                root_descriptor = os.open(source, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                source_descriptors.append(root_descriptor)
                _walk_source_directory(
                    selected,
                    root_descriptor=root_descriptor,
                    directory_descriptor=root_descriptor,
                    relative_parts=(),
                    destination=destination,
                )
            else:
                root_descriptor = os.open(
                    source.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
                )
                source_descriptors.append(root_descriptor)
                details = os.stat(source.name, dir_fd=root_descriptor, follow_symlinks=False)
                _select(
                    selected,
                    destination,
                    root_descriptor,
                    (source.name,),
                    details,
                )
        if not 0 < len(selected) <= _MAX_FILES:
            raise ValueError("execution bundle file count is invalid")
        files: list[_File] = []
        total = 0
        for destination, (root_descriptor, relative_parts, details) in sorted(selected.items()):
            _validate_source_details(details)
            total += details.st_size
            if total > _MAX_TOTAL_BYTES:
                raise ValueError("execution bundle source inventory exceeds its size limit")
            mode = "0700" if details.st_mode & stat.S_IXUSR else "0600"
            files.append(
                _File(
                    root_descriptor=root_descriptor,
                    relative_parts=relative_parts,
                    destination=destination,
                    sha256=_descriptor_digest(
                        root_descriptor, relative_parts, maximum=_MAX_FILE_BYTES
                    ),
                    mode=mode,
                    size=details.st_size,
                )
            )
        return tuple(files), tuple(source_descriptors)
    except BaseException:
        for source_descriptor in source_descriptors:
            os.close(source_descriptor)
        raise


def _walk_source_directory(
    selected: dict[str, tuple[int, tuple[str, ...], os.stat_result]],
    *,
    root_descriptor: int,
    directory_descriptor: int,
    relative_parts: tuple[str, ...],
    destination: str,
) -> None:
    for name in sorted(os.listdir(directory_descriptor)):
        details = os.stat(name, dir_fd=directory_descriptor, follow_symlinks=False)
        child_parts = (*relative_parts, name)
        if stat.S_ISDIR(details.st_mode):
            child = os.open(
                name,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=directory_descriptor,
            )
            try:
                _walk_source_directory(
                    selected,
                    root_descriptor=root_descriptor,
                    directory_descriptor=child,
                    relative_parts=child_parts,
                    destination=destination,
                )
            finally:
                os.close(child)
            continue
        relative = PurePosixPath(*child_parts).as_posix()
        _select(
            selected,
            f"{destination}/{relative}",
            root_descriptor,
            child_parts,
            details,
        )


def _select(
    selected: dict[str, tuple[int, tuple[str, ...], os.stat_result]],
    destination: str,
    root_descriptor: int,
    relative_parts: tuple[str, ...],
    details: os.stat_result,
) -> None:
    normalized = _destination(destination)
    if normalized in selected:
        raise ValueError("execution bundle destination is duplicated")
    selected[normalized] = (root_descriptor, relative_parts, details)


def _destination(value: str) -> str:
    path = PurePosixPath(value)
    if (
        value.startswith("/")
        or "\\" in value
        or not path.parts
        or path.parts[0] not in _ALLOWED_SECTIONS
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError("execution bundle destination is invalid")
    return path.as_posix()


def _read_exact(item: _File) -> bytes:
    descriptor = _open_relative(item.root_descriptor, item.relative_parts)
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(before.st_mode)
            or stat.S_IMODE(before.st_mode) not in {0o600, 0o700}
            or before.st_uid != os.geteuid()
            or before.st_nlink != 1
            or before.st_size != item.size
        ):
            raise PermissionError("execution bundle source permissions changed")
        content = stream.read(_MAX_FILE_BYTES + 1)
        after = os.fstat(stream.fileno())
    if (
        len(content) != item.size
        or hashlib.sha256(content).hexdigest() != item.sha256
        or after.st_size != before.st_size
        or after.st_mtime_ns != before.st_mtime_ns
        or after.st_ctime_ns != before.st_ctime_ns
    ):
        raise ValueError("execution bundle source changed during preparation")
    return content


def _validate_source_details(details: os.stat_result) -> None:
    if (
        not stat.S_ISREG(details.st_mode)
        or stat.S_IMODE(details.st_mode) not in {0o600, 0o700}
        or details.st_nlink != 1
        or details.st_uid != os.geteuid()
        or not 0 < details.st_size <= _MAX_FILE_BYTES
    ):
        raise ValueError("execution bundle source must be a private regular single-link file")


def _open_relative(root_descriptor: int, relative_parts: tuple[str, ...]) -> int:
    if not relative_parts:
        raise ValueError("execution bundle source path is empty")
    parent = os.dup(root_descriptor)
    try:
        for part in relative_parts[:-1]:
            child = os.open(
                part,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=parent,
            )
            os.close(parent)
            parent = child
        return os.open(
            relative_parts[-1],
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
            dir_fd=parent,
        )
    finally:
        os.close(parent)


def _descriptor_digest(
    root_descriptor: int, relative_parts: tuple[str, ...], *, maximum: int
) -> str:
    descriptor = _open_relative(root_descriptor, relative_parts)
    digest = hashlib.sha256()
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        _validate_source_details(before)
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
        after = os.fstat(stream.fileno())
    if (
        before.st_size > maximum
        or after.st_size != before.st_size
        or after.st_mtime_ns != before.st_mtime_ns
        or after.st_ctime_ns != before.st_ctime_ns
    ):
        raise ValueError("execution bundle source changed while being read")
    return digest.hexdigest()


def _add(stream: tarfile.TarFile, name: str, content: bytes, mode: int) -> None:
    member = tarfile.TarInfo(name)
    member.size = len(content)
    member.mode = mode
    member.mtime = 0
    member.uid = 0
    member.gid = 0
    member.uname = ""
    member.gname = ""
    stream.addfile(member, io.BytesIO(content))


def _zip_add(archive: zipfile.ZipFile, name: str, content: bytes) -> None:
    member = zipfile.ZipInfo(name)
    member.create_system = 3
    member.date_time = (1980, 1, 1, 0, 0, 0)
    member.external_attr = 0o100600 << 16
    archive.writestr(member, content)


def _module_content(path: Path) -> bytes:
    details = path.lstat()
    if path.is_symlink() or not stat.S_ISREG(details.st_mode) or details.st_nlink != 1:
        raise ValueError("run command receiver module is invalid")
    content = path.read_bytes()
    after = path.lstat()
    if (
        len(content) != details.st_size
        or after.st_ino != details.st_ino
        or after.st_mtime_ns != details.st_mtime_ns
    ):
        raise ValueError("run command receiver module changed")
    return content


def _receipt(
    *,
    operation_id: str,
    bundle_digest: str,
    bundle_size: int,
    file_count: int,
    inventory_digest: str,
) -> dict[str, object]:
    result: dict[str, object] = {
        "schema_version": "fdai.execution-bundle-receipt.v1",
        "state": "prepared",
        "operation_id": operation_id,
        "bundle_digest": bundle_digest,
        "bundle_size": bundle_size,
        "file_count": file_count,
        "inventory_digest": inventory_digest,
        "apply_authorized": False,
        "deployment_ready": False,
        "mutation_performed": False,
    }
    result["receipt_digest"] = canonical_digest(result)
    return result


def _file_digest(path: Path, *, maximum: int) -> str:
    details = path.lstat()
    if (
        path.is_symlink()
        or not stat.S_ISREG(details.st_mode)
        or details.st_nlink != 1
        or not 0 < details.st_size <= maximum
    ):
        raise ValueError("execution bundle file type or size is invalid")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    digest = hashlib.sha256()
    with os.fdopen(descriptor, "rb") as stream:
        opened = os.fstat(stream.fileno())
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
        after = os.fstat(stream.fileno())
    if (
        opened.st_ino != details.st_ino
        or opened.st_size != details.st_size
        or after.st_size != opened.st_size
        or after.st_mtime_ns != opened.st_mtime_ns
    ):
        raise ValueError("execution bundle file changed while being read")
    return digest.hexdigest()
