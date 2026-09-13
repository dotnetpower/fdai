from __future__ import annotations

import io
import json
import re
import subprocess
import sys
from types import SimpleNamespace

import pytest
from rich.cells import cell_len
from rich.console import Console

from fdai_deployment_cli import cli, deployment_kit, standalone_deploy
from fdai_deployment_cli.deployment_progress import (
    DeploymentProgress,
    begin_stage,
    downloaded_bytes,
    progress_detail,
    terminal_output,
)


def _display(*, mode="plain", terminal=False, width=80, clock=lambda: 0.0):
    output = io.StringIO()
    console = Console(file=output, force_terminal=terminal, width=width, height=40, record=True)
    display = DeploymentProgress(mode=mode, console=console, clock=clock, auto_refresh=False)
    return display, output


def test_plain_output_has_no_terminal_sequences_or_stdout(capsys) -> None:
    clock = [0.0]
    display, output = _display(clock=lambda: clock[0])
    with display:
        begin_stage("azure")
        clock[0] = 2.0
        begin_stage("kit")
        downloaded_bytes(1024 * 1024)
        clock[0] = 62.0
        begin_stage("discovery")

    text = output.getvalue()
    assert "[01/13] OK   Azure sign-in (00:02)" in text
    assert "Signed deployment kit (01:00)" in text
    assert "1.0 MiB received; verification pending" in text
    assert "without a ready result" in text
    assert "\x1b" not in text
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("error", [ValueError("provider-private-output"), KeyboardInterrupt()])
def test_failure_and_interruption_preserve_unfinished_phase(error) -> None:
    display, output = _display()
    with pytest.raises(type(error)), display:
        begin_stage("azure")
        begin_stage("kit")
        begin_stage("discovery")
        raise error

    text = output.getvalue()
    assert "Foundation discovery" in text
    assert "STOP" in text if isinstance(error, KeyboardInterrupt) else "FAIL" in text
    assert "Deployment ready" not in text
    assert "provider-private-output" not in text
    assert "OK   Foundation discovery" not in text
    begin_stage("cleanup")
    assert output.getvalue() == text


@pytest.mark.parametrize("mode", ["off", "plain", "auto"])
def test_approval_never_redirects_or_consumes_standard_streams(mode, monkeypatch) -> None:
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.delenv("NO_COLOR", raising=False)
    display, output = _display(mode=mode, terminal=True)
    original = (sys.stdin, sys.stdout, sys.stderr)
    with display:
        begin_stage("foundation")
        with terminal_output("Review the exact Foundation plan", approval=True):
            assert (sys.stdin, sys.stdout, sys.stderr) == original
            assert not display._live.is_started
            assert display._phases["foundation"].state == "waiting"
        assert display._phases["foundation"].state == "running"
        assert display._live.is_started is display.dynamic

    if mode == "off":
        assert output.getvalue() == ""
    else:
        text = display.console.export_text() if display.dynamic else output.getvalue()
        assert "[WAIT] Review the exact Foundation plan" in text


@pytest.mark.parametrize("environment", [{"NO_COLOR": ""}, {"TERM": "dumb"}])
def test_terminal_preferences_disable_ansi_and_redraw(environment, monkeypatch) -> None:
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.delenv("NO_COLOR", raising=False)
    for key, value in environment.items():
        monkeypatch.setenv(key, value)
    display, output = _display(mode="auto", terminal=True)
    with display:
        begin_stage("azure")
    assert not display.dynamic
    assert "\x1b" not in output.getvalue()


def test_redirected_output_uses_plain_messages(monkeypatch) -> None:
    monkeypatch.setenv("TERM", "xterm-256color")
    display, output = _display(mode="auto")
    with display:
        begin_stage("azure")
        progress_detail("Checking the active Azure context")
    assert "Checking the active Azure context" in output.getvalue()
    assert "\x1b" not in output.getvalue()


def test_full_phase_count_is_not_automatically_a_ready_result() -> None:
    display, output = _display()
    with display:
        for name in display._phases:
            begin_stage(name)
    assert "Deployment ready" not in output.getvalue()

    display, output = _display()
    with display:
        for name in display._phases:
            begin_stage(name)
        display.ready()
    assert "Deployment ready" in output.getvalue()
    assert "[13/13] OK   Cleanup and final receipt" in output.getvalue()


