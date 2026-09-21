"""Focused policy tests for local development database recreation."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

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


def test_max_bytes_defaults_to_one_gibibyte_and_rejects_unsafe_floor() -> None:
    assert _MODULE._max_bytes(None) == 1024 * 1024 * 1024

    with pytest.raises(ValueError, match="MUST be at least"):
        _MODULE._max_bytes(str(64 * 1024 * 1024 - 1))


def test_console_state_preparation_checks_and_applies_database_maintenance() -> None:
    source = _PREPARE.read_text(encoding="utf-8")

    assert source.count("maintain-development-database.py") == 2
    assert 'maintain-development-database.py" --check' in source
    assert '--recreated-marker "$database_recreated_marker"' in source
    assert 'reset-development-broker.py"' in source
    assert source.index('reset-development-broker.py"') < source.index(
        'rm -f "$database_recreated_marker"'
    )


def test_recreated_marker_is_private(tmp_path: Path) -> None:
    marker = tmp_path / "state" / "recreated"

    _MODULE._write_recreated_marker(marker)

    assert marker.read_text(encoding="ascii") == "database_recreated\n"
    assert marker.stat().st_mode & 0o777 == 0o600


def test_local_broker_defaults_are_bounded() -> None:
    source = _DEV_UP.read_text(encoding="utf-8")

    assert "rpk cluster config set log_retention_ms 86400000" in source
    assert "rpk cluster config set retention_bytes 268435456" in source
    assert "rpk cluster config set group_offset_retention_sec 86400" in source
    assert "rpk cluster config set group_offset_retention_check_ms 60000" in source
