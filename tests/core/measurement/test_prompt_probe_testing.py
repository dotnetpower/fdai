"""Unit tests for :mod:`aiopspilot.core.measurement.prompt_probe_testing`."""

from __future__ import annotations

import json

import pytest

from aiopspilot.core.measurement.prompt_probe_testing import (
    AbstainResponder,
    RecordingResponder,
)
from aiopspilot.core.prompts.types import ComposedPrompt, LayerRef, PromptLayer


def _composed(system_text: str = "sys") -> ComposedPrompt:
    return ComposedPrompt(
        system_text=system_text,
        layer_manifest=(LayerRef(id="base", version=1, layer=PromptLayer.BASE, token_estimate=1),),
        token_estimate=1,
    )


class TestAbstainResponder:
    @pytest.mark.asyncio
    async def test_returns_canned_hil_escalate_action(self) -> None:
        responder = AbstainResponder()
        response_json, response_text = await responder.respond(
            composed_prompt=_composed(),
            capability_id="t2.reasoner.primary",
        )
        assert response_json["action_type"] == "hil.escalate"
        assert isinstance(response_json["params"], dict)
        # The text is the canonical JSON form of the same object so
        # canary-echo scoring is deterministic.
        assert json.loads(response_text) == dict(response_json)

    @pytest.mark.asyncio
    async def test_same_response_across_multiple_calls(self) -> None:
        """The abstain responder MUST be deterministic across calls so
        a shadow run is reproducible - a caller comparing runs against
        the baseline cannot see spurious variation."""

        responder = AbstainResponder()
        first_json, first_text = await responder.respond(
            composed_prompt=_composed("A"), capability_id="cap"
        )
        second_json, second_text = await responder.respond(
            composed_prompt=_composed("B"), capability_id="cap"
        )
        assert first_json == second_json
        assert first_text == second_text


class TestRecordingResponder:
    @pytest.mark.asyncio
    async def test_pops_queue_and_records_calls(self) -> None:
        responder = RecordingResponder(
            [
                ({"action_type": "ok", "params": {}}, "text-1"),
                (None, "text-2"),
            ]
        )
        first_json, first_text = await responder.respond(
            composed_prompt=_composed("PROMPT_1"),
            capability_id="cap-a",
        )
        second_json, second_text = await responder.respond(
            composed_prompt=_composed("PROMPT_2"),
            capability_id="cap-b",
        )
        assert first_json == {"action_type": "ok", "params": {}}
        assert first_text == "text-1"
        assert second_json is None
        assert second_text == "text-2"
        assert responder.calls == [
            ("cap-a", "PROMPT_1"),
            ("cap-b", "PROMPT_2"),
        ]

    @pytest.mark.asyncio
    async def test_exhausted_queue_raises(self) -> None:
        """A test that primed fewer responses than the runner needs
        SHOULD fail loudly so the omission is not hidden by silent
        ``None`` results that would flow into scoring."""

        responder = RecordingResponder([])
        with pytest.raises(AssertionError, match="exhausted"):
            await responder.respond(
                composed_prompt=_composed(),
                capability_id="cap",
            )
