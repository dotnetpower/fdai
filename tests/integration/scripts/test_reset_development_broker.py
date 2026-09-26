"""Focused safety tests for local broker generation reset."""

from __future__ import annotations

import fcntl
import importlib.util
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]
_PATH = _ROOT / "scripts/deployment/local/reset-development-broker.py"
_SPEC = importlib.util.spec_from_file_location("reset_development_broker", _PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)


def test_groups_require_every_consumer_to_be_empty() -> None:
    with pytest.raises(RuntimeError, match="every consumer group to be empty"):
        _MODULE.groups("BROKER GROUP STATE\n0 fdai-core Stable\n")


def test_groups_accept_current_rpk_empty_listing() -> None:
    assert _MODULE.groups("BROKER  GROUP\n") == ()


def test_reset_removes_all_dedicated_resources_before_recreating_probe() -> None:
    calls: list[tuple[str, ...]] = []

    def run(*parts: str) -> str:
        calls.append(parts)
        if parts[-2:] == ("group", "list"):
            return "BROKER GROUP STATE\n0 core-worker Empty\n0 fdai-core Empty\n"
        if parts[-2:] == ("topic", "list"):
            return "NAME PARTITIONS REPLICAS\nfdai.change.events 2 1\nobject.command 2 1\n"
        return ""

    result = _MODULE.reset(run=run)

    assert result == {"groups_removed": 2, "topics_removed": 2}
    assert calls[1][-3:] == ("group", "delete", "core-worker")
    assert calls[2][-3:] == ("group", "delete", "fdai-core")
    assert calls[4][-3:] == ("topic", "delete", "fdai.change.events")
    assert calls[5][-3:] == ("topic", "delete", "object.command")
    assert calls[-1][3:6] == ("topic", "create", "fdai.startup.probes")


def test_reset_waits_for_group_coordinator_to_become_empty() -> None:
    group_lists = iter(
        (
            "BROKER GROUP STATE\n0 fdai-core Stable\n",
            "BROKER GROUP STATE\n0 fdai-core Empty\n",
        )
    )
    clock = iter((0.0, 0.0, 0.25))
    sleeps: list[float] = []

    def run(*parts: str) -> str:
        if parts[-2:] == ("group", "list"):
            return next(group_lists)
        if parts[-2:] == ("topic", "list"):
            return "NAME PARTITIONS REPLICAS\n"
        return ""

    result = _MODULE.reset_when_idle(
        run=run,
        monotonic=lambda: next(clock),
        sleeper=sleeps.append,
    )

    assert result == {"groups_removed": 1, "topics_removed": 0}
    assert sleeps == [0.25]


def test_managed_service_locks_reject_running_service(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    lock_path = log_dir / "document-processing-worker.log.lock"

    with lock_path.open("a+", encoding="utf-8") as active_lock:
        fcntl.flock(active_lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

        with pytest.raises(RuntimeError, match="every managed Console service to be stopped"):
            with _MODULE.managed_service_locks(log_dir):
                pytest.fail("broker reset lock fence admitted an active service")


def test_managed_service_locks_hold_complete_reset_fence(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"

    with _MODULE.managed_service_locks(log_dir):
        for name in _MODULE._MANAGED_SERVICE_LOCKS:
            with (log_dir / name).open("a+", encoding="utf-8") as contender:
                with pytest.raises(BlockingIOError):
                    fcntl.flock(contender.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
