from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import fdai_operator_service.application as operator_application
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


def test_application_factory_appends_diagnostics_to_runtime_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Lifecycle:
        async def start(self) -> None:
            return None

        async def aclose(self) -> None:
            return None

    @dataclass(frozen=True)
    class Environment:
        values: Mapping[str, str]

    @dataclass(frozen=True)
    class Runtime:
        environment: Environment
        lifecycle: Any

        def create_app(self) -> Any:
            return self.lifecycle

    runtime_lifecycle = Lifecycle()
    diagnostics_lifecycle = Lifecycle()
    runtime = Runtime(Environment({}), runtime_lifecycle)

    class Composition:
        def build_runtime(self, environ: Mapping[str, str] | None = None) -> Runtime:
            del environ
            return runtime

    monkeypatch.setattr(
        operator_application,
        "build_development_diagnostics",
        lambda values: diagnostics_lifecycle,
    )

    lifecycle = operator_application.create_app(
        {},
        composition=cast(Any, Composition()),
    )

    assert isinstance(lifecycle, _CompositeLifecycle)
    assert lifecycle.services == (runtime_lifecycle, diagnostics_lifecycle)


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
