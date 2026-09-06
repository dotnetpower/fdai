from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import cast

import httpx
import pytest
from delivery.dev_operations_gateway.gateway import (
    GatewayConfig,
    GatewayError,
    GatewayPrincipal,
    ManagedIdentityTokenProvider,
    OperationsGateway,
    PrivateProbe,
)
from delivery.dev_operations_gateway.idempotency import IdempotencyError


class _Ledger:
    def __init__(self) -> None:
        self.records: dict[str, tuple[str, Mapping[str, object] | None]] = {}
        self.consumed_dry_runs: set[str] = set()
        self.issued_dry_runs = 0
        self.dry_run_digests: dict[str, str] = {}

    async def begin(self, idempotency_key: str, request_digest: str) -> Mapping[str, object] | None:
        existing = self.records.get(idempotency_key)
        if existing is None:
            self.records[idempotency_key] = (request_digest, None)
            return None
        assert existing[0] == request_digest
        assert existing[1] is not None
        return existing[1]

    async def complete(
        self,
        idempotency_key: str,
        request_digest: str,
        response: Mapping[str, object],
    ) -> None:
        self.records[idempotency_key] = (request_digest, response)

    async def abort(self, idempotency_key: str, request_digest: str) -> None:
        assert self.records.get(idempotency_key) == (request_digest, None)
        self.records.pop(idempotency_key)

    async def lookup(self, idempotency_key: str) -> Mapping[str, object]:
        existing = self.records.get(idempotency_key)
        assert existing is not None
        assert existing[1] is not None
        return existing[1]

    async def acquire_resource(self, resource_key: str) -> str:
        assert resource_key
        return "lease-one"

    async def release_resource(self, resource_key: str, lease_id: str) -> None:
        assert resource_key
        assert lease_id == "lease-one"

    async def renew_resource(self, resource_key: str, lease_id: str) -> None:
        assert resource_key
        assert lease_id == "lease-one"

    async def update_response(
        self,
        idempotency_key: str,
        response: Mapping[str, object],
    ) -> None:
        existing = self.records.get(idempotency_key)
        assert existing is not None
        self.records[idempotency_key] = (existing[0], response)

    async def issue_dry_run(self, request_digest: str) -> str:
        assert request_digest
        self.issued_dry_runs += 1
        receipt = f"dry-run:issued-{self.issued_dry_runs}"
        self.dry_run_digests[receipt] = request_digest
        return receipt

    async def consume_dry_run(self, receipt: str, request_digest: str) -> None:
        assert request_digest
        issued_digest = self.dry_run_digests.get(receipt)
        if issued_digest is not None and issued_digest != request_digest:
            raise IdempotencyError(409, "dry_run_invalid", "dry-run receipt is invalid")
        if not receipt.startswith("dry-run:") or receipt in self.consumed_dry_runs:
            raise IdempotencyError(409, "dry_run_invalid", "dry-run receipt is invalid")
        self.consumed_dry_runs.add(receipt)


class _Tokens:
    async def get_token(self, audience: str) -> str:
        assert audience
        return "token"


def _config() -> GatewayConfig:
    return GatewayConfig(
        subscription_id="sub-example",
        resource_groups=frozenset({"rg-example"}),
        contributor_group_id="group-contributor",
        executor_principal_ids=(
            "principal-change",
            "principal-resilience",
            "principal-finops",
        ),
        reader_identity_client_id="client-reader",
        executor_identity_client_id="client-executor",
        idempotency_container_url="https://storage.example.com/operation-idempotency",
        private_probes={},
        mutations_enabled=True,
    )


def _safety(idempotency_key: str = "operation:one") -> Mapping[str, object]:
    return {
        "idempotency_key": idempotency_key,
        "audit_ref": "audit:one",
        "dry_run_receipt": f"dry-run:{idempotency_key}",
        "stop_condition": "provisioning_state_terminal",
        "rollback_ref": "rollback:one",
        "max_resources": 1,
    }


def _environment(**overrides: str) -> dict[str, str]:
    values = {
        "FDAI_DEV_GATEWAY_ENABLED": "1",
        "FDAI_ENV": "dev",
        "FDAI_DEV_GATEWAY_SUBSCRIPTION_ID": "sub-example",
        "FDAI_DEV_GATEWAY_RESOURCE_GROUPS": "rg-example",
        "FDAI_DEV_GATEWAY_CONTRIBUTOR_GROUP_ID": "group-contributor",
        "FDAI_DEV_GATEWAY_EXECUTOR_PRINCIPAL_IDS": (
            "principal-change,principal-resilience,principal-finops"
        ),
        "FDAI_DEV_GATEWAY_READER_MI_CLIENT_ID": "client-reader",
        "FDAI_DEV_GATEWAY_EXECUTOR_MI_CLIENT_ID": "client-executor",
        "FDAI_DEV_GATEWAY_IDEMPOTENCY_CONTAINER_URL": (
            "https://storage.example.com/operation-idempotency"
        ),
        "FDAI_DEV_GATEWAY_PRIVATE_PROBES_JSON": "{}",
    }
    values.update(overrides)
    return values


def test_config_rejects_unsafe_idempotency_container_url() -> None:
    with pytest.raises(ValueError, match="one HTTPS container"):
        GatewayConfig.from_env(
            _environment(
                FDAI_DEV_GATEWAY_IDEMPOTENCY_CONTAINER_URL=(
                    "https://storage.example.com/operation-idempotency?sig=secret"
                )
            )
        )


@pytest.mark.parametrize(
    "url",
    [
        "https://169.254.169.254/metadata/instance",
        "https://127.0.0.1/private",
        "https://localhost/private",
        "https://service.example.com/private#fragment",
    ],
)
def test_private_probe_rejects_unsafe_targets(url: str) -> None:
    with pytest.raises(ValueError, match="private probe URL"):
        PrivateProbe(url=url, audience="api-application-id")


