from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_REFRESH = (_ROOT / ".github/workflows/refresh-catalogs.yml").read_text(encoding="utf-8")
_REQUEST = (_ROOT / ".github/workflows/request-catalog-refresh.yml").read_text(encoding="utf-8")


def test_catalog_refresh_is_exact_approved_and_postgresql_verified() -> None:
    assert "Verify protected workflow source" in _REFRESH
    assert _REFRESH.index("Install pinned GitHub CLI") < _REFRESH.index("Verify required CI")
    assert "Verify required CI" in _REFRESH
    assert "Verify protected environment approval policy" in _REFRESH
    assert "Bind exact Core catalog image" in _REFRESH
    assert "refresh-authoritative-catalogs.sh infra" in _REFRESH


def test_catalog_refresh_request_is_bot_owned() -> None:
    assert "actions: write" in _REQUEST
    assert "Verify protected workflow source" in _REQUEST
    assert "Verify required CI" in _REQUEST
    assert "actions/workflows/refresh-catalogs.yml/dispatches" in _REQUEST
