from __future__ import annotations

import hashlib
import io
import json
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from fdai_deployment_cli.control_package import ControlPackage, verify_control_package
from fdai_deployment_cli.standalone_remote_prepare import prepare_remote

VERSION = "0.1.2"
CLI_WHEEL = f"wheels/fdai_deployment_cli-{VERSION}-py3-none-any.whl"


def _files() -> dict[str, bytes]:
    return {
        "INSTALL.txt": b"install\n",
        "requirements.txt": f"fdai-deployment-cli=={VERSION}\n".encode(),
        CLI_WHEEL: b"cli wheel",
        "wheels/rich-14.3.4-py3-none-any.whl": b"rich wheel",
    }


def _sums(files: dict[str, bytes]) -> bytes:
    return "".join(
        f"{hashlib.sha256(data).hexdigest()}  {name}\n" for name, data in sorted(files.items())
    ).encode()


def _write(
    path: Path,
    files: dict[str, bytes],
    *,
    key: Ed25519PrivateKey,
    sums: bytes | None = None,
    extra: tarfile.TarInfo | None = None,
) -> Path:
    listed = _sums(files) if sums is None else sums
    members = {**files, "SHA256SUMS": listed, "SHA256SUMS.sig": key.sign(listed)}
    with tarfile.open(path, mode="w:gz") as archive:
        for name, data in members.items():
            info = tarfile.TarInfo(f"package/{name}")
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
        if extra is not None:
            archive.addfile(extra)
    path.chmod(0o600)
    return path


def _public(key: Ed25519PrivateKey) -> bytes:
    return key.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)


def test_verifies_signed_wheelhouse(tmp_path: Path) -> None:
    key = Ed25519PrivateKey.generate()
    archive = _write(tmp_path / "control.tar.gz", _files(), key=key)

    control = verify_control_package(archive, public_key_pem=_public(key))

    assert control.version == VERSION
    assert control.archive_digest == hashlib.sha256(archive.read_bytes()).hexdigest()
    assert control.sums_digest == hashlib.sha256(_sums(_files())).hexdigest()


def test_rejects_signature_from_another_key(tmp_path: Path) -> None:
    archive = _write(tmp_path / "control.tar.gz", _files(), key=Ed25519PrivateKey.generate())

    with pytest.raises(ValueError, match="signature is invalid"):
        verify_control_package(archive, public_key_pem=_public(Ed25519PrivateKey.generate()))


def test_rejects_unlisted_or_altered_file(tmp_path: Path) -> None:
    key = Ed25519PrivateKey.generate()
    files = _files()
    unlisted = _write(
        tmp_path / "unlisted.tar.gz",
        {**files, "wheels/extra-1.0-py3-none-any.whl": b"extra"},
        key=key,
        sums=_sums(files),
    )
    altered = _write(
        tmp_path / "altered.tar.gz",
        {**files, CLI_WHEEL: b"changed"},
        key=key,
        sums=_sums(files),
    )

    with pytest.raises(ValueError, match="file set differs"):
        verify_control_package(unlisted, public_key_pem=_public(key))
    with pytest.raises(ValueError, match="digest differs"):
        verify_control_package(altered, public_key_pem=_public(key))


def test_rejects_links_and_escaping_paths(tmp_path: Path) -> None:
    key = Ed25519PrivateKey.generate()
    link = tarfile.TarInfo("package/wheels/link.whl")
    link.type = tarfile.SYMTYPE
    link.linkname = "/etc/passwd"
    escaping = tarfile.TarInfo("package/../outside")

    with pytest.raises(ValueError, match="bounded regular file"):
        verify_control_package(
            _write(tmp_path / "link.tar.gz", _files(), key=key, extra=link),
            public_key_pem=_public(key),
        )
    with pytest.raises(ValueError, match="path is unsafe"):
        verify_control_package(
            _write(tmp_path / "escape.tar.gz", _files(), key=key, extra=escaping),
            public_key_pem=_public(key),
        )


def test_requires_exactly_the_pinned_cli_wheel(tmp_path: Path) -> None:
    key = Ed25519PrivateKey.generate()
    files = _files()
    del files[CLI_WHEEL]
    files["wheels/fdai_deployment_cli-0.1.1-py3-none-any.whl"] = b"old"

    with pytest.raises(ValueError, match="pinned CLI wheel"):
        verify_control_package(
            _write(tmp_path / "control.tar.gz", files, key=key), public_key_pem=_public(key)
        )


def test_rejects_symlinked_archive(tmp_path: Path) -> None:
    key = Ed25519PrivateKey.generate()
    archive = _write(tmp_path / "control.tar.gz", _files(), key=key)
    link = tmp_path / "link.tar.gz"
    link.symlink_to(archive)

    with pytest.raises(ValueError, match="regular file"):
        verify_control_package(link, public_key_pem=_public(key))