async def test_mutations_are_disabled_by_default() -> None:
    config = GatewayConfig.from_env(_environment())
    assert config.mutations_enabled is False
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        gateway = OperationsGateway(
            config=config,
            reader_token_provider=_Tokens(),
            executor_token_provider=_Tokens(),
            http_client=client,
            idempotency_ledger=_Ledger(),
        )
        with pytest.raises(GatewayError) as error:
            await gateway.invoke(
                "azure.compute.vm.start",
                {
                    "resource_group": "rg-example",
                    "vm_name": "vm-app",
                    "safety": _safety(),
                },
                GatewayPrincipal("principal-resilience", frozenset()),
            )

    assert error.value.status_code == 404
    assert error.value.code == "operation_not_found"
    assert calls == 0


async def test_vmss_scale_plan_and_execution_are_bounded_to_one_instance() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "etag": 'W/"revision-one"',
                    "sku": {"capacity": 2},
                    "properties": {"orchestrationMode": "Uniform"},
                },
            )
        return httpx.Response(200, json={"sku": {"capacity": 3}})

    ledger = _Ledger()
    payload = {
        "resource_group": "rg-example",
        "vmss_name": "vmss-app",
        "target_resource_ref": (
            "/subscriptions/sub-example/resourceGroups/rg-example/providers/"
            "Microsoft.Compute/virtualMachineScaleSets/vmss-app"
        ),
        "replica_count": 3,
        "reason": "increase capacity for the measured workload",
        "safety": _safety("operation:scale-one"),
    }
    principal = GatewayPrincipal("principal-finops", frozenset())
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        gateway = OperationsGateway(
            config=_config(),
            reader_token_provider=_Tokens(),
            executor_token_provider=_Tokens(),
            http_client=client,
            idempotency_ledger=ledger,
        )
        plan = await gateway.invoke(
            "azure.operation.plan",
            {
                "operation_id": "azure.compute.vmss.scale",
                "arguments": {key: value for key, value in payload.items() if key != "safety"},
                "safety": {
                    key: value
                    for key, value in _safety("operation:scale-one").items()
                    if key != "dry_run_receipt"
                },
            },
            principal,
        )
        dry_run = cast(Mapping[str, object], plan["result"])["dry_run_receipt"]
        payload["safety"] = {**_safety("operation:scale-one"), "dry_run_receipt": dry_run}
        result = await gateway.invoke("azure.compute.vmss.scale", payload, principal)

    assert result["status"] == "succeeded"
    mutation = requests[-1]
    assert mutation.method == "PATCH"
    assert mutation.url.path.endswith(
        "/providers/Microsoft.Compute/virtualMachineScaleSets/vmss-app"
    )
    assert mutation.read().decode() == '{"sku":{"capacity":3}}'
    assert mutation.headers["If-Match"] == 'W/"revision-one"'


async def test_vmss_scale_plan_rejects_capacity_increase_larger_than_one() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "sku": {"capacity": 2},
                "properties": {"orchestrationMode": "Uniform"},
            },
        )

    arguments = {
        "resource_group": "rg-example",
        "vmss_name": "vmss-app",
        "target_resource_ref": (
            "/subscriptions/sub-example/resourceGroups/rg-example/providers/"
            "Microsoft.Compute/virtualMachineScaleSets/vmss-app"
        ),
        "replica_count": 4,
        "reason": "increase capacity beyond the bounded envelope",
    }
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        gateway = OperationsGateway(
            config=_config(),
            reader_token_provider=_Tokens(),
            executor_token_provider=_Tokens(),
            http_client=client,
            idempotency_ledger=_Ledger(),
        )
        with pytest.raises(GatewayError) as caught:
            await gateway.invoke(
                "azure.operation.plan",
                {
                    "operation_id": "azure.compute.vmss.scale",
                    "arguments": arguments,
                    "safety": {
                        key: value
                        for key, value in _safety("operation:scale-two").items()
                        if key != "dry_run_receipt"
                    },
                },
                GatewayPrincipal("principal-finops", frozenset()),
            )

    assert caught.value.status_code == 409
    assert caught.value.code == "scale_out_of_bounds"
    assert [request.method for request in requests] == ["GET"]


async def test_vmss_scale_execution_rejects_capacity_changed_after_plan() -> None:
    observations = iter((2, 5))
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.method == "GET"
        capacity = next(observations)
        return httpx.Response(
            200,
            json={
                "etag": f'W/"revision-{capacity}"',
                "sku": {"capacity": capacity},
                "properties": {"orchestrationMode": "Uniform"},
            },
        )

    ledger = _Ledger()
    arguments = {
        "resource_group": "rg-example",
        "vmss_name": "vmss-app",
        "target_resource_ref": (
            "/subscriptions/sub-example/resourceGroups/rg-example/providers/"
            "Microsoft.Compute/virtualMachineScaleSets/vmss-app"
        ),
        "replica_count": 3,
        "reason": "increase capacity from a stale observation",
    }
    principal = GatewayPrincipal("principal-finops", frozenset())
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        gateway = OperationsGateway(
            config=_config(),
            reader_token_provider=_Tokens(),
            executor_token_provider=_Tokens(),
            http_client=client,
            idempotency_ledger=ledger,
        )
        plan = await gateway.invoke(
            "azure.operation.plan",
            {
                "operation_id": "azure.compute.vmss.scale",
                "arguments": arguments,
                "safety": {
                    key: value
                    for key, value in _safety("operation:stale-scale").items()
                    if key != "dry_run_receipt"
                },
            },
            principal,
        )
        dry_run = cast(Mapping[str, object], plan["result"])["dry_run_receipt"]
        with pytest.raises(GatewayError) as caught:
            await gateway.invoke(
                "azure.compute.vmss.scale",
                {
                    **arguments,
                    "safety": {
                        **_safety("operation:stale-scale"),
                        "dry_run_receipt": dry_run,
                    },
                },
                principal,
            )

    assert caught.value.status_code == 409
    assert caught.value.code == "scale_out_of_bounds"
    assert [request.method for request in requests] == ["GET", "GET"]


