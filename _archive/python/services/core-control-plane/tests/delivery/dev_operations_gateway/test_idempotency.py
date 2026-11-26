from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from delivery.dev_operations_gateway.idempotency import (
    AzureBlobIdempotencyConfig,
    AzureBlobIdempotencyLedger,
    IdempotencyError,
)


class _Tokens:
    def __init__(self) -> None:
        self.audiences: list[str] = []

    async def get_token(self, audience: str) -> str:
        self.audiences.append(audience)
        return "storage-token"


def _config() -> AzureBlobIdempotencyConfig:
    return AzureBlobIdempotencyConfig(
        container_url="https://storage.example.com/operation-idempotency"
    )


def test_config_rejects_unsafe_container_urls() -> None:
    for url in (
        "http://storage.example.com/operation-idempotency",
        "https://user@storage.example.com/operation-idempotency",
        "https://storage.example.com/",
        "https://storage.example.com/one/two",
        "https://storage.example.com/operation-idempotency?sig=secret",
    ):
        with pytest.raises(ValueError, match="one HTTPS container"):
            AzureBlobIdempotencyConfig(container_url=url)


async def test_claim_and_complete_use_conditional_blob_writes() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(201, headers={"ETag": '"claim-etag"'})
        return httpx.Response(201, headers={"ETag": '"completed-etag"'})

    tokens = _Tokens()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        ledger = AzureBlobIdempotencyLedger(
            config=_config(),
            token_provider=tokens,
            http_client=client,
        )
        replay = await ledger.begin("operation:secret", "request-digest")
        await ledger.complete(
            "operation:secret",
            "request-digest",
            {"status": "succeeded", "result": {"accepted": True}},
        )

    assert replay is None
    assert len(requests) == 2
    expected_name = hashlib.sha256(b"operation:secret").hexdigest()
    assert requests[0].url.path.endswith(f"/{expected_name}.json")
    assert "operation:secret" not in str(requests[0].url)
    assert requests[0].headers["If-None-Match"] == "*"
    assert requests[1].headers["If-Match"] == '"claim-etag"'
    assert requests[0].headers["Authorization"] == "Bearer storage-token"
    assert tokens.audiences == ["https://storage.azure.com/"] * 2
    completed = json.loads(requests[1].content)
    assert completed["state"] == "completed"
    assert completed["request_digest"] == "request-digest"


