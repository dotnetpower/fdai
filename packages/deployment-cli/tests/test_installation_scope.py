"""Initial-only installation confirmation never grants checkpoint authority."""

from datetime import UTC, datetime, timedelta
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from fdai_deployment_cli import installation_scope as scope
from fdai_deployment_cli.contracts import canonical_bytes, canonical_digest
from fdai_deployment_cli.private_output import read_private_bytes, write_private_bytes
from fdai_deployment_cli.runtime_profile import RuntimeDeploymentProfile

NOW = datetime(2026, 9, 15, tzinfo=UTC)


@pytest.fixture
def arguments(tmp_path):
    tmp_path.chmod(0o700)
    runtime_profile = RuntimeDeploymentProfile.create(
        runtime_platform="aks", database_placement="postgres-flex"
    )
    return {
        "work_dir": tmp_path,
        "runtime_profile": runtime_profile,
        "binding": {
            "source_commit": "a" * 40,
            "target_binding": "b" * 64,
            "preparation_digest": "c" * 64,
            "runtime_profile_digest": runtime_profile.digest,
            "region": "eastus",
            "monthly_cost_ceiling": 1200,
        },
        "options": scope.InstallationOptions(setup_cost_ceiling=300),
        "interactive": True,
        "timeout_seconds": 3600,
        "now": NOW,
    }


