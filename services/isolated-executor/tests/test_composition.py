import json
import ssl
from datetime import UTC, datetime

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fdai_executor_service.adapters.kubernetes_direct_api import (
    KubernetesDirectApiConfig,
    KubernetesDirectApiExecutor,
)
from fdai_executor_service.composition import _build_kubernetes_direct_api
from fdai_service_contracts.executor import IdentityToken


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


class _Identity:
    async def get_token(self, audience: str) -> IdentityToken:
        raise AssertionError("composition must not acquire a token")


def test_builds_explicit_workload_identity_binding(monkeypatch: pytest.MonkeyPatch) -> None:
    value = json.loads(_kubernetes_environment()["FDAI_KUBERNETES_DIRECT_API_JSON"])
    value.pop("token_path")
    value["audience"] = "api://kubernetes-test"
    monkeypatch.setenv("FDAI_KUBERNETES_DIRECT_API_JSON", json.dumps(value))

    adapter = _build_kubernetes_direct_api(identities={"identity/resilience": _Identity()})

    assert isinstance(adapter, KubernetesDirectApiExecutor)


@pytest.mark.parametrize(
    "defect", ["both", "neither", "empty", "unbound", "unknown", "relative_ca"]
)
def test_invalid_identity_binding_fails_startup(
    defect: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = json.loads(_kubernetes_environment()["FDAI_KUBERNETES_DIRECT_API_JSON"])
    value["audience"] = "api://kubernetes-test"
    if defect != "both":
        value.pop("token_path")
    if defect == "neither":
        value.pop("audience")
    if defect == "empty":
        value["audience"] = ""
    if defect == "relative_ca":
        value["ca_path"] = "relative.crt"
    identities = {"identity/resilience": _Identity()}
    if defect == "unbound":
        identities = {}
    if defect == "unknown":
        identities = {"identity/reader": _Identity()}
    monkeypatch.setenv("FDAI_KUBERNETES_DIRECT_API_JSON", json.dumps(value))

    with pytest.raises(RuntimeError):
        _build_kubernetes_direct_api(identities=identities)


def _public_ca_pem() -> str:
    key = Ed25519PrivateKey.generate()
    name = x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME, "example.invalid")])
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(1)
        .not_valid_before(datetime(2026, 1, 1, tzinfo=UTC))
        .not_valid_after(datetime(2027, 1, 1, tzinfo=UTC))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, algorithm=None)
    )
    return certificate.public_bytes(serialization.Encoding.PEM).decode("ascii")


def test_inline_public_ca_keeps_hostname_and_certificate_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = KubernetesDirectApiConfig(
        api_server="https://kubernetes.example.com",
        cluster_ref="cluster:example",
        token_path=None,
        ca_path=None,
        allowed_namespaces=frozenset({"example-store"}),
        audience="api://kubernetes-test",
        ca_pem=_public_ca_pem(),
    )
    context = config.tls_verification()
    assert isinstance(context, ssl.SSLContext)
    assert context.check_hostname
    assert context.verify_mode == ssl.CERT_REQUIRED
    value = json.loads(_kubernetes_environment()["FDAI_KUBERNETES_DIRECT_API_JSON"])
    value.pop("ca_path")
    value.pop("token_path")
    value.update(ca_pem=config.ca_pem, audience=config.audience)
    monkeypatch.setenv("FDAI_KUBERNETES_DIRECT_API_JSON", json.dumps(value))
    assert isinstance(
        _build_kubernetes_direct_api(identities={"identity/resilience": _Identity()}),
        KubernetesDirectApiExecutor,
    )


@pytest.mark.parametrize("defect", ["both", "neither", "invalid", "private_key", "oversized"])
def test_invalid_inline_ca_fails_before_identity_use(
    defect: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    value = json.loads(_kubernetes_environment()["FDAI_KUBERNETES_DIRECT_API_JSON"])
    if defect != "both":
        value.pop("ca_path")
    if defect != "neither":
        value["ca_pem"] = _public_ca_pem()
    if defect == "invalid":
        value["ca_pem"] = "not-a-certificate"
    if defect == "private_key":
        value["ca_pem"] += "-----BEGIN PRIVATE KEY-----"
    if defect == "oversized":
        value["ca_pem"] = "x" * 65_537
    monkeypatch.setenv("FDAI_KUBERNETES_DIRECT_API_JSON", json.dumps(value))
    with pytest.raises(RuntimeError):
        _build_kubernetes_direct_api()
