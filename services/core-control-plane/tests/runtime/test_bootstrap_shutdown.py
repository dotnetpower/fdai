from __future__ import annotations

from fdai.runtime.bootstrap_messaging import MessagingRuntime
from fdai.runtime.bootstrap_pantheon import PantheonInitializationResult
from fdai.runtime.bootstrap_resources import RuntimeResources
from fdai.runtime.bootstrap_shutdown import close_runtime_resources


class _Resource:
    def __init__(self, name: str, calls: list[str], *, fail: bool = False) -> None:
        self._name = name
        self._calls = calls
        self._fail = fail

    async def _record(self) -> None:
        self._calls.append(self._name)
        if self._fail:
            raise RuntimeError(self._name)

    async def close(self) -> None:
        await self._record()

    async def stop(self) -> None:
        await self._record()

    async def aclose(self) -> None:
        await self._record()


async def test_close_runtime_resources_preserves_order_after_bounded_failures() -> None:
    calls: list[str] = []

    await close_runtime_resources(
        health_server=_Resource("health", calls, fail=True),
        pantheon_runtime=_Resource("pantheon", calls, fail=True),
        runtime_state_publisher=_Resource("publisher", calls, fail=True),
        diagnostic_bus=_Resource("diagnostic", calls, fail=True),
        auxiliary_bus=_Resource("auxiliary", calls, fail=True),
        bus=_Resource("bus", calls, fail=True),
        http_client=_Resource("http", calls, fail=True),
    )

    assert calls == [
        "health",
        "pantheon",
        "publisher",
        "diagnostic",
        "auxiliary",
        "bus",
        "http",
    ]


async def test_runtime_resources_stops_isolated_executor_before_shared_resources() -> None:
    calls: list[str] = []
    messaging = MessagingRuntime(
        bus=_Resource("bus", calls),  # type: ignore[arg-type]
        auxiliary_bus=_Resource("auxiliary", calls),  # type: ignore[arg-type]
        operational_bus=_Resource("operational", calls),  # type: ignore[arg-type]
        stage_publisher=_Resource("stage", calls),  # type: ignore[arg-type]
        diagnostic_bus=_Resource("diagnostic", calls),  # type: ignore[arg-type]
    )
    resources = RuntimeResources(
        health_server=_Resource("health", calls),  # type: ignore[arg-type]
        http_client=_Resource("http", calls),  # type: ignore[arg-type]
        messaging=messaging,
        isolated_executor_client=_Resource("isolated", calls),
        pantheon=PantheonInitializationResult(
            runtime=_Resource("pantheon", calls),  # type: ignore[arg-type]
            runtime_state_publisher=_Resource("publisher", calls),  # type: ignore[arg-type]
        ),
    )

    await resources.close()

    assert calls == [
        "isolated",
        "health",
        "pantheon",
        "publisher",
        "diagnostic",
        "auxiliary",
        "bus",
        "http",
    ]
