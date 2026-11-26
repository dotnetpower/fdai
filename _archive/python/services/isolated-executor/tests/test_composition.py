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


async def test_composition_builders_and_human_access_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dataclasses import replace
    from uuid import UUID

    import httpx
    from fdai_executor_service import composition
    from fdai_executor_service.human_access_binding import (
        HumanAccessDirectApiRouter,
        human_access_role_groups,
        require_human_access_identity,
    )
    from fdai_service_contracts.executor import (
        DirectApiOutcome,
        DirectApiReceipt,
        DirectApiRequest,
        Mode,
    )

    client = composition.new_http_client()
    await client.aclose()

    monkeypatch.delenv("FDAI_STATE_STORE_DSN", raising=False)
    with pytest.raises(RuntimeError, match="FDAI_STATE_STORE_DSN MUST be configured"):
        composition.build_audit_store()

    monkeypatch.setenv("FDAI_STATE_STORE_DSN", "postgresql://example.invalid/fdai")
    assert composition.build_audit_store() is not None
    assert composition.build_idempotency_store() is not None
    assert composition.build_safeguard_bundle_store() is not None
    assert composition.build_resource_lock() is not None

    monkeypatch.setenv("FDAI_RESOURCE_LOCK_TIMEOUT_MS", "not-an-int")
    with pytest.raises(RuntimeError, match="MUST be an integer"):
        composition.build_resource_lock()

    monkeypatch.setenv("FDAI_RESOURCE_LOCK_TIMEOUT_MS", "-1")
    with pytest.raises(RuntimeError, match="MUST be non-negative"):
        composition.build_resource_lock()
    monkeypatch.delenv("FDAI_RESOURCE_LOCK_TIMEOUT_MS", raising=False)

    monkeypatch.delenv("FDAI_TEST_MI", raising=False)
    async with httpx.AsyncClient() as http_client:
        with pytest.raises(RuntimeError, match="MUST identify the dedicated workload identity"):
            composition.build_workload_identity(
                http_client, client_id_env="FDAI_TEST_MI", require_client_id=True
            )
        monkeypatch.setenv("FDAI_TEST_MI", "00000000-0000-0000-0000-000000000010")
        monkeypatch.setenv("IDENTITY_ENDPOINT", "https://identity.example/token")
        monkeypatch.setenv("IDENTITY_HEADER", "header-secret")
        assert (
            composition.build_workload_identity(
                http_client, client_id_env="FDAI_TEST_MI", require_client_id=True
            )
            is not None
        )

        # Kubernetes validation errors for allowed_namespaces and text_fields
        bad_ns = json.loads(_kubernetes_environment()["FDAI_KUBERNETES_DIRECT_API_JSON"])
        bad_ns["allowed_namespaces"] = []
        monkeypatch.setenv("FDAI_KUBERNETES_DIRECT_API_JSON", json.dumps(bad_ns))
        with pytest.raises(RuntimeError, match="non-empty string array"):
            _build_kubernetes_direct_api()

        bad_txt = json.loads(_kubernetes_environment()["FDAI_KUBERNETES_DIRECT_API_JSON"])
        bad_txt["cluster_ref"] = " leading-space "
        monkeypatch.setenv("FDAI_KUBERNETES_DIRECT_API_JSON", json.dumps(bad_txt))
        with pytest.raises(RuntimeError, match="non-empty strings"):
            _build_kubernetes_direct_api()
        monkeypatch.delenv("FDAI_KUBERNETES_DIRECT_API_JSON", raising=False)

        # Gateway URL without audience
        monkeypatch.setenv("FDAI_DEV_OPERATIONS_GATEWAY_URL", "https://gateway.example.com")
        monkeypatch.delenv("FDAI_DEV_OPERATIONS_GATEWAY_AUDIENCE", raising=False)
        with pytest.raises(RuntimeError, match="configured together"):
            composition.build_direct_api_effect_executor(
                audit_store=composition.build_audit_store(),
                resource_lock=composition.build_resource_lock(),
                idempotency=composition.build_idempotency_store(),
                http_client=http_client,
                identities={},
            )

        # No adapter configured
        monkeypatch.delenv("FDAI_DEV_OPERATIONS_GATEWAY_URL", raising=False)
        monkeypatch.delenv("AZURE_SUBSCRIPTION_ID", raising=False)
        with pytest.raises(RuntimeError, match="requires a direct-API adapter"):
            composition.build_direct_api_effect_executor(
                audit_store=composition.build_audit_store(),
                resource_lock=composition.build_resource_lock(),
                idempotency=composition.build_idempotency_store(),
                http_client=http_client,
                identities={},
            )

        # Full composition with gateway, subscription_tag, kubernetes, and human_access
        monkeypatch.setenv("FDAI_DEV_OPERATIONS_GATEWAY_URL", "https://gateway.example.com")
        monkeypatch.setenv("FDAI_DEV_OPERATIONS_GATEWAY_AUDIENCE", "api://gateway")
        monkeypatch.setenv("AZURE_SUBSCRIPTION_ID", "00000000-0000-0000-0000-000000000001")
        monkeypatch.setenv(
            "FDAI_KUBERNETES_DIRECT_API_JSON",
            _kubernetes_environment()["FDAI_KUBERNETES_DIRECT_API_JSON"],
        )
        role_groups_raw = json.dumps(
            {
                "Owner": "00000000-0000-0000-0000-000000000101",
                "Approver": "00000000-0000-0000-0000-000000000102",
                "Contributor": "00000000-0000-0000-0000-000000000103",
                "Reader": "00000000-0000-0000-0000-000000000104",
            }
        )
        monkeypatch.setenv("FDAI_HUMAN_ACCESS_ROLE_GROUPS_JSON", role_groups_raw)
        monkeypatch.setenv("FDAI_HUMAN_ACCESS_MI_CLIENT_ID", "00000000-0000-0000-0000-000000000099")
        full_exec = composition.build_direct_api_effect_executor(
            audit_store=composition.build_audit_store(),
            resource_lock=composition.build_resource_lock(),
            idempotency=composition.build_idempotency_store(),
            http_client=http_client,
            identities={"identity/change": _Identity()},
        )
        assert full_exec is not None

    # human_access_binding tests
    assert human_access_role_groups({}) is None
    with pytest.raises(ValueError, match="distinct dedicated isolated workload identity"):
        require_human_access_identity(
            {
                "FDAI_HUMAN_ACCESS_MI_CLIENT_ID": "same-id",
                "FDAI_CHANGE_MI_CLIENT_ID": "SAME-ID",
            }
        )

    class _Route:
        def __init__(self, tag: str, *, with_status: bool = True) -> None:
            self.tag = tag
            if with_status:
                self.operation_status = self._status  # type: ignore[method-assign]

        async def execute(self, _req: DirectApiRequest) -> DirectApiReceipt:
            return DirectApiReceipt(outcome=DirectApiOutcome.SUCCEEDED, receipt_ref=self.tag)

        async def _status(self, _req: DirectApiRequest) -> DirectApiReceipt | None:
            return DirectApiReceipt(
                outcome=DirectApiOutcome.ALREADY_APPLIED, receipt_ref=f"{self.tag}:status"
            )

    req_ha = DirectApiRequest(
        action_id=UUID(int=1),
        idempotency_key="k1",
        action_type_name="ops.apply-human-access",
        rule_ids=("r1",),
        resource_ref="res1",
        arguments={},
        labels=("enforce",),
        mode=Mode.ENFORCE,
    )
    req_gw = replace(req_ha, action_type_name="ops.start-vm")
    router = HumanAccessDirectApiRouter(_Route("ha"), _Route("gw"))  # type: ignore[arg-type]
    assert (await router.execute(req_ha)).receipt_ref == "ha"
    assert (await router.execute(req_gw)).receipt_ref == "gw"
    assert (await router.operation_status(req_ha)).receipt_ref == "ha:status"  # type: ignore[union-attr]
    assert (await router.operation_status(req_gw)).receipt_ref == "gw:status"  # type: ignore[union-attr]

    router_no_gw_status = HumanAccessDirectApiRouter(
        _Route("ha"),
        _Route("gw", with_status=False),  # type: ignore[arg-type]
    )
    assert await router_no_gw_status.operation_status(req_gw) is None


