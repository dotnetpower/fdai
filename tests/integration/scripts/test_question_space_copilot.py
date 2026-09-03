"""Tool-disabled explicit Copilot question adapter tests."""

from __future__ import annotations

import json
from pathlib import Path

from fdai.core.conversation.question_campaign_runner import QuestionGenerationInput
from fdai.core.conversation.question_perspectives import (
    QuestionAnchorKind,
    QuestionCapabilityFamily,
    QuestionEvidencePosture,
    QuestionExpectedPosture,
    QuestionPerspective,
)
from fdai.core.conversation.question_universe import GeneratedQuestionCase, QuestionCaseClass
from scripts.automation.question_space_copilot import _copilot_command, _json_object, _prompt

DIGEST = "sha256:" + "a" * 64


def test_copilot_command_denies_every_tool_and_implicit_context_surface(tmp_path: Path) -> None:
    command = _copilot_command(Path("/example/copilot"), tmp_path, "prompt")

    assert "--deny-tool=shell" in command
    assert "--deny-tool=write" in command
    assert "--deny-tool=url" in command
    assert "--deny-tool=read" in command
    assert "--no-custom-instructions" in command
    assert "--no-ask-user" in command
    assert "--no-remote" in command
    assert "--disable-builtin-mcps" in command


def test_copilot_json_parser_ignores_bounded_non_json_prefix() -> None:
    assert _json_object('notice\n{"question":"example question"}') == {
        "question": "example question"
    }


def test_copilot_prompt_limits_model_output_to_question_wording() -> None:
    prompt = _prompt(
        case=GeneratedQuestionCase(
            case_id="q:1",
            principal_manifest_digest=DIGEST,
            declaration_id="object:Resource",
            declaration_digest=DIGEST,
            locale="en",
            case_class=QuestionCaseClass.POSITIVE,
            perspective=QuestionPerspective.RESOURCE,
            required_capability=QuestionCapabilityFamily.OBJECT_SET,
            evidence_posture=QuestionEvidencePosture.FRESH,
            anchor_kind=QuestionAnchorKind.SELECTED_OBJECT,
            expected_posture=QuestionExpectedPosture.ANSWER,
            action_posture="advise_only",
            path_depth=1,
            result_bound=20,
        ),
        descriptor=QuestionGenerationInput(
            case_id="q:1",
            declaration_kind="object",
            declaration_name="Resource",
            public_description="A provider-neutral managed resource.",
            readable_property_names=("id",),
            link_semantics=(),
            available_capabilities=("object_set",),
        ),
        attempt_number=1,
        prior_fingerprints=(),
    )
    payload = json.loads(prompt.splitlines()[-1])

    assert payload["response_schema"] == {"question": "string"}
    assert payload["case"]["entity_state"] == "not_applicable"
    assert 'Return only {"question":"..."}' in prompt
    assert "Copy every case field" not in prompt
