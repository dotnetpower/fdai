"""Focused tests for Executor-owned managed identity and gateway adapters."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx
import pytest
from azure.core.credentials import AccessToken
from azure.core.exceptions import ClientAuthenticationError
from fdai_executor_service.adapters import workload_identity as identity_module
from fdai_executor_service.adapters.gateway_direct_api import (
    AzureGatewayDirectApiConfig,
    AzureGatewayDirectApiExecutor,
)
from fdai_executor_service.adapters.workload_identity import (
    ManagedIdentityWorkloadIdentity,
    ManagedIdentityWorkloadIdentityConfig,
)
from fdai_service_contracts.executor import (
    DirectApiAuthenticationError,
    DirectApiOutcome,
    DirectApiPermissionDeniedError,
    DirectApiPreconditionError,
    DirectApiRequest,
    IdentityToken,
    Mode,
)

_VM_TARGET = "/resourcegroups/example/providers/microsoft.compute/virtualmachines/vm-app"
_TAG_TARGET = (
    "scope-0123456789abcdef/resource-group/example/"
    "providers/microsoft.storage/storageaccounts/storage-app"
)


def _future_epoch(seconds: int = 3600) -> int:
    return int((datetime(2099, 1, 1, tzinfo=UTC) + timedelta(seconds=seconds)).timestamp())


async def test_managed_identity_coalesces_concurrent_audience_requests() -> None:
    calls: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        await asyncio.sleep(0.01)
        return httpx.Response(
            200,
            json={"access_token": "executor-token", "expires_on": _future_epoch()},
        )

    config = ManagedIdentityWorkloadIdentityConfig(
        endpoint="https://identity.example/token",
        header="proof",
        client_id="executor-client",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        identity = ManagedIdentityWorkloadIdentity(http_client=client, config=config)
        tokens = await asyncio.gather(*(identity.get_token("gateway") for _ in range(4)))

    assert [token.token for token in tokens] == ["executor-token"] * 4
    assert len(calls) == 1
    assert calls[0].url.params["client_id"] == "executor-client"
    assert calls[0].headers["X-IDENTITY-HEADER"] == "proof"


async def test_managed_identity_malformed_response_is_redacted() -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(200, json={"secret-field": "must-not-leak"})
    )
    config = ManagedIdentityWorkloadIdentityConfig(
        endpoint="https://identity.example/token",
        header="proof",
    )
    async with httpx.AsyncClient(transport=transport) as client:
        identity = ManagedIdentityWorkloadIdentity(http_client=client, config=config)
        with pytest.raises(RuntimeError, match="unrecognized body") as caught:
            await identity.get_token("gateway")

    assert "must-not-leak" not in str(caught.value)


@pytest.mark.parametrize("failure", [False, True])
async def test_executor_federation_is_cached_closed_and_never_falls_back(monkeypatch, failure):
    calls = []

    class Credential:
        def __init__(self, **kwargs):
            assert kwargs["client_id"] == "00000000-0000-0000-0000-000000000001"
            assert kwargs["retry_total"] == 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            calls.append("closed")

        async def get_token(self, scope):
            calls.append(scope)
            if failure:
                raise ClientAuthenticationError("provider diagnostic must not escape")
            return AccessToken("executor-example-token", _future_epoch())

    monkeypatch.setattr(identity_module, "WorkloadIdentityCredential", Credential)

    async def forbidden(request):
        pytest.fail("attached identity fallback is forbidden")

    async with httpx.AsyncClient(transport=httpx.MockTransport(forbidden)) as http:
        identity = ManagedIdentityWorkloadIdentity.from_env(
            http_client=http,
            env={
                "AZURE_CLIENT_ID": "00000000-0000-0000-0000-000000000001",
                "AZURE_TENANT_ID": "00000000-0000-0000-0000-000000000002",
                "AZURE_FEDERATED_TOKEN_FILE": "/var/run/secrets/azure/tokens/token",
            },
        )
        if failure:
            with pytest.raises(
                RuntimeError, match="^AKS workload identity token acquisition failed$"
            ):
                await identity.get_token("https://management.azure.com/.default")
        else:
            token = await identity.get_token("https://management.azure.com/.default")
            assert token.token == "executor-example-token"
            assert await identity.get_token(token.audience) is token
    assert calls == ["https://management.azure.com/.default", "closed"]


def test_executor_federation_rejects_identity_substitution():
    with pytest.raises(identity_module.ManagedIdentityConfigurationError, match="selected service"):
        ManagedIdentityWorkloadIdentity.from_env(
            http_client=httpx.AsyncClient(),
            env={
                "AZURE_CLIENT_ID": "00000000-0000-0000-0000-000000000001",
                "FDAI_MI_CLIENT_ID": "00000000-0000-0000-0000-000000000003",
                "AZURE_TENANT_ID": "00000000-0000-0000-0000-000000000002",
                "AZURE_FEDERATED_TOKEN_FILE": "/var/run/secrets/azure/tokens/token",
            },
        )


class _Identity:
    def __init__(self, token: str) -> None:
        self.token = token
        self.audiences: list[str] = []

    async def get_token(self, audience: str) -> IdentityToken:
        self.audiences.append(audience)
        return IdentityToken(
            token=self.token,
            expires_at=datetime(2099, 1, 1, tzinfo=UTC) + timedelta(hours=1),
            audience=audience,
        )


def _request(mode: Mode) -> DirectApiRequest:
    return DirectApiRequest(
        action_id=UUID("00000000-0000-0000-0000-000000000001"),
        idempotency_key="operation-one",
        action_type_name="ops.start-vm",
        rule_ids=("operator.request.ops.start-vm",),
        resource_ref=_VM_TARGET,
        arguments={"resource_group": "example", "vm_name": "vm-app"},
        labels=("enforce",) if mode is Mode.ENFORCE else ("shadow",),
        mode=mode,
        metadata={
            "audit_ref": "action:one",
            "stop_condition": "provider_api_error_streak",
            "rollback_ref": "state_forward_only",
            "max_resources": "1",
            "executor_identity_ref": "identity/resilience",
        },
    )


def _tag_request(mode: Mode) -> DirectApiRequest:
    return DirectApiRequest(
        action_id=UUID("00000000-0000-0000-0000-000000000004"),
        idempotency_key="tag-operation-one",
        action_type_name="remediate.tag-add",
        rule_ids=("object-storage.owner-tag.required",),
        resource_ref=_TAG_TARGET,
        arguments={
            "target_resource_ref": _TAG_TARGET,
            "tag_name": "environment",
            "tag_value": "dev",
        },
        labels=("enforce",) if mode is Mode.ENFORCE else ("shadow",),
        mode=mode,
        metadata={
            "audit_ref": "action:tag-one",
            "stop_condition": "provider_api_error_streak",
            "rollback_ref": "snapshot_restore",
            "max_resources": "1",
            "executor_identity_ref": "identity/change",
        },
    )


def _gateway_config() -> AzureGatewayDirectApiConfig:
    return AzureGatewayDirectApiConfig(
        base_url="https://gateway.example.com",
        audience="gateway-audience",
        poll_interval_seconds=0,
    )


async def test_gateway_plans_before_enforce_mutation() -> None:
    operations: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        operation = request.url.path.rsplit("/", 1)[-1]
        operations.append(operation)
        if operation == "azure.operation.status":
            return httpx.Response(
                404,
                json={
                    "status": "failed",
                    "code": "idempotency_not_found",
                    "detail": "operation record was not found",
                },
            )
        if operation == "azure.operation.plan":
            return httpx.Response(
                200,
                json={
                    "operation_id": operation,
                    "status": "succeeded",
                    "result": {"dry_run_receipt": "dry-run-one"},
                },
            )
        assert b'"dry_run_receipt":"dry-run-one"' in request.read()
        return httpx.Response(
            200,
            json={"operation_id": operation, "status": "succeeded"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        receipt = await AzureGatewayDirectApiExecutor(
            config=_gateway_config(),
            identities={"identity/resilience": _Identity("gateway-token")},
            http_client=client,
        ).execute(_request(Mode.ENFORCE))

    assert receipt.outcome is DirectApiOutcome.SUCCEEDED
    assert operations == [
        "azure.operation.status",
        "azure.operation.plan",
        "azure.compute.vm.start",
    ]


async def test_gateway_routes_tag_remediation_through_change_identity() -> None:
    operations: list[str] = []
    identity = _Identity("change-token")

    def handler(request: httpx.Request) -> httpx.Response:
        operation = request.url.path.rsplit("/", 1)[-1]
        operations.append(operation)
        return httpx.Response(
            200,
            json={
                "operation_id": "azure.operation.plan",
                "status": "succeeded",
                "result": {"dry_run_receipt": "dry-run-one"},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        receipt = await AzureGatewayDirectApiExecutor(
            config=_gateway_config(),
            identities={"identity/change": identity},
            http_client=client,
        ).execute(_tag_request(Mode.SHADOW))

    assert receipt.outcome is DirectApiOutcome.SUCCEEDED
    assert operations == ["azure.operation.plan"]
    assert identity.audiences == ["gateway-audience"]


async def test_gateway_redelivery_reconstructs_applied_receipt_without_re_effect() -> None:
    operations: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        operation = request.url.path.rsplit("/", 1)[-1]
        operations.append(operation)
        return httpx.Response(
            200,
            json={"operation_id": operation, "status": "succeeded"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        receipt = await AzureGatewayDirectApiExecutor(
            config=_gateway_config(),
            identities={"identity/resilience": _Identity("gateway-token")},
            http_client=client,
        ).execute(_request(Mode.ENFORCE))

    assert receipt.outcome is DirectApiOutcome.ALREADY_APPLIED
    assert receipt.receipt_ref == "gateway:operation-one"
    assert operations == ["azure.operation.status"]


async def test_gateway_status_only_recovery_never_plans_or_dispatches() -> None:
    operations: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        operation = request.url.path.rsplit("/", 1)[-1]
        operations.append(operation)
        return httpx.Response(
            404,
            json={
                "status": "failed",
                "code": "idempotency_not_found",
                "detail": "operation record was not found",
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        receipt = await AzureGatewayDirectApiExecutor(
            config=_gateway_config(),
            identities={"identity/resilience": _Identity("gateway-token")},
            http_client=client,
        ).operation_status(_request(Mode.ENFORCE))

    assert receipt is None
    assert operations == ["azure.operation.status"]


async def test_gateway_uses_exact_action_bound_executor_identity() -> None:
    change_identity = _Identity("change-token")
    resilience_identity = _Identity("resilience-token")
    authorization_headers: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        authorization_headers.append(request.headers["Authorization"])
        operation = request.url.path.rsplit("/", 1)[-1]
        if operation == "azure.operation.status":
            return httpx.Response(
                404,
                json={
                    "status": "failed",
                    "code": "idempotency_not_found",
                    "detail": "operation record was not found",
                },
            )
        if operation == "azure.operation.plan":
            return httpx.Response(
                200,
                json={
                    "operation_id": operation,
                    "status": "succeeded",
                    "result": {"dry_run_receipt": "dry-run-one"},
                },
            )
        return httpx.Response(
            200,
            json={"operation_id": operation, "status": "succeeded"},
        )

    request = replace(
        _request(Mode.ENFORCE),
        metadata={
            **_request(Mode.ENFORCE).metadata,
            "executor_identity_ref": "identity/resilience",
        },
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        receipt = await AzureGatewayDirectApiExecutor(
            config=_gateway_config(),
            identities={
                "identity/change": change_identity,
                "identity/resilience": resilience_identity,
            },
            http_client=client,
        ).execute(request)

    assert receipt.outcome is DirectApiOutcome.SUCCEEDED
    assert authorization_headers == ["Bearer resilience-token"] * 3
    assert change_identity.audiences == []
    assert resilience_identity.audiences == ["gateway-audience"] * 3


@pytest.mark.parametrize("identity_ref", (None, "identity/unknown"))
async def test_gateway_rejects_unbound_executor_identity_before_http(
    identity_ref: str | None,
) -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    request = _request(Mode.ENFORCE)
    metadata = dict(request.metadata)
    if identity_ref is None:
        metadata.pop("executor_identity_ref")
    else:
        metadata["executor_identity_ref"] = identity_ref
    request = replace(request, metadata=metadata)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        executor = AzureGatewayDirectApiExecutor(
            config=_gateway_config(),
            identities={"identity/change": _Identity("gateway-token")},
            http_client=client,
        )
        with pytest.raises(DirectApiPreconditionError, match="executor_identity_ref"):
            await executor.execute(request)

    assert calls == 0


@pytest.mark.parametrize(
    ("action_type_name", "wrong_identity_ref"),
    (
        ("ops.start-vm", "identity/change"),
        ("ops.deallocate-vm", "identity/resilience"),
        ("ops.upsert-network-rule", "identity/resilience"),
        ("ops.delete-network-rule", "identity/finops"),
    ),
)
async def test_gateway_rejects_wrong_vertical_identity_before_http(
    action_type_name: str,
    wrong_identity_ref: str,
) -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    request = replace(
        _request(Mode.ENFORCE),
        action_type_name=action_type_name,
        metadata={
            **_request(Mode.ENFORCE).metadata,
            "executor_identity_ref": wrong_identity_ref,
        },
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        executor = AzureGatewayDirectApiExecutor(
            config=_gateway_config(),
            identities={
                "identity/change": _Identity("change-token"),
                "identity/resilience": _Identity("resilience-token"),
                "identity/finops": _Identity("finops-token"),
            },
            http_client=client,
        )
        with pytest.raises(DirectApiPreconditionError, match="vertical identity"):
            await executor.execute(request)

    assert calls == 0


@pytest.mark.parametrize(
    ("status_code", "error_type"),
    ((401, DirectApiAuthenticationError), (403, DirectApiPermissionDeniedError)),
)
async def test_gateway_redacts_authorization_response(
    status_code: int,
    error_type: type[Exception],
) -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(status_code, content=b"sensitive-provider-body")
    )
    async with httpx.AsyncClient(transport=transport) as client:
        executor = AzureGatewayDirectApiExecutor(
            config=_gateway_config(),
            identities={"identity/resilience": _Identity("gateway-token")},
            http_client=client,
        )
        with pytest.raises(error_type) as caught:
            await executor.execute(_request(Mode.SHADOW))

    assert "sensitive-provider-body" not in str(caught.value)


async def test_gateway_rejects_oversized_response() -> None:
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, content=b"x" * 262_145))
    async with httpx.AsyncClient(transport=transport) as client:
        executor = AzureGatewayDirectApiExecutor(
            config=_gateway_config(),
            identities={"identity/resilience": _Identity("gateway-token")},
            http_client=client,
        )
        with pytest.raises(RuntimeError, match="too large"):
            await executor.execute(_request(Mode.SHADOW))


def test_gateway_requires_https_origin_without_credentials() -> None:
    for base_url in (
        "http://gateway.example.com",
        "https://user:password@gateway.example.com",
        "https://gateway.example.com/path",
    ):
        with pytest.raises(ValueError, match="HTTPS origin"):
            AzureGatewayDirectApiConfig(base_url=base_url, audience="gateway")


async def test_gateway_rejects_unregistered_operation_before_http() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    request = _request(Mode.SHADOW)
    request = replace(request, action_type_name="ops.unknown")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        executor = AzureGatewayDirectApiExecutor(
            config=_gateway_config(),
            identities={"identity/resilience": _Identity("gateway-token")},
            http_client=client,
        )
        with pytest.raises(DirectApiPreconditionError, match="no registered operation"):
            await executor.execute(request)

    assert calls == 0


async def test_gateway_rejects_decoy_target_before_status_or_plan() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    request = replace(_request(Mode.ENFORCE), resource_ref="resource:decoy")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        executor = AzureGatewayDirectApiExecutor(
            config=_gateway_config(),
            identities={"identity/resilience": _Identity("gateway-token")},
            http_client=client,
        )
        with pytest.raises(DirectApiPreconditionError, match="canonical Azure target"):
            await executor.execute(request)

    assert calls == 0


async def test_gateway_and_workload_identity_remaining_branches() -> None:
    from fdai_executor_service.adapters.gateway_direct_api import _safety, _validated_body
    from fdai_executor_service.adapters.workload_identity import (
        ManagedIdentityConfigurationError,
        _audience_to_resource,
    )
    from fdai_service_contracts.executor import DirectApiError, DirectApiPromotionError

    # Workload identity config & validation branches
    async with httpx.AsyncClient() as client:
        for cfg_kwargs, match in [
            ({"endpoint": "relative-url", "header": "h"}, "MUST be an absolute URL"),
            ({"endpoint": "https://id.example", "header": ""}, "IDENTITY_HEADER MUST NOT be empty"),
            (
                {"endpoint": "https://id.example", "header": "h", "timeout_seconds": 0},
                "timeout_seconds MUST be > 0",
            ),
            (
                {
                    "endpoint": "",
                    "header": "",
                    "federated_tenant_id": "bad",
                    "client_id": "bad",
                    "federated_token_file": "/abs/path",
                },
                "valid tenant and client identifiers",
            ),
            (
                {
                    "endpoint": "https://id.example",
                    "header": "",
                    "federated_tenant_id": "00000000-0000-0000-0000-000000000001",
                    "client_id": "00000000-0000-0000-0000-000000000002",
                    "federated_token_file": "relative/path",
                },
                "one absolute projected token path",
            ),
        ]:
            with pytest.raises(ManagedIdentityConfigurationError, match=match):
                ManagedIdentityWorkloadIdentity(
                    http_client=client,
                    config=ManagedIdentityWorkloadIdentityConfig(**cfg_kwargs),  # type: ignore[arg-type]
                )
        with pytest.raises(ManagedIdentityConfigurationError, match="IDENTITY_ENDPOINT"):
            ManagedIdentityWorkloadIdentity.from_env(http_client=client, env={})

    list_tx = httpx.MockTransport(lambda _req: httpx.Response(200, json=["not-a-dict"]))
    async with httpx.AsyncClient(transport=list_tx) as client:
        mi = ManagedIdentityWorkloadIdentity(
            http_client=client,
            config=ManagedIdentityWorkloadIdentityConfig(
                endpoint="https://id.example/token", header="h"
            ),
        )
        with pytest.raises(RuntimeError, match="unrecognized body"):
            await mi.get_token("https://management.azure.com/.default")
    assert _audience_to_resource("https://example/.default") == "https://example"

    # Gateway config validation
    for gw_kwargs, match in [
        ({"audience": ""}, "audience MUST be bounded"),
        ({"timeout_seconds": 0.0}, "timeout_seconds MUST be in"),
        ({"poll_interval_seconds": -1.0}, "poll_interval_seconds MUST be in"),
        ({"max_poll_attempts": 0}, "max_poll_attempts MUST be in"),
    ]:
        with pytest.raises(ValueError, match=match):
            AzureGatewayDirectApiConfig(
                base_url="https://gateway.example.com",
                audience=gw_kwargs.get("audience", "aud"),  # type: ignore[arg-type]
                **{k: v for k, v in gw_kwargs.items() if k != "audience"},  # type: ignore[arg-type]
            )

    async with httpx.AsyncClient() as client:
        with pytest.raises(ValueError, match="registered identity refs"):
            AzureGatewayDirectApiExecutor(
                config=_gateway_config(), identities={}, http_client=client
            )
        gw_exec = AzureGatewayDirectApiExecutor(
            config=_gateway_config(),
            identities={"identity/resilience": _Identity("t")},
            http_client=client,
        )
        assert await gw_exec.operation_status(_request(Mode.SHADOW)) is None
        with pytest.raises(DirectApiPromotionError, match="explicit enforce label"):
            await gw_exec.execute(replace(_request(Mode.ENFORCE), labels=()))

    with pytest.raises(DirectApiPreconditionError, match="safety metadata is missing"):
        _safety(replace(_request(Mode.ENFORCE), metadata={}))
    with pytest.raises(DirectApiPreconditionError, match="max_resources must be an integer"):
        _safety(
            replace(
                _request(Mode.ENFORCE),
                metadata={**_request(Mode.ENFORCE).metadata, "max_resources": "bad"},
            )
        )
    with pytest.raises(DirectApiError, match="operation did not match"):
        _validated_body({"operation_id": "other", "status": "ok"}, expected_operation="exp")
    with pytest.raises(DirectApiError, match="status was missing"):
        _validated_body({"operation_id": "exp", "status": 123}, expected_operation="exp")

    # Gateway polling, status recovery, and HTTP error branches
    seq: list[httpx.Response | Exception] = []

    def seq_handler(req: httpx.Request) -> httpx.Response:
        item = seq.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def r_op(op: str, status: str, **extra: object) -> httpx.Response:
        return httpx.Response(200, json={"operation_id": op, "status": status, **extra})

    poll_cfg = AzureGatewayDirectApiConfig(
        base_url="https://gateway.example.com",
        audience="gateway-audience",
        poll_interval_seconds=0.001,
        max_poll_attempts=2,
    )
    st_op = "azure.operation.status"
    pl_op = "azure.operation.plan"
    vm_op = "azure.compute.vm.start"
    not_found = httpx.Response(404, json={"status": "failed", "code": "idempotency_not_found"})
    plan_ok = r_op(pl_op, "succeeded", result={"dry_run_receipt": "dr-1"})
    submitted = r_op(vm_op, "submitted")

    async with httpx.AsyncClient(transport=httpx.MockTransport(seq_handler)) as client:
        gw = AzureGatewayDirectApiExecutor(
            config=poll_cfg,
            identities={"identity/resilience": _Identity("t")},
            http_client=client,
        )
        seq.extend([r_op(st_op, "running"), r_op(st_op, "succeeded")])
        replayed = await gw.execute(_request(Mode.ENFORCE))
        assert replayed.outcome is DirectApiOutcome.ALREADY_APPLIED

        seq.append(r_op(st_op, "failed"))
        assert (await gw.execute(_request(Mode.ENFORCE))).outcome is DirectApiOutcome.FAILED

        for bad_seq, mode, match in [
            ([r_op(st_op, "weird")], Mode.ENFORCE, "not recognized"),
            ([r_op(pl_op, "failed")], Mode.SHADOW, "plan did not succeed"),
            ([r_op(pl_op, "succeeded", result={})], Mode.SHADOW, "omitted dry_run_receipt"),
            ([not_found, plan_ok, submitted, r_op(st_op, "weird")], Mode.ENFORCE, "not recognized"),
        ]:
            seq.extend(bad_seq)
            with pytest.raises(DirectApiError, match=match):
                await gw.execute(_request(mode))

        for fail_seq in [
            [not_found, plan_ok, r_op(vm_op, "queued")],
            [not_found, plan_ok, submitted, r_op(st_op, "failed")],
            [not_found, plan_ok, submitted, r_op(st_op, "running"), r_op(st_op, "running")],
        ]:
            seq.extend(fail_seq)
            assert (await gw.execute(_request(Mode.ENFORCE))).outcome is DirectApiOutcome.FAILED

        for err_item, exc_type, match in [
            (httpx.ConnectError("boom"), DirectApiError, "request failed"),
            (httpx.Response(200, content=b"not-json"), DirectApiError, "not JSON"),
            (httpx.Response(200, json=["list"]), DirectApiError, "not an object"),
            (httpx.Response(409, json={}), DirectApiPreconditionError, "precondition failed"),
            (httpx.Response(500, json={}), DirectApiError, "returned HTTP 500"),
        ]:
            seq.append(err_item)
            with pytest.raises(exc_type, match=match):
                await gw.execute(_request(Mode.SHADOW))

        class _FailingId:
            async def get_token(self, _aud: str) -> IdentityToken:
                raise RuntimeError("id fail")

        gw_fail_id = AzureGatewayDirectApiExecutor(
            config=poll_cfg,
            identities={"identity/resilience": _FailingId()},
            http_client=client,
        )
        with pytest.raises(DirectApiAuthenticationError, match="acquisition failed"):
            await gw_fail_id.execute(_request(Mode.SHADOW))
