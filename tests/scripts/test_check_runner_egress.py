"""Runner TLS egress preflight tests."""

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
    / "check-runner-egress.py"
)


@pytest.fixture(scope="module")
def egress_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_runner_egress", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_success_records_only_hashed_sorted_refs(egress_module: ModuleType) -> None:
    connected: list[tuple[str, float]] = []

    evidence = egress_module.run_checks(
        ["management.azure.com", "api.github.com", "api.github.com"],
        connector=lambda host, timeout: connected.append((host, timeout)),
    )

    assert connected == [("api.github.com", 5.0), ("management.azure.com", 5.0)]
    serialized = str(evidence)
    assert "api.github.com" not in serialized
    assert "management.azure.com" not in serialized
    assert evidence["checked_count"] == 2


def test_failed_endpoint_raises_with_hashed_ref(egress_module: ModuleType) -> None:
    def fail(_host: str, _timeout: float) -> None:
        raise OSError("customer endpoint detail")

    with pytest.raises(egress_module.EgressPreflightError) as error:
        egress_module.run_checks(["private.example.com"], connector=fail)

    assert "private.example.com" not in str(error.value)
    assert "customer endpoint detail" not in str(error.value)


@pytest.mark.parametrize(
    "hosts",
    ([], ["localhost"], ["https://example.com"], ["example.com"] * 33),
)
def test_invalid_or_unbounded_hosts_fail(egress_module: ModuleType, hosts: list[str]) -> None:
    with pytest.raises(egress_module.EgressPreflightError):
        egress_module.run_checks(hosts, connector=lambda _host, _timeout: None)
