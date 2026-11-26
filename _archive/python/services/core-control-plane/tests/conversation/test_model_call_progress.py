"""Planning model calls are reported content-free, bounded, and never block the call."""

from __future__ import annotations

import asyncio
import threading
from datetime import UTC, datetime

import pytest
from fdai.core.conversation import model_call_progress
from fdai.core.conversation.adaptive_call_scope import call_scoped_provider
from fdai.core.conversation.model_call_progress import (
    MAX_REPORTED_MODEL_CALLS,
    ModelCallProgress,
    bind_model_call_progress_observer,
    model_call_ended,
    model_call_started,
)
from fdai_core_service.semantic_turn_consumer import _model_call_mapping

_REQUEST = {
    "request_id": "request-1",
    "semantic_turn": {"session_id": "session-1", "turn_id": "turn-1", "turn_sequence": 2},
}


async def test_the_gate_reports_each_call_start_and_end_with_its_deployment() -> None:
    reports: list[ModelCallProgress] = []

    async def answer() -> str:
        return "ok"

    async def fail() -> str:
        raise TimeoutError

    with bind_model_call_progress_observer(reports.append):
        await call_scoped_provider(
            answer,
            request={"messages": []},
            output_tokens=16,
            stage="semantic-question-form",
            model="narrator-gpt-5-4-mini",
        )
        with pytest.raises(TimeoutError):
            await call_scoped_provider(
                fail, request={}, output_tokens=16, stage="semantic-concept-selection"
            )

    assert [(r.call_index, r.stage, r.status, r.model) for r in reports] == [
        (1, "form", "running", "narrator-gpt-5-4-mini"),
        (1, "form", "completed", "narrator-gpt-5-4-mini"),
        (2, "concept_chooser", "running", None),
        (2, "concept_chooser", "failed", None),
    ]
    ended = reports[1]
    assert ended.completed_at is not None and ended.duration_ms is not None


async def test_an_unbound_or_unreviewed_call_reports_nothing() -> None:
    reports: list[ModelCallProgress] = []

    async def answer() -> str:
        return "ok"

    await call_scoped_provider(answer, request={}, output_tokens=1, stage="semantic-question-form")
    with bind_model_call_progress_observer(reports.append):
        await call_scoped_provider(answer, request={}, output_tokens=1, stage="unreviewed")
        await call_scoped_provider(answer, request={}, output_tokens=1)

    assert reports == []


async def test_reports_stop_at_the_per_turn_bound() -> None:
    reports: list[ModelCallProgress] = []

    with bind_model_call_progress_observer(reports.append):
        handles = [
            model_call_started("semantic-question-form", None)
            for _ in range(MAX_REPORTED_MODEL_CALLS + 3)
        ]

    assert sum(handle is not None for handle in handles) == MAX_REPORTED_MODEL_CALLS
    assert len(reports) == MAX_REPORTED_MODEL_CALLS


async def test_a_call_on_another_thread_reports_on_the_binding_loop() -> None:
    reports: list[tuple[ModelCallProgress, bool]] = []
    loop = asyncio.get_running_loop()

    def observe(progress: ModelCallProgress) -> None:
        reports.append((progress, asyncio.get_running_loop() is loop))

    with bind_model_call_progress_observer(observe):
        binding = model_call_progress._BINDING.get()

        def worker() -> None:
            token = model_call_progress._BINDING.set(binding)
            try:
                model_call_ended(model_call_started("conversation-preflight", "m"), failed=False)
            finally:
                model_call_progress._BINDING.reset(token)

        thread = threading.Thread(target=worker)
        thread.start()
        thread.join()
        await asyncio.sleep(0)
        await asyncio.sleep(0)

    assert [(p.status, on_loop) for p, on_loop in reports] == [
        ("running", True),
        ("completed", True),
    ]


async def test_an_observer_failure_never_fails_the_call() -> None:
    def explode(_progress: ModelCallProgress) -> None:
        raise RuntimeError("observer bug")

    async def answer() -> str:
        return "ok"

    with bind_model_call_progress_observer(explode):
        result, _reservation = await call_scoped_provider(
            answer, request={}, output_tokens=1, stage="semantic-question-form"
        )

    assert result == "ok"


def test_the_mapping_binds_the_request_identity_without_content() -> None:
    started = datetime(2026, 10, 8, 6, 0, tzinfo=UTC)
    record = _model_call_mapping(
        _REQUEST,
        ModelCallProgress(3, "form", "completed", "m", started, started, 1200),
        progress_sequence=7,
    )

    payload = record.model_dump(mode="json")
    assert payload["record_kind"] == "model_call_progress"
    assert (payload["request_id"], payload["turn_sequence"], payload["call_index"]) == (
        "request-1",
        2,
        3,
    )
    assert payload["execution_authority"] is False