async def test_vmss_scale_async_duplicate_replays_without_second_patch() -> None:
    status_url = (
        "https://management.azure.com/subscriptions/sub-example/providers/"
        "Microsoft.Compute/locations/koreacentral/operations/operation-scale"
    )
    patch_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal patch_count
        if request.method == "GET" and str(request.url) == status_url:
            return httpx.Response(200, json={"status": "Succeeded"})
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "etag": 'W/"revision-one"',
                    "sku": {"capacity": 2},
                    "properties": {"orchestrationMode": "Uniform"},
                },
            )
        patch_count += 1
        return httpx.Response(202, headers={"Azure-AsyncOperation": status_url})

    ledger = _Ledger()
    arguments = {
        "resource_group": "rg-example",
        "vmss_name": "vmss-app",
        "target_resource_ref": (
            "/subscriptions/sub-example/resourceGroups/rg-example/providers/"
            "Microsoft.Compute/virtualMachineScaleSets/vmss-app"
        ),
        "replica_count": 3,
        "reason": "increase capacity through an async operation",
    }
    principal = GatewayPrincipal("principal-finops", frozenset())
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        gateway = OperationsGateway(
            config=_config(),
            reader_token_provider=_Tokens(),
            executor_token_provider=_Tokens(),
            http_client=client,
            idempotency_ledger=ledger,
        )
        plan = await gateway.invoke(
            "azure.operation.plan",
            {
                "operation_id": "azure.compute.vmss.scale",
                "arguments": arguments,
                "safety": {
                    key: value
                    for key, value in _safety("operation:async-scale").items()
                    if key != "dry_run_receipt"
                },
            },
            principal,
        )
        dry_run = cast(Mapping[str, object], plan["result"])["dry_run_receipt"]
        payload = {
            **arguments,
            "safety": {
                **_safety("operation:async-scale"),
                "dry_run_receipt": dry_run,
            },
        }
        first = await gateway.invoke("azure.compute.vmss.scale", payload, principal)
        duplicate = await gateway.invoke("azure.compute.vmss.scale", payload, principal)
        terminal = await gateway.invoke(
            "azure.operation.status",
            {
                "idempotency_key": "operation:async-scale",
                "operation_id": "azure.compute.vmss.scale",
            },
            principal,
        )

    assert first == duplicate
    assert patch_count == 1
    assert terminal["status"] == "succeeded"


async def test_vmss_scale_plan_rejects_missing_reason() -> None:
    arguments = {
        "resource_group": "rg-example",
        "vmss_name": "vmss-app",
        "target_resource_ref": (
            "/subscriptions/sub-example/resourceGroups/rg-example/providers/"
            "Microsoft.Compute/virtualMachineScaleSets/vmss-app"
        ),
        "replica_count": 3,
    }
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _request: httpx.Response(500))
    ) as client:
        gateway = OperationsGateway(
            config=_config(),
            reader_token_provider=_Tokens(),
            executor_token_provider=_Tokens(),
            http_client=client,
            idempotency_ledger=_Ledger(),
        )
        with pytest.raises(GatewayError) as caught:
            await gateway.invoke(
                "azure.operation.plan",
                {
                    "operation_id": "azure.compute.vmss.scale",
                    "arguments": arguments,
                    "safety": {
                        key: value
                        for key, value in _safety("operation:no-reason").items()
                        if key != "dry_run_receipt"
                    },
                },
                GatewayPrincipal("principal-finops", frozenset()),
            )

    assert caught.value.status_code == 400
    assert caught.value.code == "argument_invalid"


@pytest.mark.parametrize(
    ("replica_count", "reason"),
    (
        (3.0, "increase capacity for the measured workload"),
        (3, "too short"),
        (3, "x" * 201),
        (3, "increase\tcapacity for the measured workload"),
    ),
)
async def test_vmss_scale_plan_rejects_noncanonical_arguments(
    replica_count: object,
    reason: str,
) -> None:
    arguments = {
        "resource_group": "rg-example",
        "vmss_name": "vmss-app",
        "target_resource_ref": (
            "/subscriptions/sub-example/resourceGroups/rg-example/providers/"
            "Microsoft.Compute/virtualMachineScaleSets/vmss-app"
        ),
        "replica_count": replica_count,
        "reason": reason,
    }
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(500)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        gateway = OperationsGateway(
            config=_config(),
            reader_token_provider=_Tokens(),
            executor_token_provider=_Tokens(),
            http_client=client,
            idempotency_ledger=_Ledger(),
        )
        with pytest.raises(GatewayError) as caught:
            await gateway.invoke(
                "azure.operation.plan",
                {
                    "operation_id": "azure.compute.vmss.scale",
                    "arguments": arguments,
                    "safety": {
                        key: value
                        for key, value in _safety("operation:invalid-arguments").items()
                        if key != "dry_run_receipt"
                    },
                },
                GatewayPrincipal("principal-finops", frozenset()),
            )

    assert caught.value.status_code == 400
    assert caught.value.code == "argument_invalid"
    assert requests == []