def test_confirmation_once_and_resume_without_input(arguments, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(
        scope, "_read_initial_answer", lambda deadline: calls.append(deadline) or "install"
    )
    result = scope.confirm_installation_scope(**arguments)
    assert result["state"] == "confirmed"
    assert result["apply_authorized"] is False
    path = arguments["work_dir"] / "installation-scope.json"
    original = read_private_bytes(path, max_bytes=16384)
    assert path.stat().st_mode & 0o777 == 0o600
    output = capsys.readouterr().err
    assert "setup_cost_ceiling: 300" in output
    assert "system_node_sku" in output and "Standard_D4as_v5" in output
    assert "postgres-flex" in output
    arguments.update(interactive=False, now=NOW + timedelta(minutes=1))
    assert scope.confirm_installation_scope(**arguments) == result
    assert read_private_bytes(path, max_bytes=16384) == original
    assert len(calls) == 1
    assert not (arguments["work_dir"] / "current-source-approval.json").exists()


@pytest.mark.parametrize("answer", ["", "yes", "no", "INSTALL"])
def test_denial_writes_no_confirmation(arguments, monkeypatch, answer):
    monkeypatch.setattr(scope, "_read_initial_answer", lambda _: answer)
    assert (
        scope.confirm_installation_scope(**arguments)["reason_code"]
        == "initial_confirmation_denied"
    )
    assert not (arguments["work_dir"] / "installation-scope.json").exists()


@pytest.mark.parametrize("started", [False, True])
def test_noninteractive_or_started_run_never_prompts(arguments, monkeypatch, started):
    monkeypatch.setattr(scope, "_read_initial_answer", lambda _: pytest.fail("no prompt"))
    if started:
        path = arguments["work_dir"] / "foundation/status.json"
        path.parent.mkdir()
        path.write_text("{}")
    else:
        arguments["interactive"] = False
    assert scope.confirm_installation_scope(**arguments)["state"] == "review"


@pytest.mark.parametrize(
    "key",
    [
        "source_commit",
        "target_binding",
        "preparation_digest",
        "runtime_profile_digest",
        "region",
        "monthly_cost_ceiling",
    ],
)
def test_changed_binding_cannot_reprompt(arguments, monkeypatch, key):
    monkeypatch.setattr(scope, "_read_initial_answer", lambda _: "install")
    scope.confirm_installation_scope(**arguments)
    monkeypatch.setattr(scope, "_read_initial_answer", lambda _: pytest.fail("no reprompt"))
    original = arguments["binding"][key]
    arguments["binding"][key] = (
        "f" * len(original)
        if key.endswith("digest") or key.endswith("binding") or key == "source_commit"
        else ("westus" if key == "region" else 1201)
    )
    with pytest.raises(ValueError, match="scope changed"):
        scope.confirm_installation_scope(**arguments)


def test_expiry_cannot_renew_confirmation(arguments, monkeypatch):
    monkeypatch.setattr(scope, "_read_initial_answer", lambda _: "install")
    scope.confirm_installation_scope(**arguments)
    monkeypatch.setattr(scope, "_read_initial_answer", lambda _: pytest.fail("no reprompt"))
    arguments["now"] = NOW + timedelta(hours=1)
    assert (
        scope.confirm_installation_scope(**arguments)["reason_code"] == "installation_scope_expired"
    )


@pytest.mark.parametrize(
    "options",
    [
        scope.InstallationOptions(setup_cost_ceiling=301),
        scope.InstallationOptions(setup_cost_ceiling=300, cleanup_temporary_resources=True),
        scope.InstallationOptions(setup_cost_ceiling=300, allow_dedicated_identities=True),
        scope.InstallationOptions(setup_cost_ceiling=300, console_access="private-https-entra"),
    ],
)
def test_changed_preferences_cannot_reprompt(arguments, monkeypatch, options):
    monkeypatch.setattr(scope, "_read_initial_answer", lambda _: "install")
    scope.confirm_installation_scope(**arguments)
    monkeypatch.setattr(scope, "_read_initial_answer", lambda _: pytest.fail("no reprompt"))
    arguments["options"] = options
    with pytest.raises(ValueError, match="scope changed"):
        scope.confirm_installation_scope(**arguments)


@pytest.mark.parametrize("amount", [True, 0, -1, 1.5, "300", 1000001])
def test_invalid_budget_rejected(amount):
    with pytest.raises(ValueError):
        scope.InstallationOptions(setup_cost_ceiling=amount)


def test_missing_setup_budget_is_collected_only_at_start(arguments, monkeypatch):
    answers = iter(["300", "install"])
    monkeypatch.setattr(scope, "_read_initial_answer", lambda _: next(answers))
    arguments["options"] = scope.InstallationOptions()
    result = scope.confirm_installation_scope(**arguments)
    arguments["now"] = NOW + timedelta(minutes=1)
    assert scope.confirm_installation_scope(**arguments) == result


def test_self_declared_apply_authority_rejected_even_with_digest(arguments, monkeypatch):
    monkeypatch.setattr(scope, "_read_initial_answer", lambda _: "install")
    scope.confirm_installation_scope(**arguments)
    path = arguments["work_dir"] / "installation-scope.json"
    import json

    record = json.loads(read_private_bytes(path, max_bytes=16384))
    record.pop("digest")
    record["apply_authorized"] = True
    record["digest"] = canonical_digest(record)
    path.unlink()
    write_private_bytes(path, canonical_bytes(record))
    with pytest.raises(ValueError, match="scope is invalid"):
        scope.confirm_installation_scope(**arguments)


@pytest.mark.parametrize(
    "kind", ["timeout", "eof", "oversized", "non-tty", "valid", "partial-timeout"]
)
def test_initial_input_is_bounded(monkeypatch, kind):
    monkeypatch.setattr(
        scope.sys, "stdin", SimpleNamespace(isatty=lambda: kind != "non-tty", fileno=lambda: 10)
    )
    monkeypatch.setattr(scope.time, "monotonic", lambda: 1.0)
    reads = []
    payload = iter(b"install\n" if kind == "valid" else b"a" * 65)

    def read(descriptor, size):
        assert descriptor == 10 and size == 1
        reads.append(size)
        return b"" if kind == "eof" else bytes([next(payload)])

    def ready(descriptors, writes, errors, timeout):
        assert timeout == 1.0
        empty = kind == "timeout" or (kind == "partial-timeout" and reads)
        return ([] if empty else descriptors), [], []

    monkeypatch.setattr(scope.os, "read", read)
    monkeypatch.setattr(scope.select, "select", ready)
    if kind == "valid":
        assert scope._read_initial_answer(2.0) == "install"
    else:
        with pytest.raises((TimeoutError, ValueError)):
            scope._read_initial_answer(2.0)
    assert len(reads) <= 65


@pytest.mark.parametrize("failure", [TimeoutError, EOFError, KeyboardInterrupt])
def test_interrupted_initial_confirmation_never_writes_record(arguments, monkeypatch, failure):
    def read(_deadline):
        raise failure()

    monkeypatch.setattr(scope, "_read_initial_answer", read)
    with pytest.raises(failure):
        scope.confirm_installation_scope(**arguments)
    assert not (arguments["work_dir"] / "installation-scope.json").exists()


def test_confirmation_refuses_linked_file(arguments, monkeypatch):
    monkeypatch.setattr(scope, "_read_initial_answer", lambda _: pytest.fail("no prompt"))
    path = arguments["work_dir"] / "installation-scope.json"
    path.symlink_to(arguments["work_dir"] / "missing")
    with pytest.raises(OSError):
        scope.confirm_installation_scope(**arguments)
    assert path.is_symlink()


def test_initial_input_reads_one_line_from_real_terminal():
    master, slave = os.openpty()
    environment = dict(os.environ, PYTHONPATH=str(Path(scope.__file__).parents[1]))
    process = None
    try:
        process = subprocess.Popen(
            [
                sys.executable,
                "-c",
                "import time; from fdai_deployment_cli.installation_scope import _read_initial_answer; print(_read_initial_answer(time.monotonic()+5))",
            ],
            stdin=slave,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
        )
        os.write(master, b"install\n")
        stdout, stderr = process.communicate(timeout=10)
        assert process.returncode == 0, stderr.decode()
        assert stdout == b"install\n"
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        os.close(master)
        os.close(slave)
