"""Local-only pipe and final-screen regressions for Foundation terminal presentation."""

from __future__ import annotations

import io
import os
import subprocess
import sys
import threading

import pyte
import pytest
from rich.cells import cell_len
from rich.console import Console

from fdai_deployment_cli.deployment_progress import DeploymentProgress, begin_stage, terminal_output
from fdai_deployment_cli.foundation_output import _capture, foundation_output
from fdai_deployment_cli.foundation_progress import FoundationProgressStream, _intro, _prefix

INTRO = _intro("mutation-enabled preflight")
RECORD = _prefix(4) + "5/15 Tenant policy route - RUNNING | skipped 0 | remaining 11\n"


def display(monkeypatch, *, width=100, height=30, mode="auto", terminal=True, clock=lambda: 0.0):
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.delenv("NO_COLOR", raising=False)
    output = io.StringIO()
    console = Console(file=output, width=width, height=height, force_terminal=terminal)
    progress = DeploymentProgress(mode=mode, console=console, clock=clock, auto_refresh=False)
    return progress, output


def screen(output: str, width: int, height: int):
    view = pyte.Screen(width, height)
    pyte.Stream(view).feed(output.replace("\n", "\r\n"))
    return view


def stream(*, output=lambda _text: None):
    return FoundationProgressStream(
        output=output,
        checkpoint=lambda _value: None,
        heartbeat=lambda: None,
        mode=lambda _mode: None,
    )


@pytest.mark.parametrize("returncode", [0, 2, 3])
def test_real_child_stdout_and_exit_are_unchanged(monkeypatch, returncode) -> None:
    progress, output = display(monkeypatch)
    command = [
        sys.executable,
        "-c",
        (
            f"import os; os.write(2, {(INTRO + RECORD).encode()!r}); "
            f"os.write(1, b'child-result\\n'); raise SystemExit({returncode})"
        ),
    ]
    original_stdin = sys.stdin
    with progress:
        for phase in ("azure", "kit", "discovery", "foundation"):
            begin_stage(phase)
        with foundation_output() as descriptor:
            assert isinstance(descriptor, int)
            completed = subprocess.run(
                command, stdout=subprocess.PIPE, stderr=descriptor, check=False, timeout=5
            )
        assert completed.returncode == returncode
        assert completed.stdout == b"child-result\n"
        assert sys.stdin is original_stdin
        assert progress._checkpoint.completed == 4
        assert progress._phases["foundation"].state == "running"
        assert progress._active == "foundation"
        assert not progress._ready
        assert "Procedure:" not in output.getvalue()
        assert "FDAI Azure Genesis" not in output.getvalue()
        assert "done 4/15" not in output.getvalue()
    assert not any(thread.name == "fdai-foundation-display" for thread in threading.enumerate())


@pytest.mark.parametrize(("width", "height"), [(36, 12), (60, 14), (80, 24), (120, 30)])
def test_unified_current_and_failure_views_fit_terminal(monkeypatch, width, height) -> None:
    progress, output = display(monkeypatch, width=width, height=height)
    with pytest.raises(ValueError, match="synthetic failure"), progress:
        for phase in ("azure", "kit", "discovery", "foundation"):
            begin_stage(phase)
        with foundation_output() as descriptor:
            os.write(descriptor, (INTRO + RECORD).encode())
        rendered = "\n".join(screen(output.getvalue(), width, height).display)
        assert "FDAI" in rendered
        assert "Tenant policy" in rendered
        assert "4/15 complete" in rendered
        frame = Console(file=io.StringIO(), width=width, height=height, record=True)
        frame.print(progress.render())
        lines = frame.export_text().splitlines()
        assert len(lines) <= height
        assert all(cell_len(line) <= width for line in lines)
        raise ValueError("synthetic failure")
    final = screen(output.getvalue(), width, height)
    assert not final.cursor.hidden
    assert "Deployment failed" in "\n".join(final.display)
    assert "Deployment ready" not in "\n".join(final.display)


