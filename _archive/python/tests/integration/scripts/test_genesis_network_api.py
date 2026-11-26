"""Keep Genesis network discovery on the supported regional provider contract."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts/deployment/azure"))

import genesis_prepare_inputs as inputs  # noqa: E402

SUBSCRIPTION = "00000000-0000-0000-0000-000000000000"
RESOURCE_CASES = [
    (
        "routeTables",
        "properties.routes[].{name:name,prefix:properties.addressPrefix}",
        True,
        [{"name": "example-route", "prefix": "10.20.0.0/16"}],
    ),
    (
        "localNetworkGateways",
        "{name:name,prefixes:properties.localNetworkAddressSpace.addressPrefixes}",
        False,
        {"name": "example-gateway", "prefixes": ["10.30.0.0/16"]},
    ),
]


@pytest.fixture
def azure_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    config = tmp_path / "azure"
    config.mkdir(mode=0o700)
    monkeypatch.setenv("AZURE_CONFIG_DIR", str(config))
    return config


@pytest.mark.parametrize(("kind", "query", "list_result", "payload"), RESOURCE_CASES)
def test_resource_details_use_stable_network_api(
    monkeypatch: pytest.MonkeyPatch,
    azure_config: Path,
    kind: str,
    query: str,
    list_result: bool,
    payload: object,
) -> None:
    resource_id = (
        f"/subscriptions/{SUBSCRIPTION}/resourceGroups/example/"
        f"providers/Microsoft.Network/{kind}/example-resource"
    )
    calls: list[tuple[str, ...]] = []

    def run(arguments: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(arguments)
        assert kwargs["cwd"] == ROOT
        assert kwargs["env"] == {
            "AZURE_CONFIG_DIR": str(azure_config),
            "HOME": str(azure_config.parent),
            "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        }
        assert kwargs["timeout"] == 120
        assert kwargs["check"] is False
        if arguments[:3] == ("/usr/bin/az", "resource", "list"):
            assert arguments[3:7] == (
                "--subscription",
                SUBSCRIPTION,
                "--resource-type",
                f"Microsoft.Network/{kind}",
            )
            assert "--api-version" not in arguments
            return subprocess.CompletedProcess(arguments, 0, json.dumps([resource_id]), "")
        assert arguments[:5] == ("/usr/bin/az", "resource", "show", "--ids", resource_id)
        assert arguments[arguments.index("--query") + 1] == query
        assert "--location" not in arguments
        version = (
            arguments[arguments.index("--api-version") + 1]
            if "--api-version" in arguments
            else "2026-05-01"
        )
        if version != "2024-05-01":
            return subprocess.CompletedProcess(
                arguments, 1, "", "NoRegisteredProviderFound: unsupported regional API version"
            )
        return subprocess.CompletedProcess(arguments, 0, json.dumps(payload), "")

    monkeypatch.setattr(inputs.subprocess, "run", run)

    values = inputs._subscription_resource_values(
        repository_root=ROOT,
        subscription_id=SUBSCRIPTION,
        resource_type=f"Microsoft.Network/{kind}",
        query=query,
        list_result=list_result,
    )

    assert values == (payload if list_result else [payload])
    assert len(calls) == 2
    assert calls[1][calls[1].index("--api-version") + 1] == "2024-05-01"


@pytest.mark.parametrize(("kind", "query", "list_result", "payload"), RESOURCE_CASES)
@pytest.mark.parametrize("reason", ["NoRegisteredProviderFound", "AuthorizationFailed"])
def test_stable_network_read_failure_never_retries_or_discards_evidence(
    monkeypatch: pytest.MonkeyPatch,
    azure_config: Path,
    kind: str,
    query: str,
    list_result: bool,
    payload: object,
    reason: str,
) -> None:
    del azure_config, payload
    resource_id = (
        f"/subscriptions/{SUBSCRIPTION}/resourceGroups/example/"
        f"providers/Microsoft.Network/{kind}/example-resource"
    )
    calls: list[tuple[str, ...]] = []
    private_marker = "synthetic-private-provider-detail"

    def run(arguments: tuple[str, ...], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(arguments)
        if arguments[:3] == ("/usr/bin/az", "resource", "list"):
            return subprocess.CompletedProcess(arguments, 0, json.dumps([resource_id]), "")
        assert arguments[:5] == ("/usr/bin/az", "resource", "show", "--ids", resource_id)
        assert arguments[arguments.index("--api-version") + 1] == "2024-05-01"
        return subprocess.CompletedProcess(arguments, 1, "", f"{reason}: {private_marker}")

    monkeypatch.setattr(inputs.subprocess, "run", run)

    with pytest.raises(ValueError, match="^Genesis input discovery command failed$") as failure:
        inputs._subscription_resource_values(
            repository_root=ROOT,
            subscription_id=SUBSCRIPTION,
            resource_type=f"Microsoft.Network/{kind}",
            query=query,
            list_result=list_result,
        )

    assert private_marker not in str(failure.value)
    assert len(calls) == 2
