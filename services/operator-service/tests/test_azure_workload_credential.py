"""Azure federation must not fall back to a different workload identity."""

from __future__ import annotations

import pytest
from fdai_operator_service.adapters import azure_identity

CLIENT = "00000000-0000-0000-0000-000000000001"
TENANT = "00000000-0000-0000-0000-000000000002"


def _environment():
    return {
        "AZURE_CLIENT_ID": CLIENT,
        "AZURE_TENANT_ID": TENANT,
        "AZURE_FEDERATED_TOKEN_FILE": "/var/run/secrets/azure/tokens/token",
    }


def test_federated_identity_uses_only_explicit_sdk_inputs(monkeypatch):
    calls = []
    monkeypatch.setattr(
        azure_identity,
        "ManagedIdentityCredential",
        lambda **_: pytest.fail("MI fallback is forbidden"),
    )
    credential = object()
    monkeypatch.setattr(
        azure_identity,
        "WorkloadIdentityCredential",
        lambda **kwargs: calls.append(kwargs) or credential,
    )
    assert (
        azure_identity.create_workload_credential(environment=_environment(), client_id=CLIENT)
        is credential
    )
    assert calls == [
        {
            "tenant_id": TENANT,
            "client_id": CLIENT,
            "token_file_path": _environment()["AZURE_FEDERATED_TOKEN_FILE"],
        }
    ]


@pytest.mark.parametrize(
    "field,value",
    [
        ("AZURE_TENANT_ID", ""),
        ("AZURE_CLIENT_ID", ""),
        ("AZURE_FEDERATED_TOKEN_FILE", ""),
        ("AZURE_FEDERATED_TOKEN_FILE", "relative/token"),
    ],
)
def test_incomplete_federation_never_constructs_a_fallback(monkeypatch, field, value):
    monkeypatch.setattr(
        azure_identity,
        "ManagedIdentityCredential",
        lambda **_: pytest.fail("MI fallback is forbidden"),
    )
    environment = _environment()
    environment[field] = value
    with pytest.raises(ValueError, match="AKS workload identity"):
        azure_identity.create_workload_credential(environment=environment, client_id=CLIENT)


def test_federated_identity_must_match_selected_service():
    with pytest.raises(ValueError, match="selected service"):
        azure_identity.create_workload_credential(environment=_environment(), client_id=TENANT)


@pytest.mark.parametrize("select_command", [False, True])
def test_explicit_command_identity_uses_its_own_exchange(monkeypatch, select_command):
    command_client = "00000000-0000-0000-0000-000000000003"
    environment = {**_environment(), "FDAI_COMMAND_MI_CLIENT_ID": command_client}
    calls = []
    monkeypatch.setattr(
        azure_identity, "ManagedIdentityCredential", lambda **_: pytest.fail("no MI fallback")
    )
    monkeypatch.setattr(
        azure_identity,
        "WorkloadIdentityCredential",
        lambda **kwargs: calls.append(kwargs) or object(),
    )
    azure_identity.create_workload_credential(
        environment=environment, client_id=command_client if select_command else None
    )
    assert calls[0]["client_id"] == (command_client if select_command else CLIENT)
    assert calls[0]["tenant_id"] == TENANT
    assert calls[0]["token_file_path"] == environment["AZURE_FEDERATED_TOKEN_FILE"]
    assert environment["AZURE_CLIENT_ID"] == CLIENT


@pytest.mark.parametrize("selected", ["", "not-a-client", "00000000-0000-0000-0000-000000000004"])
def test_command_declaration_cannot_allow_unrelated_or_invalid_client(monkeypatch, selected):
    environment = {
        **_environment(),
        "FDAI_COMMAND_MI_CLIENT_ID": "00000000-0000-0000-0000-000000000003",
    }
    monkeypatch.setattr(
        azure_identity, "WorkloadIdentityCredential", lambda **_: pytest.fail("invalid client")
    )
    with pytest.raises(ValueError, match="AKS workload identity"):
        azure_identity.create_workload_credential(environment=environment, client_id=selected)


def test_container_apps_retains_selected_attached_identity(monkeypatch):
    calls = []
    monkeypatch.setattr(
        azure_identity,
        "ManagedIdentityCredential",
        lambda **kwargs: calls.append(kwargs) or object(),
    )
    azure_identity.create_workload_credential(environment={}, client_id=CLIENT)
    assert calls == [{"client_id": CLIENT}]
