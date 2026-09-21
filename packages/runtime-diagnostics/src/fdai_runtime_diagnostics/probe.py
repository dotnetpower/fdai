"""Bounded standard-library CPU, Python heap, and process capture."""

from __future__ import annotations

import asyncio
import cProfile
import gc
import pstats
import resource
import threading
import time
import tracemalloc
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from fdai_runtime_diagnostics.config import DevelopmentDiagnosticsConfig
from fdai_runtime_diagnostics.metrics import stage_snapshot
from fdai_runtime_diagnostics.models import (
    CpuProfileEntry,
    DevelopmentProfilePacket,
    HeapProfileEntry,
    ProcessSnapshot,
)

_MAX_ROWS = 50


class RuntimeProbe:
    """Capture one process without retaining request data or heap objects."""

    def __init__(self, config: DevelopmentDiagnosticsConfig) -> None:
        self._config = config
        self._capture_lock = asyncio.Lock()

    @property
    def capture_active(self) -> bool:
        return self._capture_lock.locked()

    async def capture(
        self,
        *,
        duration_ms: int = 0,
        cpu: bool = False,
        heap: bool = False,
    ) -> DevelopmentProfilePacket:
        if isinstance(duration_ms, bool) or not 0 <= duration_ms <= 30_000:
            raise ValueError("development diagnostic duration MUST be between 0 and 30000 ms")
        if duration_ms == 0 and (cpu or heap):
            raise ValueError("snapshot capture cannot enable CPU or heap profiling")
        if duration_ms > 0 and not (cpu or heap):
            raise ValueError("profile capture requires CPU or heap profiling")
        if self._capture_lock.locked():
            raise RuntimeError("development diagnostic capture is already active")
        async with self._capture_lock:
            return await self._capture(duration_ms=duration_ms, cpu=cpu, heap=heap)

    async def _capture(
        self,
        *,
        duration_ms: int,
        cpu: bool,
        heap: bool,
    ) -> DevelopmentProfilePacket:
        started_at = datetime.now(UTC)
        started_ns = time.monotonic_ns()
        before = _process_snapshot()
        profiler = cProfile.Profile() if cpu else None
        owned_tracemalloc = heap and not tracemalloc.is_tracing()
        before_heap = None
        heap_current_before = None
        sleep_started_ns: int | None = None
        sleep_completed_ns: int | None = None
        limitations: list[str] = []
        try:
            if heap:
                if owned_tracemalloc:
                    tracemalloc.start(10)
                heap_current_before, _peak = tracemalloc.get_traced_memory()
                before_heap = tracemalloc.take_snapshot()
            if profiler is not None:
                profiler.enable()
            try:
                if duration_ms:
                    sleep_started_ns = time.monotonic_ns()
                    await asyncio.sleep(duration_ms / 1000)
                    sleep_completed_ns = time.monotonic_ns()
            finally:
                if profiler is not None:
                    profiler.disable()
            after = _process_snapshot()
            cpu_rows = _cpu_rows(profiler, self._config.source_root) if profiler else ()
            heap_rows: tuple[HeapProfileEntry, ...] = ()
            heap_current_after = None
            heap_peak = None
            if heap and before_heap is not None:
                heap_current_after, heap_peak = tracemalloc.get_traced_memory()
                after_heap = tracemalloc.take_snapshot()
                heap_rows = _heap_rows(before_heap, after_heap, self._config.source_root)
        finally:
            if owned_tracemalloc and tracemalloc.is_tracing():
                tracemalloc.stop()
        if heap and not heap_rows:
            limitations.append("python_heap_no_repository_growth")
        if cpu and not cpu_rows:
            limitations.append("cpu_no_repository_samples")
        measured_ms = max(0, (time.monotonic_ns() - started_ns) // 1_000_000)
        event_loop_lag = (
            max(
                0.0,
                (sleep_completed_ns - sleep_started_ns) / 1_000_000 - duration_ms,
            )
            if sleep_started_ns is not None and sleep_completed_ns is not None
            else 0.0
        )
        untracked = (
            max(0, after.rss_bytes - heap_current_after) if heap_current_after is not None else None
        )
        return DevelopmentProfilePacket.build(
            schema_version="1.0.0",
            profile_id=str(uuid.uuid4()),
            service_id=self._config.service_id,
            capture_kind="profile" if duration_ms else "snapshot",
            source_revision=self._config.source_revision,
            service_input_digest=self._config.service_input_digest,
            worktree_digest=self._config.worktree_digest,
            runtime_scope_receipt_digest=self._config.runtime_scope_receipt_digest,
            started_at=started_at,
            completed_at=datetime.now(UTC),
            requested_duration_ms=duration_ms,
            measured_duration_ms=measured_ms,
            event_loop_lag_ms=round(event_loop_lag, 3),
            before=before,
            after=after,
            stages=stage_snapshot(),
            cpu_top=cpu_rows,
            heap_top=heap_rows,
            python_heap_before_bytes=heap_current_before,
            python_heap_after_bytes=heap_current_after,
            python_heap_peak_bytes=heap_peak,
            untracked_memory_bytes=untracked,
            limitations=tuple(limitations),
            complete=not limitations,
            external_state_authority=False,
            execution_authority=False,
        )


def _process_snapshot() -> ProcessSnapshot:
    usage = resource.getrusage(resource.RUSAGE_SELF)
    status = _proc_status()
    stats = gc.get_stats()
    try:
        open_fds = len(tuple(Path("/proc/self/fd").iterdir()))
    except OSError:
        open_fds = -1
    return ProcessSnapshot(
        cpu_user_ms=round(usage.ru_utime * 1000, 3),
        cpu_system_ms=round(usage.ru_stime * 1000, 3),
        rss_bytes=status.get("VmRSS", 0),
        vms_bytes=status.get("VmSize", 0),
        peak_rss_bytes=max(status.get("VmHWM", 0), usage.ru_maxrss * 1024),
        thread_count=threading.active_count(),
        open_fd_count=open_fds,
        gc_generation_counts=gc.get_count(),
        gc_collections=sum(int(item.get("collections", 0)) for item in stats),
    )


def _proc_status() -> dict[str, int]:
    values: dict[str, int] = {}
    try:
        lines = Path("/proc/self/status").read_text(encoding="utf-8").splitlines()
    except OSError:
        return values
    for line in lines:
        key, separator, raw = line.partition(":")
        if separator and key in {"VmRSS", "VmSize", "VmHWM"}:
            parts = raw.split()
            if parts and parts[0].isdigit():
                values[key] = int(parts[0]) * 1024
    return values


def _cpu_rows(
    profiler: cProfile.Profile,
    source_root: Path,
) -> tuple[CpuProfileEntry, ...]:
    rows: list[CpuProfileEntry] = []
    stats = pstats.Stats(profiler)
    raw_stats = cast(
        dict[tuple[str, int, str], tuple[int, int, float, float, object]],
        getattr(stats, "stats", {}),
    )
    for (filename, line, function), (primitive, total, self_time, cumulative, _callers) in sorted(
        raw_stats.items(), key=lambda item: item[1][3], reverse=True
    ):
        relative = _relative_source(filename, source_root)
        if relative is None:
            continue
        rows.append(
            CpuProfileEntry(
                path=relative,
                line=max(0, line),
                function=function[:256] or "<unknown>",
                primitive_calls=max(0, primitive),
                total_calls=max(0, total),
                self_time_ms=round(max(0.0, self_time * 1000), 3),
                cumulative_time_ms=round(max(0.0, cumulative * 1000), 3),
            )
        )
        if len(rows) == _MAX_ROWS:
            break
    return tuple(rows)


def _heap_rows(
    before: tracemalloc.Snapshot,
    after: tracemalloc.Snapshot,
    source_root: Path,
) -> tuple[HeapProfileEntry, ...]:
    rows: list[HeapProfileEntry] = []
    for statistic in after.compare_to(before, "lineno"):
        frame = statistic.traceback[0]
        relative = _relative_source(frame.filename, source_root)
        if relative is None or statistic.size_diff <= 0:
            continue
        rows.append(
            HeapProfileEntry(
                path=relative,
                line=frame.lineno,
                size_diff_bytes=statistic.size_diff,
                count_diff=statistic.count_diff,
                current_size_bytes=max(0, statistic.size),
            )
        )
        if len(rows) == _MAX_ROWS:
            break
    return tuple(rows)


def _relative_source(filename: str, source_root: Path) -> str | None:
    if filename.startswith(("<", "~")):
        return None
    try:
        relative = Path(filename).resolve().relative_to(source_root)
    except (OSError, ValueError):
        return None
    if relative.suffix != ".py" or any(part.startswith(".") for part in relative.parts):
        return None
    return relative.as_posix()


__all__ = ["RuntimeProbe"]
