from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fdai.delivery.azure.inventory_progress_blob import (
    AzureBlobInventoryProgressConfig,
    AzureBlobInventoryProgressPublisher,
)
from fdai.delivery.inventory_progress import INVENTORY_PROGRESS_GENESIS_DIGEST
from fdai.shared.providers.workload_identity import IdentityToken
from fdai_service_contracts import (
    InventoryProgressFractionBasis,
    InventoryProgressRecord,
    InventoryProgressStage,
    InventoryProgressState,
    inventory_progress_record_digest,
)

NOW = datetime(2026, 9, 16, tzinfo=UTC)


class _Identity:
    def __init__(self) -> None:
        self.audiences: list[str] = []

    async def get_token(self, audience: str) -> IdentityToken:
        self.audiences.append(audience)
        return IdentityToken("token", NOW + timedelta(minutes=5), audience)


def _record() -> InventoryProgressRecord:
    values: dict[str, object] = {
        "run_id": "run.abcdef",
        "attempt_id": "attempt.1",
        "sequence": 1,
        "previous_digest": INVENTORY_PROGRESS_GENESIS_DIGEST,
        "stage": InventoryProgressStage.COUNT,
        "state": InventoryProgressState.RUNNING,
        "scopes_completed": 0,
        "scopes_total": 1,
        "provider_types_completed": 0,
        "provider_types_total": 2,
        "resources_observed": 0,
        "resources_expected": 10,
        "pages_completed": 0,
        "pages_expected": 2,
        "links_observed": 0,
        "unmapped_objects": 0,
        "coverage_gaps": 0,
        "started_at": NOW,
        "last_progress_at": NOW + timedelta(seconds=1),
        "deadline_at": NOW + timedelta(minutes=5),
        "fraction": 0.05,
        "fraction_basis": InventoryProgressFractionBasis.COUNT,
    }
    return InventoryProgressRecord(
        **values,
        record_digest=inventory_progress_record_digest(**values),
    )


async def test_blob_publisher_creates_immutable_count_only_record() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(201)

    identity = _Identity()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        inserted = await AzureBlobInventoryProgressPublisher(
            config=AzureBlobInventoryProgressConfig(
                container_url="https://example.blob.core.windows.net/progress"
            ),
            identity=identity,
            http_client=client,
        ).append(_record())

    assert inserted is True
    assert identity.audiences == ["https://storage.azure.com/.default"]
    request = requests[0]
    assert request.headers["if-none-match"] == "*"
    assert request.headers["x-ms-blob-type"] == "BlockBlob"
    payload = json.loads(request.content)
    assert payload["execution_authority"] is False
    assert "resource_id" not in payload


async def test_blob_publisher_accepts_only_exact_duplicate() -> None:
    record = _record()
    payload = json.dumps(
        record.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    ).encode()

    def exact(request: httpx.Request) -> httpx.Response:
        return httpx.Response(412 if request.method == "PUT" else 200, content=payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(exact)) as client:
        inserted = await AzureBlobInventoryProgressPublisher(
            config=AzureBlobInventoryProgressConfig(
                container_url="https://example.blob.core.windows.net/progress"
            ),
            identity=_Identity(),
            http_client=client,
        ).append(record)
    assert inserted is False

    def conflict(request: httpx.Request) -> httpx.Response:
        return httpx.Response(412 if request.method == "PUT" else 200, content=b"{}")

    async with httpx.AsyncClient(transport=httpx.MockTransport(conflict)) as client:
        with pytest.raises(ValueError, match="conflicts"):
            await AzureBlobInventoryProgressPublisher(
                config=AzureBlobInventoryProgressConfig(
                    container_url="https://example.blob.core.windows.net/progress"
                ),
                identity=_Identity(),
                http_client=client,
            ).append(record)


@pytest.mark.parametrize(
    "url",
    (
        "http://example.blob.core.windows.net/progress",
        "https://user@example.blob.core.windows.net/progress",
        "https://example.blob.core.windows.net/progress?sig=secret",
        "https://attacker.example/progress",
        "https://example.blob.core.windows.net/progress/nested",
    ),
)
def test_blob_config_rejects_credential_or_non_tls_urls(url: str) -> None:
    with pytest.raises(ValueError, match="inventory progress container URL"):
        AzureBlobInventoryProgressConfig(container_url=url)
