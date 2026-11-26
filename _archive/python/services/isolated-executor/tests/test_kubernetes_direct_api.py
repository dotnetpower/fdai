import asyncio
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import pytest
from fdai_executor_service.adapters.kubernetes_direct_api import (
    HttpxKubernetesApiTransport,
    KubernetesApiResponse,
    KubernetesDirectApiConfig,
    KubernetesDirectApiExecutor,
    KubernetesDirectApiRouter,
)
from fdai_service_contracts.executor import (
    DirectApiAuthenticationError,
    DirectApiOutcome,
    DirectApiPreconditionError,
    DirectApiPromotionError,
    DirectApiReceipt,
    DirectApiRequest,
    IdentityToken,
    Mode,
)


class _Transport:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, Mapping[str, object], bool]] = []

    async def request(
        self,
        *,
        method: str,
        path: str,
        body: Mapping[str, object],
        dry_run: bool,
    ) -> KubernetesApiResponse:
        self.calls.append((method, path, body, dry_run))
        return KubernetesApiResponse(
            status_code=200,
            body={"metadata": {"uid": "uid-1", "resourceVersion": "rv-2"}},
            resource_version="rv-2",
        )


class _Fallback:
    def __init__(self) -> None:
        self.calls: list[DirectApiRequest] = []

    async def execute(self, request: DirectApiRequest) -> DirectApiReceipt:
        self.calls.append(request)
        return _receipt()


def _receipt() -> DirectApiReceipt:
    return DirectApiReceipt(
        outcome=DirectApiOutcome.SUCCEEDED,
        receipt_ref="fallback:one",
    )


def _request(
    *,
    action_type: str = "ops.scale-out",
    mode: Mode = Mode.ENFORCE,
) -> DirectApiRequest:
    arguments: dict[str, object] = {
        "target_resource_ref": "resource:deployment",
        "reason": "Order backlog exceeded the reviewed operating band.",
        "target_platform": "kubernetes",
        "cluster_ref": "cluster:one",
        "target_kind": "Deployment",
        "namespace": "fdai-runtime",
        "resource_name": "operator-service",
        "target_uid": "uid-1",
        "resource_version": "rv-1",
        "replica_count": 2,
    }
    if action_type == "ops.restart-service":
        arguments["target_resource_ref"] = "resource:pod"
        arguments["target_kind"] = "Pod"
        arguments["resource_name"] = "operator-service-abc"
        arguments["restart_reason"] = arguments.pop("reason")
        arguments["grace_period_seconds"] = 30
        arguments.pop("replica_count")
    if action_type == "ops.rollback-kubernetes-rollout":
        arguments.pop("replica_count")
        arguments["container_images"] = {
            "operator-service": "example.invalid/operator@sha256:" + ("a" * 64)
        }
    return DirectApiRequest(
        action_id=UUID("00000000-0000-0000-0000-000000000001"),
        idempotency_key="operation:kubernetes-one",
        action_type_name=action_type,
        rule_ids=("rule:aks-runtime",),
        resource_ref=str(arguments["target_resource_ref"]),
        arguments=arguments,
        labels=("enforce",) if mode is Mode.ENFORCE else ("shadow",),
        mode=mode,
    )


def _executor(transport: _Transport) -> KubernetesDirectApiExecutor:
    return KubernetesDirectApiExecutor(
        config=KubernetesDirectApiConfig(
            api_server="https://kubernetes.default.svc",
            cluster_ref="cluster:one",
            token_path=Path("/var/run/secrets/token"),
            ca_path=Path("/var/run/secrets/ca.crt"),
            allowed_namespaces=frozenset({"fdai-runtime"}),
        ),
        transport=transport,
    )


async def test_enforce_scale_applies_only_after_server_dry_run() -> None:
    transport = _Transport()

    receipt = await _executor(transport).execute(_request())

    assert receipt.outcome is DirectApiOutcome.SUCCEEDED
    assert receipt.receipt_ref.startswith("kubernetes:")
    assert [(method, dry_run) for method, _, _, dry_run in transport.calls] == [
        ("PUT", True),
        ("PUT", False),
    ]


async def test_restart_uses_uid_and_resource_version_preconditions() -> None:
    transport = _Transport()

    await _executor(transport).execute(_request(action_type="ops.restart-service"))

    method, path, body, dry_run = transport.calls[0]
    assert (method, dry_run) == ("DELETE", True)
    assert path.endswith("/namespaces/fdai-runtime/pods/operator-service-abc")
    assert body["preconditions"] == {"uid": "uid-1", "resourceVersion": "rv-1"}