async def test_vmss_scale_rejects_control_character_in_execution_etag() -> None:
    observations = iter(('W/"plan"', 'W/"execution\tinvalid"'))
    methods: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        assert request.method == "GET"
        return httpx.Response(
            200,
            json={
                "etag": next(observations),
                "sku": {"capacity": 2},
                "properties": {"orchestrationMode": "Uniform"},
            },
        )

    ledger = _Ledger()
    arguments = {
        "resource_group": "rg-example",
        "vmss_name": "vmss-app",
        "target_resource_ref": (
            "/subscriptions/sub-example/resourceGroups/rg-example/providers/"
            "Microsoft.Compute/virtualMachineScaleSets/vmss-app"
        ),
        "replica_count": 3,
        "reason": "increase capacity with a verified target revision",
    }
    principal = GatewayPrincipal("principal-finops", frozenset())
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        gateway = OperationsGateway(
            config=_config(),
            reader_token_provider=_Tokens(),
            executor_token_provider=_Tokens(),
            http_client=client,
            idempotency_ledger=ledger,
        )
        plan = await gateway.invoke(
            "azure.operation.plan",
            {
                "operation_id": "azure.compute.vmss.scale",
                "arguments": arguments,
                "safety": {
                    key: value
                    for key, value in _safety("operation:bad-etag").items()
                    if key != "dry_run_receipt"
                },
            },
            principal,
        )
        dry_run = cast(Mapping[str, object], plan["result"])["dry_run_receipt"]
        with pytest.raises(GatewayError) as caught:
            await gateway.invoke(
                "azure.compute.vmss.scale",
                {
                    **arguments,
                    "safety": {
                        **_safety("operation:bad-etag"),
                        "dry_run_receipt": dry_run,
                    },
                },
                principal,
            )

    assert caught.value.code == "azure_response_invalid"
    assert methods == ["GET", "GET"]


async def test_vmss_scale_maps_if_match_failure_to_target_revision_change() -> None:
    get_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal get_count
        if request.method == "GET":
            get_count += 1
            return httpx.Response(
                200,
                json={
                    "etag": f'W/"revision-{get_count}"',
                    "sku": {"capacity": 2},
                    "properties": {"orchestrationMode": "Uniform"},
                },
            )
        return httpx.Response(412)

    ledger = _Ledger()
    arguments = {
        "resource_group": "rg-example",
        "vmss_name": "vmss-app",
        "target_resource_ref": (
            "/subscriptions/sub-example/resourceGroups/rg-example/providers/"
            "Microsoft.Compute/virtualMachineScaleSets/vmss-app"
        ),
        "replica_count": 3,
        "reason": "increase capacity while preserving target revision",
    }
    principal = GatewayPrincipal("principal-finops", frozenset())
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        gateway = OperationsGateway(
            config=_config(),
            reader_token_provider=_Tokens(),
            executor_token_provider=_Tokens(),
            http_client=client,
            idempotency_ledger=ledger,
        )
        plan = await gateway.invoke(
            "azure.operation.plan",
            {
                "operation_id": "azure.compute.vmss.scale",
                "arguments": arguments,
                "safety": {
                    key: value
                    for key, value in _safety("operation:etag-race").items()
                    if key != "dry_run_receipt"
                },
            },
            principal,
        )
        dry_run = cast(Mapping[str, object], plan["result"])["dry_run_receipt"]
        with pytest.raises(GatewayError) as caught:
            await gateway.invoke(
                "azure.compute.vmss.scale",
                {
                    **arguments,
                    "safety": {
                        **_safety("operation:etag-race"),
                        "dry_run_receipt": dry_run,
                    },
                },
                principal,
            )

    assert caught.value.status_code == 409
    assert caught.value.code == "target_revision_changed"


@pytest.mark.parametrize("response", [httpx.Response(200, content=b"not-json")])
async def test_managed_identity_invalid_response_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    response: httpx.Response,
) -> None:
    monkeypatch.setenv("IDENTITY_ENDPOINT", "https://identity.example.com/token")
    monkeypatch.setenv("IDENTITY_HEADER", "identity-header")
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _request: response)
    ) as client:
        provider = ManagedIdentityTokenProvider(client_id="client-reader", http_client=client)
        with pytest.raises(GatewayError) as error:
            await provider.get_token("https://storage.azure.com/")

    assert error.value.status_code == 503
    assert error.value.code == "identity_unavailable"


async def test_managed_identity_transport_failure_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("IDENTITY_ENDPOINT", "https://identity.example.com/token")
    monkeypatch.setenv("IDENTITY_HEADER", "identity-header")

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = ManagedIdentityTokenProvider(client_id="client-reader", http_client=client)
        with pytest.raises(GatewayError) as error:
            await provider.get_token("https://storage.azure.com/")

    assert error.value.status_code == 503
    assert error.value.code == "identity_unavailable"


async def test_contributor_can_read_one_allowlisted_nsg() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "name": "nsg-app",
                "tags": {"secret-metadata": "must-not-pass"},
                "properties": {
                    "securityRules": [
                        {
                            "name": "allow-https",
                            "properties": {
                                "access": "Allow",
                                "direction": "Inbound",
                                "protocol": "Tcp",
                                "priority": 200,
                                "sourceAddressPrefix": "Internet",
                                "sourceAddressPrefixes": [],
                                "sourcePortRange": "*",
                                "sourcePortRanges": [],
                                "destinationAddressPrefix": "*",
                                "destinationAddressPrefixes": [],
                                "destinationPortRange": "443",
                                "destinationPortRanges": [],
                                "description": "must-not-pass",
                            },
                        }
                    ]
                },
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        gateway = OperationsGateway(
            config=_config(),
            reader_token_provider=_Tokens(),
            executor_token_provider=_Tokens(),
            http_client=client,
        )
        result = await gateway.invoke(
            "azure.network.nsg.read",
            {"resource_group": "rg-example", "nsg_name": "nsg-app"},
            GatewayPrincipal("principal-user", frozenset({"group-contributor"})),
        )

    assert result["status"] == "succeeded"
    assert requests[0].method == "GET"
    assert requests[0].url.path.endswith("/networkSecurityGroups/nsg-app")
    assert "must-not-pass" not in repr(result)
    projected = cast(Mapping[str, object], result["result"])
    rules = cast(list[Mapping[str, object]], projected["rules"])
    assert rules[0]["destination_port_range"] == "443"


