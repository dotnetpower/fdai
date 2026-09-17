from __future__ import annotations

import importlib.util
import os
import subprocess
from pathlib import Path
from types import ModuleType

import pytest

_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _ROOT / "scripts/deployment/local/collect-cost-governance-analytics.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("collect_cost_governance_analytics", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_local_wrapper_binds_state_store_and_existing_cli_subscription(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load()
    monkeypatch.setenv("FDAI_STATE_STORE_DSN", "postgresql://localhost/fdai")
    monkeypatch.setenv("AZURE_SUBSCRIPTION_ID", "00000000-0000-0000-0000-000000000000")
    monkeypatch.delenv("FDAI_COST_STORE_DSN", raising=False)
    monkeypatch.delenv("FDAI_COST_SCOPE_ID", raising=False)

    module._configure_local_environment()

    assert os.environ["FDAI_EXECUTION_VENUE"] == "local"
    assert os.environ["FDAI_COST_STORE_DSN"] == "postgresql://localhost/fdai"
    assert os.environ["FDAI_COST_SCOPE_ID"] == (
        "subscriptions/00000000-0000-0000-0000-000000000000"
    )


def test_local_wrapper_discovers_subscription_without_exposing_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load()
    monkeypatch.delenv("AZURE_SUBSCRIPTION_ID", raising=False)
    monkeypatch.delenv("FDAI_COST_SCOPE_ID", raising=False)
    monkeypatch.setenv("FDAI_STATE_STORE_DSN", "postgresql://localhost/fdai")
    calls: list[list[str]] = []

    def run(arguments: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        calls.append(arguments)
        return subprocess.CompletedProcess(
            arguments,
            0,
            "00000000-0000-0000-0000-000000000000\n",
            "",
        )

    monkeypatch.setattr(module.subprocess, "run", run)
    module._configure_local_environment()

    assert calls == [["az", "account", "show", "--query", "id", "--output", "tsv"]]
    assert all("token" not in argument.casefold() for argument in calls[0])