async def test_completed_duplicate_replays_recorded_response() -> None:
    expected = {"operation_id": "azure.compute.vm.start", "status": "succeeded"}
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(409)
        return httpx.Response(
            200,
            headers={"ETag": '"completed-etag"'},
            json={
                "state": "completed",
                "request_digest": "request-digest",
                "response": expected,
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        replay = await AzureBlobIdempotencyLedger(
            config=_config(), token_provider=_Tokens(), http_client=client
        ).begin("operation:one", "request-digest")

    assert replay == expected
    assert calls == 2


@pytest.mark.parametrize(
    ("record", "code"),
    [
        (
            {"state": "pending", "request_digest": "request-digest"},
            "idempotency_in_progress",
        ),
        (
            {"state": "completed", "request_digest": "different", "response": {}},
            "idempotency_conflict",
        ),
    ],
)
async def test_existing_claims_fail_closed(record: dict[str, object], code: str) -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(412)
        return httpx.Response(200, headers={"ETag": '"etag"'}, json=record)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        ledger = AzureBlobIdempotencyLedger(
            config=_config(), token_provider=_Tokens(), http_client=client
        )
        with pytest.raises(IdempotencyError) as error:
            await ledger.begin("operation:one", "request-digest")

    assert error.value.status_code == 409
    assert error.value.code == code


async def test_abort_releases_the_exact_claim() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "PUT":
            return httpx.Response(201, headers={"ETag": '"claim-etag"'})
        return httpx.Response(202)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        ledger = AzureBlobIdempotencyLedger(
            config=_config(), token_provider=_Tokens(), http_client=client
        )
        await ledger.begin("operation:one", "request-digest")
        await ledger.abort("operation:one", "request-digest")

    assert [request.method for request in requests] == ["PUT", "DELETE"]
    assert requests[1].headers["If-Match"] == '"claim-etag"'


async def test_storage_failure_blocks_the_mutation_path() -> None:
    transport = httpx.MockTransport(lambda _request: httpx.Response(500))
    async with httpx.AsyncClient(transport=transport) as client:
        ledger = AzureBlobIdempotencyLedger(
            config=_config(), token_provider=_Tokens(), http_client=client
        )
        with pytest.raises(IdempotencyError) as error:
            await ledger.begin("operation:one", "request-digest")

    assert error.value.status_code == 503
    assert error.value.code == "idempotency_unavailable"


async def test_resource_lock_uses_a_bounded_blob_lease() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(201)
        if len(requests) == 2:
            return httpx.Response(201, headers={"x-ms-lease-id": "lease-one"})
        return httpx.Response(200)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        ledger = AzureBlobIdempotencyLedger(
            config=_config(), token_provider=_Tokens(), http_client=client
        )
        lease_id = await ledger.acquire_resource("sub/rg/vm/private-name")
        await ledger.release_resource("sub/rg/vm/private-name", lease_id)

    assert lease_id == "lease-one"
    assert [request.method for request in requests] == ["PUT", "PUT", "PUT"]
    assert requests[0].headers["If-None-Match"] == "*"
    assert requests[1].url.query == b"comp=lease"
    assert requests[1].headers["x-ms-lease-action"] == "acquire"
    assert requests[1].headers["x-ms-lease-duration"] == "60"
    assert requests[2].headers["x-ms-lease-action"] == "release"
    assert requests[2].headers["x-ms-lease-id"] == "lease-one"
    assert "private-name" not in str(requests[0].url)


async def test_resource_lock_renew_uses_the_exact_lease() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        ledger = AzureBlobIdempotencyLedger(
            config=_config(), token_provider=_Tokens(), http_client=client
        )
        await ledger.renew_resource("sub/rg/vm/private-name", "lease-one")

    assert requests[0].url.query == b"comp=lease"
    assert requests[0].headers["x-ms-lease-action"] == "renew"
    assert requests[0].headers["x-ms-lease-id"] == "lease-one"


async def test_terminal_response_update_uses_operation_etag() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(
                200,
                headers={"ETag": '"operation-etag"'},
                json={
                    "state": "completed",
                    "request_digest": "request-digest",
                    "response": {"status": "submitted"},
                },
            )
        return httpx.Response(201)

    terminal = {
        "operation_id": "azure.compute.vm.start",
        "status": "succeeded",
        "result": {"provider_status": "Succeeded", "status": "succeeded"},
    }
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        ledger = AzureBlobIdempotencyLedger(
            config=_config(), token_provider=_Tokens(), http_client=client
        )
        await ledger.update_response("operation:one", terminal)

    assert [request.method for request in requests] == ["GET", "PUT"]
    assert requests[1].headers["If-Match"] == '"operation-etag"'
    body = json.loads(requests[1].content)
    assert body["request_digest"] == "request-digest"
    assert body["response"] == terminal


async def test_stale_pending_claim_is_replaced_with_etag_cas() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(412)
        if len(requests) == 2:
            return httpx.Response(
                200,
                headers={"ETag": '"stale-etag"'},
                json={
                    "state": "pending",
                    "request_digest": "request-digest",
                    "claimed_at": "2000-01-01T00:00:00+00:00",
                },
            )
        return httpx.Response(201, headers={"ETag": '"replacement-etag"'})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        replay = await AzureBlobIdempotencyLedger(
            config=_config(), token_provider=_Tokens(), http_client=client
        ).begin("operation:one", "request-digest")

    assert replay is None
    assert requests[2].headers["If-Match"] == '"stale-etag"'
    replacement = json.loads(requests[2].content)
    assert replacement["state"] == "pending"
    assert replacement["claimed_at"] != "2000-01-01T00:00:00+00:00"


async def test_dry_run_receipt_is_hashed_and_consumed_with_etag_cas() -> None:
    requests: list[httpx.Request] = []
    request_digest = "request-digest"
    expires_at = datetime.now(UTC) + timedelta(minutes=5)

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(201)
        if len(requests) == 2:
            return httpx.Response(
                200,
                headers={"ETag": '"plan-etag"'},
                json={
                    "state": "ready",
                    "request_digest": request_digest,
                    "expires_at": expires_at.isoformat(),
                },
            )
        return httpx.Response(201)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        ledger = AzureBlobIdempotencyLedger(
            config=_config(), token_provider=_Tokens(), http_client=client
        )
        receipt = await ledger.issue_dry_run(request_digest)
        await ledger.consume_dry_run(receipt, request_digest)

    receipt_digest = hashlib.sha256(receipt.encode()).hexdigest()
    assert requests[0].url.path.endswith(f"/dry-runs/{receipt_digest}.json")
    assert receipt not in str(requests[0].url)
    assert requests[0].headers["If-None-Match"] == "*"
    assert requests[2].headers["If-Match"] == '"plan-etag"'
    consumed = json.loads(requests[2].content)
    assert consumed["state"] == "consumed"


async def test_repeated_dry_run_plan_returns_the_same_receipt() -> None:
    requests: list[httpx.Request] = []
    request_digest = "request-digest"
    expires_at = datetime.now(UTC) + timedelta(minutes=5)

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(201)
        if len(requests) == 2:
            return httpx.Response(412)
        return httpx.Response(
            200,
            headers={"ETag": '"plan-etag"'},
            json={
                "state": "ready",
                "request_digest": request_digest,
                "expires_at": expires_at.isoformat(),
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        ledger = AzureBlobIdempotencyLedger(
            config=_config(), token_provider=_Tokens(), http_client=client
        )
        first = await ledger.issue_dry_run(request_digest)
        duplicate = await ledger.issue_dry_run(request_digest)

    assert duplicate == first
    assert requests[0].url == requests[1].url == requests[2].url


async def test_dry_run_receipt_rejects_mismatched_request() -> None:
    expires_at = datetime.now(UTC) + timedelta(minutes=5)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"ETag": '"plan-etag"'},
            json={
                "state": "ready",
                "request_digest": "different-digest",
                "expires_at": expires_at.isoformat(),
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        ledger = AzureBlobIdempotencyLedger(
            config=_config(), token_provider=_Tokens(), http_client=client
        )
        with pytest.raises(IdempotencyError) as error:
            await ledger.consume_dry_run("dry-run-receipt", "request-digest")

    assert error.value.status_code == 409
    assert error.value.code == "dry_run_invalid"


async def test_dry_run_receipt_rejects_expired_record() -> None:
    expired_at = datetime.now(UTC) - timedelta(seconds=1)
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            headers={"ETag": '"plan-etag"'},
            json={
                "state": "ready",
                "request_digest": "request-digest",
                "expires_at": expired_at.isoformat(),
            },
        )
    )
    async with httpx.AsyncClient(transport=transport) as client:
        ledger = AzureBlobIdempotencyLedger(
            config=_config(), token_provider=_Tokens(), http_client=client
        )
        with pytest.raises(IdempotencyError) as error:
            await ledger.consume_dry_run("dry-run-receipt", "request-digest")

    assert error.value.status_code == 409
    assert error.value.code == "dry_run_invalid"


async def test_completion_transport_loss_recovers_recorded_response() -> None:
    requests: list[httpx.Request] = []
    completed_response = {"status": "succeeded", "result": {"accepted": True}}

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(201, headers={"ETag": '"claim-etag"'})
        if len(requests) == 2:
            raise httpx.ConnectError("response lost", request=request)
        return httpx.Response(
            200,
            headers={"ETag": '"completed-etag"'},
            json={
                "state": "completed",
                "request_digest": "request-digest",
                "response": completed_response,
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        ledger = AzureBlobIdempotencyLedger(
            config=_config(), token_provider=_Tokens(), http_client=client
        )
        await ledger.begin("operation:one", "request-digest")
        await ledger.complete(
            "operation:one",
            "request-digest",
            completed_response,
        )

    assert [request.method for request in requests] == ["PUT", "PUT", "GET"]