@pytest.mark.parametrize(("rule_count", "expected_truncated"), [(64, False), (65, True)])
async def test_nsg_truncation_reports_only_omitted_rules(
    rule_count: int,
    expected_truncated: bool,
) -> None:
    rules = [
        {
            "name": f"rule-{index}",
            "properties": {
                "access": "Allow",
                "direction": "Inbound",
                "protocol": "Tcp",
                "priority": 100 + index,
            },
        }
        for index in range(rule_count)
    ]
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            json={"properties": {"securityRules": rules, "defaultSecurityRules": []}},
        )
    )
    async with httpx.AsyncClient(transport=transport) as client:
        gateway = OperationsGateway(
            config=_config(),
            reader_token_provider=_Tokens(),
            executor_token_provider=_Tokens(),
            http_client=client,
        )
        result = await gateway.invoke(
            "azure.network.nsg.read",
            {"resource_group": "rg-example", "nsg_name": "nsg-app"},
            GatewayPrincipal("principal-user", frozenset({"group-contributor"})),
        )

    projected = cast(Mapping[str, object], result["result"])
    assert len(cast(list[object], projected["rules"])) == 64
    assert projected["truncated"] is expected_truncated


async def test_scope_and_unregistered_operations_fail_closed() -> None:
    transport = httpx.MockTransport(lambda _: httpx.Response(500))
    async with httpx.AsyncClient(transport=transport) as client:
        gateway = OperationsGateway(
            config=_config(),
            reader_token_provider=_Tokens(),
            executor_token_provider=_Tokens(),
            http_client=client,
        )
        principal = GatewayPrincipal("principal-user", frozenset({"group-contributor"}))
        with pytest.raises(GatewayError, match="outside dev scope") as scope_error:
            await gateway.invoke(
                "azure.network.nsg.read",
                {"resource_group": "rg-other", "nsg_name": "nsg-app"},
                principal,
            )
        assert scope_error.value.status_code == 403
        with pytest.raises(GatewayError, match="not registered") as operation_error:
            await gateway.invoke("azure.raw.request", {}, principal)
        assert operation_error.value.status_code == 404


async def test_arm_resource_not_found_preserves_non_retryable_status() -> None:
    transport = httpx.MockTransport(lambda _request: httpx.Response(404))
    async with httpx.AsyncClient(transport=transport) as client:
        gateway = OperationsGateway(
            config=_config(),
            reader_token_provider=_Tokens(),
            executor_token_provider=_Tokens(),
            http_client=client,
        )
        with pytest.raises(GatewayError) as error:
            await gateway.invoke(
                "azure.network.nsg.read",
                {"resource_group": "rg-example", "nsg_name": "nsg-missing"},
                GatewayPrincipal("principal-user", frozenset({"group-contributor"})),
            )

    assert error.value.status_code == 404
    assert error.value.code == "azure_resource_not_found"


async def test_private_probe_never_follows_redirects() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(302, headers={"Location": "https://169.254.169.254/metadata"})

    config = _config()
    config = GatewayConfig(
        subscription_id=config.subscription_id,
        resource_groups=config.resource_groups,
        contributor_group_id=config.contributor_group_id,
        executor_principal_ids=config.executor_principal_ids,
        reader_identity_client_id=config.reader_identity_client_id,
        executor_identity_client_id=config.executor_identity_client_id,
        idempotency_container_url=config.idempotency_container_url,
        private_probes={
            "service": PrivateProbe(
                url="https://service.example.com/health",
                audience="api-application-id",
            )
        },
        mutations_enabled=config.mutations_enabled,
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        follow_redirects=True,
    ) as client:
        gateway = OperationsGateway(
            config=config,
            reader_token_provider=_Tokens(),
            executor_token_provider=_Tokens(),
            http_client=client,
        )
        result = await gateway.invoke(
            "azure.private.http.probe",
            {"probe": "service"},
            GatewayPrincipal("principal-user", frozenset({"group-contributor"})),
        )

    assert len(requests) == 1
    assert result["status"] == "succeeded"


async def test_application_dependency_probe_requires_typed_database_receipt() -> None:
    config = _config()
    config = GatewayConfig(
        subscription_id=config.subscription_id,
        resource_groups=config.resource_groups,
        contributor_group_id=config.contributor_group_id,
        executor_principal_ids=config.executor_principal_ids,
        reader_identity_client_id=config.reader_identity_client_id,
        executor_identity_client_id=config.executor_identity_client_id,
        idempotency_container_url=config.idempotency_container_url,
        private_probes={
            "service": PrivateProbe(
                url="https://service.example.com/health/database",
                audience="api-application-id",
                result_contract="application_database_dependency",
            )
        },
        mutations_enabled=config.mutations_enabled,
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                json={"dependency": "cache", "reachable": True},
            )
        )
    ) as client:
        gateway = OperationsGateway(
            config=config,
            reader_token_provider=_Tokens(),
            executor_token_provider=_Tokens(),
            http_client=client,
        )
        with pytest.raises(GatewayError) as error:
            await gateway.invoke(
                "azure.private.http.probe",
                {"probe": "service"},
                GatewayPrincipal("principal-user", frozenset({"group-contributor"})),
            )

    assert error.value.status_code == 502
    assert error.value.code == "probe_response_invalid"


async def test_read_operation_rejects_unexpected_arm_202() -> None:
    status_url = (
        "https://management.azure.com/subscriptions/sub-example/providers/"
        "Microsoft.Network/locations/koreacentral/operations/operation-one"
    )
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(202, headers={"Azure-AsyncOperation": status_url})
    )
    async with httpx.AsyncClient(transport=transport) as client:
        gateway = OperationsGateway(
            config=_config(),
            reader_token_provider=_Tokens(),
            executor_token_provider=_Tokens(),
            http_client=client,
        )
        with pytest.raises(GatewayError) as error:
            await gateway.invoke(
                "azure.network.nsg.read",
                {"resource_group": "rg-example", "nsg_name": "nsg-app"},
                GatewayPrincipal("principal-user", frozenset({"group-contributor"})),
            )

    assert error.value.status_code == 502
    assert error.value.code == "azure_response_invalid"


