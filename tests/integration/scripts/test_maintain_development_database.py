"""Focused policy tests for local development database recreation."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]
_PATH = _ROOT / "scripts/deployment/local/maintain-development-database.py"
_PREPARE = _ROOT / "scripts/deployment/local/prepare-console-state.sh"
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
        _MODULE._max_bytes(str(256 * 1024 * 1024 - 1))


def test_console_state_preparation_checks_and_applies_database_maintenance() -> None:
    source = _PREPARE.read_text(encoding="utf-8")

    assert source.count("maintain-development-database.py") == 2
    assert 'maintain-development-database.py" --check' in source
