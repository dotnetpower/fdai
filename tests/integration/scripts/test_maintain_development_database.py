"""Focused policy tests for local development database recreation."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_ROOT = Path(__file__).resolve().parents[3]
_PATH = _ROOT / "scripts/deployment/local/maintain-development-database.py"
_PREPARE = _ROOT / "scripts/deployment/local/prepare-console-state.sh"
_BROKER_RESET = _ROOT / "scripts/deployment/local/reset-development-broker.py"
_DEV_UP = _ROOT / "scripts/deployment/local/dev-up.sh"
_SPEC = importlib.util.spec_from_file_location("maintain_development_database", _PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)


@pytest.mark.parametrize("host", ("127.0.0.1", "localhost", "::1"))
def test_target_accepts_only_expected_loopback_database(host: str) -> None:
    rendered_host = f"[{host}]" if ":" in host else host
    target = _MODULE._target(f"postgresql://fdai:devonly@{rendered_host}:5432/fdai")

    assert target.database == "fdai"
    assert target.owner == "fdai"


@pytest.mark.parametrize(
    "database_url",
    (
        "postgresql://fdai:devonly@example.invalid:5432/fdai",
        "postgresql://fdai:devonly@127.0.0.1:5433/fdai",
        "postgresql://fdai:devonly@127.0.0.1:5432/other",
    ),
)
def test_target_rejects_non_runtime_database(database_url: str) -> None:
    with pytest.raises(ValueError, match="requires loopback port 5432 and database fdai"):
        _MODULE._target(database_url)


def test_max_bytes_defaults_to_two_gibibytes_and_rejects_unsafe_floor() -> None:
    assert _MODULE._max_bytes(None) == 2 * 1024 * 1024 * 1024

    with pytest.raises(ValueError, match="MUST be at least"):
        _MODULE._max_bytes(str(64 * 1024 * 1024 - 1))


@pytest.mark.parametrize("arguments", [[], ["--check"]])
def test_over_limit_never_recreates_without_explicit_permission(monkeypatch, capsys, arguments):
    statements = []

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_arguments):
            return False

        def execute(self, query, parameters=()):
            statements.append(str(query))
            assert query == "SELECT pg_database_size(%s)"
            return SimpleNamespace(fetchone=lambda: (3 * 1024 * 1024 * 1024,))

    monkeypatch.setattr(_MODULE.psycopg, "connect", lambda *_args, **_kwargs: Connection())
    monkeypatch.setenv("FDAI_DATABASE_URL", "postgresql://fdai@127.0.0.1:5432/fdai")
    monkeypatch.delenv("FDAI_LOCAL_DATABASE_RECREATE_MAX_BYTES", raising=False)
    monkeypatch.setattr(sys, "argv", [str(_PATH), *arguments])
    assert _MODULE.main() == 3
    assert statements == ["SELECT pg_database_size(%s)"]
    if not arguments:
        assert "existing data preserved" in capsys.readouterr().err


def test_recreation_requires_an_explicit_cli_mode():
    assert _MODULE._parser().parse_args([]).allow_recreate is False
    assert _MODULE._parser().parse_args(["--allow-recreate"]).allow_recreate is True
    with pytest.raises(SystemExit):
        _MODULE._parser().parse_args(["--check", "--allow-recreate"])


@pytest.mark.parametrize("active_connections", [0, 1])
def test_explicit_recreation_keeps_active_connection_guard(monkeypatch, active_connections):
    statements = []

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_arguments):
            return False

        def execute(self, query, parameters=()):
            rendered = query if isinstance(query, str) else query.as_string()
            statements.append(rendered)
            result = (
                3 * 1024 * 1024 * 1024 if "pg_database_size" in rendered else active_connections
            )
            return SimpleNamespace(fetchone=lambda: (result,))

    monkeypatch.setattr(_MODULE.psycopg, "connect", lambda *_args, **_kwargs: Connection())
    monkeypatch.setenv("FDAI_DATABASE_URL", "postgresql://fdai@127.0.0.1:5432/fdai")
    monkeypatch.delenv("FDAI_LOCAL_DATABASE_RECREATE_MAX_BYTES", raising=False)
    monkeypatch.setattr(sys, "argv", [str(_PATH), "--allow-recreate"])
    if active_connections:
        with pytest.raises(RuntimeError, match="stop local services"):
            _MODULE.main()
        assert not any(statement.startswith("DROP") for statement in statements)
    else:
        assert _MODULE.main() == 0
        assert statements[-2:] == ['DROP DATABASE "fdai"', 'CREATE DATABASE "fdai" OWNER "fdai"']


def test_console_state_preparation_checks_and_applies_database_maintenance() -> None:
    source = _PREPARE.read_text(encoding="utf-8")

    assert source.count("maintain-development-database.py") == 3
    assert "maintenance_args=()" in source
    assert "maintenance_args+=(--allow-recreate)" in source
    assert '"${maintenance_args[@]}"' in source
    assert 'maintain-development-database.py" --check' in source
    assert '--recreated-marker "$database_recreated_marker"' in source
    assert '--preserved-state "$preserved_state"' in source
    assert '--restore-preserved-state "$preserved_state"' in source
    assert 'reset-development-broker.py"' in source
    assert source.index('reset-development-broker.py"') < source.index(
        '--restore-preserved-state "$preserved_state"'
    )
    assert source.index('done\n\nif [[ -f "$database_recreated_marker" ]]') < source.index(
        '--restore-preserved-state "$preserved_state"'
    )
    assert source.index('--restore-preserved-state "$preserved_state"') < source.index(
        'rm -f "$preserved_state" "$database_recreated_marker"'
    )


def test_recreated_marker_is_private(tmp_path: Path) -> None:
    marker = tmp_path / "state" / "recreated"

    _MODULE._write_recreated_marker(marker)

    assert marker.read_text(encoding="ascii") == "database_recreated\n"
    assert marker.stat().st_mode & 0o777 == 0o600


def test_preserved_repository_state_is_private_and_round_trips(tmp_path: Path) -> None:
    preserved = tmp_path / "state" / "preserved.json"
    registration = {
        "key": "runtime:code-security-repository:example-app",
        "value": {
            "kind": "code-security-repository",
            "schema_version": "1.0.0",
            "repository_alias": "example-app",
            "provider": "github",
            "location": "example/app",
            "default_ref": "HEAD",
            "exposure": "unknown",
            "enabled": True,
            "registered_at": "2026-10-14T00:00:00+00:00",
            "registered_by": "owner@example.com",
            "revision": 1,
        },
    }

    _MODULE._write_preserved_state(preserved, [registration])

    assert preserved.stat().st_mode & 0o777 == 0o600
    assert _MODULE._read_preserved_state(preserved) == [registration]


def test_preserved_repository_state_rejects_unknown_envelope(tmp_path: Path) -> None:
    preserved = tmp_path / "preserved.json"
    preserved.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "code_security_repositories": [],
                "unexpected": True,
            }
        ),
        encoding="utf-8",
    )
    preserved.chmod(0o600)

    with pytest.raises(ValueError, match="invalid envelope"):
        _MODULE._read_preserved_state(preserved)


@pytest.mark.parametrize("value", (None, "not-a-record", []))
def test_preserved_repository_state_rejects_non_object_record(
    tmp_path: Path, value: object
) -> None:
    preserved = tmp_path / "preserved.json"
    preserved.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "code_security_repositories": [
                    {"key": "runtime:code-security-repository:example-app", "value": value}
                ],
            }
        ),
        encoding="utf-8",
    )
    preserved.chmod(0o600)

    with pytest.raises(ValueError, match="malformed repository"):
        _MODULE._read_preserved_state(preserved)


def test_local_broker_defaults_are_bounded() -> None:
    source = _DEV_UP.read_text(encoding="utf-8")

    assert "rpk cluster config set log_retention_ms 86400000" in source
    assert "rpk cluster config set retention_bytes 268435456" in source
    assert "rpk cluster config set group_offset_retention_sec 86400" in source
    assert "rpk cluster config set group_offset_retention_check_ms 60000" in source
