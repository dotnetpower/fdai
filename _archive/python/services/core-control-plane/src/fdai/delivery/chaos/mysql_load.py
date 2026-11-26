"""MySQL query-load injector + DB-CPU probe for the enforce harness (S8).

Drives sustained server-side CPU on a MySQL Flexible Server by running
concurrent ``BENCHMARK()`` queries, then observes the ``cpu_percent`` metric
through Azure Monitor. Same discipline as
:mod:`fdai.delivery.chaos.live_injectors`: never imported by ``core/``.

The DB driver is **injected** (``connect_factory``) rather than imported, so
this module adds no runtime dependency and stays fully mockable - a fork (or
a test) supplies ``pymysql.connect`` (or any DB-API ``connect``) and its own
connection parameters.
"""

from __future__ import annotations

import contextlib
import json
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Final, Protocol

from fdai.delivery.chaos.live_injectors import _run

_DEFAULT_ITERATIONS: Final[int] = 20_000_000
_LOAD_QUERY: Final[str] = "SELECT BENCHMARK(%d, SHA2(RAND(), 512))"


class _Connection(Protocol):
    """Minimal DB-API surface the load worker needs."""

    def cursor(self) -> Any: ...  # noqa: D102

    def close(self) -> None: ...  # noqa: D102


ConnectFactory = Callable[[], _Connection]


class AzMysqlQueryLoadInjector:
    """Sustain MySQL CPU pressure with concurrent BENCHMARK queries.

    ``inject`` starts ``concurrent_queries`` worker threads that loop heavy
    server-side ``BENCHMARK`` calls until ``stop`` sets the shared event
    (rollback = drop the load, the server recovers on its own).
    """

    fault_type = "query_load"

    def __init__(
        self,
        *,
        connect_factory: ConnectFactory,
        concurrent_queries: int = 4,
        iterations: int = _DEFAULT_ITERATIONS,
        join_timeout_seconds: float = 10.0,
    ) -> None:
        if concurrent_queries < 1:
            raise ValueError("concurrent_queries MUST be >= 1")
        self._connect = connect_factory
        self._default_workers = concurrent_queries
        self._iterations = iterations
        self._join_timeout = join_timeout_seconds
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []

    def _worker(self) -> None:
        while not self._stop.is_set():
            try:
                conn = self._connect()
            except Exception:  # noqa: BLE001 - transient connect failure, retry unless stopping
                if self._stop.wait(0.5):
                    return
                continue
            try:
                with contextlib.suppress(Exception):
                    cur = conn.cursor()
                    cur.execute(_LOAD_QUERY % self._iterations)
                    cur.fetchall()
            finally:
                with contextlib.suppress(Exception):
                    conn.close()

    async def inject(self, *, target: str, params: Mapping[str, str]) -> None:
        workers = int(params.get("concurrent_queries", self._default_workers))
        self._stop.clear()
        self._threads = [
            threading.Thread(target=self._worker, name=f"mysql-load-{i}", daemon=True)
            for i in range(workers)
        ]
        for thread in self._threads:
            thread.start()

    async def stop(self, *, target: str) -> None:
        self._stop.set()
        deadline = time.monotonic() + self._join_timeout
        for thread in self._threads:
            remaining = max(0.0, deadline - time.monotonic())
            thread.join(timeout=remaining)
        self._threads = []


class AzureMonitorDbCpuProbe:
    """Observe db_cpu: MySQL ``cpu_percent`` rose above a threshold."""

    def __init__(
        self,
        *,
        server_resource_id: str,
        threshold_pct: float = 40.0,
        az: str = "az",
    ) -> None:
        self._resource_id = server_resource_id
        self._threshold = threshold_pct
        self._az = az

    async def observed(self, *, signal: str, targets: Sequence[str]) -> bool:
        rc, out, _err = await _run(
            [
                self._az,
                "monitor",
                "metrics",
                "list",
                "--resource",
                self._resource_id,
                "--metric",
                "cpu_percent",
                "--interval",
                "PT1M",
                "--aggregation",
                "Maximum",
                "--query",
                "value[0].timeseries[0].data[].maximum",
                "-o",
                "json",
            ],
            timeout=90.0,
            drop_azure_config_dir=True,
        )
        if rc != 0:
            return False
        try:
            values = [v for v in json.loads(out) if isinstance(v, (int, float))]
        except json.JSONDecodeError:
            return False
        return any(v >= self._threshold for v in values)


__all__ = ["AzMysqlQueryLoadInjector", "AzureMonitorDbCpuProbe"]
