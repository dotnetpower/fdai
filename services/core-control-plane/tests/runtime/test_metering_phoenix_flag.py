"""The metering store builder mirrors to Phoenix only when the flag is on."""

from __future__ import annotations

import pytest
from fdai.core.metering import InMemoryMeteringSink, ObservedMeteringStore
from fdai.runtime.providers import _build_metering_store


@pytest.fixture(autouse=True)
def _in_memory_metering(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("FDAI_METERING_DSN", "FDAI_STATE_STORE_DSN", "FDAI_PHOENIX_TRACING_ENABLED"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr("fdai.runtime.providers._require_durable_backend", lambda **_: None)


def test_default_store_is_unwrapped() -> None:
    assert isinstance(_build_metering_store(), InMemoryMeteringSink)


def test_enabled_flag_wraps_store_without_changing_the_primary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FDAI_PHOENIX_TRACING_ENABLED", "1")
    monkeypatch.setenv("FDAI_PHOENIX_OTLP_ENDPOINT", "http://127.0.0.1:4317")

    store = _build_metering_store()

    assert isinstance(store, ObservedMeteringStore)
