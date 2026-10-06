"""The runtime starts a speculative form path before the turn body and never leaks it."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fdai.core.conversation.semantic_runtime_speculation import (
    SpeculativeForm,
    speculative_form_start,
    take_speculative_form,
)


class _Ticket:
    def __init__(self) -> None:
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True


class _Planner:
    def __init__(self, events: list[str], *, enabled: bool = True) -> None:
        self._events = events
        self.speculative_form_enabled = enabled
        self.ticket = _Ticket()
        self.arguments: dict[str, Any] = {}

    def start_speculative_form(self, **arguments: Any) -> _Ticket:
        self._events.append("form_start")
        self.arguments = arguments
        return self.ticket


class _Runtime:
    def __init__(self, planner: _Planner, events: list[str]) -> None:
        self._planner = planner
        self._purpose = "operations-review"
        self._events = events
        self.taken: list[Any] = []

    @speculative_form_start
    async def handle(self, *, utterance: str, adopt: str | None = None, **_kwargs: Any) -> str:
        # The preflight runs in a worker thread; yielding lets the speculative start begin.
        await asyncio.sleep(0.05)
        self._events.append("preflight")
        if adopt is not None:
            self.taken.append(await take_speculative_form(adopt))
            self.taken.append(await take_speculative_form(adopt))
        return "done"


def _call(runtime: _Runtime, **overrides: Any) -> str:
    arguments: dict[str, Any] = {
        "utterance": "fdai resource groups",
        "prior_turns": (),
        "principal": object(),
        "locale": "ko",
        **overrides,
    }
    return asyncio.run(runtime.handle(**arguments))


def test_an_eligible_turn_starts_the_form_path_before_the_preflight_and_adopts_it_once() -> None:
    events: list[str] = []
    planner = _Planner(events)
    runtime = _Runtime(planner, events)

    assert _call(runtime, adopt="fdai resource groups") == "done"

    assert events == ["form_start", "preflight"]
    assert runtime.taken == [planner.ticket, None]
    assert planner.ticket.cancelled is False
    assert planner.arguments["purpose"] == "operations-review"


def test_an_unadopted_ticket_is_cancelled_when_the_turn_ends() -> None:
    events: list[str] = []
    planner = _Planner(events)
    runtime = _Runtime(planner, events)

    _call(runtime, adopt="a different follow-up question")

    assert runtime.taken == [None, None]
    assert planner.ticket.cancelled is True


@pytest.mark.parametrize(
    "overrides",
    [
        {"document_context": object()},
        {"bound_incident": object()},
        {"bound_resource_context": object()},
        {"bound_investigation_continuation": object()},
    ],
)
def test_a_bound_or_document_turn_never_speculates(overrides: dict[str, Any]) -> None:
    events: list[str] = []
    planner = _Planner(events)

    _call(_Runtime(planner, events), adopt="fdai resource groups", **overrides)

    assert "form_start" not in events


def test_the_setting_off_never_speculates() -> None:
    events: list[str] = []
    planner = _Planner(events, enabled=False)
    runtime = _Runtime(planner, events)

    _call(runtime, adopt="fdai resource groups")

    assert events == ["preflight"]
    assert runtime.taken == [None, None]


def test_a_failed_speculative_start_falls_back_to_no_ticket() -> None:
    async def failing() -> None:
        raise RuntimeError("manifest unavailable")

    async def scenario() -> Any:
        speculation = SpeculativeForm("question", asyncio.create_task(failing()))
        return await speculation.take("question")

    assert asyncio.run(scenario()) is None