async def test_rollback_requires_digest_pinned_images() -> None:
    request = _request(action_type="ops.rollback-kubernetes-rollout")
    arguments = {**request.arguments, "container_images": {"operator-service": "latest"}}

    with pytest.raises(DirectApiPreconditionError, match="digest-pinned"):
        await _executor(_Transport()).execute(replace(request, arguments=arguments))


async def test_namespace_outside_allowlist_fails_before_transport() -> None:
    request = _request()
    transport = _Transport()

    with pytest.raises(DirectApiPreconditionError, match="allowlist"):
        await _executor(transport).execute(
            replace(request, arguments={**request.arguments, "namespace": "other"})
        )
    assert transport.calls == []


async def test_enforce_requires_explicit_promotion_label() -> None:
    request = _request()

    with pytest.raises(DirectApiPromotionError, match="enforce label"):
        await _executor(_Transport()).execute(replace(request, labels=()))


async def test_router_uses_fallback_only_for_non_kubernetes_actions() -> None:
    transport = _Transport()
    fallback = _Fallback()
    router = KubernetesDirectApiRouter(_executor(transport), fallback)
    request = _request(action_type="ops.flush-cache")

    receipt = await router.execute(request)

    assert receipt.receipt_ref == "fallback:one"
    assert fallback.calls == [request]
    assert transport.calls == []


class _Identity:
    def __init__(self, token: IdentityToken) -> None:
        self.token = token
        self.audiences: list[str] = []

    async def get_token(self, audience: str) -> IdentityToken:
        self.audiences.append(audience)
        return self.token


def _identity_config() -> KubernetesDirectApiConfig:
    return KubernetesDirectApiConfig(
        api_server="https://kubernetes.example.com",
        cluster_ref="cluster:one",
        token_path=None,
        ca_path=Path("/var/run/certificates/ca.crt"),
        allowed_namespaces=frozenset({"fdai-runtime"}),
        audience="api://kubernetes-test",
    )


@pytest.mark.parametrize("defect", ["expired", "naive", "audience", "empty", "oversized", "header"])
async def test_identity_token_rejected_before_http(
    defect: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = datetime(2026, 9, 17, tzinfo=UTC)
    token = IdentityToken(
        token="test-token",
        expires_at=now + timedelta(minutes=5),
        audience="api://kubernetes-test",
    )
    if defect == "expired":
        token = replace(token, expires_at=now + timedelta(seconds=30))
    elif defect == "naive":
        token = replace(token, expires_at=now.replace(tzinfo=None))
    elif defect == "audience":
        token = replace(token, audience="api://other")
    elif defect == "empty":
        token = replace(token, token="")
    elif defect == "oversized":
        token = replace(token, token="x" * 16_385)
    else:
        token = replace(token, token="invalid\r\nheader")
    identity = _Identity(token)

    def forbidden_http(**kwargs: object) -> None:
        pytest.fail("invalid identity token reached HTTP")

    monkeypatch.setattr(
        "fdai_executor_service.adapters.kubernetes_direct_api.httpx.AsyncClient", forbidden_http
    )
    transport = HttpxKubernetesApiTransport(
        _identity_config(), identity=identity, clock=lambda: now
    )

    with pytest.raises(DirectApiAuthenticationError):
        await transport.request(method="PUT", path="/scale", body={}, dry_run=True)
    assert identity.audiences == ["api://kubernetes-test"]


@pytest.mark.parametrize("identity_ref", [None, "identity/reader", "identity/change"])
async def test_identity_selection_rejects_missing_or_unbound_reference(
    identity_ref: str | None,
) -> None:
    transport = _Transport()
    identity = _Identity(IdentityToken("test-token", datetime(2026, 9, 17, tzinfo=UTC), "test"))
    executor = KubernetesDirectApiExecutor(
        config=_identity_config(), transport=transport, identities={"identity/resilience": identity}
    )
    metadata = {} if identity_ref is None else {"executor_identity_ref": identity_ref}

    with pytest.raises(DirectApiPreconditionError, match="executor_identity_ref"):
        await executor.execute(replace(_request(), metadata=metadata))
    assert transport.calls == []
    assert identity.audiences == []


async def test_identity_transport_preserves_per_command_identity_and_dry_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 9, 17, tzinfo=UTC)
    calls: list[tuple[str, bool]] = []
    config = _identity_config()
    identities = {
        reference: _Identity(
            IdentityToken(reference, now + timedelta(minutes=5), "api://kubernetes-test")
        )
        for reference in ("identity/resilience", "identity/finops")
    }

    class Client:
        def __init__(self, **settings: Any) -> None:
            assert settings["base_url"] == config.api_server
            assert settings["verify"] == str(config.ca_path)
            assert settings["follow_redirects"] is False

        async def __aenter__(self) -> "Client":
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
            await asyncio.sleep(0)
            assert method == "PUT"
            assert path.endswith("/namespaces/fdai-runtime/deployments/operator-service/scale")
            assert kwargs["json"]["metadata"]["uid"] == "uid-1"
            calls.append((kwargs["headers"]["authorization"], kwargs["params"] is not None))
            return httpx.Response(
                200, json={"metadata": {"uid": "uid-1", "resourceVersion": "rv-2"}}
            )

    original_transport = HttpxKubernetesApiTransport
    monkeypatch.setattr(
        "fdai_executor_service.adapters.kubernetes_direct_api.httpx.AsyncClient", Client
    )
    monkeypatch.setattr(
        "fdai_executor_service.adapters.kubernetes_direct_api.HttpxKubernetesApiTransport",
        lambda config, identity: original_transport(config, identity=identity, clock=lambda: now),
    )
    executor = KubernetesDirectApiExecutor(config=config, identities=identities)

    receipts = await asyncio.gather(
        *(
            executor.execute(replace(_request(), metadata={"executor_identity_ref": reference}))
            for reference in identities
        )
    )

    assert all(receipt.outcome is DirectApiOutcome.SUCCEEDED for receipt in receipts)
    for reference, identity in identities.items():
        assert identity.audiences == ["api://kubernetes-test"] * 2
        assert [dry_run for bearer, dry_run in calls if bearer == f"Bearer {reference}"] == [
            True,
            False,
        ]


