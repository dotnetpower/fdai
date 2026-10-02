"""Superseded managed-host transfers are pruned without losing unresolved apply evidence."""

from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from fdai_deployment_cli import standalone_transfer_cleanup
from fdai_deployment_cli.standalone_transfer_cleanup import (
    PRUNE_SCHEMA,
    cleanup_remote_transfers,
    prune_superseded_transfers,
    remote_prune,
    validate_prune_report,
)

_CURRENT = ".fdai-transfer-" + "c" * 24
_DONE = ".fdai-transfer-" + "a" * 24
_AMBIGUOUS = ".fdai-transfer-" + "b" * 24
_BULK_ROOT = ("kit", "venv")
_BULK_APPLICATION = ("kit-work", "oci", "runtime-venv", "azure", "terraform-data-runtime")


def _transfer(home: Path, name: str, *, claims: dict[str, bool]) -> Path:
    root = home / name
    application = root / "application"
    for directory in (*(root / item for item in _BULK_ROOT), application / "migration-evidence"):
        directory.mkdir(parents=True)
        (directory / "payload").write_bytes(b"x" * 64)
    for directory in _BULK_APPLICATION:
        (application / directory).mkdir()
        (application / directory / "payload").write_bytes(b"x" * 64)
    (root / "kit.tar.gz").write_bytes(b"archive")
    (root / "foundation-handoff.json").write_text("{}", encoding="utf-8")
    (application / "aks.kubeconfig").write_text("kubeconfig", encoding="utf-8")
    (application / "substrate.tfplan").write_bytes(b"plan")
    (application / "substrate-review.json").write_text("{}", encoding="utf-8")
    for operation, has_receipt in claims.items():
        (application / f"{operation}-claim.json").write_text("{}", encoding="utf-8")
        if has_receipt:
            (application / f"{operation}-receipt.json").write_text("{}", encoding="utf-8")
    return root


def _home(tmp_path: Path) -> tuple[Path, Path]:
    home = tmp_path / "home"
    current = _transfer(home, _CURRENT, claims={"application": True})
    _transfer(home, _DONE, claims={"substrate": True, "application": True})
    _transfer(home, _AMBIGUOUS, claims={"substrate": True, "application": False})
    (home / "notes").mkdir()
    return home, current / "application"


def test_prune_removes_settled_transfers_and_keeps_unresolved_evidence(tmp_path: Path) -> None:
    home, work_dir = _home(tmp_path)

    report = prune_superseded_transfers(work_dir)

    assert validate_prune_report(report) is report
    assert report["removed"] == [_DONE]
    assert report["preserved"] == [
        {"name": _AMBIGUOUS, "unmatched_claims": ["application-claim.json"]}
    ]
    assert report["skipped"] == []
    assert not (home / _DONE).exists()
    kept = home / _AMBIGUOUS
    for name in ("kit", "kit.tar.gz", "venv"):
        assert not (kept / name).exists()
    for name in (*_BULK_APPLICATION, "aks.kubeconfig"):
        assert not (kept / "application" / name).exists()
    for name in (
        "application-claim.json",
        "substrate-claim.json",
        "substrate-receipt.json",
        "substrate-review.json",
        "substrate.tfplan",
        "migration-evidence",
    ):
        assert (kept / "application" / name).exists()
    assert (kept / "foundation-handoff.json").exists()
    assert (home / _CURRENT / "kit").is_dir()
    assert (home / _CURRENT / "venv").is_dir()
    assert (home / "notes").is_dir()


def test_prune_is_idempotent_for_preserved_evidence(tmp_path: Path) -> None:
    _home_dir, work_dir = _home(tmp_path)
    prune_superseded_transfers(work_dir)

    again = prune_superseded_transfers(work_dir)

    assert again["removed"] == []
    assert [item["name"] for item in again["preserved"]] == [_AMBIGUOUS]


def test_prune_requires_a_converged_current_application(tmp_path: Path) -> None:
    _home_dir, work_dir = _home(tmp_path)
    (work_dir / "application-receipt.json").unlink()

    with pytest.raises(ValueError, match="converges"):
        prune_superseded_transfers(work_dir)


def test_prune_refuses_an_unexpected_layout(tmp_path: Path) -> None:
    work_dir = tmp_path / "elsewhere" / "application"
    work_dir.mkdir(parents=True)
    (work_dir / "application-receipt.json").write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="layout"):
        prune_superseded_transfers(work_dir)


def test_prune_skips_links_and_transfers_that_are_in_use(tmp_path: Path) -> None:
    home, work_dir = _home(tmp_path)
    target = tmp_path / "outside"
    target.mkdir()
    (target / "keep").write_text("keep", encoding="utf-8")
    linked = ".fdai-transfer-" + "d" * 24
    (home / linked).symlink_to(target, target_is_directory=True)
    lock_path = home / _DONE / "application" / ".checkpoint.lock"
    descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        report = prune_superseded_transfers(work_dir)
    finally:
        os.close(descriptor)

    skipped = {item["name"]: item["reason"] for item in report["skipped"]}
    assert skipped == {_DONE: "in-use-or-not-removable", linked: "not-an-owned-directory"}
    assert (home / _DONE / "kit").is_dir()
    assert (target / "keep").exists()


def test_module_entry_point_prunes_under_the_current_checkpoint(tmp_path: Path, capsys) -> None:
    _home_dir, work_dir = _home(tmp_path)
    work_dir.chmod(0o700)

    assert standalone_transfer_cleanup.main(["--work-dir", str(work_dir)]) == 0

    report = json.loads(capsys.readouterr().out)
    assert report["schema_version"] == PRUNE_SCHEMA
    assert report["removed"] == [_DONE]


