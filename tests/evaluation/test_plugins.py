"""Installed evaluation adapter discovery tests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from fdai_bench_sregym.plugin import SregymPlugin
from fdai_evaluation_sdk import EVALUATION_API_VERSION

from fdai.evaluation.plugins import (
    EvaluationPluginError,
    discover_evaluation_adapters,
    load_evaluation_adapter,
)


@dataclass(frozen=True)
class _EntryPoint:
    name: str
    factory: Any

    def load(self) -> Any:
        return self.factory


def test_discovers_adapters_in_deterministic_order() -> None:
    points = (
        _EntryPoint("sregym", lambda: object()),
        _EntryPoint("cybergym", lambda: object()),
    )

    assert discover_evaluation_adapters(
        entry_point_source=lambda: points  # type: ignore[arg-type]
    ) == ("cybergym", "sregym")


def test_loads_adapter_without_fdai_import_in_driver(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SREGYM_ARTIFACT_ID", "artifact-1")
    point = _EntryPoint("sregym", SregymPlugin)

    adapter = load_evaluation_adapter(
        "sregym",
        entry_point_source=lambda: (point,),  # type: ignore[arg-type]
    )

    assert adapter.adapter_id == "sregym"


def test_rejects_duplicate_mismatched_and_incompatible_plugins() -> None:
    duplicate = (_EntryPoint("sregym", SregymPlugin),) * 2
    with pytest.raises(EvaluationPluginError, match="duplicate"):
        discover_evaluation_adapters(
            entry_point_source=lambda: duplicate  # type: ignore[arg-type]
        )

    @dataclass(frozen=True)
    class _Plugin:
        plugin_id: str
        api_version: str = EVALUATION_API_VERSION

        def create_adapter(self):  # type: ignore[no-untyped-def]
            raise AssertionError("must not create mismatched plugin")

    with pytest.raises(EvaluationPluginError, match="does not match"):
        load_evaluation_adapter(
            "sregym",
            entry_point_source=lambda: (  # type: ignore[arg-type]
                _EntryPoint("sregym", lambda: _Plugin("other")),
            ),
        )

    with pytest.raises(EvaluationPluginError, match="uses API"):
        load_evaluation_adapter(
            "sregym",
            entry_point_source=lambda: (  # type: ignore[arg-type]
                _EntryPoint("sregym", lambda: _Plugin("sregym", "0.0")),
            ),
        )
