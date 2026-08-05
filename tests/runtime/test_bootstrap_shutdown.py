from __future__ import annotations

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
        runtime_state_publisher=_Resource("publisher", calls),
        auxiliary_bus=_Resource("auxiliary", calls, fail=True),
        bus=_Resource("bus", calls, fail=True),
        http_client=_Resource("http", calls, fail=True),
    )

    assert calls == ["health", "pantheon", "publisher", "auxiliary", "bus", "http"]
