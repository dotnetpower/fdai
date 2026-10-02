from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from fdai_deployment_cli import standalone_host
from fdai_deployment_cli.catalog_review_profile import CatalogReviewDeploymentProfile
from fdai_deployment_cli.contracts import canonical_digest
from fdai_deployment_cli.standalone_remote_prepare import prepare_remote


def test_prepare_remote_transfers_foundation_adoption(tmp_path: Path) -> None:
    tmp_path.chmod(0o700)
    root = tmp_path / "run"
    plan = root / "foundation-adoption"
    root.mkdir(mode=0o700)
    plan.mkdir(mode=0o700)
    archive = tmp_path / "kit.tar.gz"
    handoff = plan / "foundation-private-handoff.json"
    adoption = root / "foundation-adoption-receipt.json"
    for path in (archive, handoff, adoption):
        path.write_text(path.name, encoding="utf-8")
    archive_digest = "a" * 64
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
            if command[0] == "sha256sum":
                stdout = f"{archive_digest}  kit.tar.gz\n"
            elif "prepare" in command:
                stdout = json.dumps({"state": "prepared", "focused_private_access": True})
            else:
                stdout = ""
            return SimpleNamespace(returncode=0, stdout=stdout)

    tunnel = Tunnel()
    result = prepare_remote(
        tunnel,
        remote_root=remote_root,
        remote_archive=f"{remote_root}/kit.tar.gz",
        archive=archive,
        archive_digest=archive_digest,
        handoff_path=handoff,
        remote_handoff=f"{remote_root}/foundation-handoff.json",
        entra_path=None,
        remote_entra=None,
        app_work=f"{remote_root}/application",
        timeout_seconds=1800,
    )

    assert (
        adoption,
        f"{remote_root}/foundation-adoption.json",
    ) in tunnel.copies
    prepare = next(command for command in tunnel.commands if "--foundation-adoption" in command)
    assert "--entra" not in prepare
    assert prepare[prepare.index("--foundation-adoption") + 1] == (
        f"{remote_root}/foundation-adoption.json"
    )
    assert result["focused_private_access"] is True


def _selected_profile(key_path: Path) -> CatalogReviewDeploymentProfile:
    key_digest = hashlib.sha256(key_path.read_bytes()).hexdigest()
    material = {
        "schema_version": "fdai.catalog-review-deployment-profile.v1",
        "selected": True,
        "owner": "example",
        "repo": "deployment-config",
        "default_branch": "main",
        "app_client_id": "client",
        "app_installation_id": "1",
        "private_key_sha256": key_digest,
    }
    return CatalogReviewDeploymentProfile(
        selected=True,
        owner="example",
        repo="deployment-config",
        default_branch="main",
        app_client_id="client",
        app_installation_id="1",
        private_key_path=key_path,
        private_key_sha256=key_digest,
        profile_digest=canonical_digest(material),
    )


@pytest.mark.parametrize("residual", ["profile", "key"])
def test_cleanup_incomplete_overrides_and_chains_setup_failure(
    residual: str,
    tmp_path: Path,
) -> None:
    archive = tmp_path / "kit.tar.gz"
    handoff = tmp_path / "handoff.json"
    key = tmp_path / "catalog-review.pem"
    for path in (archive, handoff, key):
        path.write_text(path.name, encoding="utf-8")
    archive_digest = "a" * 64
    remote_root = "/home/fdai/.fdai-transfer-example"

    class Tunnel:
        def copy_to(self, source: Path, destination: str, *, timeout: int) -> None:
            del source, destination, timeout

        def ssh(self, command: tuple[str, ...], *, timeout: int) -> SimpleNamespace:
            del timeout
            if command[0] == "sha256sum":
                return SimpleNamespace(returncode=0, stdout=f"{archive_digest}  kit.tar.gz\n")
            if command[:2] == ("rm", "-rf"):
                return SimpleNamespace(returncode=1, stdout="")
            if command[:2] == ("rm", "-f") and "catalog-review-profile.json" in command[-2]:
                return SimpleNamespace(returncode=1, stdout="")
            if command[:3] == ("test", "!", "-e"):
                remains = (
                    command[-1].endswith("catalog-review-profile.json")
                    if residual == "profile"
                    else command[-1].endswith("catalog-review-private-key.pem")
                )
                return SimpleNamespace(returncode=1 if remains else 0, stdout="")
            return SimpleNamespace(returncode=0, stdout="")

    with pytest.raises(
        ValueError,
        match="catalog review profile cleanup is incomplete",
    ) as captured:
        prepare_remote(
            Tunnel(),
            remote_root=remote_root,
            remote_archive=f"{remote_root}/kit.tar.gz",
            archive=archive,
            archive_digest=archive_digest,
            handoff_path=handoff,
            remote_handoff=f"{remote_root}/handoff.json",
            entra_path=None,
            remote_entra=None,
            app_work=f"{remote_root}/application",
            timeout_seconds=1800,
            catalog_review_profile=_selected_profile(key),
        )

    assert isinstance(captured.value.__cause__, ValueError)
    assert (
        str(captured.value.__cause__)
        == "standalone managed-host preparation failed: step=clean-kit"
    )