@pytest.mark.parametrize("failure", ["error", "timeout"])
async def test_identity_acquisition_failure_has_no_fallback(failure: str) -> None:
    class FailingIdentity:
        async def get_token(self, audience: str) -> IdentityToken:
            if failure == "timeout":
                await asyncio.Future()
            raise RuntimeError("provider-private-diagnostic")

    transport = HttpxKubernetesApiTransport(
        replace(_identity_config(), timeout_seconds=0.1), identity=FailingIdentity()
    )
    with pytest.raises(DirectApiAuthenticationError, match="acquisition failed") as caught:
        await transport.request(method="PUT", path="/scale", body={}, dry_run=True)
    assert caught.value.__cause__ is None
    assert caught.value.__suppress_context__ is True
    assert "provider-private-diagnostic" not in str(caught.value)


async def test_file_token_source_stays_compatible(tmp_path: Path) -> None:
    token_path = tmp_path / "token"
    token_path.write_text("test-service-account\n", encoding="utf-8")
    config = replace(_identity_config(), audience=None, token_path=token_path)

    assert await HttpxKubernetesApiTransport(config)._token() == "test-service-account"


async def test_kubernetes_config_transport_executor_and_router_edge_cases(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from fdai_executor_service.adapters.kubernetes_direct_api import _operation
    from fdai_service_contracts.executor import (
        DirectApiError,
        DirectApiPermissionDeniedError,
    )

    base_cfg = _identity_config()
    for kwargs, match in [
        ({"cluster_ref": ""}, "cluster_ref MUST be bounded"),
        ({"allowed_namespaces": frozenset()}, "allowlist MUST contain 1 to 32"),
        ({"allowed_namespaces": frozenset({"BAD_NS"})}, "invalid name"),
        ({"timeout_seconds": 0.0}, "timeout MUST be in"),
        ({"audience": "bad audience"}, "audience MUST be bounded"),
    ]:
        with pytest.raises(ValueError, match=match):
            replace(base_cfg, **kwargs)  # type: ignore[arg-type]

    no_ca = object.__new__(KubernetesDirectApiConfig)
    object.__setattr__(no_ca, "ca_pem", None)
    object.__setattr__(no_ca, "ca_path", None)
    with pytest.raises(ValueError, match="CA source is unavailable"):
        no_ca.tls_verification()

    with pytest.raises(DirectApiAuthenticationError, match="workload identity is unavailable"):
        await HttpxKubernetesApiTransport(base_cfg, identity=None)._token()

    no_tok_cfg = object.__new__(KubernetesDirectApiConfig)
    object.__setattr__(no_tok_cfg, "audience", None)
    object.__setattr__(no_tok_cfg, "token_path", None)
    with pytest.raises(DirectApiAuthenticationError, match="token file is unavailable"):
        await HttpxKubernetesApiTransport(no_tok_cfg)._token()

    missing_file_cfg = replace(base_cfg, audience=None, token_path=tmp_path / "missing")
    with pytest.raises(DirectApiAuthenticationError, match="token file is unavailable"):
        await HttpxKubernetesApiTransport(missing_file_cfg)._token()

    now = datetime(2026, 9, 17, tzinfo=UTC)
    valid_id = _Identity(IdentityToken("tok", now + timedelta(minutes=5), "api://kubernetes-test"))

    def default_resp() -> httpx.Response:
        return httpx.Response(200, json={})

    resp_factory: Any = default_resp

    class _FakeClient:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> "_FakeClient":
            return self

        async def __aexit__(self, *_args: Any) -> None:
            return None

        async def request(self, *_args: Any, **_kwargs: Any) -> httpx.Response:
            res = resp_factory()
            if isinstance(res, Exception):
                raise res
            return res

    monkeypatch.setattr(
        "fdai_executor_service.adapters.kubernetes_direct_api.httpx.AsyncClient", _FakeClient
    )
    http_tx = HttpxKubernetesApiTransport(base_cfg, identity=valid_id, clock=lambda: now)

    for factory, exc_type, match in [
        (lambda: httpx.TimeoutException("timeout"), DirectApiError, "timed out"),
        (lambda: httpx.RequestError("conn"), DirectApiError, "request failed"),
        (lambda: httpx.Response(200, content=b"x" * 262_145), DirectApiError, "exceeded its bound"),
        (lambda: httpx.Response(200, content=b"not-json"), DirectApiError, "invalid JSON"),
        (lambda: httpx.Response(200, json=["list"]), DirectApiError, "non-object body"),
        (lambda: httpx.Response(401, json={}), DirectApiAuthenticationError, "rejected"),
        (lambda: httpx.Response(403, json={}), DirectApiPermissionDeniedError, "denied"),
        (lambda: httpx.Response(409, json={}), DirectApiPreconditionError, "precondition changed"),
        (
            lambda: httpx.Response(500, json={"reason": "boom"}),
            DirectApiError,
            "500:boom",
        ),
    ]:
        resp_factory = factory
        with pytest.raises(exc_type, match=match):
            await http_tx.request(method="GET", path="/p", body={}, dry_run=True)

    # Executor & _operation branches
    tx = _Transport()
    exec_inst = _executor(tx)
    with pytest.raises(DirectApiPreconditionError, match="not registered"):
        await exec_inst.execute(_request(action_type="ops.unknown"))

    shadow_rec = await exec_inst.execute(_request(mode=Mode.SHADOW))
    assert shadow_rec.receipt_ref.startswith("kubernetes-dry-run:")

    rollback_rec = await exec_inst.execute(_request(action_type="ops.rollback-kubernetes-rollout"))
    assert rollback_rec.outcome is DirectApiOutcome.SUCCEEDED

    base_req = _request()
    for arg_override, req_override, match in [
        ({"target_resource_ref": "other"}, {}, "MUST match the action resource_ref"),
        ({"cluster_ref": "other"}, {}, "does not match the bound cluster"),
        ({"resource_name": "BAD_NAME"}, {}, "resource_name is invalid"),
        ({"replica_count": 1001}, {}, "replica_count MUST be an integer"),
        ({"target_kind": "Pod"}, {}, "scale requires target_kind=Deployment"),
        (
            {"target_kind": "Deployment"},
            {"action_type_name": "ops.restart-service"},
            "restart requires target_kind=Pod",
        ),
        (
            {"target_kind": "Pod"},
            {"action_type_name": "ops.rollback-kubernetes-rollout"},
            "rollback requires target_kind=Deployment",
        ),
        (
            {"container_images": {}},
            {"action_type_name": "ops.rollback-kubernetes-rollout"},
            "1 to 32 entries",
        ),
        ({}, {"action_type_name": "ops.unknown"}, "not registered"),
    ]:
        bad_req = replace(
            base_req,
            arguments={**base_req.arguments, **arg_override},
            **req_override,  # type: ignore[arg-type]
        )
        with pytest.raises(DirectApiPreconditionError, match=match):
            _operation(bad_req, exec_inst._config)

    # Router branches
    router_no_fb = KubernetesDirectApiRouter(exec_inst, None)
    assert (await router_no_fb.execute(base_req)).outcome is DirectApiOutcome.SUCCEEDED
    assert await router_no_fb.operation_status(base_req) is None
    other_req = _request(action_type="ops.start-vm")
    with pytest.raises(DirectApiPreconditionError, match="no isolated Executor adapter"):
        await router_no_fb.execute(other_req)
    assert await router_no_fb.operation_status(other_req) is None

    class _StatusFb(_Fallback):
        async def operation_status(self, _req: DirectApiRequest) -> DirectApiReceipt | None:
            return DirectApiReceipt(outcome=DirectApiOutcome.ALREADY_APPLIED, receipt_ref="fb:st")

    router_fb = KubernetesDirectApiRouter(exec_inst, _StatusFb())
    st_rec = await router_fb.operation_status(other_req)
    assert st_rec is not None and st_rec.receipt_ref == "fb:st"
