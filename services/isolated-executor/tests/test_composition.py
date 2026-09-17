import json

import pytest
from fdai_executor_service.adapters.kubernetes_direct_api import (
    KubernetesDirectApiExecutor,
)
from fdai_executor_service.composition import _build_kubernetes_direct_api


def _kubernetes_environment() -> dict[str, str]:
    return {
        "FDAI_KUBERNETES_DIRECT_API_JSON": json.dumps(
            {
                "api_server": "https://kubernetes.default.svc",
                "cluster_ref": "cluster:one",
                "token_path": "/var/run/secrets/token",
                "ca_path": "/var/run/secrets/ca.crt",
                "allowed_namespaces": ["fdai-runtime"],
            }
        )
    }


def test_builds_kubernetes_only_direct_api_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "FDAI_KUBERNETES_DIRECT_API_JSON",
        _kubernetes_environment()["FDAI_KUBERNETES_DIRECT_API_JSON"],
    )

    adapter = _build_kubernetes_direct_api()

    assert isinstance(adapter, KubernetesDirectApiExecutor)


def test_missing_kubernetes_binding_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FDAI_KUBERNETES_DIRECT_API_JSON", raising=False)

    assert _build_kubernetes_direct_api() is None


@pytest.mark.parametrize(
    "payload",
    [
        "{",
        "{}",
        '{"api_server":"https://kubernetes.default.svc"}',
        (
            '{"api_server":"http://kubernetes.default.svc",'
            '"cluster_ref":"cluster:one","token_path":"/token","ca_path":"/ca",'
            '"allowed_namespaces":["fdai-runtime"]}'
        ),
    ],
)
def test_rejects_invalid_kubernetes_binding(
    payload: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FDAI_KUBERNETES_DIRECT_API_JSON", payload)

    with pytest.raises(RuntimeError):
        _build_kubernetes_direct_api()
