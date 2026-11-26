"""Azure target revisions pin a development approval to the exact current resource state."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fdai.delivery.azure.target_revision import AzureTargetRevisionReader, revision_digest
from fdai.shared.providers.workload_identity import IdentityToken

TARGET = (
    "/subscriptions/00000000-0000-0000-0000-00000000de01/resourceGroups/rg-fdai-dev"
    "/providers/Microsoft.Insights/metricAlerts/cpu-high"
)
AUDIENCE = "https://management.azure.com/.default"


class Identity:
    def __init__(self, *, audience: str = AUDIENCE, fail: bool = False) -> None:
        self.audience, self.fail = audience, fail

    async def get_token(self, audience: str) -> IdentityToken:
        if self.fail:
            raise RuntimeError("identity unavailable")
        return IdentityToken("test-token", datetime.now(UTC) + timedelta(minutes=5), self.audience)


def _resource(**overrides: object) -> dict[str, object]:
    return {
        "id": TARGET,
        "type": "Microsoft.Insights/metricAlerts",
        "location": "global",
        "tags": {},
        "properties": {"enabled": True, "severity": 3},
        **overrides,
    }


async def _read(
    handler: httpx.MockTransport | None = None,
    *,
    target: str = TARGET,
    identity: Identity | None = None,
) -> str | None:
    transport = handler or httpx.MockTransport(lambda _: httpx.Response(200, json=_resource()))
    async with httpx.AsyncClient(transport=transport) as http:
        reader = AzureTargetRevisionReader(http=http, identity=identity or Identity())
        return await reader.read_revision(target)


async def test_reader_pins_the_complete_configuration_of_the_exact_resource() -> None:
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=_resource(id=TARGET.upper()))

    revision = await _read(httpx.MockTransport(handle))

    assert revision == revision_digest(_resource(id=TARGET.upper()))
    assert seen[0].url.path == TARGET
    assert seen[0].url.params["api-version"] == "2018-03-01"
    assert seen[0].headers["authorization"] == "Bearer test-token"
    changed = revision_digest(_resource(properties={"enabled": False, "severity": 3}))
    assert changed != revision_digest(_resource())


def test_an_etag_alone_is_the_revision_when_the_provider_offers_one() -> None:
    assert revision_digest(_resource(etag='"1"')) == revision_digest({"etag": '"1"', "id": "x"})
    assert revision_digest(_resource(etag='"1"')) != revision_digest(_resource(etag='"2"'))


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(404, json={}),
        httpx.Response(200, content=b"{not json"),
        httpx.Response(200, json=[]),
        httpx.Response(200, json=_resource(id=TARGET.replace("cpu-high", "other"))),
        httpx.Response(200, content=json.dumps(_resource(padding="x" * 1_000_001)).encode()),
    ],
)
async def test_any_doubtful_provider_answer_establishes_no_revision(
    response: httpx.Response,
) -> None:
    assert await _read(httpx.MockTransport(lambda _: response)) is None


async def test_unsupported_targets_and_identities_establish_no_revision() -> None:
    def refuse(_: httpx.Request) -> httpx.Response:
        raise AssertionError("an unsupported target MUST NOT be read")

    virtual_machine = TARGET.replace(
        "Microsoft.Insights/metricAlerts", "Microsoft.Compute/virtualMachines"
    )

    assert await _read(httpx.MockTransport(refuse), target=virtual_machine) is None
    assert await _read(httpx.MockTransport(refuse), target="resource:example/rg/vm1") is None
    assert await _read(identity=Identity(fail=True)) is None
    assert await _read(identity=Identity(audience="api://other/.default")) is None

    def fail(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("unreachable")

    assert await _read(httpx.MockTransport(fail)) is None


def test_reader_rejects_an_unbounded_timeout() -> None:
    with pytest.raises(ValueError, match="timeout"):
        AzureTargetRevisionReader(http=httpx.AsyncClient(), identity=Identity(), timeout_seconds=31)