async def test_contributor_app_role_can_read_without_group_claim() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"properties": {"securityRules": []}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        gateway = OperationsGateway(
            config=_config(),
            reader_token_provider=_Tokens(),
            executor_token_provider=_Tokens(),
            http_client=client,
        )
        result = await gateway.invoke(
            "azure.network.nsg.read",
            {"resource_group": "rg-example", "nsg_name": "nsg-app"},
            GatewayPrincipal(
                "principal-user",
                frozenset(),
                frozenset({"Contributor"}),
            ),
        )
    assert result["status"] == "succeeded"


async def test_user_cannot_mutate_even_with_contributor_group() -> None:
    transport = httpx.MockTransport(lambda _: httpx.Response(500))
    async with httpx.AsyncClient(transport=transport) as client:
        gateway = OperationsGateway(
            config=_config(),
            reader_token_provider=_Tokens(),
            executor_token_provider=_Tokens(),
            http_client=client,
        )
        with pytest.raises(GatewayError, match="Thor executor") as error:
            await gateway.invoke(
                "azure.compute.vm.start",
                {"resource_group": "rg-example", "vm_name": "vm-app", "safety": _safety()},
                GatewayPrincipal("principal-user", frozenset({"group-contributor"})),
            )
        assert error.value.status_code == 403


