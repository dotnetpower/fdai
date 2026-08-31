"""Coverage for the optional in-memory report cache."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast

import fdai.core.reporting.cache as cache_module
import pytest
from fdai.core.reporting.cache import InMemoryReportCache
from fdai.core.reporting.engine import ReportEngine
from fdai.core.reporting.models import RenderedReport


class _Engine:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def catalog(self) -> str:
        return "catalog"

    def widget_registry(self) -> str:
        return "widgets"

    def datasource_registry(self) -> str:
        return "datasources"

    def config(self) -> str:
        return "config"

    def health(self) -> dict[str, object]:
        return {"status": "ok"}

    async def render(
        self,
        report_id: str,
        *,
        variables: object = None,
    ) -> RenderedReport:
        self.calls.append((report_id, variables))
        now = datetime(2026, 8, 31, tzinfo=UTC)
        return RenderedReport(
            id=report_id,
            version="1.0.0",
            name=report_id,
            description="",
            generated_at=now,
            time_range=(now, now),
            variables=cast(Any, variables or {}),
            widgets=(),
        )


def _cache(engine: _Engine, **kwargs: object) -> InMemoryReportCache:
    return InMemoryReportCache(cast(ReportEngine, engine), **kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "kwargs",
    ({"ttl_seconds": 0}, {"max_entries": 0}),
)
def test_cache_rejects_unbounded_configuration(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        _cache(_Engine(), **kwargs)


async def test_cache_ttl_lru_delegates_and_invalidation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [1.0]
    monkeypatch.setattr(
        cache_module,
        "time",
        SimpleNamespace(monotonic=lambda: clock[0]),
    )
    engine = _Engine()
    cache = _cache(engine, ttl_seconds=0.5, max_entries=2)

    first = await cache.render("first", variables={"b": "2", "a": "1"})
    clock[0] = 1.1
    assert await cache.render("first", variables={"a": "1", "b": "2"}) is first
    clock[0] = 2.0
    refreshed = await cache.render("first", variables={"a": "1", "b": "2"})
    assert refreshed is not first
    clock[0] = 2.1
    await cache.render("second")
    clock[0] = 2.2
    await cache.render("third")
    assert cache.health()["cache"] == {
        "ttl_seconds": 0.5,
        "max_entries": 2,
        "size": 2,
    }
    assert cache.catalog() == "catalog"
    assert cache.widget_registry() == "widgets"
    assert cache.datasource_registry() == "datasources"
    assert cache.config() == "config"

    cache.invalidate("second")
    assert cache.health()["cache"]["size"] == 1  # type: ignore[index]
    cache.invalidate()
    assert cache.health()["cache"]["size"] == 0  # type: ignore[index]
