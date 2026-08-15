from __future__ import annotations

import importlib.util
import io
import sys
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any
from urllib.error import HTTPError

import pytest

_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _ROOT / "scripts/deployment/azure/run_live_preflight.py"
sys.path.insert(0, str(_SCRIPT.parent))
_SPEC = importlib.util.spec_from_file_location("run_live_preflight", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)

from live_preflight import transport  # noqa: E402 - imported after adding the script package root.


class _Reader:
    def __init__(self) -> None:
        self.policy_assignments: list[dict[str, Any]] = []
        self.policy_definitions: dict[str, dict[str, Any]] = {}
        self.usages = [{"name": {"value": "cores"}, "currentValue": 1, "limit": 10}]
        self.roles = [
            {"roleDefinitionId": "/roles/event-role", "scope": "/event-hubs/topic"},
            {
                "roleDefinitionId": "/roles/secret-role",
                "scope": "/providers/Microsoft.KeyVault/vaults/example",
            },
        ]
        self.secret_statuses = {"state-dsn": 200}

    def get_json(self, path: str, *, api_version: str) -> dict[str, Any]:
        del api_version
        return self.policy_definitions[path]

    def get_values(
        self,
        path: str,
        *,
        api_version: str,
        params: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        del api_version, params
        return self.usages if path.endswith("/usages") else self.policy_assignments

    def query_role_assignments(
        self, *, subscription_id: str, principal_id: str
    ) -> list[dict[str, Any]]:
        del subscription_id, principal_id
        return self.roles

    def secret_status(self, *, vault_endpoint: str, secret_name: str) -> int:
        del vault_endpoint
        return self.secret_statuses[secret_name]


class _Response(AbstractContextManager["_Response"]):
    def __init__(self, status: int, payload: bytes) -> None:
        self.status = status
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __exit__(self, *args: object) -> None:
        del args


def _profile() -> dict[str, Any]:
    return {
        "schema_version": "fdai.deployment.preflight-input.v1",
        "scope": "resource-group-equivalent:deployment",
        "mode": "enforce",
        "resource_types": [],
        "egress_hosts": [],
        "terraform_resource_type_map": {"azurerm_eventhub": "event.stream"},
        "policy": {
            "denied_resource_types": [],
            "blocked_egress_hosts": [],
        },
        "azure_live": {
            "required_categories": [
                "policy_guardrail",
                "quota_capacity",
                "identity_rbac",
                "secret_config",
            ],
            "resource_group": "example-group",
            "arm_resource_type_map": {"event.stream": "Microsoft.EventHub/namespaces/eventhubs"},
            "quota_checks": [{"quota_name": "cores", "required": 1}],
            "identity_rbac": {
                "executor_principal_id": "executor-principal",
                "event_role_definition_id": "event-role",
                "secret_role_definition_id": "secret-role",
            },
            "key_vault": {
                "vault_endpoint": "https://example.vault.azure.net/",
                "required_secret_names": ["state-dsn"],
            },
        },
    }


def _plan() -> dict[str, Any]:
    return {
        "format_version": "1.2",
        "resource_changes": [
            {
                "mode": "managed",
                "type": "azurerm_eventhub",
                "change": {"actions": ["create"]},
            }
        ],
    }


def _environment() -> dict[str, Any]:
    return {
        "environment": "dev",
        "azure": {
            "subscription_id": "00000000-0000-0000-0000-000000000001",
            "tenant_id": "00000000-0000-0000-0000-000000000002",
            "region": "koreacentral",
        },
    }


def test_live_preflight_reports_all_categories_clear() -> None:
    result = _MODULE.run_preflight(_profile(), _plan(), _environment(), _Reader())

    report = result["report"]
    assert report["verdict"] == "clear"
    assert report["blocks_deploy"] is False
    assert {check["category"] for check in report["checks"]} == {
        "policy_guardrail",
        "quota_capacity",
        "identity_rbac",
        "secret_config",
    }


def test_live_preflight_blocks_grounded_policy_quota_rbac_and_secret_failures() -> None:
    reader = _Reader()
    reader.policy_assignments = [
        {
            "properties": {
                "policyDefinitionId": "/providers/policyDefinitions/deny-event-hubs",
                "parameters": {},
            }
        }
    ]
    reader.policy_definitions = {
        "/providers/policyDefinitions/deny-event-hubs": {
            "name": "deny-event-hubs",
            "properties": {
                "policyRule": {
                    "if": {
                        "field": "type",
                        "equals": "Microsoft.EventHub/namespaces/eventhubs",
                    },
                    "then": {"effect": "deny"},
                }
            },
        }
    }
    reader.usages[0]["currentValue"] = 10
    reader.roles = []
    reader.secret_statuses["state-dsn"] = 404

    result = _MODULE.run_preflight(_profile(), _plan(), _environment(), reader)

    report = result["report"]
    assert report["verdict"] == "blocked"
    assert report["blocks_deploy"] is True
    assert {finding["category"] for finding in report["findings"]} == {
        "policy_guardrail",
        "quota_capacity",
        "identity_rbac",
        "secret_config",
    }
    assert {check["status"] for check in report["checks"]} == {"blocked"}


def test_live_preflight_fails_closed_on_unmapped_created_resource() -> None:
    profile = _profile()
    profile["terraform_resource_type_map"] = {}

    with pytest.raises(_MODULE.PreflightError, match="mapping is incomplete"):
        _MODULE.run_preflight(profile, _plan(), _environment(), _Reader())


def test_azure_reader_retries_transient_throttle_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    delays: list[float] = []

    def fake_urlopen(request: object, *, timeout: int) -> _Response:
        nonlocal calls
        del request, timeout
        calls += 1
        if calls < 3:
            raise HTTPError("https://management.azure.com", 429, "throttled", {}, io.BytesIO())
        return _Response(200, b'{"value":"ok"}')

    monkeypatch.setattr(transport, "urlopen", fake_urlopen)
    reader = transport.AzureCliReader(
        subscription_id="00000000-0000-0000-0000-000000000000",
        retry_delays_seconds=(0.1, 0.2),
        sleep=delays.append,
    )
    reader._tokens["https://management.azure.com"] = "test-token"

    result = reader.get_json("/subscriptions/example", api_version="2024-01-01")

    assert result == {"value": "ok"}
    assert calls == 3
    assert delays == [0.1, 0.2]


def test_azure_reader_stops_at_the_overall_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = iter([0.0, 0.0, 301.0, 301.0, 301.0])

    def fake_urlopen(request: object, *, timeout: float) -> _Response:
        del request, timeout
        raise HTTPError("https://management.azure.com", 503, "busy", {}, io.BytesIO())

    monkeypatch.setattr(transport, "urlopen", fake_urlopen)
    reader = transport.AzureCliReader(
        subscription_id="00000000-0000-0000-0000-000000000000",
        retry_delays_seconds=(0.1, 0.2),
        sleep=lambda _seconds: None,
        monotonic=lambda: next(clock),
    )
    reader._tokens["https://management.azure.com"] = "test-token"

    with pytest.raises(_MODULE.PreflightError, match="bounded 300s preflight deadline"):
        reader.get_json("/subscriptions/example", api_version="2024-01-01")


def test_azure_reader_caps_each_request_by_the_remaining_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[float] = []
    clock = iter([0.0, 295.0, 295.0])

    def fake_urlopen(request: object, *, timeout: float) -> _Response:
        del request
        observed.append(timeout)
        return _Response(200, b'{"value":"ok"}')

    monkeypatch.setattr(transport, "urlopen", fake_urlopen)
    reader = transport.AzureCliReader(
        subscription_id="00000000-0000-0000-0000-000000000000",
        sleep=lambda _seconds: None,
        monotonic=lambda: next(clock),
    )
    reader._tokens["https://management.azure.com"] = "test-token"

    reader.get_json("/subscriptions/example", api_version="2024-01-01")

    assert observed == [5.0]


def test_azure_reader_rejects_an_unusable_overall_deadline() -> None:
    with pytest.raises(ValueError, match="overall deadline MUST be positive"):
        transport.AzureCliReader(
            subscription_id="00000000-0000-0000-0000-000000000000",
            overall_deadline_seconds=0,
        )


def test_azure_reader_does_not_retry_permanent_error(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0
    delays: list[float] = []

    def fake_urlopen(request: object, *, timeout: int) -> _Response:
        nonlocal calls
        del request, timeout
        calls += 1
        raise HTTPError("https://management.azure.com", 403, "forbidden", {}, io.BytesIO())

    monkeypatch.setattr(transport, "urlopen", fake_urlopen)
    reader = transport.AzureCliReader(
        subscription_id="00000000-0000-0000-0000-000000000000",
        sleep=delays.append,
    )
    reader._tokens["https://management.azure.com"] = "test-token"
    reader._tokens["https://vault.azure.net"] = "test-token"

    status = reader.secret_status(
        vault_endpoint="https://example.vault.azure.net",
        secret_name="example",
    )

    assert status == 403
    assert calls == 1
    assert delays == []


def test_azure_reader_bounds_network_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0
    delays: list[float] = []

    def fake_urlopen(request: object, *, timeout: int) -> _Response:
        nonlocal calls
        del request, timeout
        calls += 1
        raise OSError("transient network failure")

    monkeypatch.setattr(transport, "urlopen", fake_urlopen)
    reader = transport.AzureCliReader(
        subscription_id="00000000-0000-0000-0000-000000000000",
        retry_delays_seconds=(0.1, 0.2),
        sleep=delays.append,
    )
    reader._tokens["https://management.azure.com"] = "test-token"

    with pytest.raises(transport.PreflightError, match="complete result"):
        reader.get_json("/subscriptions/example", api_version="2024-01-01")

    assert calls == 3
    assert delays == [0.1, 0.2]