async def test_executor_requires_complete_safety_envelope() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert request.method == "POST"
        return httpx.Response(200, json={"status": "succeeded"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        gateway = OperationsGateway(
            config=_config(),
            reader_token_provider=_Tokens(),
            executor_token_provider=_Tokens(),
            http_client=client,
            idempotency_ledger=_Ledger(),
        )
        principal = GatewayPrincipal("principal-resilience", frozenset())
        with pytest.raises(GatewayError, match="safety envelope"):
            await gateway.invoke(
                "azure.compute.vm.start",
                {"resource_group": "rg-example", "vm_name": "vm-app"},
                principal,
            )
        for field in (
            "idempotency_key",
            "audit_ref",
            "dry_run_receipt",
            "stop_condition",
            "rollback_ref",
        ):
            incomplete_safety = dict(_safety())
            incomplete_safety.pop(field)
            with pytest.raises(GatewayError, match=f"safety.{field}"):
                await gateway.invoke(
                    "azure.compute.vm.start",
                    {
                        "resource_group": "rg-example",
                        "vm_name": "vm-app",
                        "safety": incomplete_safety,
                    },
                    principal,
                )
        missing_receipt = dict(_safety())
        missing_receipt["dry_run_receipt"] = "caller-asserted"
        with pytest.raises(GatewayError, match="dry-run receipt") as receipt_error:
            await gateway.invoke(
                "azure.compute.vm.start",
                {
                    "resource_group": "rg-example",
                    "vm_name": "vm-app",
                    "safety": missing_receipt,
                },
                principal,
            )
        assert receipt_error.value.status_code == 409
        result = await gateway.invoke(
            "azure.compute.vm.start",
            {"resource_group": "rg-example", "vm_name": "vm-app", "safety": _safety()},
            principal,
        )

    assert result["status"] == "succeeded"
    assert calls == 1


async def test_executor_plan_issues_receipt_for_matching_mutation() -> None:
    methods: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        return httpx.Response(200, json={"status": "succeeded"})

    ledger = _Ledger()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        gateway = OperationsGateway(
            config=_config(),
            reader_token_provider=_Tokens(),
            executor_token_provider=_Tokens(),
            http_client=client,
            idempotency_ledger=ledger,
        )
        principal = GatewayPrincipal("principal-resilience", frozenset())
        arguments = {"resource_group": "rg-example", "vm_name": "vm-app"}
        planned_safety = dict(_safety("operation:planned"))
        planned_safety.pop("dry_run_receipt")
        plan = await gateway.invoke(
            "azure.operation.plan",
            {
                "operation_id": "azure.compute.vm.start",
                "arguments": arguments,
                "safety": planned_safety,
            },
            principal,
        )
        plan_result = cast(Mapping[str, object], plan["result"])
        safety = dict(planned_safety)
        safety["dry_run_receipt"] = plan_result["dry_run_receipt"]
        applied = await gateway.invoke(
            "azure.compute.vm.start",
            {**arguments, "safety": safety},
            principal,
        )

    assert plan_result["status"] == "planned"
    assert applied["status"] == "succeeded"
    assert methods == ["GET", "POST"]


async def test_executor_plan_receipt_rejects_changed_safety_evidence() -> None:
    ledger = _Ledger()
    mutation_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal mutation_calls
        if request.method == "GET":
            return httpx.Response(200, json={"status": "observed"})
        mutation_calls += 1
        return httpx.Response(500)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        gateway = OperationsGateway(
            config=_config(),
            reader_token_provider=_Tokens(),
            executor_token_provider=_Tokens(),
            http_client=client,
            idempotency_ledger=ledger,
        )
        principal = GatewayPrincipal("principal-resilience", frozenset())
        arguments = {"resource_group": "rg-example", "vm_name": "vm-app"}
        planned_safety = dict(_safety("operation:changed"))
        planned_safety.pop("dry_run_receipt")
        plan = await gateway.invoke(
            "azure.operation.plan",
            {
                "operation_id": "azure.compute.vm.start",
                "arguments": arguments,
                "safety": planned_safety,
            },
            principal,
        )
        plan_result = cast(Mapping[str, object], plan["result"])
        changed_safety = dict(planned_safety)
        changed_safety["rollback_ref"] = "rollback:different"
        changed_safety["dry_run_receipt"] = plan_result["dry_run_receipt"]
        with pytest.raises(GatewayError) as error:
            await gateway.invoke(
                "azure.compute.vm.start",
                {**arguments, "safety": changed_safety},
                principal,
            )

    assert error.value.status_code == 409
    assert error.value.code == "dry_run_invalid"
    assert mutation_calls == 0


async def test_executor_plan_receipt_rejects_another_operation() -> None:
    ledger = _Ledger()
    mutation_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal mutation_calls
        if request.method == "GET":
            return httpx.Response(200, json={"status": "observed"})
        mutation_calls += 1
        return httpx.Response(500)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        gateway = OperationsGateway(
            config=_config(),
            reader_token_provider=_Tokens(),
            executor_token_provider=_Tokens(),
            http_client=client,
            idempotency_ledger=ledger,
        )
        principal = GatewayPrincipal("principal-resilience", frozenset())
        arguments = {"resource_group": "rg-example", "vm_name": "vm-app"}
        planned_safety = dict(_safety("operation:cross"))
        planned_safety.pop("dry_run_receipt")
        plan = await gateway.invoke(
            "azure.operation.plan",
            {
                "operation_id": "azure.compute.vm.start",
                "arguments": arguments,
                "safety": planned_safety,
            },
            principal,
        )
        plan_result = cast(Mapping[str, object], plan["result"])
        safety = dict(planned_safety)
        safety["dry_run_receipt"] = plan_result["dry_run_receipt"]
        with pytest.raises(GatewayError) as error:
            await gateway.invoke(
                "azure.compute.vm.deallocate",
                {**arguments, "safety": safety},
                GatewayPrincipal("principal-finops", frozenset()),
            )

    assert error.value.code == "dry_run_invalid"
    assert mutation_calls == 0


async def test_arm_retries_429_with_bounded_retry_after() -> None:
    calls = 0
    delays: list[float] = []

    async def sleeper(delay: float) -> None:
        delays.append(delay)

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "2"})
        return httpx.Response(200, json={"properties": {"securityRules": []}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        gateway = OperationsGateway(
            config=_config(),
            reader_token_provider=_Tokens(),
            executor_token_provider=_Tokens(),
            http_client=client,
            sleep=sleeper,
        )
        result = await gateway.invoke(
            "azure.network.nsg.read",
            {"resource_group": "rg-example", "nsg_name": "nsg-app"},
            GatewayPrincipal("principal-user", frozenset({"group-contributor"})),
        )

    assert result["status"] == "succeeded"
    assert calls == 2
    assert delays == [2.0]


async def test_executor_mutation_is_idempotent_across_duplicate_delivery() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert request.method == "POST"
        return httpx.Response(200, json={"status": "succeeded"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        gateway = OperationsGateway(
            config=_config(),
            reader_token_provider=_Tokens(),
            executor_token_provider=_Tokens(),
            http_client=client,
            idempotency_ledger=_Ledger(),
        )
        principal = GatewayPrincipal("principal-resilience", frozenset())
        payload = {
            "resource_group": "rg-example",
            "vm_name": "vm-app",
            "safety": _safety(),
        }

        first = await gateway.invoke("azure.compute.vm.start", payload, principal)
        duplicate = await gateway.invoke("azure.compute.vm.start", payload, principal)

    assert duplicate == first
    assert calls == 1


async def test_executor_tracks_arm_long_running_operation_by_idempotency_key() -> None:
    status_url = (
        "https://management.azure.com/subscriptions/sub-example/providers/"
        "Microsoft.Compute/locations/koreacentral/operations/operation-one"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(202, headers={"Azure-AsyncOperation": status_url})
        assert str(request.url) == status_url
        return httpx.Response(200, json={"status": "Succeeded"})

    class TrackingLedger(_Ledger):
        def __init__(self) -> None:
            super().__init__()
            self.lease_events: list[str] = []

        async def acquire_resource(self, resource_key: str) -> str:
            self.lease_events.append(f"acquire:{resource_key}")
            return "lease-one"

        async def renew_resource(self, resource_key: str, lease_id: str) -> None:
            assert lease_id == "lease-one"
            self.lease_events.append(f"renew:{resource_key}")

        async def release_resource(self, resource_key: str, lease_id: str) -> None:
            assert lease_id == "lease-one"
            self.lease_events.append(f"release:{resource_key}")

    ledger = TrackingLedger()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        gateway = OperationsGateway(
            config=_config(),
            reader_token_provider=_Tokens(),
            executor_token_provider=_Tokens(),
            http_client=client,
            idempotency_ledger=ledger,
        )
        principal = GatewayPrincipal("principal-resilience", frozenset())
        payload = {
            "resource_group": "rg-example",
            "vm_name": "vm-app",
            "safety": _safety(),
        }

        submitted = await gateway.invoke("azure.compute.vm.start", payload, principal)
        status = await gateway.invoke(
            "azure.operation.status",
            {
                "idempotency_key": "operation:one",
                "operation_id": "azure.compute.vm.start",
            },
            principal,
        )

    assert submitted == {
        "operation_id": "azure.compute.vm.start",
        "status": "submitted",
        "result": {"accepted": True, "status": "submitted"},
    }
    assert status == {
        "operation_id": "azure.operation.status",
        "status": "succeeded",
        "result": {"provider_status": "Succeeded", "status": "succeeded"},
    }
    assert status_url not in repr(submitted)
    assert [event.split(":", 1)[0] for event in ledger.lease_events] == [
        "acquire",
        "renew",
        "release",
    ]


async def test_mutation_rejects_unrecognized_arm_status_query() -> None:
    status_url = (
        "https://management.azure.com/subscriptions/sub-example/providers/"
        "Microsoft.Compute/locations/koreacentral/operations/operation-one"
        "?redirect=https://example.com"
    )
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(202, headers={"Azure-AsyncOperation": status_url})
    )
    async with httpx.AsyncClient(transport=transport) as client:
        gateway = OperationsGateway(
            config=_config(),
            reader_token_provider=_Tokens(),
            executor_token_provider=_Tokens(),
            http_client=client,
            idempotency_ledger=_Ledger(),
        )
        with pytest.raises(GatewayError) as error:
            await gateway.invoke(
                "azure.compute.vm.start",
                {
                    "resource_group": "rg-example",
                    "vm_name": "vm-app",
                    "safety": _safety("operation:query"),
                },
                GatewayPrincipal("principal-resilience", frozenset()),
            )

    assert error.value.code == "azure_response_invalid"


async def test_executor_token_failure_releases_claim_and_resource() -> None:
    class FailingTokens:
        async def get_token(self, audience: str) -> str:
            assert audience
            raise GatewayError(503, "identity_unavailable", "executor identity failed")

    class TrackingLedger(_Ledger):
        def __init__(self) -> None:
            super().__init__()
            self.held: set[str] = set()

        async def acquire_resource(self, resource_key: str) -> str:
            self.held.add(resource_key)
            return "lease-one"

        async def release_resource(self, resource_key: str, lease_id: str) -> None:
            assert lease_id == "lease-one"
            self.held.remove(resource_key)

    ledger = TrackingLedger()
    transport = httpx.MockTransport(lambda _request: httpx.Response(500))
    async with httpx.AsyncClient(transport=transport) as client:
        gateway = OperationsGateway(
            config=_config(),
            reader_token_provider=_Tokens(),
            executor_token_provider=FailingTokens(),
            http_client=client,
            idempotency_ledger=ledger,
        )
        with pytest.raises(GatewayError, match="executor identity failed"):
            await gateway.invoke(
                "azure.compute.vm.start",
                {
                    "resource_group": "rg-example",
                    "vm_name": "vm-app",
                    "safety": _safety("operation:token-failure"),
                },
                GatewayPrincipal("principal-resilience", frozenset()),
            )

    assert ledger.held == set()
    assert "operation:token-failure" not in ledger.records


async def test_same_resource_different_idempotency_keys_are_serialized() -> None:
    entered_token = asyncio.Event()
    release_token = asyncio.Event()

    class BlockingTokens:
        async def get_token(self, audience: str) -> str:
            assert audience
            entered_token.set()
            await release_token.wait()
            return "token"

    class BusyLedger(_Ledger):
        def __init__(self) -> None:
            super().__init__()
            self.held: set[str] = set()

        async def acquire_resource(self, resource_key: str) -> str:
            if resource_key in self.held:
                raise IdempotencyError(
                    409,
                    "resource_busy",
                    "another mutation is already operating on this resource",
                )
            self.held.add(resource_key)
            return "lease-one"

        async def release_resource(self, resource_key: str, lease_id: str) -> None:
            assert lease_id == "lease-one"
            self.held.remove(resource_key)

    transport = httpx.MockTransport(lambda _request: httpx.Response(200, json={"ok": True}))
    async with httpx.AsyncClient(transport=transport) as client:
        gateway = OperationsGateway(
            config=_config(),
            reader_token_provider=_Tokens(),
            executor_token_provider=BlockingTokens(),
            http_client=client,
            idempotency_ledger=BusyLedger(),
        )
        resilience_principal = GatewayPrincipal("principal-resilience", frozenset())
        first = asyncio.create_task(
            gateway.invoke(
                "azure.compute.vm.start",
                {
                    "resource_group": "rg-example",
                    "vm_name": "vm-app",
                    "safety": _safety("operation:first"),
                },
                resilience_principal,
            )
        )
        await entered_token.wait()
        with pytest.raises(GatewayError) as busy:
            await gateway.invoke(
                "azure.compute.vm.deallocate",
                {
                    "resource_group": "rg-example",
                    "vm_name": "vm-app",
                    "safety": _safety("operation:second"),
                },
                GatewayPrincipal("principal-finops", frozenset()),
            )
        release_token.set()
        await first

    assert busy.value.status_code == 409
    assert busy.value.code == "resource_busy"


@pytest.mark.parametrize(
    ("operation_id", "wrong_principal"),
    (
        ("azure.network.nsg.rule.upsert", "principal-resilience"),
        ("azure.network.nsg.rule.delete", "principal-finops"),
        ("azure.compute.vm.start", "principal-change"),
        ("azure.compute.vm.deallocate", "principal-resilience"),
    ),
)
async def test_wrong_vertical_executor_is_rejected_before_plan_or_mutation(
    operation_id: str,
    wrong_principal: str,
) -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        gateway = OperationsGateway(
            config=_config(),
            reader_token_provider=_Tokens(),
            executor_token_provider=_Tokens(),
            http_client=client,
            idempotency_ledger=_Ledger(),
        )
        with pytest.raises(GatewayError) as error:
            await gateway.invoke(
                "azure.operation.plan",
                {
                    "operation_id": operation_id,
                    "arguments": {"resource_group": "rg-example", "vm_name": "vm-app"},
                    "safety": {
                        key: value
                        for key, value in _safety("operation:wrong-vertical").items()
                        if key != "dry_run_receipt"
                    },
                },
                GatewayPrincipal(wrong_principal, frozenset()),
            )

    assert error.value.status_code == 403
    assert error.value.code == "executor_vertical_denied"
    assert calls == 0


async def test_wrong_vertical_status_is_rejected_before_ledger_lookup() -> None:
    class NoLookupLedger(_Ledger):
        async def lookup(self, idempotency_key: str) -> Mapping[str, object]:
            del idempotency_key
            raise AssertionError("wrong-vertical status reached the operation ledger")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _request: httpx.Response(500))
    ) as client:
        gateway = OperationsGateway(
            config=_config(),
            reader_token_provider=_Tokens(),
            executor_token_provider=_Tokens(),
            http_client=client,
            idempotency_ledger=NoLookupLedger(),
        )
        with pytest.raises(GatewayError) as error:
            await gateway.invoke(
                "azure.operation.status",
                {
                    "idempotency_key": "operation:one",
                    "operation_id": "azure.compute.vm.start",
                },
                GatewayPrincipal("principal-change", frozenset()),
            )

    assert error.value.status_code == 403
    assert error.value.code == "executor_vertical_denied"
