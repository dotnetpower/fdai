from __future__ import annotations

from pathlib import Path

import pytest
from fdai.runtime.development_diagnostics import build_development_diagnostics

ROOT = Path(__file__).resolve().parents[4]
RECEIPT = "sha256:" + ("d" * 64)


def _environment(tmp_path: Path, *, venue: str = "local") -> dict[str, str]:
    return {
        "FDAI_DEVELOPMENT_DIAGNOSTICS": "1",
        "FDAI_EXECUTION_VENUE": venue,
        "FDAI_DEVELOPMENT_DIAGNOSTICS_SOURCE_REVISION": "a" * 40,
        "FDAI_DEVELOPMENT_DIAGNOSTICS_INPUT_DIGEST": "b" * 64,
        "FDAI_DEVELOPMENT_DIAGNOSTICS_WORKTREE_DIGEST": "c" * 64,
        "FDAI_DEVELOPMENT_DIAGNOSTICS_SOURCE_ROOT": str(ROOT),
        "FDAI_DEVELOPMENT_DIAGNOSTICS_SOCKET_DIR": str(
            ROOT / ".fdai" / "core-rdt" / tmp_path.name[-8:]
        ),
    }


def test_core_diagnostics_are_disabled_without_explicit_activation() -> None:
    assert build_development_diagnostics({}, runtime_scope_receipt_digest=None) is None


def test_core_diagnostics_require_the_runtime_scope_receipt(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="runtime scope receipt"):
        build_development_diagnostics(
            _environment(tmp_path),
            runtime_scope_receipt_digest=None,
        )


def test_core_diagnostics_build_only_for_local_venue(tmp_path: Path) -> None:
    server = build_development_diagnostics(
        _environment(tmp_path),
        runtime_scope_receipt_digest=RECEIPT,
    )
    assert server is not None
    with pytest.raises(ValueError, match="local execution venue"):
        build_development_diagnostics(
            _environment(tmp_path, venue="deployed"),
            runtime_scope_receipt_digest=RECEIPT,
        )
