from __future__ import annotations

import json
import stat
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from fdai_lifecycle_hub import domain
from fdai_lifecycle_hub.catalog import load_catalog
from fdai_lifecycle_hub.cli import DATABASE_URL_ENV, main
from fdai_lifecycle_hub.domain import Installation
from fdai_lifecycle_hub.schemas import entity_settings_json, ownership_json, reported_state_json


def _run(capsys: pytest.CaptureFixture[str], *argv: str) -> dict[str, Any]:
    assert main(list(argv)) == 0
    output: dict[str, Any] = json.loads(capsys.readouterr().out)
    return output


def _enroll(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    template: dict[str, Any],
    installation: Installation,
) -> None:
    """Migrate, then enroll, approve, and manage the installation's managed entities."""

    request, key = tmp_path / "enrollment.json", tmp_path / "installation.pem"
    request.write_text(json.dumps(template))
    _run(capsys, "migrate")
    _run(capsys, "dev-keygen", str(key))
    pending = _run(capsys, "dev-enroll", str(request), "--key", str(key))
    installation_id = pending["pending"]
    key_id = pending["installation_key_id"]
    _run(capsys, "approve", installation_id, "--approver", "alice", "--installation-key-id", key_id)
    for entity in installation.entities:
        if entity.ownership is None or entity.settings is None:
            continue
        evidence = tmp_path / f"{entity.entity_id}-ownership.json"
        evidence.write_bytes(ownership_json.dump_json(entity.ownership))
        settings = tmp_path / f"{entity.entity_id}-settings.json"
        settings.write_bytes(entity_settings_json.dump_json(entity.settings))
        _run(capsys, "record-ownership", installation_id, entity.entity_id, str(evidence))
        _run(
            capsys, "manage", installation_id, entity.entity_id, str(settings), "--operator", "bob"
        )


def test_catalog_directory_loads_releases_and_channels(catalog_dir: Path) -> None:
    catalog = load_catalog(catalog_dir)

    assert [release_id for release_id, _ in catalog.newer_than("stable", "1.4.0")] == [
        "1.6.0",
        "1.5.0",
    ]


def test_catalog_rejects_symlinked_entries(catalog_dir: Path) -> None:
    channels = catalog_dir / "channels.json"
    target = catalog_dir / "real-channels.json"
    channels.rename(target)
    channels.symlink_to(target)

    with pytest.raises(ValueError, match="not a regular file"):
        load_catalog(catalog_dir)


