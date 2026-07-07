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
    assert "aiopspilot-chat" in out
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
    assert "aiopspilot-chat:" in out
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
