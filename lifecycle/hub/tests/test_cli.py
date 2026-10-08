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
from fdai_lifecycle_hub.schemas import installation_json, reported_state_json


def _run(capsys: pytest.CaptureFixture[str], *argv: str) -> dict[str, Any]:
    assert main(list(argv)) == 0
    output: dict[str, Any] = json.loads(capsys.readouterr().out)
    return output


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


def test_register_recompute_show_flow(
    tmp_path: Path,
    catalog_dir: Path,
    installation: Installation,
    now: datetime,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(DATABASE_URL_ENV, f"sqlite+pysqlite:///{tmp_path / 'hub.db'}")
    monkeypatch.setattr(domain, "utc_now", lambda: now)
    spec = tmp_path / "installation.json"
    spec.write_bytes(installation_json.dump_json(installation))
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

    _run(capsys, "migrate")
    assert _run(capsys, "register", str(spec)) == {"registered": "installation-alpha"}
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


def test_record_state_then_recompute_reports_up_to_date(
    tmp_path: Path,
    catalog_dir: Path,
    installation: Installation,
    now: datetime,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(DATABASE_URL_ENV, f"sqlite+pysqlite:///{tmp_path / 'hub.db'}")
    monkeypatch.setattr(domain, "utc_now", lambda: now)
    spec = tmp_path / "installation.json"
    spec.write_bytes(installation_json.dump_json(installation))
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
    _run(capsys, "migrate")
    _run(capsys, "register", str(spec))

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
    installation: Installation,
    now: datetime,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(DATABASE_URL_ENV, f"sqlite+pysqlite:///{tmp_path / 'hub.db'}")
    monkeypatch.setattr(domain, "utc_now", lambda: now)
    spec = tmp_path / "installation.json"
    spec.write_bytes(installation_json.dump_json(installation))
    _run(capsys, "migrate")
    _run(capsys, "register", str(spec))

    suppressed = _run(capsys, "suppress", "installation-alpha", "--minutes", "30")
    lifted = _run(capsys, "unsuppress", "installation-alpha")

    assert suppressed == {"suppressed": "installation", "until": "2026-10-05T03:30:00+00:00"}
    assert lifted == {"lifted": "installation"}
    assert main(["unsuppress", "installation-alpha"]) == 1
    assert main(["suppress", "installation-alpha", "--scope", "region"]) == 1
    assert "unknown suppression scope" in capsys.readouterr().err


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
