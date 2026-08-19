"""Tool-disabled explicit Copilot question adapter tests."""

from __future__ import annotations

from pathlib import Path

from scripts.automation.question_space_copilot import _copilot_command, _json_object


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
    assert _json_object('notice\n{"case_id":"q:1","question":"example question"}') == {
        "case_id": "q:1",
        "question": "example question",
    }
