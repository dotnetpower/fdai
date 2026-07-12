"""Unit tests for the MySQL query-load injector + DB-CPU probe.

The DB driver and subprocess are both faked, so these never touch a real
server - they lock the load-query shape, the start/stop lifecycle, and the
metric parse logic.
"""

from __future__ import annotations

import json
import threading

import pytest

import fdai.delivery.chaos.mysql_load as ml


class _FakeCursor:
    def __init__(self, sink: list[str], fired: threading.Event) -> None:
        self._sink = sink
        self._fired = fired

    def execute(self, sql: str) -> None:
        self._sink.append(sql)
        self._fired.set()

    def fetchall(self) -> list[object]:
        return []


class _FakeConn:
    def __init__(self, sink: list[str], fired: threading.Event) -> None:
        self._sink = sink
        self._fired = fired
        self.closed = False

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self._sink, self._fired)

    def close(self) -> None:
        self.closed = True


def test_fault_type() -> None:
    inj = ml.AzMysqlQueryLoadInjector(connect_factory=lambda: _FakeConn([], threading.Event()))
    assert inj.fault_type == "query_load"


def test_rejects_non_positive_workers() -> None:
    with pytest.raises(ValueError, match="concurrent_queries"):
        ml.AzMysqlQueryLoadInjector(
            connect_factory=lambda: _FakeConn([], threading.Event()), concurrent_queries=0
        )


async def test_inject_runs_benchmark_and_stop_joins() -> None:
    sink: list[str] = []
    fired = threading.Event()
    inj = ml.AzMysqlQueryLoadInjector(
        connect_factory=lambda: _FakeConn(sink, fired),
        concurrent_queries=2,
        iterations=1_000,
    )
    await inj.inject(target="db:orders", params={})
    assert fired.wait(timeout=5.0), "worker never issued a query"
    await inj.stop(target="db:orders")
    assert inj._threads == []  # all workers joined
    assert any("BENCHMARK(1000" in sql for sql in sink)  # iterations rendered into the query


async def test_param_override_sets_worker_count() -> None:
    fired = threading.Event()
    inj = ml.AzMysqlQueryLoadInjector(
        connect_factory=lambda: _FakeConn([], fired),
        concurrent_queries=1,
        iterations=1_000,
    )
    await inj.inject(target="db:orders", params={"concurrent_queries": "3"})
    started = len(inj._threads)
    await inj.stop(target="db:orders")
    assert started == 3


async def test_stop_without_inject_is_safe() -> None:
    inj = ml.AzMysqlQueryLoadInjector(connect_factory=lambda: _FakeConn([], threading.Event()))
    await inj.stop(target="db:orders")  # no threads yet - must not raise
    assert inj._threads == []


def _fake_run(values):  # type: ignore[no-untyped-def]
    async def runner(cmd, *, timeout=60.0, drop_azure_config_dir=False):  # type: ignore[no-untyped-def]
        return values

    return runner


async def test_db_cpu_probe_true_above_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ml, "_run", _fake_run((0, json.dumps([5.0, 42.0, 100.0]), "")))
    probe = ml.AzureMonitorDbCpuProbe(server_resource_id="/db/id", threshold_pct=40.0)
    assert await probe.observed(signal="db_cpu", targets=["db:orders"]) is True


async def test_db_cpu_probe_false_below_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ml, "_run", _fake_run((0, json.dumps([5.0, 12.0, 9.0]), "")))
    probe = ml.AzureMonitorDbCpuProbe(server_resource_id="/db/id", threshold_pct=40.0)
    assert await probe.observed(signal="db_cpu", targets=["db:orders"]) is False


async def test_db_cpu_probe_false_on_error_rc(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ml, "_run", _fake_run((1, "", "boom")))
    probe = ml.AzureMonitorDbCpuProbe(server_resource_id="/db/id", threshold_pct=40.0)
    assert await probe.observed(signal="db_cpu", targets=["db:orders"]) is False


async def test_db_cpu_probe_false_on_bad_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ml, "_run", _fake_run((0, "not-json", "")))
    probe = ml.AzureMonitorDbCpuProbe(server_resource_id="/db/id", threshold_pct=40.0)
    assert await probe.observed(signal="db_cpu", targets=["db:orders"]) is False
