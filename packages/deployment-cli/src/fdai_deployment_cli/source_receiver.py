"""Build a dependency-free receiver from the exact selected source, never a release kit."""

from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import Path

from fdai_deployment_cli.private_output import read_private_bytes, write_private_bytes
from fdai_deployment_cli.source_input import _read_tracked
from fdai_deployment_cli.source_snapshot import verify_source_snapshot
from fdai_deployment_cli.source_transport import _records

_MODULES = (
    "__init__",
    "__about__",
    "contracts",
    "private_output",
    "source_input",
    "source_snapshot",
    "source_transport",
)
_ENTRY = b"from fdai_deployment_cli.source_transport import main\nraise SystemExit(main())\n"
_MAX_BOOTSTRAP = 4 * 1024 * 1024


def prepare_source_receiver(snapshot: Path, work_dir: Path, *, snapshot_digest: str) -> str:
    """Retain a deterministic private zipapp and return its independently transferable digest.

    Only verified snapshot modules and a fixed launcher are packaged. This does not install
    dependencies, execute source, authorize effects, or grant signed-release provenance.
    A retained bootstrap must match exactly; ambiguous partial outputs are never overwritten.
    """
    verify_source_snapshot(snapshot, expected_digest=snapshot_digest)
    records = {
        record["path"]: record
        for record in _records(
            read_private_bytes(snapshot / "source-input.json", max_bytes=16 * 1024 * 1024),
            snapshot_digest,
        )
    }
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w", compression=zipfile.ZIP_STORED) as archive:
        _add(archive, "__main__.py", _ENTRY)
        for module in _MODULES:
            relative = f"packages/deployment-cli/src/fdai_deployment_cli/{module}.py"
            content = _read_tracked(snapshot / "tree", relative, mode="100644")
            record = records.get(relative)
            if (
                record is None
                or record["mode"] != "100644"
                or hashlib.sha256(content).hexdigest() != record["sha256"]
            ):
                raise ValueError("source receiver module differs from the selected snapshot")
            if len(content) > _MAX_BOOTSTRAP or payload.tell() + len(content) > _MAX_BOOTSTRAP:
                raise ValueError("source receiver bootstrap exceeds its bound")
            _add(archive, f"fdai_deployment_cli/{module}.py", content)
    verify_source_snapshot(snapshot, expected_digest=snapshot_digest)
    content = payload.getvalue()
    if len(content) > _MAX_BOOTSTRAP:
        raise ValueError("source receiver bootstrap exceeds its bound")
    destination = work_dir / "source-receiver.pyz"
    if destination.exists() or destination.is_symlink():
        if read_private_bytes(destination, max_bytes=_MAX_BOOTSTRAP) != content:
            raise ValueError("source receiver bootstrap differs; preserve the run")
    else:
        write_private_bytes(destination, content)
    return hashlib.sha256(content).hexdigest()


def _add(archive: zipfile.ZipFile, name: str, content: bytes) -> None:
    member = zipfile.ZipInfo(name)
    member.create_system = 3
    member.external_attr = 0o100600 << 16
    archive.writestr(member, content)