class _RecordingTunnel:
    def __init__(self, digests: dict[str, str]) -> None:
        self.digests = digests
        self.commands: list[tuple[str, ...]] = []

    def copy_to(self, source: Path, destination: str, *, timeout: int) -> None:
        del source, destination, timeout

    def ssh(self, command: tuple[str, ...], *, timeout: int) -> SimpleNamespace:
        del timeout
        self.commands.append(command)
        if command[0] == "sha256sum":
            return SimpleNamespace(returncode=0, stdout=f"{self.digests[command[1]]}  file\n")
        if command[1:3] == ("-m", "fdai_deployment_cli.standalone_host"):
            prepared = {"state": "prepared", "focused_private_access": False}
            return SimpleNamespace(returncode=0, stdout=json.dumps(prepared))
        return SimpleNamespace(returncode=0, stdout="")


@pytest.mark.parametrize("mode", ["kit", "source"])
def test_prepare_command_parses_with_the_host_parser(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    tmp_path.chmod(0o700)
    plan = tmp_path / "plan"
    plan.mkdir(mode=0o700)
    handoff = plan / "foundation-private-handoff.json"
    handoff.write_text("{}", encoding="utf-8")
    inputs = {name: tmp_path / name for name in ("kit.tar.gz", "source.tar", "receiver.pyz")}
    for path in inputs.values():
        path.write_bytes(path.name.encode())
    remote_root = "/home/fdai/.fdai-transfer-example"
    tunnel = _RecordingTunnel(
        {
            f"{remote_root}/kit.tar.gz": "a" * 64,
            f"{remote_root}/source-transfer.tar": "b" * 64,
            f"{remote_root}/source-receiver.pyz": "c" * 64,
        }
    )
    common: dict[str, object] = {
        "remote_root": remote_root,
        "remote_archive": f"{remote_root}/kit.tar.gz",
        "handoff_path": handoff,
        "remote_handoff": f"{remote_root}/foundation-handoff.json",
        "entra_path": None,
        "remote_entra": None,
        "app_work": str(tmp_path / "application"),
        "timeout_seconds": 1800,
    }
    if mode == "kit":
        prepare_remote(
            tunnel,
            archive=inputs["kit.tar.gz"],
            archive_digest="a" * 64,
            **common,  # type: ignore[arg-type]
        )
    else:
        prepare_remote(
            tunnel,
            archive=None,
            archive_digest=None,
            source_archive=inputs["source.tar"],
            source_archive_digest="b" * 64,
            source_receiver=inputs["receiver.pyz"],
            source_receiver_digest="c" * 64,
            source_snapshot_digest="d" * 64,
            **common,  # type: ignore[arg-type]
        )
    command = next(
        item
        for item in tunnel.commands
        if item[1:3] == ("-m", "fdai_deployment_cli.standalone_host")
    )
    seen: dict[str, argparse.Namespace] = {}

    def prepare(args: argparse.Namespace, _work_dir: Path) -> dict[str, object]:
        seen["args"] = args
        return {"state": "prepared"}

    monkeypatch.setattr(standalone_host, "_prepare", prepare)
    umask = os.umask(0o077)
    os.umask(umask)
    try:
        # The real host parser must accept the exact command the coordinator sends.
        assert standalone_host.main(list(command[3:])) == 0
    finally:
        os.umask(umask)

    if mode == "kit":
        assert str(seen["args"].kit) == f"{remote_root}/kit"
    else:
        assert seen["args"].source_snapshot_digest == "d" * 64
