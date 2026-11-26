"""Wave (small quality bump) - exemption_cli.py coverage.

The CLI validator is invoked by CI to check every exemption JSON file
in the catalog. These tests exercise every branch (success, file not
found, invalid JSON, top-level non-object, ExemptionError from the
loader, overall exit-code contract) so a regression in the wrapper
does not slip past.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fdai.rule_catalog.schema import exemption_cli


def _valid_raw() -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "id": "example.tag.owner-required.example-rg",
        "rule_id": "example.tag.owner-required",
        "scope": {
            "subscription_id": "00000000-0000-0000-0000-000000000000",
            "resource_group": "rg-fdai",
        },
        "justification": "Waived while an owner tag lookup service is being provisioned.",
        "requested_by": "00000000-0000-0000-0000-000000000001",
        "approved_by": "00000000-0000-0000-0000-000000000002",
        "state": "active",
        "created_at": "2026-07-05T00:00:00Z",
        "expires_at": "2026-08-05T00:00:00Z",
    }


def _write(path: Path, payload: object) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_cli_returns_zero_when_every_file_valid(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    file_a = _write(tmp_path / "a.json", _valid_raw())
    file_b = _write(tmp_path / "b.json", _valid_raw())

    rc = exemption_cli.main([str(file_a), str(file_b)])
    assert rc == 0
    out = capsys.readouterr().out
    assert str(file_a) in out
    assert str(file_b) in out


# ---------------------------------------------------------------------------
# Failure paths
# ---------------------------------------------------------------------------


def test_cli_reports_missing_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = exemption_cli.main([str(tmp_path / "missing.json")])
    assert rc == 1
    err = capsys.readouterr().err
    assert "file not found" in err


def test_cli_reports_invalid_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")

    rc = exemption_cli.main([str(bad)])
    assert rc == 1
    err = capsys.readouterr().err
    # JSONDecodeError surfaces via the same failure branch as ValueError.
    assert "bad.json" in err


def test_cli_reports_non_object_top_level(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The loader helper rejects top-level JSON arrays / scalars."""

    arr = _write(tmp_path / "arr.json", ["not", "an", "object"])
    rc = exemption_cli.main([str(arr)])
    assert rc == 1
    err = capsys.readouterr().err
    assert "top-level" in err


def test_cli_reports_exemption_validation_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A structurally valid JSON that fails ExemptionError - e.g. bad
    state value - surfaces every issue for a reviewer to fix in bulk."""

    payload = _valid_raw()
    payload["state"] = "not-a-real-state"
    invalid = _write(tmp_path / "state.json", payload)

    rc = exemption_cli.main([str(invalid)])
    assert rc == 1
    err = capsys.readouterr().err
    assert "validation failed" in err


def test_cli_aggregates_failures_across_files(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Every file is validated even when earlier files fail; the
    footer names the total failure count."""

    ok = _write(tmp_path / "ok.json", _valid_raw())
    missing = tmp_path / "missing.json"
    bad_json = tmp_path / "bad.json"
    bad_json.write_text("{not json", encoding="utf-8")

    rc = exemption_cli.main([str(ok), str(missing), str(bad_json)])
    assert rc == 1
    err = capsys.readouterr().err
    assert "FAILED" in err
    assert "2 file(s) invalid" in err


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def test_cli_requires_at_least_one_file(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as info:
        exemption_cli.main([])
    # argparse exits with code 2 on invalid usage.
    assert info.value.code == 2
    err = capsys.readouterr().err
    assert "files" in err
