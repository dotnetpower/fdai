"""Smoke tests for tools/chat.py CLI.

Deliberately minimal: verify argparse contract, catalog load, and one
stdin round-trip. Deep coordinator behaviour is covered under
:mod:`tests.conversation.test_coordinator`.
"""

from __future__ import annotations

import io
import json

import pytest
import tools.chat as chat_cli


def test_cli_help_exits_zero(capsys):
    with pytest.raises(SystemExit) as exc_info:
        chat_cli.main(["--help"])
    assert exc_info.value.code == 0
    out = capsys.readouterr().out
    assert "fdai-chat" in out
    assert "--role" in out
    assert "--json" in out


def test_cli_json_mode_round_trip(monkeypatch, capsys):
    """Feed one utterance, verify one JSON line comes back."""

    monkeypatch.setattr("sys.stdin", io.StringIO("explore_catalog tag\n"))
    rc = chat_cli.main(["--role", "reader", "--json"])
    assert rc == 0
    out_lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
    # First line = catalog load banner? No - banner is suppressed in JSON mode.
    # Every line should parse as JSON.
    payloads = [json.loads(ln) for ln in out_lines]
    assert payloads, "expected at least one JSON response"
    # Last payload is a tool result or abstain.
    last = payloads[-1]
    assert last["kind"] in {"tool_result", "abstain"}


def test_cli_text_mode_banner_then_response(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("explore_catalog tag\n:quit\n"))
    rc = chat_cli.main(["--role", "reader"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "fdai-chat:" in out
    assert "tools:" in out
    # Response has [ok] or [abstain] prefix.
    assert "[ok]" in out or "[abstain]" in out


def test_cli_unknown_role_rejects(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    with pytest.raises(SystemExit) as exc_info:
        chat_cli.main(["--role", "wizard"])
    # argparse exits with 2 on invalid choice.
    assert exc_info.value.code == 2
    err = capsys.readouterr().err
    assert "wizard" in err


# ---------------------------------------------------------------------------
# Wave M1.5c: every M1.5c + W1.6 read tool is wired in
# ---------------------------------------------------------------------------


def test_build_tools_wires_all_observation_and_memory_verbs(monkeypatch, capsys) -> None:
    """Regression: the CLI composition includes every shipped read tool.

    A miswired ``_build_tools`` would silently drop a verb (e.g. the
    Wave M1.5c tools) so a chat REPL user's ``query_log`` request
    would return 'unknown verb' instead of dispatching. This tests
    the tools list itself is complete.
    """

    tools_list = chat_cli._build_tools(
        rules=[],
        action_types=[],
        repo_root=__import__("pathlib").Path(__file__).resolve().parents[4],
    )
    tool_names = {t.name for t in tools_list}
    for verb in (
        "explore_catalog",
        "describe_event",
        "explain_verdict",
        "query_audit",
        "query_inventory",
        "query_operator_memory",  # W1.6
        "query_log",  # M1.5b
        "query_metric",  # M1.5b
        "query_deployments",  # M1.5b
        "correlate_incident",  # M1.5b
        "simulate_change",
        "list_hil",
        "approve_hil",
        "run_runbook",
        "activate_break_glass",
    ):
        assert verb in tool_names, f"{verb!r} MUST be wired in _build_tools"


@pytest.mark.parametrize(
    "utterance, verb_marker",
    [
        ("query_operator_memory resource-group rg/example", "query_operator_memory"),
        ("query_log q PT1H", "query_log"),
        ("query_metric ns m Average PT5M", "query_metric"),
        ("query_deployments P1D", "query_deployments"),
        ("correlate_incident INC-1", "correlate_incident"),
    ],
)
def test_cli_dispatches_new_read_verbs(
    monkeypatch, capsys, utterance: str, verb_marker: str
) -> None:
    """End-to-end: type a new verb, CLI produces a JSON payload for it."""

    monkeypatch.setattr("sys.stdin", io.StringIO(utterance + "\n"))
    rc = chat_cli.main(["--role", "reader", "--json"])
    assert rc == 0
    out_lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
    payloads = [json.loads(ln) for ln in out_lines]
    assert payloads, f"no response for {utterance!r}"
    last = payloads[-1]
    # Fakes return abstain (no seed data); confirm the tool actually ran.
    assert last["kind"] in {"tool_result", "abstain"}
    preview = last.get("preview", "")
    assert verb_marker.replace("_", "").lower().split("[")[0] in preview.replace("_", "").lower(), (
        f"preview does not identify {verb_marker!r}: {preview!r}"
    )
