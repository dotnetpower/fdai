"""Read-API composition group for durable busy-input arbitration."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from fdai.core.conversation import BusyInputCoordinator
from fdai.delivery.persistence import PostgresBusyInputStore, PostgresBusyInputStoreConfig

BUSY_INPUT_METRIC_NAMES = (
    "queued",
    "interrupting",
    "steered",
    "rejected",
    "duplicate",
    "overflow",
    "expiry",
    "steer_fallback",
    "race_recovery",
)


class BusyInputRuntimeMetrics:
    """Small process-local counter set for busy-input dispositions and recovery paths."""

    def __init__(self) -> None:
        self._counts: Counter[str] = Counter(dict.fromkeys(BUSY_INPUT_METRIC_NAMES, 0))

    def increment(self, name: str) -> None:
        self._counts[name] += 1

    def snapshot(self) -> dict[str, int]:
        return dict(self._counts)


@dataclass(frozen=True, slots=True)
class BusyInputRuntime:
    coordinator: BusyInputCoordinator
    metrics: BusyInputRuntimeMetrics


def build_postgres_busy_input_runtime(
    *,
    dsn: str,
    statement_timeout_ms: int,
    connect_timeout_s: int,
) -> BusyInputRuntime:
    metrics = BusyInputRuntimeMetrics()
    store = PostgresBusyInputStore(
        config=PostgresBusyInputStoreConfig(
            dsn=dsn,
            statement_timeout_ms=statement_timeout_ms,
            connect_timeout_s=connect_timeout_s,
        )
    )
    return BusyInputRuntime(
        coordinator=BusyInputCoordinator(store=store, metrics=metrics),
        metrics=metrics,
    )


__all__ = [
    "BUSY_INPUT_METRIC_NAMES",
    "BusyInputRuntime",
    "BusyInputRuntimeMetrics",
    "build_postgres_busy_input_runtime",
]