def test_dev_keygen_writes_owner_only_private_key(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    private = tmp_path / "keys" / "hub.pem"

    output = _run(capsys, "dev-keygen", str(private))

    assert stat.S_IMODE(private.stat().st_mode) == 0o600
    assert output == {"public_key": str(private.with_suffix(".pub.pem"))}
    with pytest.raises(FileExistsError):
        main(["dev-keygen", str(private)])


def test_enroll_recompute_show_flow(
    tmp_path: Path,
    enrollment_template: dict[str, Any],
    catalog_dir: Path,
    installation: Installation,
    now: datetime,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(DATABASE_URL_ENV, f"sqlite+pysqlite:///{tmp_path / 'hub.db'}")
    monkeypatch.setattr(domain, "utc_now", lambda: now)
    key = tmp_path / "hub.pem"
    _run(capsys, "dev-keygen", str(key))
    recompute = [
        "recompute",
        "installation-alpha",
        "--catalog",
        str(catalog_dir),
        "--key",
        str(key),
    ]

    _enroll(capsys, tmp_path, enrollment_template, installation)
    issued = _run(capsys, *recompute)
    unchanged = _run(capsys, *recompute)
    shown = _run(capsys, "show", "installation-alpha")

    assert (issued["outcome"], issued["plan_id"], issued["target"]) == (
        "issued",
        "installation-alpha-00000001",
        "1.6.0",
    )
    assert (unchanged["outcome"], unchanged["plan_id"]) == (
        "unchanged",
        "installation-alpha-00000001",
    )
    assert shown["plan"] == {
        "plan_id": "installation-alpha-00000001",
        "target": "1.6.0",
        "expires_at": "2026-10-05T03:30:00+00:00",
    }
    assert shown["last_evaluation"]["outcome"] == "unchanged"
    assert shown["enrollment"] == "enrolled"


def test_record_state_then_recompute_reports_up_to_date(
    tmp_path: Path,
    enrollment_template: dict[str, Any],
    catalog_dir: Path,
    installation: Installation,
    now: datetime,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(DATABASE_URL_ENV, f"sqlite+pysqlite:///{tmp_path / 'hub.db'}")
    monkeypatch.setattr(domain, "utc_now", lambda: now)
    core = replace(installation.reported.entities["core"], release_id="1.6.0")
    upgraded = replace(
        installation.reported,
        entities={**installation.reported.entities, "core": core},
        observed_at=now,
    )
    state = tmp_path / "state.json"
    state.write_bytes(reported_state_json.dump_json(upgraded))
    key = tmp_path / "hub.pem"
    _run(capsys, "dev-keygen", str(key))
    _enroll(capsys, tmp_path, enrollment_template, installation)

    assert _run(capsys, "record-state", "installation-alpha", str(state)) == {
        "recorded": upgraded.digest
    }
    outcome = _run(
        capsys, "recompute", "installation-alpha", "--catalog", str(catalog_dir), "--key", str(key)
    )

    assert outcome == {"outcome": "up-to-date", "checks": []}


@pytest.mark.parametrize(
    ("field", "value"),
    [("release_id", "not-a-version"), ("health", "whatever"), ("digest", "x")],
)
def test_invalid_state_is_rejected_at_the_boundary(
    tmp_path: Path,
    installation: Installation,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    field: str,
    value: str,
) -> None:
    monkeypatch.setenv(DATABASE_URL_ENV, f"sqlite+pysqlite:///{tmp_path / 'hub.db'}")
    state = reported_state_json.dump_python(installation.reported, mode="json")
    target = state if field == "digest" else state["entities"]["core"]
    target[field] = value
    path = tmp_path / "state.json"
    path.write_text(json.dumps(state))
    _run(capsys, "migrate")

    assert main(["record-state", "installation-alpha", str(path)]) == 1
    assert capsys.readouterr().err.startswith("ValidationError")


def test_suppress_and_unsuppress(
    tmp_path: Path,
    enrollment_template: dict[str, Any],
    installation: Installation,
    now: datetime,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(DATABASE_URL_ENV, f"sqlite+pysqlite:///{tmp_path / 'hub.db'}")
    monkeypatch.setattr(domain, "utc_now", lambda: now)
    _enroll(capsys, tmp_path, enrollment_template, installation)

    suppressed = _run(capsys, "suppress", "installation-alpha", "--minutes", "30")
    lifted = _run(capsys, "unsuppress", "installation-alpha")

    assert suppressed == {"suppressed": "installation", "until": "2026-10-05T03:30:00+00:00"}
    assert lifted == {"lifted": "installation"}
    assert main(["unsuppress", "installation-alpha"]) == 1
    assert main(["suppress", "installation-alpha", "--scope", "region"]) == 1
    assert "unknown suppression scope" in capsys.readouterr().err


def test_approval_needs_the_requesting_key_and_rejection_is_final(
    tmp_path: Path,
    enrollment_template: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(DATABASE_URL_ENV, f"sqlite+pysqlite:///{tmp_path / 'hub.db'}")
    request, key = tmp_path / "enrollment.json", tmp_path / "installation.pem"
    request.write_text(json.dumps(enrollment_template))
    _run(capsys, "migrate")
    _run(capsys, "dev-keygen", str(key))
    _run(capsys, "dev-enroll", str(request), "--key", str(key))
    approve = ["approve", "installation-alpha", "--approver", "alice"]

    assert main([*approve, "--installation-key-id", "installation-other"]) == 1
    assert capsys.readouterr().err.startswith("InstallationKeyMismatchError")
    rejected = _run(
        capsys, "reject", "installation-alpha", "--approver", "alice", "--reason", "unknown_key"
    )
    assert rejected == {"rejected": "installation-alpha"}
    assert _run(capsys, "show", "installation-alpha")["enrollment"] == "rejected"


def test_refused_request_exits_with_a_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv(DATABASE_URL_ENV, f"sqlite+pysqlite:///{tmp_path / 'hub.db'}")
    _run(capsys, "migrate")

    assert main(["show", "missing"]) == 1
    assert capsys.readouterr().err.startswith("UnknownInstallationError")


def test_missing_database_url_exits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(DATABASE_URL_ENV, raising=False)

    with pytest.raises(SystemExit, match=DATABASE_URL_ENV):
        main(["migrate"])
