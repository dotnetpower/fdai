from __future__ import annotations

from pathlib import Path
from typing import Any

import fdai_operator_service.main as operator_main
import pytest
from fdai_operator_service.composition import _CompositeLifecycle
from fdai_operator_service.development_diagnostics import build_development_diagnostics

ROOT = Path(__file__).resolve().parents[3]
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
            ROOT / ".fdai" / "operator-rdt" / tmp_path.name[-8:]
        ),
        "FDAI_RUNTIME_SCOPE_RECEIPT_DIGEST": RECEIPT,
    }


def test_operator_diagnostics_are_disabled_without_explicit_activation() -> None:
    assert build_development_diagnostics({}) is None


def test_asgi_factory_binds_runtime_scope_receipt_for_direct_uvicorn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, str] = {}

    def build_application(environment: dict[str, str]) -> Any:
        captured.update(environment)
        return object()

    monkeypatch.setattr(operator_main, "build_application", build_application)
    source = {"FDAI_EXECUTION_VENUE": "local"}

    operator_main.create_app(source)

    assert source == {"FDAI_EXECUTION_VENUE": "local"}
    assert captured["FDAI_RUNTIME_SCOPE_RECEIPT_DIGEST"].startswith("sha256:")
    assert len(captured["FDAI_RUNTIME_SCOPE_RECEIPT_DIGEST"]) == 71


def test_operator_diagnostics_build_only_for_local_venue(tmp_path: Path) -> None:
    assert build_development_diagnostics(_environment(tmp_path)) is not None
    with pytest.raises(ValueError, match="local execution venue"):
        build_development_diagnostics(_environment(tmp_path, venue="deployed"))


async def test_composite_lifecycle_closes_in_reverse_start_order() -> None:
    events: list[str] = []

    class Lifecycle:
        def __init__(self, name: str) -> None:
            self.name = name

        async def start(self) -> None:
            events.append(f"start:{self.name}")

        async def aclose(self) -> None:
            events.append(f"close:{self.name}")

    lifecycle = _CompositeLifecycle((Lifecycle("runtime"), Lifecycle("diagnostics")))  # type: ignore[arg-type]
    await lifecycle.start()
    await lifecycle.aclose()
    assert events == [
        "start:runtime",
        "start:diagnostics",
        "close:diagnostics",
        "close:runtime",
    ]
