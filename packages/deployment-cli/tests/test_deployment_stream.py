"""Check chronological terminal output without Azure, credentials, or operational state."""

from __future__ import annotations

import io
import re

import pyte
import pytest
from rich.cells import cell_len
from rich.console import Console
from rich.text import Text

from fdai_deployment_cli.deployment_progress import DeploymentProgress
from fdai_deployment_cli.foundation_progress import FoundationCheckpoint


def display(monkeypatch, *, width=100, height=30, clock=lambda: 0.0):
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.delenv("NO_COLOR", raising=False)
    output = io.StringIO()
    console = Console(file=output, force_terminal=True, width=width, height=height)
    progress = DeploymentProgress(console=console, clock=clock, auto_refresh=False)
    return progress, output


def screen(text, width=100, height=100):
    terminal = pyte.Screen(width, height)
    pyte.Stream(terminal).feed(text.replace("\n", "\r\n"))
    return terminal


def snapshot(progress, width=100):
    frame = Console(file=io.StringIO(), width=width, record=True)
    frame.print(progress.render())
    return frame.export_text()


def test_stream_has_no_box_or_unstarted_phase_table(monkeypatch) -> None:
    progress, output = display(monkeypatch)
    with progress:
        progress.begin("azure")
        progress.begin("kit")
        progress.detail("Verifying signed files")
        current = snapshot(progress)
        assert "Signed deployment kit" in current
        assert "Azure sign-in" not in current
        assert "Application identity" not in current
        assert not any(character in current for character in "╭╮╰╯│─━")
        assert len(current.splitlines()) <= 5
    history = "\n".join(screen(output.getvalue()).display)
    assert history.index("Azure sign-in") < history.index("Signed deployment kit")
    assert "Verifying signed files" in history
    assert "without a ready result" in history
    assert "Application identity" not in history
    assert re.search(r"\x1b\[[0-9;]*32m", output.getvalue())
    assert re.search(r"\x1b\[[0-9;]*36m", output.getvalue())


def test_checkpoint_events_are_distinct_and_heartbeats_never_append(monkeypatch) -> None:
    clock = [0.0]
    progress, _output = display(monkeypatch, clock=lambda: clock[0])
    events = []
    original = progress.console.print

    def record(*args, **kwargs):
        if args and isinstance(args[0], Text):
            events.append(args[0].plain)
        original(*args, **kwargs)

    monkeypatch.setattr(progress.console, "print", record)
    running = FoundationCheckpoint(8, "Runner image exact apply", "RUNNING", 7, 0)
    blocked = FoundationCheckpoint(8, "Runner image exact apply", "BLOCKED", 7, 0)
    with progress:
        progress.begin("foundation")
        progress.foundation_checkpoint(running)
        before = list(events)
        for _ in range(20):
            clock[0] += 1
            progress.foundation_checkpoint(running)
            progress.foundation_signal()
        assert events == before
        assert progress._checkpoint_signal == 20
        progress.foundation_checkpoint(blocked)
        matching = [line for line in events if "Runner image exact apply" in line]
        assert len(matching) == 2
        assert "RUNNING" in matching[0]
        assert "BLOCKED" in matching[1]
        assert progress._phases["foundation"].state == "running"
        assert not progress._ready


@pytest.mark.parametrize(("width", "height"), [(36, 12), (60, 14), (80, 24), (120, 30)])
def test_current_and_failed_work_remain_visible_without_pending_rows(
    monkeypatch, width, height
) -> None:
    progress, output = display(monkeypatch, width=width, height=height)
    with pytest.raises(ValueError, match="synthetic failure"), progress:
        for phase in ("azure", "kit", "discovery", "foundation"):
            progress.begin(phase)
        progress.foundation_checkpoint(
            FoundationCheckpoint(8, "Runner image exact apply", "BLOCKED", 7, 0)
        )
        current = snapshot(progress, width)
        assert "Runner image" in current
        assert "7/15 complete" in current
        assert len(current.splitlines()) <= 6
        assert all(cell_len(line) <= width for line in current.splitlines())
        raise ValueError("synthetic failure")
    terminal = screen(output.getvalue(), width, height)
    final = "\n".join(terminal.display)
    assert "Deployment failed" in final
    assert "Runner image" in final
    assert "BLOCKED" in final or "Blocked" in final
    assert "Application identity" not in final
    assert "Deployment ready" not in final
    assert not terminal.cursor.hidden


def test_completed_history_survives_native_output_and_approval(monkeypatch) -> None:
    progress, output = display(monkeypatch, width=100, height=45)
    with progress:
        progress.begin("azure")
        progress.begin("foundation")
        with progress.terminal_output("Exact plan approval", approval=True):
            output.write("Reviewed plan: synthetic-digest\nType exact approval: declined\n")
        progress.detail("Approval did not grant new authority")
    history = "\n".join(screen(output.getvalue()).display)
    assert "Azure sign-in" in history
    assert "Reviewed plan: synthetic-digest" in history
    assert "Type exact approval: declined" in history
    assert "Approval did not grant new authority" in history


def test_injected_detail_is_literal_and_cannot_clear_history(monkeypatch) -> None:
    progress, output = display(monkeypatch)
    with progress:
        progress.begin("kit")
        progress.detail("[bold red]literal[/]\x1b[2J\r\n\u202e" + "x" * 200)
    text = "\n".join(screen(output.getvalue()).display)
    assert "[bold red]literal[/]" in text
    assert "\x1b[2J" not in output.getvalue()
    assert "\u202e" not in output.getvalue()


def test_completed_event_duration_is_frozen(monkeypatch) -> None:
    clock = [0.0]
    progress, output = display(monkeypatch, clock=lambda: clock[0])
    with progress:
        progress.begin("azure")
        progress.begin("kit")
        clock[0] = 60
        progress.detail("Observed activity")
    text = "\n".join(screen(output.getvalue()).display)
    assert re.search(r"OK\s+Azure sign-in.*00:00", text)
    assert progress._phases["azure"].ended == 0
