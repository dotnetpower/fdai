from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest

from fdai.delivery.azure.dev_workload_identity import AsyncAzureCliWorkloadIdentity
from fdai.delivery.azure.workload_identity import ManagedIdentityWorkloadIdentity
from fdai.runtime.bootstrap import (
    _RUNTIME_LOGICAL_TOPICS,
    _build_runtime_saga,
    _build_runtime_workload_identity,
    _case_history_identity_client_id,
    _run_main,
)
from fdai.runtime.bootstrap_lifecycle import (
    raise_required_task_failure as _raise_required_task_failure,
)
from fdai.runtime.bootstrap_lifecycle import runtime_process_lock
from fdai.shared.config.runtime_flags import pantheon_start_enabled
from fdai.shared.providers.testing.state_store import InMemoryStateStore


def test_pantheon_starts_by_default() -> None:
    assert pantheon_start_enabled({}) is True


def test_runtime_multiplexes_startup_readiness_transitions() -> None:
    assert "runtime.readiness.transitions" in _RUNTIME_LOGICAL_TOPICS


@pytest.mark.parametrize("value", ["0", "false", "NO", "off"])
def test_pantheon_requires_explicit_disable(value: str) -> None:
    assert pantheon_start_enabled({"FDAI_START_PANTHEON": value}) is False


@pytest.mark.parametrize("value", ["1", "true", "yes", "on"])
def test_pantheon_accepts_explicit_enable(value: str) -> None:
    assert pantheon_start_enabled({"FDAI_START_PANTHEON": value}) is True


async def test_dev_runtime_uses_explicit_azure_cli_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RUNTIME_ENV", "dev")
    monkeypatch.setenv("FDAI_RUNTIME_LOCAL_AZURE_CLI", "1")

    async with httpx.AsyncClient() as http_client:
        identity = _build_runtime_workload_identity(http_client)

    assert isinstance(identity, AsyncAzureCliWorkloadIdentity)


async def test_non_dev_runtime_keeps_managed_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RUNTIME_ENV", "production")
    monkeypatch.setenv("FDAI_RUNTIME_LOCAL_AZURE_CLI", "1")
    monkeypatch.setenv("IDENTITY_ENDPOINT", "http://127.0.0.1/identity")
    monkeypatch.setenv("IDENTITY_HEADER", "test-header")

    async with httpx.AsyncClient() as http_client:
        identity = _build_runtime_workload_identity(http_client)

    assert isinstance(identity, ManagedIdentityWorkloadIdentity)


async def test_case_history_runtime_requires_dedicated_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RUNTIME_ENV", "production")
    monkeypatch.setenv("IDENTITY_ENDPOINT", "https://identity.local/token")
    monkeypatch.setenv("IDENTITY_HEADER", "test-header")
    monkeypatch.delenv("FDAI_CASE_HISTORY_MI_CLIENT_ID", raising=False)

    async with httpx.AsyncClient() as http_client:
        with pytest.raises(RuntimeError, match="FDAI_CASE_HISTORY_MI_CLIENT_ID"):
            _build_runtime_workload_identity(
                http_client,
                client_id_env="FDAI_CASE_HISTORY_MI_CLIENT_ID",
                require_client_id=True,
            )


async def test_case_history_runtime_selects_dedicated_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json={"access_token": "token", "expires_on": "4102444800"},
        )

    monkeypatch.setenv("RUNTIME_ENV", "production")
    monkeypatch.setenv("IDENTITY_ENDPOINT", "https://identity.local/token")
    monkeypatch.setenv("IDENTITY_HEADER", "test-header")
    monkeypatch.setenv("FDAI_CASE_HISTORY_MI_CLIENT_ID", "case-history-client")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        identity = _build_runtime_workload_identity(
            http_client,
            client_id_env="FDAI_CASE_HISTORY_MI_CLIENT_ID",
            require_client_id=True,
        )
        await identity.get_token("https://storage.azure.com/")

    assert captured[0].url.params["client_id"] == "case-history-client"


def test_case_history_startup_requires_identity_before_runtime_branching() -> None:
    with pytest.raises(RuntimeError, match="FDAI_CASE_HISTORY_MI_CLIENT_ID"):
        _case_history_identity_client_id({"FDAI_CASE_HISTORY_CONTAINER_URL": "https://example"})


def test_case_history_startup_rejects_executor_identity_reuse() -> None:
    with pytest.raises(RuntimeError, match="MUST be distinct"):
        _case_history_identity_client_id(
            {
                "FDAI_CASE_HISTORY_MI_CLIENT_ID": "shared-client",
                "FDAI_MI_CLIENT_ID": "shared-client",
            }
        )


async def test_runtime_saga_uses_durable_state_store_audit() -> None:
    state_store = InMemoryStateStore()
    saga = _build_runtime_saga(state_store)
    assert saga.durable_audit is True

    await saga.on_typed_message(
        "object.forecast-outcome",
        {
            "producer_principal": "Heimdall",
            "correlation_id": "corr-forecast",
            "outcome_id": "outcome-1",
        },
    )

    assert len(tuple(state_store.audit_entries)) == 1


async def test_required_runtime_task_failure_is_not_swallowed() -> None:
    async def fail() -> None:
        raise RuntimeError("retention publisher unavailable")

    task = asyncio.create_task(fail(), name="case-history-retention-ticks")
    await asyncio.gather(task, return_exceptions=True)

    with pytest.raises(RuntimeError, match="case-history-retention-ticks") as captured:
        _raise_required_task_failure({task})
    assert isinstance(captured.value.__cause__, RuntimeError)
    assert str(captured.value.__cause__) == "retention publisher unavailable"


def test_runtime_main_returns_async_result() -> None:
    async def complete() -> int:
        return 7

    assert _run_main(complete) == 7


def test_runtime_main_maps_keyboard_interrupt_to_clean_exit() -> None:
    async def interrupted() -> int:
        raise KeyboardInterrupt

    assert _run_main(interrupted) == 0


def test_runtime_process_lock_rejects_duplicate_local_instance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FDAI_RUNTIME_LOCK_FILE", str(tmp_path / "runtime.lock"))

    with runtime_process_lock():
        with pytest.raises(RuntimeError, match="already active"):
            with runtime_process_lock():
                pass


def test_runtime_process_lock_defaults_for_local_azure_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("FDAI_RUNTIME_LOCK_FILE", raising=False)
    monkeypatch.setenv("RUNTIME_ENV", "dev")
    monkeypatch.setenv("FDAI_RUNTIME_LOCAL_AZURE_CLI", "1")

    with runtime_process_lock():
        assert (tmp_path / ".fdai/core-runtime.lock").is_file()
        with pytest.raises(RuntimeError, match="already active"):
            with runtime_process_lock():
                pass


def test_runtime_process_lock_remains_optional_outside_local_azure_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FDAI_RUNTIME_LOCK_FILE", raising=False)
    monkeypatch.setenv("RUNTIME_ENV", "production")
    monkeypatch.setenv("FDAI_RUNTIME_LOCAL_AZURE_CLI", "1")

    with runtime_process_lock():
        with runtime_process_lock():
            pass
