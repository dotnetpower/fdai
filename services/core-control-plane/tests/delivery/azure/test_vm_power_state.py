"""Tests for the dedicated Azure VM power-state observer source."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fdai.delivery.azure.vm_power_state import (
    AzureArmVmPowerStateSource,
    AzureVmPowerStateConfig,
    AzureVmPowerStateSourceError,
)
from fdai.shared.providers.workload_identity import IdentityToken

from tests.delivery.azure.vm_power_state_fixtures import RESOURCE_REF

NOW = datetime(2026, 9, 12, 4, 1, tzinfo=UTC)


class _Identity:
    def __init__(self) -> None:
        self.audiences: list[str] = []

    async def get_token(self, audience: str) -> IdentityToken:
        self.audiences.append(audience)
        return IdentityToken(
            token="test-token",
            expires_at=NOW + timedelta(minutes=5),
            audience=audience,
        )


def _config(**changes: object) -> AzureVmPowerStateConfig:
    values: dict[str, object] = {
        "resource_ref": RESOURCE_REF,
        "resource_group": "rg-example",
        "vm_name": "vm-example",
    }
    values.update(changes)
    return AzureVmPowerStateConfig(**values)  # type: ignore[arg-type]


def _payload(*codes: str, resource_ref: str = RESOURCE_REF) -> dict[str, object]:
    return {
        "id": resource_ref,
        "type": "Microsoft.Compute/virtualMachines",
        "etag": 'W/"synthetic-etag"',
        "properties": {
            "instanceView": {
                "statuses": [{"code": code} for code in codes],
            }
        },
    }


def _source(
    handler: httpx.MockTransport,
    *,
    identity: _Identity | None = None,
) -> tuple[AzureArmVmPowerStateSource, _Identity]:
    observer = identity or _Identity()
    return (
        AzureArmVmPowerStateSource(
            identity=observer,
            http_client=httpx.AsyncClient(transport=handler),
            config=_config(),
            clock=lambda: NOW,
        ),
        observer,
    )


async def test_reads_only_the_pinned_vm_instance_view() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path.casefold() == RESOURCE_REF.casefold()
        assert request.url.params["api-version"] == "2024-07-01"
        assert request.url.params["$expand"] == "instanceView"
        assert request.headers["Authorization"] == "Bearer test-token"
        return httpx.Response(200, json=_payload("PowerState/running"))

    source, identity = _source(httpx.MockTransport(handler))
    reading = await source.observe(resource_ref=RESOURCE_REF, target_revision=3)

    assert reading.state == "running"
    assert reading.complete is True
    assert reading.conflicts == ()
    assert reading.target_revision == 3
    assert reading.evidence_refs[0].startswith("sha256:")
    assert identity.audiences == ["https://management.azure.com/.default"]


@pytest.mark.parametrize(
    "state",
    ["starting", "stopped", "stopping", "deallocating", "deallocated"],
)
async def test_preserves_recognized_power_states_as_complete_evidence(state: str) -> None:
    source, _ = _source(
        httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                json=_payload(f"PowerState/{state}"),
            )
        )
    )

    reading = await source.observe(resource_ref=RESOURCE_REF, target_revision=3)

    assert reading.state == state
    assert reading.complete is True


@pytest.mark.parametrize(
    ("codes", "expected_conflict"),
    [
        ((), ()),
        (
            ("PowerState/running", "PowerState/stopped"),
            (
                "conflicting_power_state:running",
                "conflicting_power_state:stopped",
            ),
        ),
        (("PowerState/future-state",), ("unsupported_power_state:future-state",)),
    ],
)
async def test_unusable_state_is_never_scored_as_a_definitive_value(
    codes: tuple[str, ...],
    expected_conflict: tuple[str, ...],
) -> None:
    source, _ = _source(
        httpx.MockTransport(lambda _request: httpx.Response(200, json=_payload(*codes)))
    )

    reading = await source.observe(resource_ref=RESOURCE_REF, target_revision=3)

    assert reading.state is None
    assert reading.complete is bool(expected_conflict)
    assert reading.conflicts == expected_conflict


async def test_provider_unknown_state_remains_unscorable() -> None:
    source, _ = _source(
        httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                json=_payload("PowerState/unknown"),
            )
        )
    )

    reading = await source.observe(resource_ref=RESOURCE_REF, target_revision=3)

    assert reading.state is None
    assert reading.complete is True
    assert reading.conflicts == ("unsupported_power_state:unknown",)


async def test_substituted_target_is_rejected() -> None:
    source, _ = _source(
        httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                json=_payload(
                    "PowerState/running",
                    resource_ref=RESOURCE_REF.replace("vm-example", "vm-other"),
                ),
            )
        )
    )

    with pytest.raises(AzureVmPowerStateSourceError, match="target changed"):
        await source.observe(resource_ref=RESOURCE_REF, target_revision=3)


@pytest.mark.parametrize("status_code", [302, 404, 429, 500])
async def test_non_success_status_fails_closed(status_code: int) -> None:
    source, _ = _source(
        httpx.MockTransport(
            lambda _request: httpx.Response(status_code, json={"error": "synthetic"})
        )
    )

    with pytest.raises(AzureVmPowerStateSourceError, match="non-success"):
        await source.observe(resource_ref=RESOURCE_REF, target_revision=3)


async def test_oversized_or_invalid_response_fails_closed() -> None:
    oversized_source, _ = _source(
        httpx.MockTransport(lambda _request: httpx.Response(200, content=b"x" * 70_000))
    )
    invalid_source, _ = _source(
        httpx.MockTransport(lambda _request: httpx.Response(200, content=b"not-json"))
    )

    with pytest.raises(AzureVmPowerStateSourceError, match="size limit"):
        await oversized_source.observe(resource_ref=RESOURCE_REF, target_revision=3)
    with pytest.raises(AzureVmPowerStateSourceError, match="invalid JSON"):
        await invalid_source.observe(resource_ref=RESOURCE_REF, target_revision=3)


def test_config_rejects_scope_or_endpoint_substitution() -> None:
    with pytest.raises(ValueError, match="matching Azure VM"):
        _config(resource_group="rg-other")
    with pytest.raises(ValueError, match="Azure management origin"):
        _config(endpoint="https://example.com")
    with pytest.raises(ValueError, match="canonical UUID"):
        _config(
            resource_ref=RESOURCE_REF.replace(
                "00000000-0000-0000-0000-000000000000",
                "sub?redirect=1",
            )
        )
