from __future__ import annotations

import io
import sys

import pyte
import pytest
from rich.console import Console

from fdai_deployment_cli.deployment_progress import (
    DeploymentProgress,
    begin_stage,
    progress_detail,
    terminal_output,
)


def _screen(output: str, width: int, height: int):
    screen = pyte.Screen(width, height)
    pyte.Stream(screen).feed(output.replace("\n", "\r\n"))
    return screen


def _display(monkeypatch, width=80, height=24):
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.delenv("NO_COLOR", raising=False)
    output = io.StringIO()
    console = Console(file=output, width=width, height=height, force_terminal=True)
    display = DeploymentProgress(console=console, auto_refresh=False)
    return display, output


@pytest.mark.parametrize(("width", "height"), [(36, 12), (60, 14), (80, 14), (120, 30)])
def test_current_and_terminal_failure_fit_real_viewport(monkeypatch, width, height) -> None:
    display, output = _display(monkeypatch, width, height)
    with pytest.raises(ValueError, match="local test failure"), display:
        begin_stage("azure")
        begin_stage("kit")
        begin_stage("verification")
        progress_detail("checking-health")
        live = "\n".join(_screen(output.getvalue(), width, height).display)
        assert "FDAI" in live
        assert "Health" in live
        assert "checking-health" in live
        raise ValueError("local test failure")
    final = _screen(output.getvalue(), width, height)
    assert not final.cursor.hidden
    terminal = "\n".join(final.display)
    assert "Deployment failed" in terminal
    assert "Health" in terminal


def test_prompt_redraw_preserves_review_and_terminal_owner(monkeypatch) -> None:
    display, output = _display(monkeypatch, 90, 45)
    original_streams = (sys.stdin, sys.stdout, sys.stderr)
    output.write("Existing terminal history\n")
    with display:
        begin_stage("substrate")
        with terminal_output("Exact plan approval", approval=True):
            with terminal_output("Additional review details"):
                assert not display._live.is_started
            output.write("Plan digest: " + "a" * 64 + "\nType substrate-apply: ")
            pending = _screen(output.getvalue(), 90, 45)
            assert not pending.cursor.hidden
            assert "Type substrate-apply:" in "\n".join(pending.display)
            assert (sys.stdin, sys.stdout, sys.stderr) == original_streams
            output.write("substrate-apply\n")
        progress_detail("Approved plan is running")
        resumed = "\n".join(_screen(output.getvalue(), 90, 45).display)
        assert "Plan digest:" in resumed
        assert "Type substrate-apply: substrate-apply" in resumed
        assert "Approved plan is running" in resumed
    assert (sys.stdin, sys.stdout, sys.stderr) == original_streams
    assert not _screen(output.getvalue(), 90, 45).cursor.hidden


@pytest.mark.parametrize("error", [ValueError("denied"), EOFError(), KeyboardInterrupt()])
def test_prompt_failure_always_restores_cursor_and_stderr(monkeypatch, error) -> None:
    display, output = _display(monkeypatch, 80, 14)
    original_stderr = sys.stderr
    with pytest.raises(type(error)), display:
        begin_stage("application")
        with terminal_output("Exact plan approval", approval=True):
            raise error
    assert sys.stderr is original_stderr
    assert not display._live.is_started
    assert not _screen(output.getvalue(), 80, 14).cursor.hidden


def test_force_color_does_not_turn_redirected_logs_into_live_output(monkeypatch) -> None:
    output = io.StringIO()
    monkeypatch.setattr(sys, "stderr", output)
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.setenv("FORCE_COLOR", "1")
    monkeypatch.delenv("NO_COLOR", raising=False)
    with DeploymentProgress(auto_refresh=False):
        begin_stage("azure")
        begin_stage("kit")
    assert "\x1b" not in output.getvalue()
    assert "[02/13] RUN" in output.getvalue()
    assert not _screen(output.getvalue(), 80, 14).cursor.hidden


def test_auto_refresh_thread_is_stopped_on_exit(monkeypatch) -> None:
    display, output = _display(monkeypatch)
    display._live.auto_refresh = True
    with display:
        begin_stage("kit")
        worker = display._live._refresh_thread
        assert worker is not None
    assert display._live._refresh_thread is None
    assert worker.done.is_set()
    assert not _screen(output.getvalue(), 80, 24).cursor.hidden


def test_interrupted_live_start_releases_terminal_ownership(monkeypatch) -> None:
    display, output = _display(monkeypatch)
    original_write = output.write
    interrupted = [False]
    original_stderr = sys.stderr

    def interrupt_once(text):
        result = original_write(text)
        if "\x1b[?25l" in text and not interrupted[0]:
            interrupted[0] = True
            raise KeyboardInterrupt()
        return result

    monkeypatch.setattr(output, "write", interrupt_once)
    with pytest.raises(KeyboardInterrupt), display:
        pytest.fail("interrupted startup cannot enter the body")
    assert sys.stderr is original_stderr
    assert not display._live.is_started
    assert not _screen(output.getvalue(), 80, 24).cursor.hidden


def test_interrupted_live_resume_releases_terminal_ownership(monkeypatch) -> None:
    display, output = _display(monkeypatch)
    original_write = output.write
    interrupted = [False]

    def interrupt_once(text):
        result = original_write(text)
        if "\x1b[?25l" in text and not interrupted[0]:
            interrupted[0] = True
            raise KeyboardInterrupt()
        return result

    with pytest.raises(KeyboardInterrupt), display:
        begin_stage("application")
        with terminal_output("Review the exact application plan", approval=True):
            monkeypatch.setattr(output, "write", interrupt_once)
    assert not display._live.is_started
    assert not _screen(output.getvalue(), 80, 24).cursor.hidden


@pytest.mark.parametrize("mode", ["auto", "plain"])
@pytest.mark.parametrize("error", [ValueError("original failure"), KeyboardInterrupt()])
def test_exit_output_failure_preserves_original_error(monkeypatch, mode, error) -> None:
    display, _output = _display(monkeypatch)
    if mode == "plain":
        display.dynamic = False
    original_stderr = sys.stderr

    def broken_write(_text):
        raise OSError("terminal disconnected")

    with pytest.raises(type(error)) as caught, display:
        begin_stage("verification")
        monkeypatch.setattr(display.console.file, "write", broken_write)
        raise error
    assert caught.value is error
    assert sys.stderr is original_stderr
    assert not display._live.is_started
