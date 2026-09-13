"""Local DB export boundary checks. These tests use fake credentials and no database connection."""

# ruff: noqa: S101
import json
import stat
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import local_ontology_db  # noqa: E402
from export_database_map import safe_state, write_private_snapshot  # noqa: E402
from local_ontology_db import local_connection_parameters  # noqa: E402


def test_only_loopback_application_database_is_accepted(tmp_path: Path, monkeypatch) -> None:
    for key in ("PGSERVICE", "PGSERVICEFILE", "PGHOSTADDR"):
        monkeypatch.delenv(key, raising=False)
    env = tmp_path / "runtime.env"
    env.write_text("FDAI_STATE_STORE_DSN='postgresql://fixture:fixture@127.0.0.1:5432/fixture'\n")
    params = local_connection_parameters(env)
    assert params["host"] == "127.0.0.1"
    env.write_text(
        "FDAI_STATE_STORE_DSN='postgresql://fixture:fixture@example.invalid:5432/fixture'\n"
    )
    with pytest.raises(ValueError, match="loopback"):
        local_connection_parameters(env)
    env.write_text("FDAI_STATE_STORE_DSN='postgresql://fixture:fixture@127.0.0.1:5433/fixture'\n")
    with pytest.raises(ValueError, match="standard local"):
        local_connection_parameters(env)


def test_ambient_route_override_is_rejected(tmp_path: Path, monkeypatch) -> None:
    env = tmp_path / "runtime.env"
    env.write_text("FDAI_STATE_STORE_DSN='postgresql://fixture:fixture@localhost:5432/fixture'\n")
    monkeypatch.setenv("PGHOSTADDR", "192.0.2.1")
    with pytest.raises(ValueError, match="Ambient"):
        local_connection_parameters(env)


def test_private_output_modes_and_state_allowlist(tmp_path: Path) -> None:
    directory = tmp_path / "private"
    path = write_private_snapshot({"counts": {"instances": 2}}, directory)
    assert json.loads(path.read_text()) == {"counts": {"instances": 2}}
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    assert safe_state("Running") == "Running"
    assert safe_state("arbitrary private content") is None
    assert safe_state({"secret": "fixture"}) is None


def test_connection_is_readonly_before_any_application_query(monkeypatch) -> None:
    class Connection:
        def __init__(self) -> None:
            self.statements = []
            self.closed = False

        def execute(self, statement):
            self.statements.append(statement)
            return self

        def fetchone(self):
            return {"transaction_read_only": "on"}

        def close(self):
            self.closed = True

    connection = Connection()
    monkeypatch.setattr(local_ontology_db, "local_connection_parameters", lambda _path: {})
    monkeypatch.setattr(local_ontology_db.psycopg, "connect", lambda **_params: connection)
    assert local_ontology_db.connect_readonly() is connection
    assert connection.statements[0] == "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
    assert connection.statements[-1] == "SHOW transaction_read_only"