def test_prepare_remote_installs_cli_only_from_verified_control_package(tmp_path: Path) -> None:
    tmp_path.chmod(0o700)
    plan = tmp_path / "run" / "foundation-adoption"
    plan.mkdir(parents=True, mode=0o700)
    (tmp_path / "run").chmod(0o700)
    archive = tmp_path / "kit.tar.gz"
    handoff = plan / "foundation-private-handoff.json"
    entra = tmp_path / "entra.json"
    for path in (archive, handoff, entra):
        path.write_text(path.name, encoding="utf-8")
    control_archive = tmp_path / "control.tar.gz"
    control_archive.write_bytes(b"control")
    control = ControlPackage(
        archive=control_archive,
        archive_digest="c" * 64,
        sums_digest="d" * 64,
        version=VERSION,
    )
    remote_root = "/home/fdai/.fdai-transfer-example"

    class Tunnel:
        def __init__(self) -> None:
            self.commands: list[tuple[str, ...]] = []
            self.copies: list[tuple[Path, str]] = []

        def copy_to(self, source: Path, destination: str, *, timeout: int) -> None:
            del timeout
            self.copies.append((source, destination))

        def ssh(self, command: tuple[str, ...], *, timeout: int) -> SimpleNamespace:
            del timeout
            self.commands.append(command)
            stdout = ""
            if command[0] == "sha256sum":
                digest = "c" * 64 if command[1].endswith("control.tar.gz") else "a" * 64
                stdout = f"{digest}  file\n"
            elif "prepare" in command:
                stdout = json.dumps({"state": "prepared", "focused_private_access": False})
            return SimpleNamespace(returncode=0, stdout=stdout)

    tunnel = Tunnel()
    prepare_remote(
        tunnel,
        remote_root=remote_root,
        remote_archive=f"{remote_root}/kit.tar.gz",
        archive=archive,
        archive_digest="a" * 64,
        handoff_path=handoff,
        remote_handoff=f"{remote_root}/foundation-handoff.json",
        entra_path=entra,
        remote_entra=f"{remote_root}/entra-bindings.json",
        app_work=f"{remote_root}/application",
        timeout_seconds=1800,
        control_package=control,
    )

    assert (control_archive, f"{remote_root}/control.tar.gz") in tunnel.copies
    installs = [command for command in tunnel.commands if command[1:2] == ("install",)]
    assert installs == [
        (
            f"{remote_root}/venv/bin/pip",
            "install",
            "--no-index",
            "--no-cache-dir",
            "--find-links",
            f"{remote_root}/control/package/wheels",
            "--requirement",
            f"{remote_root}/control/package/requirements.txt",
        )
    ]
    assert tunnel.commands.index(("rm", "-rf", "--", f"{remote_root}/venv")) < (
        tunnel.commands.index(("python3", "-m", "venv", f"{remote_root}/venv"))
    )


def test_prepare_remote_rejects_control_package_digest_mismatch(tmp_path: Path) -> None:
    tmp_path.chmod(0o700)
    plan = tmp_path / "run" / "foundation-adoption"
    plan.mkdir(parents=True, mode=0o700)
    (tmp_path / "run").chmod(0o700)
    archive = tmp_path / "kit.tar.gz"
    handoff = plan / "foundation-private-handoff.json"
    entra = tmp_path / "entra.json"
    for path in (archive, handoff, entra):
        path.write_text(path.name, encoding="utf-8")
    control = ControlPackage(
        archive=tmp_path / "control.tar.gz",
        archive_digest="c" * 64,
        sums_digest="d" * 64,
        version=VERSION,
    )

    class Tunnel:
        def copy_to(self, source: Path, destination: str, *, timeout: int) -> None:
            del source, destination, timeout

        def ssh(self, command: tuple[str, ...], *, timeout: int) -> SimpleNamespace:
            del timeout
            stdout = f"{'a' * 64}  file\n" if command[0] == "sha256sum" else ""
            return SimpleNamespace(returncode=0, stdout=stdout)

    with pytest.raises(ValueError, match="control package digest differs"):
        prepare_remote(
            Tunnel(),
            remote_root="/home/fdai/.fdai-transfer-example",
            remote_archive="/home/fdai/.fdai-transfer-example/kit.tar.gz",
            archive=archive,
            archive_digest="a" * 64,
            handoff_path=handoff,
            remote_handoff="/home/fdai/.fdai-transfer-example/foundation-handoff.json",
            entra_path=entra,
            remote_entra="/home/fdai/.fdai-transfer-example/entra-bindings.json",
            app_work="/home/fdai/.fdai-transfer-example/application",
            timeout_seconds=1800,
            control_package=control,
        )
