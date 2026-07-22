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
        executor_principal_id="principal-executor",
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
        "FDAI_DEV_GATEWAY_EXECUTOR_PRINCIPAL_ID": "principal-executor",
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
                GatewayPrincipal("principal-executor", frozenset()),
            )

    assert error.value.status_code == 404
    assert error.value.code == "operation_not_found"
    assert calls == 0


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
        executor_principal_id=config.executor_principal_id,
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
        principal = GatewayPrincipal("principal-executor", frozenset())
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
        principal = GatewayPrincipal("principal-executor", frozenset())
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
        principal = GatewayPrincipal("principal-executor", frozenset())
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
        principal = GatewayPrincipal("principal-executor", frozenset())
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
                principal,
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
        principal = GatewayPrincipal("principal-executor", frozenset())
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

    ledger = _Ledger()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        gateway = OperationsGateway(
            config=_config(),
            reader_token_provider=_Tokens(),
            executor_token_provider=_Tokens(),
            http_client=client,
            idempotency_ledger=ledger,
        )
        principal = GatewayPrincipal("principal-executor", frozenset())
        payload = {
            "resource_group": "rg-example",
            "vm_name": "vm-app",
            "safety": _safety(),
        }

        submitted = await gateway.invoke("azure.compute.vm.start", payload, principal)
        status = await gateway.invoke(
            "azure.operation.status",
            {"idempotency_key": "operation:one"},
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
        principal = GatewayPrincipal("principal-executor", frozenset())
        first = asyncio.create_task(
            gateway.invoke(
                "azure.compute.vm.start",
                {
                    "resource_group": "rg-example",
                    "vm_name": "vm-app",
                    "safety": _safety("operation:first"),
                },
                principal,
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
                principal,
            )
        release_token.set()
        await first

    assert busy.value.status_code == 409
    assert busy.value.code == "resource_busy"
