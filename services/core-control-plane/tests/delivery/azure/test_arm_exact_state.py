from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fdai.delivery.azure.arm_exact_state import AzureArmExactStateReader
from fdai.shared.providers.exact_resource_state import ExactResourceStateUnavailableError
from fdai.shared.providers.workload_identity import IdentityToken

_SUB = "00000000-0000-0000-0000-000000000001"
_VM = f"/subscriptions/{_SUB}/resourceGroups/rg-a/providers/Microsoft.Compute/virtualMachines/vm-a"
_PG = (
    f"/subscriptions/{_SUB}/resourceGroups/rg-a/providers/"
    "Microsoft.DBforPostgreSQL/flexibleServers/pg-a"
)
_DATE = "Thu, 08 Oct 2026 07:31:30 GMT"


class _Identity:
    async def get_token(self, audience: str) -> IdentityToken:
        return IdentityToken(
            token="token",
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
            audience=audience,
        )


def _reader(handler: httpx.MockTransport) -> AzureArmExactStateReader:
    return AzureArmExactStateReader(
        identity=_Identity(),
        http_client=httpx.AsyncClient(transport=handler),
    )


async def test_vm_state_comes_from_the_single_power_status_of_the_instance_view() -> None:
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            headers={"date": _DATE},
            json={
                "statuses": [
                    {"code": "ProvisioningState/succeeded"},
                    {"code": "PowerState/running"},
                ]
            },
        )

    reading = await _reader(httpx.MockTransport(handle)).read_state(
        resource_ref="vm-a-id",
        resource_type="compute.vm",
        provider_ref=_VM,
        timeout_seconds=3.0,
    )

    assert reading is not None
    assert reading.state == "PowerState/running"
    assert reading.provider_time == datetime(2026, 10, 8, 7, 31, 30, tzinfo=UTC)
    assert reading.evidence_ref.startswith("arm-state:sha256:")
    assert seen[0].url.path.endswith("/virtualMachines/vm-a/instanceView")
    assert seen[0].headers["authorization"] == "Bearer token"


async def test_database_state_comes_from_properties_state() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"date": _DATE}, json={"properties": {"state": "Stopped"}}
        )

    reading = await _reader(httpx.MockTransport(handle)).read_state(
        resource_ref="pg-a-id",
        resource_type="postgresql-server",
        provider_ref=_PG,
        timeout_seconds=3.0,
    )

    assert reading is not None and reading.state == "Stopped"


@pytest.mark.parametrize(
    ("status", "headers", "body"),
    [
        (200, {}, {"statuses": [{"code": "PowerState/running"}]}),
        (
            200,
            {"date": _DATE},
            {"statuses": [{"code": "PowerState/running"}, {"code": "PowerState/stopped"}]},
        ),
        (200, {"date": _DATE}, {"statuses": [{"code": "ProvisioningState/succeeded"}]}),
        (403, {"date": _DATE}, {}),
        (404, {"date": _DATE}, {}),
    ],
)
async def test_unproven_or_denied_reads_yield_no_reading(
    status: int,
    headers: dict[str, str],
    body: dict[str, object],
) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, headers=headers, json=body)

    reading = await _reader(httpx.MockTransport(handle)).read_state(
        resource_ref="vm-a-id",
        resource_type="compute.vm",
        provider_ref=_VM,
        timeout_seconds=3.0,
    )

    assert reading is None


@pytest.mark.parametrize("status", [429, 500, 503])
async def test_throttling_and_outage_are_unavailable_not_absent(status: int) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, headers={"date": _DATE})

    with pytest.raises(ExactResourceStateUnavailableError):
        await _reader(httpx.MockTransport(handle)).read_state(
            resource_ref="vm-a-id",
            resource_type="compute.vm",
            provider_ref=_VM,
            timeout_seconds=3.0,
        )


async def test_unsupported_types_and_mismatched_ids_are_never_read() -> None:
    def handle(request: httpx.Request) -> httpx.Response:  # pragma: no cover - must not run
        raise AssertionError("no request expected")

    reader = _reader(httpx.MockTransport(handle))

    assert not reader.supports("cache")
    assert (
        await reader.read_state(
            resource_ref="x", resource_type="cache", provider_ref=_VM, timeout_seconds=3.0
        )
        is None
    )
    # A database id cannot be read with the virtual machine capability.
    assert (
        await reader.read_state(
            resource_ref="x", resource_type="compute.vm", provider_ref=_PG, timeout_seconds=3.0
        )
        is None
    )
    assert (
        await reader.read_state(
            resource_ref="x", resource_type="compute.vm", provider_ref="vm-a", timeout_seconds=3.0
        )
        is None
    )
