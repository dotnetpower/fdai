"""Revalidate retained kit inputs; cache metadata never grants trust or deployment authority."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import stat
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from fdai_deployment_cli.contracts import load_json_object
from fdai_deployment_cli.offline_kit import (
    MANIFEST_NAME,
    SIGNATURE_NAME,
    MaterializedOfflineArtifacts,
    OfflineKitVerification,
    _scan_tree,
)
from fdai_deployment_cli.private_output import read_private_bytes, write_private_output

_MAX_CACHE_ENTRIES = 40_000


def path_present(path: Path) -> bool:
    """Detect even dangling links so exclusive destinations are never silently reused."""

    return os.path.lexists(path)


@contextmanager
def acquisition_lock(work_dir: Path) -> Iterator[None]:
    """Serialize local acquisition only, never replacing target or execution locks."""

    descriptor = os.open(work_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        details = os.fstat(descriptor)
        if stat.S_IMODE(details.st_mode) != 0o700 or details.st_uid != os.geteuid():
            raise ValueError("deployment kit work directory must be current-UID mode 0700")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError(
                "deployment kit acquisition is already active in this work directory"
            ) from exc
        yield
    finally:
        os.close(descriptor)


def bind_online_source(work_dir: Path, *, url: str, default_url: str) -> bool:
    """Pin the requested URL digest, not its remote provenance or authenticity.

    Unbound retained inputs are candidates only for the default versioned source.
    The returned legacy flag requires version checking after full signature verification.
    """

    marker = work_dir / "online-source.json"
    source_digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
    if path_present(marker):
        value = load_json_object(
            read_private_bytes(marker, max_bytes=4096),
            label="online kit source record",
            max_bytes=4096,
        )
        kind = value.get("kind")
        if (
            set(value) != {"schema_version", "source_sha256", "kind"}
            or value.get("schema_version") != "fdai.online-kit-source.v1"
            or not isinstance(kind, str)
            or kind not in ("request", "legacy-retained")
            or value.get("source_sha256") != source_digest
        ):
            raise ValueError(
                "retained deployment kit source differs or is invalid; preserve the work directory for review"
            )
        return kind == "legacy-retained"
    legacy = any(
        path_present(work_dir / name)
        for name in ("downloaded-kit.tar.gz", "kit", "verified", "bundle")
    )
    if legacy and url != default_url:
        raise ValueError(
            "retained deployment kit source is unbound; an online URL override cannot reuse it"
        )
    write_private_output(
        marker,
        json.dumps(
            {
                "schema_version": "fdai.online-kit-source.v1",
                "source_sha256": source_digest,
                "kind": "legacy-retained" if legacy else "request",
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
    )
    return legacy


def validate_retained_archive(path: Path, *, max_bytes: int) -> None:
    """Reject unsafe cached archive metadata before reading; signatures still decide trust."""

    details = path.lstat()
    if (
        not stat.S_ISREG(details.st_mode)
        or stat.S_IMODE(details.st_mode) != 0o600
        or details.st_uid != os.geteuid()
        or details.st_nlink != 1
        or not 0 < details.st_size <= max_bytes
    ):
        raise ValueError(
            "retained deployment kit archive is unsafe or empty; preserve it for review"
        )


def validate_cached_tree(root: Path, *, executable: Path | None = None) -> None:
    """Require private, owned, non-linked cached files; content is checked separately."""

    directories = [root]
    entries = 0
    while directories:
        directory = directories.pop()
        details = directory.lstat()
        mode = stat.S_IMODE(details.st_mode)
        # mkdir(parents=True, mode=0700) uses the umask for intermediate parents.
        # The enclosing 0700 root still prevents external traversal; no descendant
        # may be writable by another principal or owned by one.
        if (
            not stat.S_ISDIR(details.st_mode)
            or (directory == root and mode != 0o700)
            or mode & 0o022
            or details.st_uid != os.geteuid()
        ):
            raise ValueError("retained deployment kit directory is unsafe; preserve it for review")
        for path in directory.iterdir():
            entries += 1
            if entries > _MAX_CACHE_ENTRIES:
                raise ValueError("retained deployment kit exceeds its entry limit")
            details = path.lstat()
            if stat.S_ISDIR(details.st_mode):
                directories.append(path)
                continue
            expected_mode = 0o700 if path == executable else 0o600
            if (
                not stat.S_ISREG(details.st_mode)
                or stat.S_IMODE(details.st_mode) != expected_mode
                or details.st_uid != os.geteuid()
                or details.st_nlink != 1
            ):
                raise ValueError("retained deployment kit file is unsafe; preserve it for review")


def verify_retained_artifacts(
    destination: Path, verification: OfflineKitVerification
) -> MaterializedOfflineArtifacts:
    """Recheck the entire existing snapshot against newly authenticated source digests."""

    terraform = destination / verification.terraform_binary
    validate_cached_tree(destination, executable=terraform)
    files, sizes, _total = _scan_tree(destination)
    if (
        files != dict(verification.file_digests)
        or sizes != dict(verification.file_sizes)
        or any(path_present(destination / name) for name in (MANIFEST_NAME, SIGNATURE_NAME))
    ):
        raise ValueError(
            "retained deployment kit snapshot differs or is incomplete; preserve it for review"
        )
    return MaterializedOfflineArtifacts(
        terraform_binary=terraform,
        provider_mirror=destination / verification.provider_mirror_prefix,
        deployment_bundle=destination / verification.deployment_bundle,
        python_wheels=destination / "python",
    )


def execution_bundle_destination(work_dir: Path) -> Path:
    """Create a fresh bundle destination without touching previous execution evidence."""

    original = work_dir / "bundle"
    if not path_present(original):
        return original
    return Path(tempfile.mkdtemp(prefix="bundle-recheck-", dir=work_dir)) / "bundle"