def test_warning_without_newline_is_visible_before_child_finishes(monkeypatch) -> None:
    progress, output = display(monkeypatch, width=100, height=45)
    visible = threading.Event()
    write = output.write

    def observed_write(text):
        result = write(text)
        if "WARNING: review required: " in text:
            visible.set()
        return result

    monkeypatch.setattr(output, "write", observed_write)
    with progress:
        begin_stage("foundation")
        with foundation_output() as descriptor:
            os.write(descriptor, (INTRO + "WARNING: review required: ").encode())
            assert visible.wait(timeout=2)
            assert "WARNING: review required: " in output.getvalue()
            assert not progress._live.is_started
            os.write(descriptor, b"do not retry\n" + RECORD.encode())
        assert "WARNING: review required: do not retry" in "\n".join(
            screen(output.getvalue(), 100, 45).display
        )
        assert progress._live.is_started
        with terminal_output("Exact plan approval", approval=True):
            output.write("Plan digest: " + "a" * 64 + "\nType foundation-apply: ")
            assert not progress._live.is_started
            output.write("declined\n")
    assert "Type foundation-apply: declined" in "\n".join(
        screen(output.getvalue(), 100, 45).display
    )


def test_unterminated_error_survives_dashboard_resume(monkeypatch) -> None:
    progress, output = display(monkeypatch, width=100, height=45)
    with progress:
        begin_stage("foundation")
        with foundation_output() as descriptor:
            os.write(descriptor, (INTRO + "ERROR: retained effect requires review").encode())
        assert "ERROR: retained effect requires review" in "\n".join(
            screen(output.getvalue(), 100, 45).display
        )


@pytest.mark.parametrize(("mode", "terminal"), [("plain", True), ("off", True), ("auto", False)])
def test_non_live_modes_keep_native_stderr(monkeypatch, mode, terminal) -> None:
    progress, _output = display(monkeypatch, mode=mode, terminal=terminal)
    with progress, foundation_output() as descriptor:
        assert descriptor is None
    with foundation_output() as descriptor:
        assert descriptor is None


@pytest.mark.parametrize(("name", "value"), [("NO_COLOR", ""), ("TERM", "dumb")])
def test_terminal_preferences_preserve_native_path(monkeypatch, name, value) -> None:
    progress, _output = display(monkeypatch)
    monkeypatch.setenv(name, value)
    progress = DeploymentProgress(console=progress.console, auto_refresh=False)
    with progress, foundation_output() as descriptor:
        assert descriptor is None


def test_utf8_split_across_pipe_writes_is_not_corrupted() -> None:
    output = []
    with _capture(stream(output=output.append)) as descriptor:
        for byte in "검토가 필요합니다\n".encode():
            os.write(descriptor, bytes([byte]))
    assert "".join(output) == "검토가 필요합니다\n"


def test_retained_descendant_descriptor_cannot_hold_reader_open() -> None:
    output = []
    with _capture(stream(output=output.append)) as descriptor:
        retained = os.dup(descriptor)
        os.write(descriptor, b"diagnostic\n")
    os.close(retained)
    assert "".join(output) == "diagnostic\n"
    assert not any(thread.name == "fdai-foundation-display" for thread in threading.enumerate())


@pytest.mark.parametrize("primary", [None, ValueError("original failure"), KeyboardInterrupt()])
def test_reader_failure_drains_and_preserves_original_error(primary) -> None:
    failed = threading.Event()

    def broken_output(_text):
        failed.set()
        raise OSError("synthetic disconnected terminal")

    expected = ValueError if primary is None else type(primary)
    with pytest.raises(expected) as caught, _capture(stream(output=broken_output)) as descriptor:
        os.write(descriptor, b"ERROR: diagnostic\n")
        assert failed.wait(timeout=2)
        for _ in range(32):
            os.write(descriptor, b"x" * 4096)
        if primary is not None:
            raise primary
    if primary is not None:
        assert caught.value is primary
        assert "Foundation display" in " ".join(caught.value.__notes__)
    else:
        assert "output is incomplete" in str(caught.value)


def test_timeout_exception_is_not_replaced_by_display_cleanup() -> None:
    error = subprocess.TimeoutExpired(["synthetic-child"], 1)
    with pytest.raises(subprocess.TimeoutExpired) as caught, _capture(stream()) as descriptor:
        os.write(descriptor, b"diagnostic\n")
        raise error
    assert caught.value is error


def test_heartbeat_never_advances_the_coordinator_or_claims_ready(monkeypatch) -> None:
    clock = [0.0]
    progress, _output = display(monkeypatch, clock=lambda: clock[0])
    with progress:
        begin_stage("foundation")
        with foundation_output() as descriptor:
            os.write(descriptor, (INTRO + RECORD).encode())
        clock[0] = 70.0
        progress.foundation_signal()
        assert progress._checkpoint.completed == 4
        assert progress._checkpoint_signal == 70.0
        assert progress._phases["foundation"].state == "running"
        assert not progress._ready
        begin_stage("identity")
        assert progress._checkpoint is None
