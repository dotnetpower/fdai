"""Deterministic responder fakes for the recognition-probe runner.

Colocated with production code (not under ``tests/``) so a fork's test
suite can import the same helpers via the public
``fdai.core.measurement`` package. Mirrors the pattern
established in :mod:`fdai.core.prompts.testing` and
:mod:`fdai.core.tools.testing`.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Final

from fdai.core.measurement.prompt_probe_runner import ScenarioResponder
from fdai.core.prompts.types import ComposedPrompt


class AbstainResponder(ScenarioResponder):
    """Always returns a HIL-escalate answer.

    The upstream default for :func:`run_scenarios`: no live model, so
    every scenario is deterministically scored against a
    ``hil.escalate`` action. That makes the CLI smoke-runnable
    without a fork's model wiring, and gives the recognition probe a
    known-good "response satisfies the JSON contract but always
    escalates" baseline against which shadow runs can be compared.
    """

    _RESPONSE: Final[dict[str, Any]] = {
        "action_type": "hil.escalate",
        "params": {"reason": "AbstainResponder default"},
    }

    def __init__(self) -> None:
        # Serialize once so every ``respond`` call returns the same
        # text bytes - important for the recognition probe's raw
        # response scan (canary echoes look at the exact string).
        self._response_text: Final[str] = json.dumps(self._RESPONSE, sort_keys=True)

    async def respond(
        self,
        *,
        composed_prompt: ComposedPrompt,
        capability_id: str,
    ) -> tuple[Mapping[str, Any], str]:
        # The composed prompt is intentionally unused: the abstain
        # responder ignores the model context and always returns the
        # same escalate action, so the responder cost stays constant
        # per scenario regardless of composer output.
        del composed_prompt, capability_id
        return dict(self._RESPONSE), self._response_text


class RecordingResponder(ScenarioResponder):
    """Records every call and hands back canned responses in order.

    Test-only helper. Tests build the response queue up front; the
    responder pops one entry per ``respond`` call and appends the
    scenario's ``(capability_id, composed system_text)`` pair to
    :attr:`calls` for after-the-fact assertions.
    """

    def __init__(
        self,
        responses: list[tuple[Mapping[str, Any] | None, str]],
    ) -> None:
        self._queue: list[tuple[Mapping[str, Any] | None, str]] = list(responses)
        self.calls: list[tuple[str, str]] = []

    async def respond(
        self,
        *,
        composed_prompt: ComposedPrompt,
        capability_id: str,
    ) -> tuple[Mapping[str, Any] | None, str]:
        if not self._queue:
            raise AssertionError(
                "RecordingResponder exhausted - test primed fewer responses than the runner called"
            )
        self.calls.append((capability_id, composed_prompt.system_text))
        return self._queue.pop(0)


__all__ = ["AbstainResponder", "RecordingResponder"]
