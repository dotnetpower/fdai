"""Provider starts are concurrent and bounded; cancellation never terminates running CI jobs."""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from unittest.mock import Mock

import pytest
from scripts.automation.runner_controller.config import Settings
from scripts.automation.runner_controller.controller import Controller
from scripts.automation.runner_controller.github import GitHubAPI
from scripts.automation.runner_controller.state import StateStore
from scripts.automation.runner_controller.transport import ProviderError
from scripts.automation.runner_controller.workers import Workers

NOW = datetime.now(UTC)


def _controller() -> Controller:
    return Controller(
        Mock(spec=Settings),
        {},
        {},
        Mock(spec=StateStore),
        Mock(spec=GitHubAPI),
        Mock(spec=Workers),
    )


def test_starts_use_eight_concurrent_slots_and_dispatch_every_request_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _controller()
    barrier = threading.Barrier(8, timeout=3)
    lock = threading.Lock()
    live, peak, completed = 0, 0, []

    def start(name, now):
        nonlocal live, peak
        with lock:
            live += 1
            peak = max(peak, live)
        barrier.wait()
        with lock:
            completed.append(name)
            live -= 1

    monkeypatch.setattr(engine, "_start", start)
    engine._start_batch([f"worker-{index}" for index in range(16)], NOW)
    assert peak == 8
    assert sorted(completed) == sorted(f"worker-{index}" for index in range(16))
    engine.workers.cleanup.assert_not_called()
    engine.github.remove_idle.assert_not_called()


def test_provider_failure_stops_pending_starts_without_stopping_jobs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _controller()
    created = []

    def start(name, now):
        if name == "failure":
            raise ProviderError("unavailable", 503)
        if not engine.stop.is_set():
            created.append(name)
        engine.stop.wait(3)

    monkeypatch.setattr(engine, "_start", start)
    with pytest.raises(ProviderError):
        engine._start_batch(["failure"] + ["waiting"] * 64, NOW)
    assert engine.stop.is_set()
    assert len(created) <= 8
    engine.workers.cleanup.assert_not_called()
    engine.github.remove_idle.assert_not_called()


def test_dispatch_deadline_is_bounded_and_stops_pending_effects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _controller()
    monkeypatch.setattr(
        "scripts.automation.runner_controller.controller.START_BATCH_TIMEOUT_SECONDS", 0.02
    )

    def start(name, now):
        engine.stop.wait(3)

    monkeypatch.setattr(engine, "_start", start)
    with pytest.raises(TimeoutError):
        engine._start_batch(["waiting"] * 32, NOW)
    assert engine.stop.is_set()
    engine.workers.cleanup.assert_not_called()


def test_stopped_controller_never_reserves_or_starts_a_worker() -> None:
    engine = _controller()
    engine.stop.set()
    with pytest.raises(RuntimeError, match="stopped before worker start"):
        engine._start("general", NOW)
    engine.state.transaction.assert_not_called()
    engine.workers.start.assert_not_called()


@pytest.mark.parametrize(
    "field,value",
    [
        ("parallelism", 2),
        ("parallelism", True),
        ("replicaCompletionCount", 2),
        ("replicaRetryLimit", 1),
        ("replicaTimeout", 1800),
    ],
)
def test_provider_template_cannot_multiply_a_single_reserved_slot(field, value) -> None:
    settings = Mock(spec=Settings)
    settings.subscription_id = "00000000-0000-0000-0000-000000000000"
    settings.resource_group = "rg-example-ci"
    settings.jobs = {"general": "job-example-general"}
    settings.worker_image = "registry.example.com/runner@sha256:" + "a" * 64
    configuration = {
        "triggerType": "Manual",
        "replicaRetryLimit": 0,
        "replicaTimeout": 86400,
        "manualTriggerConfig": {"parallelism": 1, "replicaCompletionCount": 1},
    }
    if field in {"parallelism", "replicaCompletionCount"}:
        configuration["manualTriggerConfig"][field] = value
    else:
        configuration[field] = value
    azure = Mock()
    azure.get_resource.return_value = {
        "properties": {
            "configuration": configuration,
            "template": {"containers": [{"name": "runner", "image": settings.worker_image}]},
        }
    }
    with pytest.raises(ValueError):
        Workers(settings, azure).check_ownership()
    azure.start_container.assert_not_called()
