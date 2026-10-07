"""Tests for the operator CLI that exports packs and validates returned results."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fdai.delivery import code_security_cli

from ._support import CATALOG_ROOT, REVISION, result, sarif


def test_export_then_import_rejects_unchanged_result_without_commits(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mdash = tmp_path / "mdash.sarif"
    mdash.write_bytes(
        sarif(
            "MDASH", [result("sqli", "src/db.py", 2, cwe=89), result("bad", "../x.py", 1, cwe=89)]
        )
    )
    opengrep = tmp_path / "opengrep.sarif"
    opengrep.write_bytes(sarif("Opengrep", [result("python.sqli", "src/db.py", 2, cwe=89)]))
    code = code_security_cli.main(
        [
            "export",
            "--sarif",
            f"{mdash}:external",
            "--sarif",
            f"{opengrep}:deterministic",
            "--revision",
            REVISION,
            "--repo-alias",
            "example-service",
            "--out",
            str(tmp_path / "out"),
            "--mode",
            "minimized",
            "--catalog-root",
            str(CATALOG_ROOT),
        ]
    )
    exported = json.loads(capsys.readouterr().out)
    assert code == 0, exported
    assert exported["occurrences"] == 2 and exported["issues"] == 1
    assert exported["dropped"] == {"unresolvable_location": 1}
    pack_dir = Path(exported["pack_dir"])
    assert (pack_dir.stat().st_mode & 0o077) == 0
    manifest = json.loads((pack_dir / "pack.manifest.json").read_text())
    assert any("unresolvable_location=1" in note for note in manifest["coverage_limits"])
    record = json.loads(Path(exported["record"]).read_text())
    issue_id = record["issue_ids"][0]
    result_file = tmp_path / "result.json"
    result_file.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "pack_id": record["pack_id"],
                "manifest_sha256": record["manifest_sha256"],
                "base_commit": REVISION,
                "final_head": "c" * 40,
                "issues": [{"issue_id": issue_id, "status": "deferred"}],
            }
        )
    )
    assert (
        code_security_cli.main(
            ["import-result", "--record", exported["record"], "--result", str(result_file)]
        )
        == 0
    )
    imported = json.loads(capsys.readouterr().out)
    assert imported["claims"][0]["status"] == "deferred"
    result_file.write_text(result_file.read_text().replace(record["manifest_sha256"], "0" * 64))
    assert (
        code_security_cli.main(
            ["import-result", "--record", exported["record"], "--result", str(result_file)]
        )
        == 1
    )
    assert json.loads(capsys.readouterr().out)["reason"] == "manifest_digest_mismatch"