def test_module_entry_point_refuses_without_a_converged_application(tmp_path: Path, capsys) -> None:
    _home_dir, work_dir = _home(tmp_path)
    work_dir.chmod(0o700)
    (work_dir / "application-receipt.json").unlink()

    assert standalone_transfer_cleanup.main(["--work-dir", str(work_dir)]) == 3

    captured = capsys.readouterr()
    assert captured.out == ""
    assert (tmp_path / "home" / _DONE).is_dir()


def test_remote_prune_runs_the_current_environment_and_validates_its_report() -> None:
    report = {
        "schema_version": PRUNE_SCHEMA,
        "removed": [],
        "preserved": [],
        "skipped": [],
        "free_bytes_before": 1,
        "free_bytes_after": 1,
    }
    commands: list[tuple[str, ...]] = []

    def ssh(command: tuple[str, ...], **_kwargs: object) -> SimpleNamespace:
        commands.append(command)
        return SimpleNamespace(returncode=0, stdout=json.dumps(report))

    result = remote_prune(SimpleNamespace(ssh=ssh), remote_root="/h/t", work_dir="/h/t/application")

    assert result == report
    assert commands == [
        (
            "/h/t/venv/bin/python",
            "-m",
            "fdai_deployment_cli.standalone_transfer_cleanup",
            "--work-dir",
            "/h/t/application",
        )
    ]


@pytest.mark.parametrize(("returncode", "stdout"), [(3, ""), (0, "not-json"), (0, "[]")])
def test_remote_prune_rejects_a_failed_or_invalid_run(returncode: int, stdout: str) -> None:
    tunnel = SimpleNamespace(
        ssh=lambda *_args, **_kwargs: SimpleNamespace(returncode=returncode, stdout=stdout)
    )
    with pytest.raises(ValueError, match="prune"):
        remote_prune(tunnel, remote_root="/h/t", work_dir="/h/t/application")


@pytest.mark.parametrize(
    "change",
    [
        {"schema_version": "other"},
        {"removed": ["../escape"]},
        {"preserved": [{"name": _AMBIGUOUS, "unmatched_claims": []}]},
        {"skipped": [{"name": "notes"}]},
        {"free_bytes_after": "1"},
    ],
)
def test_prune_report_validation_rejects_unexpected_values(change: dict[str, object]) -> None:
    report = {
        "schema_version": PRUNE_SCHEMA,
        "removed": [_DONE],
        "preserved": [],
        "skipped": [],
        "free_bytes_before": 1,
        "free_bytes_after": 2,
    }
    with pytest.raises(ValueError, match="prune report"):
        validate_prune_report({**report, **change})


class _Tunnel:
    def __init__(self, returncode: int = 0) -> None:
        self.commands: list[tuple[str, ...]] = []
        self.returncode = returncode

    def ssh(self, command: tuple[str, ...], **_kwargs: object) -> SimpleNamespace:
        self.commands.append(command)
        return SimpleNamespace(returncode=self.returncode)


@pytest.mark.parametrize(
    "transient_paths",
    [("/h/kit.tar.gz",), ("/h/source-transfer.tar", "/h/source-receiver.pyz")],
)
def test_cleanup_removes_transients_then_reports_the_prune(
    transient_paths: tuple[str, ...], monkeypatch
) -> None:
    details: list[str] = []
    monkeypatch.setattr(standalone_transfer_cleanup, "progress_detail", details.append)
    tunnel = _Tunnel()
    report = {
        "schema_version": PRUNE_SCHEMA,
        "removed": [_DONE],
        "preserved": [{"name": _AMBIGUOUS, "unmatched_claims": ["application-claim.json"]}],
        "skipped": [],
        "free_bytes_before": 1_000_000_000,
        "free_bytes_after": 6_000_000_000,
    }

    cleanup_remote_transfers(
        tunnel,
        transient_paths=transient_paths,
        remote_approval="/h/approval.json",
        prune=lambda: report,
    )

    assert tunnel.commands[0] == ("rm", "-f", "--", *transient_paths, "/h/approval.json")
    assert tunnel.commands[1:] == [
        ("test", "!", "-e", path) for path in (*transient_paths, "/h/approval.json")
    ]
    assert (
        "Pruned 1 superseded transfer(s), kept the evidence of 1, skipped 0; 5.0 GB freed"
        in details
    )


def test_prune_failure_never_fails_a_converged_run(monkeypatch) -> None:
    details: list[str] = []
    monkeypatch.setattr(standalone_transfer_cleanup, "progress_detail", details.append)

    def failing_prune() -> dict[str, object]:
        raise ValueError("standalone managed-host checkpoint failed")

    cleanup_remote_transfers(
        _Tunnel(),
        transient_paths=("/h/a.tar.gz",),
        remote_approval="/h/a.json",
        prune=failing_prune,
    )

    assert any("were not pruned" in detail for detail in details)


def test_transient_cleanup_failure_still_stops_the_run() -> None:
    with pytest.raises(ValueError, match="cleanup is incomplete"):
        cleanup_remote_transfers(
            _Tunnel(returncode=1),
            transient_paths=("/h/a.tar.gz",),
            remote_approval="/h/a.json",
            prune=lambda: pytest.fail("prune must not run after a failed transient cleanup"),
        )
