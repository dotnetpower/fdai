"""Prepared handoffs bind complete source bytes without giving scanners acquisition credentials."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
from pathlib import Path
from unittest.mock import Mock

import pytest
from fdai.core.security.code_findings.review_signal import ReviewSource
from fdai.delivery import code_security_prepared_source as handoff
from fdai.delivery import code_security_scan_cli as scan_cli
from fdai.delivery.code_security_acquire import AcquiredSource, SourceAcquisitionError
from fdai.delivery.code_security_cli import _parser, main
from fdai.delivery.code_security_prepare_cli import prepare_scan
from fdai.delivery.code_security_sandbox import ScannerRunResult

_REVISION = "a" * 40


def _export(tmp_path: Path) -> handoff.PreparedSource:
    tree = tmp_path / "original"
    (tree / "src").mkdir(parents=True)
    (tree / "src" / "app.py").write_text("import os\nos.system(user_input)\n")
    (tree / "start.sh").write_text("#!/bin/sh\nexit 0\n")
    (tree / "start.sh").chmod(0o755)
    return handoff.export_prepared_source(
        AcquiredSource(tree, _REVISION, "b" * 40),
        tmp_path / "prepared",
        repository_alias="example-app",
        source=ReviewSource(kind="git_repository", provider="git", trigger="cli"),
    )


def _changed_manifest(tmp_path: Path, value: dict[str, object]) -> str:
    path = tmp_path / "prepared" / "manifest.json"
    path.chmod(0o600)
    encoded = json.dumps(value).encode()
    path.write_bytes(encoded)
    return hashlib.sha256(encoded).hexdigest()


def test_export_is_private_read_only_and_portable(tmp_path: Path) -> None:
    prepared = _export(tmp_path)
    root = tmp_path / "prepared"
    assert prepared.repository_alias == "example-app"
    assert prepared.acquired.revision == _REVISION
    assert set(path.name for path in root.iterdir()) == {"source", "manifest.json"}
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    assert not (root / "manifest.json").stat().st_mode & 0o222
    assert not prepared.acquired.path.stat().st_mode & 0o222
    assert stat.S_IMODE((prepared.acquired.path / "start.sh").stat().st_mode) == 0o500
    assert stat.S_IMODE((prepared.acquired.path / "src/app.py").stat().st_mode) == 0o400
    relocated = tmp_path / "relocated"
    shutil.copytree(root, relocated)
    loaded = handoff.load_prepared_source(relocated, prepared.manifest_digest)
    assert loaded.tree_digest == prepared.tree_digest
    assert loaded.acquired.path == relocated / "source"
    with pytest.raises(SourceAcquisitionError, match="already exists"):
        handoff.export_prepared_source(
            prepared.acquired, root, repository_alias="example-app", source=prepared.source
        )


def test_modified_tree_is_rejected_before_scanning(tmp_path: Path) -> None:
    prepared = _export(tmp_path)
    file = prepared.acquired.path / "src/app.py"
    file.chmod(0o600)
    file.write_text("changed\n")
    with pytest.raises(SourceAcquisitionError, match="contents changed"):
        handoff.load_prepared_source(tmp_path / "prepared", prepared.manifest_digest)


def test_executable_mode_is_bound(tmp_path: Path) -> None:
    prepared = _export(tmp_path)
    (prepared.acquired.path / "start.sh").chmod(0o400)
    with pytest.raises(SourceAcquisitionError, match="contents changed"):
        prepared.verify_tree()


@pytest.mark.parametrize("name", ["link", "directory-link", ".git", "pipe"])
def test_rejects_untracked_entries(tmp_path: Path, name: str) -> None:
    prepared = _export(tmp_path)
    tree = prepared.acquired.path
    tree.chmod(0o700)
    if name == "link":
        (tree / name).symlink_to(tree / "start.sh")
    elif name == "directory-link":
        (tree / name).symlink_to(tree / "src", target_is_directory=True)
    elif name == ".git":
        (tree / name).mkdir()
    else:
        os.mkfifo(tree / name)
    with pytest.raises(SourceAcquisitionError, match="links or special|Git metadata"):
        prepared.verify_tree()


def test_manifest_requires_external_digest_and_regular_file(tmp_path: Path) -> None:
    prepared = _export(tmp_path)
    root = tmp_path / "prepared"
    for wrong in ("", "z" * 64, "0" * 64):
        with pytest.raises(SourceAcquisitionError, match="digest"):
            handoff.load_prepared_source(root, wrong)
    path = root / "manifest.json"
    path.unlink()
    os.mkfifo(path)
    with pytest.raises(SourceAcquisitionError, match="regular file"):
        handoff.load_prepared_source(root, prepared.manifest_digest)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", True),
        ("schema_version", 2),
        ("revision", "../other"),
        ("tree_id", []),
        ("tree_digest", "x" * 64),
        ("source", {"kind": "local_path"}),
        ("repository_alias", "bad alias"),
        ("extra", "ignored"),
    ],
)
def test_manifest_rejects_invalid_schema(tmp_path: Path, field: str, value: object) -> None:
    _export(tmp_path)
    document = json.loads((tmp_path / "prepared/manifest.json").read_bytes())
    document[field] = value
    digest = _changed_manifest(tmp_path, document)
    with pytest.raises((ValueError, SourceAcquisitionError)):
        handoff.load_prepared_source(tmp_path / "prepared", digest)


def test_manifest_and_tree_bounds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    prepared = _export(tmp_path)
    monkeypatch.setattr(handoff, "_MAX_MANIFEST_BYTES", 8)
    with pytest.raises(SourceAcquisitionError, match="manifest exceeds"):
        handoff.load_prepared_source(tmp_path / "prepared", prepared.manifest_digest)
    monkeypatch.setattr(handoff, "_MAX_ENTRIES", 1)
    with pytest.raises(SourceAcquisitionError, match="entry limit"):
        prepared.verify_tree()
    monkeypatch.setattr(handoff, "_MAX_ENTRIES", 200_000)
    monkeypatch.setattr(handoff, "_MAX_BYTES", 1)
    with pytest.raises(SourceAcquisitionError, match="byte limit"):
        prepared.verify_tree()


def test_export_refuses_links_without_changing_existing_acquisition(tmp_path: Path) -> None:
    tree = tmp_path / "tree"
    tree.mkdir()
    (tree / "file").write_text("safe\n")
    (tree / "link").symlink_to("file")
    with pytest.raises(SourceAcquisitionError, match="links"):
        handoff.export_prepared_source(
            AcquiredSource(tree, _REVISION, "b" * 40),
            tmp_path / "prepared",
            repository_alias="example-app",
            source=ReviewSource(kind="git_repository", provider="git"),
        )
    assert not (tmp_path / "prepared").exists()
    assert (tree / "link").is_symlink()


async def test_prepare_cli_exports_a_local_snapshot(tmp_path: Path) -> None:
    source = tmp_path / "input"
    source.mkdir()
    (source / "app.py").write_text("print('hello')\n")
    args = _parser().parse_args(
        [
            "prepare-scan",
            "--path",
            str(source),
            "--include-uncommitted",
            "--work-root",
            str(tmp_path / "work"),
            "--out",
            str(tmp_path / "prepared"),
        ]
    )
    result = await prepare_scan(args)
    assert result["ok"] is True
    assert result["revision_kind"] == "snapshot"
    prepared = handoff.load_prepared_source(tmp_path / "prepared", str(result["manifest_digest"]))
    assert prepared.source.kind == "local_path"
    assert str(source) not in (tmp_path / "prepared/manifest.json").read_text()


@pytest.mark.parametrize(
    "arguments",
    [
        ["--path", "/input"],
        ["--repository", "/origin"],
        ["--revision", _REVISION],
        ["--repo-alias", "override"],
        ["--source-provider", "override"],
        ["--include-uncommitted"],
        ["--record-state"],
        ["--kafka-bootstrap-servers", "localhost:9092"],
        ["--lens-model", "model=unused"],
    ],
)
def test_prepared_cli_rejects_acquisition_and_credential_paths(arguments: list[str]) -> None:
    args = _parser().parse_args(
        ["scan", "--prepared-source", "/prepared", "--prepared-digest", "a" * 64, *arguments]
    )
    with pytest.raises(ValueError, match="prepared scanning cannot"):
        scan_cli._prepared_target(args)


def test_prepared_cli_requires_both_input_and_digest() -> None:
    for arguments in (
        ["--prepared-source", "/prepared"],
        ["--prepared-digest", "a" * 64],
    ):
        with pytest.raises(ValueError, match="requires"):
            scan_cli._prepared_target(_parser().parse_args(["scan", *arguments]))


@pytest.mark.parametrize("option", ["--work-root", "--report"])
def test_prepared_scan_cannot_write_into_the_handoff(tmp_path: Path, option: str) -> None:
    prepared = _export(tmp_path)
    args = _parser().parse_args(
        [
            "scan",
            "--prepared-source",
            str(tmp_path / "prepared"),
            "--prepared-digest",
            prepared.manifest_digest,
            option,
            str(tmp_path / "prepared/source/output"),
        ]
    )
    with pytest.raises(ValueError, match="outside the handoff"):
        scan_cli._prepared_target(args)


async def test_prepared_code_cannot_be_selected_as_the_scanner(tmp_path: Path) -> None:
    prepared = _export(tmp_path)
    args = _parser().parse_args(
        [
            "scan",
            "--prepared-source",
            str(tmp_path / "prepared"),
            "--prepared-digest",
            prepared.manifest_digest,
            "--scanner-bin",
            f"opengrep={prepared.acquired.path / 'start.sh'}",
        ]
    )
    with pytest.raises(ValueError, match="cannot be a scanner executable"):
        await scan_cli.run_scan(args)


async def test_prepared_scan_never_constructs_a_git_acquirer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepared = _export(tmp_path)
    acquisition = Mock(side_effect=AssertionError("acquisition must not run"))
    monkeypatch.setattr(scan_cli, "GitSourceAcquirer", acquisition)
    result_sarif = json.dumps(
        {
            "version": "2.1.0",
            "runs": [
                {
                    "tool": {"driver": {"name": "Opengrep", "version": "1"}},
                    "results": [
                        {
                            "ruleId": "test",
                            "message": {"text": "finding"},
                            "properties": {"tags": ["CWE-78"]},
                            "locations": [
                                {
                                    "physicalLocation": {
                                        "artifactLocation": {"uri": "src/app.py"},
                                        "region": {"startLine": 2},
                                    }
                                }
                            ],
                        }
                    ],
                }
            ],
        }
    ).encode()

    async def scanner(*_args: object, **_kwargs: object) -> ScannerRunResult:
        return ScannerRunResult("opengrep", "Opengrep", result_sarif, 0, True, False, False, 1, "")

    monkeypatch.setattr(scan_cli.BubblewrapScannerSandbox, "run", scanner)
    args = _parser().parse_args(
        [
            "scan",
            "--prepared-source",
            str(tmp_path / "prepared"),
            "--prepared-digest",
            prepared.manifest_digest,
            "--work-root",
            str(tmp_path / "scan"),
            "--scanner-bin",
            "opengrep=/unused",
            "--report",
            str(tmp_path / "report"),
        ]
    )
    result = await scan_cli.run_scan(args)
    assert result["issues"] == 1
    assert result["revision"] == _REVISION
    assert result["repository_alias"] == "example-app"
    assert result["published"] is False and result["recorded"] is False
    assert result["coverage_complete"] is False
    assert result["prepared_manifest_digest"] == prepared.manifest_digest
    receipt = json.loads((tmp_path / "scan/scans" / _REVISION / "receipt.json").read_text())
    assert receipt["prepared_manifest_digest"] == prepared.manifest_digest
    assert (tmp_path / "report/report.json").is_file()
    acquisition.assert_not_called()


async def test_changed_source_cannot_produce_a_success_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepared = _export(tmp_path)

    async def scanner(*_args: object, **_kwargs: object) -> ScannerRunResult:
        file = prepared.acquired.path / "src/app.py"
        file.chmod(0o600)
        file.write_text("changed during scan\n")
        return ScannerRunResult(
            "opengrep",
            "Opengrep",
            b'{"version":"2.1.0","runs":[]}',
            0,
            True,
            False,
            False,
            1,
            "",
        )

    monkeypatch.setattr(scan_cli.BubblewrapScannerSandbox, "run", scanner)
    args = _parser().parse_args(
        [
            "scan",
            "--prepared-source",
            str(tmp_path / "prepared"),
            "--prepared-digest",
            prepared.manifest_digest,
            "--work-root",
            str(tmp_path / "scan"),
            "--scanner-bin",
            "opengrep=/unused",
            "--report",
            str(tmp_path / "report"),
        ]
    )
    with pytest.raises(SourceAcquisitionError, match="contents changed"):
        await scan_cli.run_scan(args)
    assert not list((tmp_path / "scan").rglob("review.json"))
    assert not (tmp_path / "report").exists()


def test_cli_returns_explicit_failure_for_wrong_digest(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _export(tmp_path)
    assert (
        main(
            [
                "scan",
                "--prepared-source",
                str(tmp_path / "prepared"),
                "--prepared-digest",
                "0" * 64,
            ]
        )
        == 1
    )
    assert json.loads(capsys.readouterr().out)["reason"] == "source_unavailable"
