"""Tests for SREGym plugin construction."""

from __future__ import annotations

import pytest
from fdai_evaluation_sdk import EVALUATION_API_VERSION

from fdai_bench_sregym import create_plugin


def test_plugin_requires_harness_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SREGYM_ARTIFACT_ID", raising=False)

    with pytest.raises(RuntimeError, match="SREGYM_ARTIFACT_ID"):
        create_plugin().create_adapter()


def test_plugin_builds_generic_bindings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SREGYM_ARTIFACT_ID", "attempt-1")
    monkeypatch.setenv("API_HOSTNAME", "0.0.0.0")
    monkeypatch.setenv("API_PORT", "8000")

    plugin = create_plugin()
    adapter = plugin.create_adapter()

    assert plugin.api_version == EVALUATION_API_VERSION
    assert adapter.adapter_id == "sregym"
