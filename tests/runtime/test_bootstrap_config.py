from __future__ import annotations

import httpx
import pytest

from fdai.delivery.azure.dev_workload_identity import AsyncAzureCliWorkloadIdentity
from fdai.delivery.azure.workload_identity import ManagedIdentityWorkloadIdentity
from fdai.runtime.bootstrap import _build_runtime_workload_identity
from fdai.shared.config.runtime_flags import pantheon_start_enabled


def test_pantheon_starts_by_default() -> None:
    assert pantheon_start_enabled({}) is True


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
