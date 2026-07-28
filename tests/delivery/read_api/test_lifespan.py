from __future__ import annotations

from typing import Any

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