@pytest.mark.parametrize("width", [36, 60, 100])
def test_current_work_view_fits_terminal_width(width, monkeypatch) -> None:
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.delenv("NO_COLOR", raising=False)
    display, _output = _display(mode="auto", terminal=True, width=width)
    with display:
        begin_stage("azure")
        begin_stage("kit")
        downloaded_bytes(128 * 1024 * 1024)
    frame = Console(file=io.StringIO(), width=width, record=True)
    frame.print(display.render())
    snapshot = frame.export_text()
    assert "FDAI" in snapshot
    assert "1/13 phases" in snapshot
    assert "128.0 MiB received" in snapshot
    assert all(cell_len(line) <= width for line in snapshot.splitlines())


def test_download_logs_are_bounded_and_do_not_claim_verification() -> None:
    display, output = _display()
    with display:
        begin_stage("kit")
        for count in range(1, 130):
            downloaded_bytes(count * 1024 * 1024)
    assert output.getvalue().count("verification pending") == 3
    assert "OK   Signed deployment kit" not in output.getvalue()


def test_phase_timer_freezes_even_when_finish_time_is_zero() -> None:
    clock = [0.0]
    display, output = _display(clock=lambda: clock[0])
    with display:
        begin_stage("azure")
        begin_stage("kit")
        clock[0] = 60.0
        snapshot = Console(file=io.StringIO(), record=True)
        snapshot.print(display.render())
        assert "Azure sign-in" not in snapshot.export_text()
        assert "OK   Azure sign-in (00:00)" in output.getvalue()
        assert display._phases["azure"].ended == 0.0


def test_download_instrumentation_preserves_bytes_and_size_guard(tmp_path, monkeypatch) -> None:
    observed = []
    monkeypatch.setattr(deployment_kit, "downloaded_bytes", observed.append)
    monkeypatch.setattr(deployment_kit, "_BUFFER_BYTES", 3)
    destination = tmp_path / "kit.tar.gz"
    deployment_kit._write_bounded_stream(io.BytesIO(b"example"), destination)
    assert destination.read_bytes() == b"example"
    assert observed == [3, 6, 7]

    monkeypatch.setattr(deployment_kit, "_MAX_ARCHIVE_BYTES", 4)
    oversized = tmp_path / "oversized.tar.gz"
    with pytest.raises(ValueError, match="byte limit"):
        deployment_kit._write_bounded_stream(io.BytesIO(b"example"), oversized)
    assert not oversized.exists()


def test_cli_marks_failed_acquisition_without_running_azure(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        standalone_deploy,
        "active_azure_target",
        lambda: standalone_deploy.ActiveAzureTarget("0" * 36, "0" * 36),
    )

    def fail_acquisition(**_kwargs):
        raise ValueError("deployment kit signature is invalid")

    monkeypatch.setattr(standalone_deploy, "acquire_deployment_kit", fail_acquisition)
    result = cli.main(
        ["provision", "azure", "--online", "--progress", "plain", "--work-dir", str(tmp_path)]
    )
    captured = capsys.readouterr()
    assert result == 3
    assert captured.out == ""
    assert "FAIL Signed deployment kit" in captured.err
    assert "deployment kit signature is invalid" in captured.err
    assert "Deployment ready" not in captured.err


@pytest.mark.parametrize("error", [KeyboardInterrupt(), ValueError("approval denied")])
def test_cli_interrupt_and_failure_never_print_a_ready_result(error, monkeypatch, capsys) -> None:
    def stop(**_kwargs):
        begin_stage("application")
        raise error

    monkeypatch.setattr(cli, "deploy_azure_foundation", stop)
    result = cli.main(["provision", "azure", "--online", "--progress", "plain"])
    captured = capsys.readouterr()
    assert result == (130 if isinstance(error, KeyboardInterrupt) else 3)
    assert "Application deployment" in captured.err
    assert captured.out == ""
    assert "Deployment ready" not in captured.err


