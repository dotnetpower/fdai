"""The README walkthrough uses `samples/`, so the CLI must keep producing its results."""

from __future__ import annotations

import json
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Any

import pytest

from fdai_lifecycle_hub import domain
from fdai_lifecycle_hub.cli import DATABASE_URL_ENV, main

SAMPLES = Path(__file__).resolve().parents[1] / "samples"


def _run(capsys: pytest.CaptureFixture[str], *argv: str) -> dict[str, Any]:
    assert main(list(argv)) == 0
    output: dict[str, Any] = json.loads(capsys.readouterr().out)
    return output


def test_readme_walkthrough(
    tmp_path: Path,
    now: datetime,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(DATABASE_URL_ENV, f"sqlite+pysqlite:///{tmp_path / 'hub.db'}")
    monkeypatch.setattr(domain, "utc_now", lambda: now)
    run = partial(_run, capsys)
    hub_key, installation_key = tmp_path / "hub.pem", tmp_path / "installation.pem"
    catalog = str(SAMPLES / "catalog")
    recompute = ("recompute", "example", "--catalog", catalog, "--key", str(hub_key))
    manage = ("manage", "example", "core", str(SAMPLES / "core-settings.json"), "--operator", "bob")

    run("migrate")
    run("dev-keygen", str(hub_key))
    run("dev-keygen", str(installation_key))
    pending = run("dev-enroll", str(SAMPLES / "enrollment.json"), "--key", str(installation_key))
    assert run("show", "example") == {
        "enrollment": "pending",
        "plan": None,
        "last_evaluation": None,
    }

    key_id = pending["installation_key_id"]
    run("approve", "example", "--approver", "alice", "--installation-key-id", key_id)
    assert run(*recompute)["outcome"] == "no-managed-entity"

    tag_only = run("record-ownership", "example", "core", str(SAMPLES / "ownership-tag-only.json"))
    assert tag_only == {"entity": "core", "proven": False, "reason": "ownership_tag_only"}
    assert main(list(manage)) == 1
    assert "ownership_tag_only" in capsys.readouterr().err

    proven = run("record-ownership", "example", "core", str(SAMPLES / "ownership.json"))
    assert proven == {"entity": "core", "proven": True, "reason": None}
    assert run(*manage)["covering_range"] == ">=1.0.0 <2.0.0"

    issued = run(*recompute)
    assert (issued["outcome"], issued["target"]) == ("issued", "1.6.0")
    assert run(*recompute)["outcome"] == "unchanged"

    run("suppress", "example", "--minutes", "60")
    held = run(*recompute)
    run("unsuppress", "example")
    assert (held["outcome"], held["target"]) == ("waiting", "1.6.0")
    assert run(*recompute)["outcome"] == "issued"

    run("record-state", "example", str(SAMPLES / "state-1.6.0.json"))
    assert run(*recompute)["outcome"] == "up-to-date"
