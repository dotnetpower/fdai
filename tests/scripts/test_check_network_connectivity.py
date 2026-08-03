"""DNS, IP policy, port reachability, and action-summary tests."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

_SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "deployment"
    / "azure"
    / "network_connectivity.py"
)


@pytest.fixture(scope="module")
def connectivity_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_network_connectivity", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_private_runtime_discovers_required_and_optional_endpoints(
    connectivity_module: ModuleType,
) -> None:
    checks, issues = connectivity_module.build_checks(
        "runtime-private",
        {
            "KAFKA_BOOTSTRAP_SERVERS": "events.example.com:9093",
            "POSTGRES_HOST": "db.example.com",
            "FDAI_LLM_ENDPOINT": "https://models.example.com/",
        },
        (),
    )

    by_id = {check.id: check for check in checks}
    assert issues == ()
    assert by_id["event-bus-primary"].port == 9093
    assert by_id["state-store"].port == 5432
    assert by_id["model-endpoint"].port == 443
    assert by_id["event-bus-primary"].expected_ip == "private"
    assert by_id["identity"].expected_ip == "public"


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://models.example.com/openai/deployments/model",
        "https://models.example.com?api-version=2026-01-01",
        "https://models.example.com#deployment",
        "models.example.com/openai/deployments/model",
    ],
)
def test_discovered_endpoint_rejects_non_origin_url(
    connectivity_module: ModuleType,
    endpoint: str,
) -> None:
    with pytest.raises(connectivity_module.ConnectivityInputError, match="origin"):
        connectivity_module.build_checks(
            "runtime-private",
            {
                "KAFKA_BOOTSTRAP_SERVERS": "events.example.com:9093",
                "POSTGRES_HOST": "db.example.com",
                "FDAI_LLM_ENDPOINT": endpoint,
            },
            (),
        )


def test_private_dns_mismatch_produces_split_dns_action(
    connectivity_module: ModuleType,
) -> None:
    check = connectivity_module.EndpointCheck(
        id="event-bus-primary",
        host="events.example.com",
        port=9093,
        required=True,
        expected_ip="private",
    )

    report = connectivity_module.run_checks(
        (check,),
        resolver=lambda _host, _port: ("203.0.113.10",),
        connector=lambda _address, _port, _timeout: None,
    )

    assert report["status"] == "fail"
    assert report["checks"][0]["status"] == "fail"
    assert report["checks"][0]["reason"] == "ip_policy_mismatch"
    assert "split DNS" in report["actions_required"][0]["action"]


def test_tcp_failure_names_required_port_action(connectivity_module: ModuleType) -> None:
    check = connectivity_module.EndpointCheck(
        id="state-store",
        host="db.example.com",
        port=5432,
        required=True,
        expected_ip="private",
    )

    def fail(_address: str, _port: int, _timeout: float) -> None:
        raise OSError("customer network detail")

    report = connectivity_module.run_checks(
        (check,),
        resolver=lambda _host, _port: ("10.0.0.8",),
        connector=fail,
    )

    assert report["status"] == "fail"
    action = report["actions_required"][0]["action"]
    assert "TCP 5432" in action
    assert "customer network detail" not in str(report)


def test_optional_failure_warns_without_blocking(connectivity_module: ModuleType) -> None:
    check = connectivity_module.EndpointCheck(
        id="optional-webhook",
        host="hooks.example.com",
        port=443,
        required=False,
        expected_ip="any",
    )

    report = connectivity_module.run_checks(
        (check,),
        resolver=lambda _host, _port: (_ for _ in ()).throw(OSError("no dns")),
        connector=lambda _address, _port, _timeout: None,
    )

    assert report["status"] == "warn"
    assert connectivity_module.exit_code(report) == 0


def test_missing_required_env_produces_configuration_actions(
    connectivity_module: ModuleType,
) -> None:
    checks, issues = connectivity_module.build_checks("runtime-private", {}, ())
    report = connectivity_module.run_checks(
        checks,
        resolver=lambda _host, _port: ("8.8.8.8",),
        connector=lambda _address, _port, _timeout: None,
    )

    report = connectivity_module.add_input_issues(report, issues)

    assert report["status"] == "fail"
    assert {action["id"] for action in report["actions_required"]} >= {
        "event-bus-primary",
        "state-store",
    }
    assert "KAFKA_BOOTSTRAP_SERVERS" in str(report["actions_required"])


def test_redaction_removes_hosts_and_addresses(connectivity_module: ModuleType) -> None:
    check = connectivity_module.EndpointCheck(
        id="model-endpoint",
        host="models.example.com",
        port=443,
        required=True,
        expected_ip="private",
    )
    report = connectivity_module.run_checks(
        (check,),
        resolver=lambda _host, _port: ("10.0.0.9",),
        connector=lambda _address, _port, _timeout: None,
    )

    redacted = connectivity_module.redact_report(report)

    assert "models.example.com" not in str(redacted)
    assert "10.0.0.9" not in str(redacted)
    assert redacted["checks"][0]["host_ref"].startswith("sha256:")


def test_manifest_rejects_invalid_or_unbounded_checks(connectivity_module: ModuleType) -> None:
    with pytest.raises(connectivity_module.ConnectivityInputError):
        connectivity_module.parse_manifest(
            {
                "schema_version": "fdai.network-connectivity-manifest.v1",
                "checks": [
                    {
                        "id": "bad",
                        "host": "https://example.com",
                        "port": 443,
                        "required": True,
                        "expected_ip": "private",
                    }
                ],
            }
        )
