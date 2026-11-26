"""Focused tests for `fdaictl security audit`, `fdaictl deploy preflight`, and copy pruning."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest
from fdai_deployment_cli.cli import main
from fdai_deployment_cli.security_and_preflight_cli import (
    evaluate_deploy_preflight_plan,
    prune_obsolete_execution_copies,
    run_security_scan_command,
)


def test_fdaictl_security_audit_text_and_json_modes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    work_dir = tmp_path / "private_work"
    work_dir.mkdir(mode=0o700)
    work_dir.chmod(0o700)
    (work_dir / "state.json").write_text('{"status":"clean"}\n', encoding="utf-8")

    rc_text = main(["security", "audit", "--work-dir", str(work_dir), "--output", "text"])
    assert rc_text == 0
    assert "security audit PASS" in capsys.readouterr().out

    rc_json = main(["security", "audit", "--work-dir", str(work_dir), "--output", "json"])
    assert rc_json == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["passed"] is True
    assert payload["execution_authority"] == "none"

    # Leak a bearer token and verify audit fails closed
    (work_dir / "leaked.txt").write_text(
        "Authorization: Bearer secret_token_12345678\n", encoding="utf-8"
    )
    rc_fail = main(["security", "audit", "--work-dir", str(work_dir), "--output", "json"])
    assert rc_fail == 3
    failed_payload = json.loads(capsys.readouterr().out)
    assert failed_payload["passed"] is False


def test_fdaictl_deploy_preflight_passes_safe_plan_and_holds_destructive_plan(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    safe_plan = tmp_path / "safe-plan.json"
    safe_plan.write_text(
        json.dumps(
            {
                "format_version": "1.2",
                "errored": False,
                "resource_changes": [
                    {"address": "azurerm_resource_group.app", "change": {"actions": ["create"]}},
                ],
            }
        ),
        encoding="utf-8",
    )
    rc_ok = main(["deploy", "preflight", "--plan-json", str(safe_plan), "--output", "json"])
    assert rc_ok == 0
    report_ok = json.loads(capsys.readouterr().out)
    assert report_ok["passed"] is True
    assert report_ok["create_count"] == 1
    assert report_ok["destructive_count"] == 0
    assert report_ok["execution_authority"] == "none"
    assert str(report_ok["plan_sha256"]).startswith("sha256:")
    assert report_ok["plan_sha256"] == report_ok["plan_digest"]

    destructive_plan = tmp_path / "destructive-plan.json"
    destructive_plan.write_text(
        json.dumps(
            {
                "format_version": "1.2",
                "errored": False,
                "resource_changes": [
                    {
                        "address": "azurerm_postgresql_flexible_server.db",
                        "change": {"actions": ["delete", "create"]},
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    rc_hold = main(
        ["deploy", "preflight", "--plan-json", str(destructive_plan), "--output", "text"]
    )
    assert rc_hold == 3
    assert "deploy preflight HOLD" in capsys.readouterr().out


def test_prune_obsolete_execution_copies_preserves_unfinished_run_evidence(
    tmp_path: Path,
) -> None:
    c1 = tmp_path / "offline-source-aaaa1111"
    c2 = tmp_path / "offline-source-bbbb2222"
    c3 = tmp_path / "bundle-recheck-cccc3333"
    unfinished = tmp_path / "offline-source-dddd4444"
    for idx, d in enumerate((c1, c2, c3, unfinished), start=1):
        d.mkdir()
    (unfinished / ".unfinished-run").write_text("active", encoding="utf-8")

    removed = prune_obsolete_execution_copies(tmp_path, max_retained=1)
    assert len(removed) == 2
    assert unfinished.exists()


def test_evaluate_deploy_preflight_rejects_duplicate_json_keys_and_scan_rejects_control_chars(
    tmp_path: Path,
) -> None:
    dup_plan = tmp_path / "dup-plan.json"
    dup_plan.write_text(
        '{"format_version":"1.2","errored":false,"errored":true,"resource_changes":[]}\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate key"):
        evaluate_deploy_preflight_plan(dup_plan)

    with pytest.raises(ValueError, match="control characters"):
        run_security_scan_command(argparse.Namespace(target="bad\x00target", output="text"))

    with pytest.raises(ValueError, match="control characters"):
        run_security_scan_command(target="bad\ntarget")