@pytest.mark.parametrize("ready", [False, None, "true"])
def test_cli_requires_verified_readiness_for_success(ready, monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        cli, "deploy_azure_foundation", lambda **_kwargs: {"deployment_ready": ready}
    )
    assert cli.main(["provision", "azure", "--online", "--output", "json"]) == 3
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize(
    ("terminal_returncode", "status_current", "terminal_state"),
    [
        (0, True, "waiting"),
        (2, True, "waiting"),
        (1, True, "waiting"),
        (-15, True, "waiting"),
        (2, False, "waiting"),
        (1, True, "blocked"),
        (1, False, "blocked"),
        (-15, True, "failed"),
    ],
)
def test_real_coordinator_keeps_approval_and_intermediate_json_off_stdout(
    tmp_path, monkeypatch, capsys, terminal_returncode, status_current, terminal_state
) -> None:
    """Exercise the local coordinator with fake external boundaries, never Azure or Terraform."""

    scripts = tmp_path / "bundle/scripts/deployment/azure"
    scripts.mkdir(parents=True)
    root = tmp_path / "work"
    kit = SimpleNamespace(
        bundle_root=tmp_path / "bundle",
        source_commit="a" * 40,
        verification=SimpleNamespace(manifest_digest="b" * 64),
        bundle_manifest_digest="c" * 64,
        runtime=SimpleNamespace(digest="d" * 64),
    )
    prepared = SimpleNamespace(
        root=root / "run",
        offline_kit=root / "kit",
        release_root=root / "release.pub",
        bundle_public_key=root / "bundle.pub",
        profile=root / "profile.json",
        variables=root / "variables.json",
        terraform=root / "terraform",
        ssh_private_key=root / "private-key-path-only",
        run_binding="e" * 64,
    )
    status_base = {
        "schema_version": "fdai.genesis-orchestration-status.v2",
        "attempt": 1,
        "sequence": 1,
        "mode": "apply",
        "state": "waiting",
        "source_commit": kit.source_commit,
        "target_binding": prepared.run_binding,
        "route": "private-runner",
    }
    statuses = iter(
        [
            {**status_base, "current_stage": "foundation-plan", "completed_stages": []},
            {
                **status_base,
                "attempt": 2 if status_current else 1,
                "state": terminal_state,
                "current_stage": (
                    "application-plan" if terminal_state == "waiting" else "runner-image-apply"
                ),
                "reason_code": "runner_image_apply_or_verification_failed",
                "completed_stages": ["foundation-state"],
                "foundation_report": {"state_handoff": {"receipt_digest": "f" * 64}},
            },
        ]
    )
    monkeypatch.setattr(
        standalone_deploy,
        "active_azure_target",
        lambda: SimpleNamespace(
            subscription_id="00000000-0000-0000-0000-000000000000",
            tenant_id="00000000-0000-0000-0000-000000000000",
        ),
    )
    monkeypatch.setattr(standalone_deploy, "acquire_deployment_kit", lambda **_kwargs: kit)
    monkeypatch.setattr(standalone_deploy, "_current_operator_object_id", lambda: "0" * 36)

    def configure_identity(**_kwargs):
        print("Original identity review remains visible")
        return {}

    modules = {
        "genesis_prepare": SimpleNamespace(prepare_standalone_genesis=lambda **_kwargs: prepared),
        "genesis_supervisor": SimpleNamespace(_configure_entra=configure_identity),
        "genesis_entra": SimpleNamespace(plan_entra=lambda: {}),
        "genesis_approval_prompt": SimpleNamespace(current_actor_digest=lambda _binding: "a" * 64),
    }
    original_import = standalone_deploy.importlib.import_module
    monkeypatch.setattr(
        standalone_deploy.importlib,
        "import_module",
        lambda name: modules[name] if name in modules else original_import(name),
    )
    commands = []

    def run(command, **kwargs):
        commands.append(command[1].rsplit("/", 1)[-1])
        if commands[-1] == "genesis_orchestrator.py":
            assert kwargs["stdout"] == subprocess.DEVNULL
            prepared.root.mkdir(mode=0o700, exist_ok=True)
            status_path = prepared.root / "status.json"
            status_path.write_text(json.dumps(next(statuses)))
            status_path.chmod(0o600)
            code = 2 if commands.count("genesis_orchestrator.py") == 1 else terminal_returncode
            return subprocess.CompletedProcess(command, code)
        assert commands[-1] == "genesis_approval_prompt.py"
        assert kwargs["stdout"] is sys.stderr
        print("Original Foundation approval remains visible", file=kwargs["stdout"])
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(standalone_deploy.subprocess, "run", run)

    def application(**_kwargs):
        for stage in (
            "transfer",
            "substrate",
            "images",
            "capability",
            "migration",
            "application",
            "verification",
            "cleanup",
        ):
            begin_stage(stage)
        return {"receipt_digest": "b" * 64, "license_mode": "observation-only"}

    monkeypatch.setattr(standalone_deploy, "deploy_standalone_application", application)
    result = cli.main(
        ["provision", "azure", "--online", "--output", "json", "--work-dir", str(root)]
    )
    captured = capsys.readouterr()
    assert "FDAI | Azure deployment" not in captured.err
    assert "Original Foundation approval remains visible" in captured.err
    if terminal_returncode in {0, 2} and status_current:
        assert result == 0
        assert json.loads(captured.out)["deployment_ready"] is True
        assert len(captured.out.splitlines()) == 1
        assert "Original identity review remains visible" in captured.err
    else:
        assert result == 3
        assert captured.out == ""
        if status_current or terminal_returncode not in {0, 2}:
            assert "orchestration failed" in captured.err
        else:
            assert "current Foundation status" in captured.err
        if status_current and terminal_state in {"blocked", "failed"}:
            assert "Runner image exact apply (08/15)" in captured.err
            assert "verification only" in captured.err
            assert "new approval" in captured.err
        else:
            assert "Runner image exact apply (08/15)" not in captured.err
        assert "Original identity review remains visible" not in captured.err
    assert commands == [
        "genesis_orchestrator.py",
        "genesis_approval_prompt.py",
        "genesis_orchestrator.py",
    ]


