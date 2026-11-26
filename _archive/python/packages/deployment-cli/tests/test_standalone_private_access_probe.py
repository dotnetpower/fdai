from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from fdai_deployment_cli.standalone_private_access_probe import (
    wait_for_private_data_planes,
)


def _context() -> dict[str, object]:
    return {
        "key_vault_name": "kv-example",
        "document_storage_account_name": "stexample",
        "key_vault_private_access": True,
        "document_storage_private_access": True,
    }


def test_private_data_plane_probe_waits_for_both_sources(tmp_path: Path) -> None:
    moments = [0.0]
    calls: list[tuple[str, ...]] = []

    def run(command, **_kwargs):
        calls.append(tuple(command))
        attempt = (len(calls) - 1) // 2
        ready = attempt > 0
        return subprocess.CompletedProcess(
            command,
            0 if ready else 1,
            stdout="0\n" if ready else "",
            stderr="",
        )

    def sleep(seconds: float) -> None:
        moments[0] += seconds

    receipt = wait_for_private_data_planes(
        context=_context(),
        work_dir=tmp_path,
        timeout_seconds=60,
        interval_seconds=5,
        clock=lambda: moments[0],
        sleep=sleep,
        run=run,
    )

    assert receipt["state"] == "ready"
    assert receipt["attempts"] == 2
    assert len(calls) == 4
    assert calls[0][:4] == ("az", "keyvault", "secret", "list")
    assert calls[1][:4] == ("az", "storage", "fs", "list")


def test_private_data_plane_probe_times_out_without_mutation(tmp_path: Path) -> None:
    moments = [0.0]

    def run(command, **_kwargs):
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="")

    def sleep(seconds: float) -> None:
        moments[0] += seconds

    with pytest.raises(ValueError, match="did not become ready"):
        wait_for_private_data_planes(
            context=_context(),
            work_dir=tmp_path,
            timeout_seconds=10,
            interval_seconds=5,
            clock=lambda: moments[0],
            sleep=sleep,
            run=run,
        )


def test_private_data_plane_probe_requires_selected_private_access(tmp_path: Path) -> None:
    context = _context()
    context["key_vault_private_access"] = False

    with pytest.raises(ValueError, match="context is invalid"):
        wait_for_private_data_planes(context=context, work_dir=tmp_path)