async def test_cli_runtime_config_supervisor_and_run_entrypoints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import httpx
    from fdai_executor_service import cli

    base_env = {
        "RUNTIME_ENV": "prod",
        "FDAI_EXECUTION_VENUE": "deployed",
        "FDAI_ISOLATED_EXECUTOR_DEPLOYED": "1",
        "KAFKA_BOOTSTRAP_SERVERS": "events.example.invalid:9093",
        "FDAI_STATE_STORE_DSN": "postgresql://example.invalid/fdai",
        "FDAI_DATABASE_ROLE": "fdai_executor",
        "FDAI_ISOLATED_EXECUTOR_MI_CLIENT_ID": "00000000-0000-0000-0000-000000000001",
    }

    for override, match in [
        ({"FDAI_ISOLATED_EXECUTOR_DEPLOYED": "0"}, "MUST select the deployed"),
        ({"FDAI_DATABASE_ROLE": "postgres"}, "MUST be fdai_executor"),
        (
            {
                "FDAI_ISOLATED_EXECUTOR_AUTHORITY_CUTOVER": "1",
                "FDAI_DEV_OPERATIONS_GATEWAY_URL": "https://gateway.example.com",
            },
            "configured together",
        ),
        (
            {
                "FDAI_EXECUTOR_COMMAND_TOPIC": "same",
                "FDAI_EXECUTOR_RECEIPT_TOPIC": "same",
            },
            "topics MUST be distinct",
        ),
        ({"KAFKA_TOPIC_DLQ_SUFFIX": "   "}, "DLQ_SUFFIX MUST NOT be empty"),
        ({"FDAI_ISOLATED_EXECUTOR_HEALTH_PORT": "bad"}, "MUST be an integer"),
        ({"FDAI_ISOLATED_EXECUTOR_HEALTH_PORT": "70000"}, "between 1 and 65535"),
        ({"FDAI_ISOLATED_EXECUTOR_INSTANCE_ID": "x" * 513}, "bounded and non-empty"),
        ({"RUNTIME_ENV": ""}, "RUNTIME_ENV MUST be configured"),
    ]:
        with pytest.raises(RuntimeError, match=match):
            cli.IsolatedExecutorRuntimeConfig.from_env({**base_env, **override})

    cutover_env = {
        **base_env,
        "FDAI_ISOLATED_EXECUTOR_AUTHORITY_CUTOVER": "1",
        "FDAI_DEV_OPERATIONS_GATEWAY_URL": "https://gateway.example.com",
        "FDAI_DEV_OPERATIONS_GATEWAY_AUDIENCE": "api://gateway",
        "FDAI_CHANGE_MI_CLIENT_ID": "00000000-0000-0000-0000-000000000011",
        "FDAI_RESILIENCE_MI_CLIENT_ID": "00000000-0000-0000-0000-000000000012",
        "FDAI_FINOPS_MI_CLIENT_ID": "00000000-0000-0000-0000-000000000013",
        "FDAI_HUMAN_ACCESS_MI_CLIENT_ID": "00000000-0000-0000-0000-000000000014",
        "FDAI_HUMAN_ACCESS_ROLE_GROUPS_JSON": json.dumps(
            {
                "Owner": "00000000-0000-0000-0000-000000000101",
                "Approver": "00000000-0000-0000-0000-000000000102",
                "Contributor": "00000000-0000-0000-0000-000000000103",
                "Reader": "00000000-0000-0000-0000-000000000104",
            }
        ),
        "FDAI_ISOLATED_EXECUTOR_INSTANCE_ID": "explicit-instance",
    }
    for k, v in cutover_env.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("IDENTITY_ENDPOINT", "https://identity.example/token")
    monkeypatch.setenv("IDENTITY_HEADER", "secret")

    cutover_cfg = cli.IsolatedExecutorRuntimeConfig.from_env(cutover_env)
    assert cutover_cfg.executor_instance_id == "explicit-instance"

    shadow_cfg = cli.IsolatedExecutorRuntimeConfig.from_env(
        {
            "RUNTIME_ENV": "dev",
            "FDAI_EXECUTION_VENUE": "local",
            "KAFKA_BOOTSTRAP_SERVERS": "127.0.0.1:19092",
            "FDAI_STATE_STORE_DSN": "postgresql://example.invalid/fdai",
            "FDAI_DATABASE_ROLE": "fdai_executor",
        }
    )

    async with httpx.AsyncClient() as http_client:
        sup_shadow = cli.build_isolated_executor_supervisor(
            config=shadow_cfg, http_client=http_client
        )
        sup_cutover = cli.build_isolated_executor_supervisor(
            config=cutover_cfg, http_client=http_client
        )
        assert sup_shadow.ready is False
        assert sup_cutover.ready is False
        for check in sup_shadow._readiness_checks:
            assert check() is False

    class _FakeSupervisor:
        async def run(self, *, stop: object) -> int:
            assert stop is not None
            return 0

    monkeypatch.setattr(cli, "install_shutdown_signals", lambda: object())
    monkeypatch.setattr(
        cli, "build_isolated_executor_supervisor", lambda **_kwargs: _FakeSupervisor()
    )
    assert await cli._run() == 0

    def fail_build(**_kwargs: object) -> None:
        raise RuntimeError("build failed")

    monkeypatch.setattr(cli, "build_isolated_executor_supervisor", fail_build)
    with pytest.raises(RuntimeError, match="build failed"):
        await cli._run()

    monkeypatch.setattr(cli, "run_main", lambda fn: 0 if callable(fn) else 1)
    assert cli.main() == 0