def test_download_does_not_force_one_redraw_per_chunk(monkeypatch) -> None:
    display, _output = _display()
    refreshes = []
    monkeypatch.setattr(display, "_refresh", lambda: refreshes.append(True))
    with display:
        begin_stage("kit")
        for count in range(1, 130):
            downloaded_bytes(count * 1024 * 1024)
    assert len(refreshes) == 4


def test_failed_display_start_restores_context(monkeypatch) -> None:
    display, output = _display()

    def unavailable(_text):
        raise OSError("terminal unavailable")

    monkeypatch.setattr(display, "_plain", unavailable)
    with pytest.raises(OSError, match="terminal unavailable"), display:
        pytest.fail("display startup should have failed")
    begin_stage("azure")
    assert output.getvalue() == ""


def test_detail_text_cannot_inject_ansi_lines_or_markup() -> None:
    display, output = _display()
    with display:
        begin_stage("kit")
        progress_detail("[bold red]not-ready[/]\x1b[2J\r\n\u202e" + "x" * 200)
    text = output.getvalue()
    assert "\x1b" not in text
    assert "\r" not in text
    assert "\u202e" not in text
    assert "[bold red]not-ready[/]" in text
    detail_line = next(line for line in text.splitlines() if "not-ready" in line)
    assert len(detail_line.strip()) <= 160


def test_elapsed_time_stays_frozen_after_exit_and_supports_hours() -> None:
    clock = [0.0]
    display, output = _display(clock=lambda: clock[0])
    with display:
        begin_stage("azure")
        clock[0] = 3661.0
        begin_stage("kit")
        clock[0] = 3663.0
    clock[0] = 9999.0
    frame = Console(file=io.StringIO(), width=100, record=True)
    frame.print(display.render())
    text = frame.export_text()
    assert "elapsed 01:01:03" in text
    assert "OK   Azure sign-in (01:01:01)" in output.getvalue()
    assert "Azure sign-in" not in text
    assert re.search(r"Signed deployment kit\s+00:02", text)


def test_empty_download_has_no_success_or_partial_file(tmp_path) -> None:
    display, output = _display()
    destination = tmp_path / "empty.tar.gz"
    with pytest.raises(ValueError, match="empty"), display:
        begin_stage("kit")
        deployment_kit._write_bounded_stream(io.BytesIO(b""), destination)
    assert not destination.exists()
    assert "OK   Signed deployment kit" not in output.getvalue()


def test_interrupted_download_removes_partial_file(tmp_path, monkeypatch) -> None:
    def interrupt(_count):
        raise KeyboardInterrupt()

    monkeypatch.setattr(deployment_kit, "downloaded_bytes", interrupt)
    destination = tmp_path / "partial.tar.gz"
    with pytest.raises(KeyboardInterrupt):
        deployment_kit._write_bounded_stream(io.BytesIO(b"example"), destination)
    assert not destination.exists()


def test_download_does_not_replace_existing_artifact(tmp_path) -> None:
    destination = tmp_path / "retained.tar.gz"
    destination.write_bytes(b"retained")
    with pytest.raises(FileExistsError):
        deployment_kit._write_bounded_stream(io.BytesIO(b"replacement"), destination)
    assert destination.read_bytes() == b"retained"


def test_exact_download_bound_reports_observed_bytes(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(deployment_kit, "_MAX_ARCHIVE_BYTES", 7)
    display, output = _display()
    with display:
        begin_stage("kit")
        deployment_kit._write_bounded_stream(io.BytesIO(b"example"), tmp_path / "exact.tar.gz")
    assert "verification pending" in output.getvalue()
    assert "Deployment ready" not in output.getvalue()
