"""Current-source concept evidence, not a provider incident or live qualification."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from functools import partial
from typing import cast

import httpx
import pytest
from fdai.delivery.azure import arg_transport, arm_inventory_transport
from fdai.delivery.azure.arm_inventory_transport import fetch_arm_json
from fdai.delivery.azure.arm_inventory_vm_state import ArmInventoryError
from fdai.delivery.azure.workload_identity import (
    ManagedIdentityWorkloadIdentity,
    ManagedIdentityWorkloadIdentityConfig,
)
from fdai.delivery.inventory_change_acceleration import load_resource_type_registry
from fdai.delivery.inventory_collection import collection_context_digest
from fdai.delivery.inventory_job_config import InventoryJobConfig
from fdai.delivery.inventory_sync_cli_support import build_sources
from fdai.shared.providers.inventory import Inventory
from fdai.shared.providers.inventory_snapshot import InventoryCoverageManifest


async def test_arg_cooldown_is_adapter_local_not_replayed_by_a_replacement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = 0.0
    waits: list[float] = []

    async def sleep(delay: float) -> None:
        nonlocal now
        waits.append(delay)
        now += delay

    monkeypatch.setattr(arg_transport, "_monotonic", lambda: now)
    monkeypatch.setattr(arg_transport, "_sleep", sleep)
    original = arg_transport.ArgThrottleGate()
    await original.defer(20.0)
    replacement = arg_transport.ArgThrottleGate()
    await replacement.wait()
    assert waits == []
    assert now == 0.0
    await original.wait()
    assert waits == [20.0]
    assert now == 20.0


@pytest.mark.parametrize("source_name", ["arg", "arm"])
async def test_source_context_does_not_bind_the_selected_managed_identity(
    source_name: str,
) -> None:
    """Exercise actual source reads; equal context digests are not identity witnesses."""

    config = InventoryJobConfig.from_env(
        {
            "FDAI_INVENTORY_DSN": "postgresql://example.invalid/unused",
            "FDAI_INVENTORY_SCOPES": "00000000-0000-0000-0000-000000000000",
            "FDAI_INVENTORY_SOURCES": source_name,
            "FDAI_INVENTORY_RESOURCE_TYPES": "resource-group",
        }
    )
    identity_selections: list[str] = []
    provider_authorizations: list[str] = []
    manifests: list[InventoryCoverageManifest] = []

    async def respond(request: httpx.Request) -> httpx.Response:
        if request.url.host == "identity.example.invalid":
            selected = request.url.params["client_id"]
            identity_selections.append(selected)
            return httpx.Response(
                200,
                json={"access_token": f"synthetic-{selected}", "expires_on": 1_893_456_000},
            )
        provider_authorizations.append(request.headers["Authorization"])
        if request.method == "POST":
            return httpx.Response(
                200,
                json={"data": [], "count": 0, "totalRecords": 0, "resultTruncated": "false"},
            )
        return httpx.Response(200, json={"value": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        for principal in (
            "00000000-0000-0000-0000-000000000001",
            "00000000-0000-0000-0000-000000000002",
        ):
            identity = ManagedIdentityWorkloadIdentity(
                http_client=client,
                config=ManagedIdentityWorkloadIdentityConfig(
                    endpoint="https://identity.example.invalid/token",
                    header="synthetic-header",
                    client_id=principal,
                ),
            )
            (source,) = build_sources(
                config=config,
                vocabulary=load_resource_type_registry(),
                resource_types=("resource-group",),
                identity=identity,
                http_client=client,
                started_at=datetime(2026, 10, 21, tzinfo=UTC),
            )
            manifests.append(source.manifest)
            before = len(provider_authorizations)
            batches = [batch async for batch in cast(Inventory, source.inventory).full_snapshot()]
            assert batches
            assert len(provider_authorizations) > before
            assert set(provider_authorizations[before:]) == {f"Bearer synthetic-{principal}"}

    assert len(set(identity_selections)) == 2
    assert manifests[0] == manifests[1]
    assert collection_context_digest(manifests[0]) == collection_context_digest(manifests[1])


async def test_arm_retry_after_is_not_retained_by_the_next_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A retained error deadline is not a gate on the next physical request."""

    now = datetime(2026, 10, 21, tzinfo=UTC)
    waits: list[float] = []
    calls = 0

    class Clock:
        @staticmethod
        def now(_: object) -> datetime:
            return now

    async def sleep(delay: float) -> None:
        waits.append(delay)

    def respond(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "120"})
        return httpx.Response(200, json={"value": []})

    monkeypatch.setattr(arm_inventory_transport, "_sleep", sleep)
    monkeypatch.setattr(arm_inventory_transport, "datetime", Clock)
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        fetch = partial(
            fetch_arm_json,
            client=client,
            url="https://management.example.invalid/resources",
            headers={},
            resource_type="resource-group",
            timeout_seconds=1.0,
            max_response_bytes=1024,
            max_attempts=1,
        )
        with pytest.raises(ArmInventoryError) as failure:
            await fetch()
        deadline = failure.value.retry_not_before
        assert deadline == now + timedelta(seconds=120)
        payload, _ = await fetch()

    assert payload == {"value": []}
    assert calls == 2
    assert waits == []
