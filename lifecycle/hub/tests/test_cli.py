from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from base64 import b64encode
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fdai_deployment_cli.lifecycle_plan import SuppressionWindow

from fdai_lifecycle_hub import cli, domain, schemas
from fdai_lifecycle_hub.catalog import load_catalog
from fdai_lifecycle_hub.cli import DATABASE_URL_ENV, main
from fdai_lifecycle_hub.domain import Installation
from fdai_lifecycle_hub.schemas import entity_settings_json, ownership_json, reported_state_json
from fdai_lifecycle_hub.store import HubStore


@pytest.mark.parametrize(
    "configuration", ["", "invalid", '{"kind":"target"}', '{"kind":"release"}']
)
def test_remote_cli_rejects_unauthenticated_serve(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    configuration: str,
) -> None:
    def forbidden(*args: object) -> int:
        pytest.fail("Remote local-server handler must never be dispatched")

    monkeypatch.setenv("FDAI_HUB_REMOTE_CONFIG", configuration)
    monkeypatch.setattr(cli, "_serve", forbidden)
    assert main(["serve"]) == 1
    output = capsys.readouterr()
    assert "fdai-hub-remote serve" in output.err
    assert output.out == ""


def test_local_cli_migrates_without_azure_dependencies(tmp_path: Path) -> None:
    environment = os.environ.copy()
    environment.pop("FDAI_HUB_REMOTE_CONFIG", None)
    environment[DATABASE_URL_ENV] = f"sqlite:///{tmp_path / 'local.sqlite'}"
    environment["PYTHONPATH"] = os.pathsep.join(path for path in sys.path if path)
    script = """
import sys

class DenyAzure:
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "azure" or fullname.startswith("azure."):
            raise ModuleNotFoundError("Azure dependencies are unavailable")

sys.meta_path.insert(0, DenyAzure())
from fdai_lifecycle_hub.cli import main
raise SystemExit(main(["migrate"]))
"""
    result = subprocess.run(  # noqa: S603 - fixed interpreter and local import-isolation probe.
        [sys.executable, "-c", script],
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"schema": "created"}


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
        _run(
            capsys,
            "record-ownership",
            installation_id,
            entity.entity_id,
            str(evidence),
            "--operator",
            "bob",
        )
        _run(
            capsys, "manage", installation_id, entity.entity_id, str(settings), "--operator", "bob"
        )


def test_sign_enrollment_writes_only_the_upload_file_and_never_overwrites(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    enrollment_template: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(DATABASE_URL_ENV, f"sqlite+pysqlite:///{tmp_path / 'hub.db'}")
    out_dir = tmp_path / "out"
    out_dir.mkdir(mode=0o700)
    request, key, out = tmp_path / "request.json", tmp_path / "installation.pem", out_dir / "s.json"
    request.write_text(json.dumps(enrollment_template))
    _run(capsys, "migrate")
    _run(capsys, "dev-keygen", str(key))
    receipt = _run(capsys, "sign-enrollment", str(request), "--key", str(key), "--out", str(out))
    assert receipt["installation_id"] == enrollment_template["installation_id"]
    assert stat.S_IMODE(out.stat().st_mode) == 0o600
    uploaded = json.loads(out.read_text())
    assert set(uploaded) == {"signed_payload", "proof"}
    assert "PRIVATE KEY" not in out.read_text()
    pending = _run(capsys, "submit-enrollment", str(out))
    assert pending["installation_key_id"] == receipt["installation_key_id"]
    assert main(["sign-enrollment", str(request), "--key", str(key), "--out", str(out)]) == 1


def test_signed_enrollment_can_be_submitted_without_private_key_handoff(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    enrollment_template: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(DATABASE_URL_ENV, f"sqlite+pysqlite:///{tmp_path / 'hub.db'}")
    _run(capsys, "migrate")
    key = Ed25519PrivateKey.generate()
    request = schemas.sign_enrollment(enrollment_template, key, datetime.now(UTC))
    signed = schemas.SignedEnrollment.model_validate(
        {
            "signed_payload": b64encode(request.signed_payload).decode("ascii"),
            "proof": b64encode(request.proof).decode("ascii"),
        }
    )
    path = tmp_path / "signed-enrollment.json"
    path.write_text(signed.model_dump_json(), encoding="utf-8")

    pending = _run(capsys, "submit-enrollment", str(path))

    assert pending["pending"] == request.installation.installation_id
    assert pending["installation_key_id"] == request.installation_key_id


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


def test_show_lists_only_suppressions_active_right_now(
    tmp_path: Path,
    enrollment_template: dict[str, Any],
    installation: Installation,
    now: datetime,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A future-dated or expired suppression doesn't appear, only one whose window covers now."""

    database_url = f"sqlite+pysqlite:///{tmp_path / 'hub.db'}"
    monkeypatch.setenv(DATABASE_URL_ENV, database_url)
    monkeypatch.setattr(domain, "utc_now", lambda: now)
    _enroll(capsys, tmp_path, enrollment_template, installation)
    store = HubStore.connect(database_url)
    active = SuppressionWindow("entity:core", now - timedelta(minutes=1), now + timedelta(hours=1))
    future = SuppressionWindow("entity:console", now + timedelta(hours=1), now + timedelta(hours=2))
    store.add_suppression("installation-alpha", active, now=now)
    store.add_suppression("installation-alpha", future, now=now)

    shown = _run(capsys, "show", "installation-alpha")

    assert [s["scope"] for s in shown["suppressions"]] == ["entity:core"]


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
