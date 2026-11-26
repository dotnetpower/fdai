"""The metering store builder mirrors to Phoenix only when the flag is on."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fdai.core.metering import InMemoryMeteringSink, ObservedMeteringStore
from fdai.delivery.azure.llm import model_trace
from fdai.runtime.providers import _build_metering_store


@pytest.fixture(autouse=True)
def _in_memory_metering(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    model_trace.clear_model_trace_observers()
    for name in (
        "FDAI_METERING_DSN",
        "FDAI_STATE_STORE_DSN",
        "FDAI_PHOENIX_TRACING_ENABLED",
        "APPLICATIONINSIGHTS_CONNECTION_STRING",
        "FDAI_APPINSIGHTS_LLM_TRACING_ENABLED",
        "FDAI_APPINSIGHTS_LLM_CAPTURE_CONTENT",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr("fdai.runtime.providers._require_durable_backend", lambda **_: None)
    yield
    model_trace.clear_model_trace_observers()


def test_default_store_is_unwrapped() -> None:
    assert isinstance(_build_metering_store(), InMemoryMeteringSink)


def test_enabled_flag_wraps_store_without_changing_the_primary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FDAI_PHOENIX_TRACING_ENABLED", "1")
    monkeypatch.setenv("FDAI_PHOENIX_OTLP_ENDPOINT", "http://127.0.0.1:4317")

    store = _build_metering_store()

    assert isinstance(store, ObservedMeteringStore)
    assert len(model_trace._OBSERVERS) == 1


def test_application_insights_connection_string_attaches_llm_trace_observer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "APPLICATIONINSIGHTS_CONNECTION_STRING",
        "InstrumentationKey=00000000-0000-0000-0000-000000000000",
    )

    store = _build_metering_store()

    assert isinstance(store, ObservedMeteringStore)
    assert len(model_trace._OBSERVERS) == 1
