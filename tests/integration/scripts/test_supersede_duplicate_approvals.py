"""Loopback destination validation for the duplicate approval cleanup tool."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPT = (
    Path(__file__).resolve().parents[3]
    / "scripts"
    / "deployment"
    / "local"
    / "supersede-duplicate-approvals.py"
)
_SPEC = importlib.util.spec_from_file_location("supersede_duplicate_approvals", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)


@pytest.mark.parametrize("hostaddr", ("127.0.0.1", "::1", "127.0.0.1,::1"))
def test_dsn_accepts_only_loopback_hostaddr_entries(
    monkeypatch: pytest.MonkeyPatch,
    hostaddr: str,
) -> None:
    dsn = f"host=127.0.0.1 hostaddr={hostaddr} port=5432 dbname=fdai"
    monkeypatch.setenv("FDAI_STATE_STORE_DSN", dsn)

    assert _MODULE._dsn() == dsn


@pytest.mark.parametrize(
    "hostaddr",
    (
        "203.0.113.10",
        "127.0.0.1,203.0.113.10",
        "localhost",
        "127.0.0.1,",
    ),
)
def test_dsn_rejects_non_loopback_or_invalid_hostaddr_entries(
    monkeypatch: pytest.MonkeyPatch,
    hostaddr: str,
) -> None:
    monkeypatch.setenv(
        "FDAI_STATE_STORE_DSN",
        f"host=127.0.0.1 hostaddr={hostaddr} port=5432 dbname=fdai",
    )

    with pytest.raises(SystemExit, match="requires loopback port 5432 and database fdai"):
        _MODULE._dsn()
