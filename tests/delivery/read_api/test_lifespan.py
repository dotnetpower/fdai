from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from starlette.applications import Starlette

from fdai.delivery.read_api.app import lifespan
from fdai.shared.telemetry.correlation import current_correlation_id


async def test_latency_probe_binds_and_restores_system_correlation(monkeypatch: Any) -> None:
    observed: list[str | None] = []

    async def probe(
        target: object,
        *,
        label: str,
        interval_seconds: int,
    ) -> None:
        del target, label, interval_seconds
        observed.append(current_correlation_id())

    monkeypatch.setattr(lifespan.chat_registration, "periodic_latency_probe", probe)

    await lifespan._run_correlated_latency_probe(
        object(),
        label="CommandDeck narrator router",
        interval_seconds=30,
        correlation_id="read-api:narrator-latency-probe",
    )

    assert observed == ["read-api:narrator-latency-probe"]
    assert current_correlation_id() is None


async def test_web_search_readiness_runs_before_app_serves(monkeypatch: Any) -> None:
    events: list[str] = []

    class WebSearch:
        probe_interval_seconds = 300

        async def verify_availability(self) -> bool:
            events.append("readiness")
            return False

        def descriptor(self) -> dict[str, object]:
            return {"available": False}

    async def unexpected_probe(*args: Any, **kwargs: Any) -> None:
        del args, kwargs
        raise AssertionError("unavailable web search must not schedule latency probes")

    monkeypatch.setattr(lifespan.chat_registration, "periodic_latency_probe", unexpected_probe)
    config = SimpleNamespace(
        startup_callbacks=(),
        shutdown_callbacks=(),
        chat=None,
        chat_web_search=WebSearch(),
        chat_probe_interval_seconds=300,
    )
    app_lifespan = lifespan.build_lifespan(
        config=config,
        live_emitter=None,
        live_broadcaster=None,
        agent_emitter=None,
        agent_broadcaster=None,
        logger=SimpleNamespace(warning=lambda *args, **kwargs: None),
    )

    async with app_lifespan(Starlette()):
        events.append("serving")

    assert events == ["readiness", "serving"]
