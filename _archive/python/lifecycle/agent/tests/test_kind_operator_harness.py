"""Offline regressions for the opt-in kind harness, not real Operator evidence."""

from collections.abc import Callable
from typing import TYPE_CHECKING
from unittest.mock import Mock

import pytest
from kubernetes import client  # type: ignore[import-untyped]
from kubernetes.client.exceptions import ApiException  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from test_kind_operator import RecordingCluster, _reader, _verify_failure_configuration
else:
    from .test_kind_operator import RecordingCluster, _reader, _verify_failure_configuration


@pytest.mark.parametrize("failure_stage", ["config", "deployment", "service", "token"])
def test_jwks_partial_setup_registers_only_created_resources(
    monkeypatch: pytest.MonkeyPatch, failure_stage: str
) -> None:
    core = Mock()
    apps = Mock()
    cleanup: list[Callable[[], None]] = []
    request = Mock()
    request.addfinalizer.side_effect = cleanup.append
    monkeypatch.setenv("FDAI_OPERATOR_KIND_IMAGE", "example/operator")
    monkeypatch.setattr(client, "AppsV1Api", lambda _: apps)
    stages = {
        "config": core.create_namespaced_config_map,
        "deployment": apps.create_namespaced_deployment,
        "service": core.create_namespaced_service,
    }
    if failure_stage == "token":
        import jwt

        monkeypatch.setattr(jwt, "encode", Mock(side_effect=RuntimeError("injected")))
    else:
        stages[failure_stage].side_effect = RuntimeError("injected")
    generator = _reader((core, "fdai-operator-test", Mock()), request)
    with pytest.raises(RuntimeError, match="injected"):
        next(generator)
    expected = ["config", "deployment", "service", "token"].index(failure_stage)
    assert len(cleanup) == expected
    for finalizer in reversed(cleanup):
        finalizer()
    assert core.delete_namespaced_config_map.call_count == (expected >= 1)
    assert apps.delete_namespaced_deployment.call_count == (expected >= 2)
    assert core.delete_namespaced_service.call_count == (expected >= 3)


def test_completed_schema_jobs_are_distinct() -> None:
    raw = Mock()
    raw.get.return_value = {"status": {"conditions": [{"type": "Complete", "status": "True"}]}}
    cluster = RecordingCluster(raw)
    for _ in range(5):
        cluster.get("Job", "operator-schema-first")
    assert cluster.verified_jobs == {"operator-schema-first"}
    cluster.get("Job", "operator-schema-second")
    assert len(cluster.verified_jobs) == 2
    raw.get.return_value = {"status": {}}
    cluster.get("Job", "operator-schema-incomplete")
    assert len(cluster.verified_jobs) == 2


@pytest.mark.parametrize("data", [None, {}, {"FDAI_API_AUDIENCE": "valid"}])
def test_failure_configuration_requires_explicit_empty_audience(
    data: dict[str, str] | None,
) -> None:
    core = Mock()
    core.read_namespaced_config_map.return_value.data = data
    with pytest.raises(AssertionError, match="explicitly"):
        _verify_failure_configuration(core, "fdai-operator-test")


def test_failure_configuration_requires_existing_config_map() -> None:
    core = Mock()
    core.read_namespaced_config_map.side_effect = ApiException(status=404)
    with pytest.raises(ApiException):
        _verify_failure_configuration(core, "fdai-operator-test")


def test_failure_configuration_accepts_empty_audience() -> None:
    core = Mock()
    core.read_namespaced_config_map.return_value.data = {"FDAI_API_AUDIENCE": ""}
    _verify_failure_configuration(core, "fdai-operator-test")
    core.read_namespaced_config_map.assert_called_once_with(
        "operator-config-failure", "fdai-operator-test", _request_timeout=10
    )
