"""AzureDbDrRestoreAdapter — HTTP-level round-trip via httpx.MockTransport.

Verifies the wire contract the P3 Deep DB-DR verifier depends on:

- Bearer-token auth via the injected :class:`WorkloadIdentity`.
- ``restore`` submits a ``POST .../providers/Microsoft.DBforPostgreSQL/
  flexibleServers/{name}/restore`` under a fresh RG, with the API-version
  query parameter and a ``PointInTimeRestore`` body.
- The isolation invariant refuses a config whose target RG equals the
  source RG.
- A 202 accepted response is followed by LRO polling of the
  ``Azure-AsyncOperation`` (or ``Location``) URL until the state
  resolves to ``Succeeded``; a non-success terminal state trips
  fail-closed with :class:`DbDrError`.
- The final resource GET populates ``target_ref`` (ARM id) and
  ``endpoint`` (FQDN) on the returned handle; a partial ``state`` is
  refused.
- ``teardown`` DELETEs the target resource group; 404 is an
  idempotent no-op; other 4xx/5xx raise.
- Non-2xx / non-JSON / transport failures raise :class:`DbDrError`
  with a truncated snippet — no raw response body leaks.

No real Azure endpoints are contacted; every test builds an
``httpx.AsyncClient`` on top of :class:`httpx.MockTransport` and
overrides ``sleep`` so LRO tests do not wait a real second.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

import httpx
import pytest

from aiopspilot.delivery.azure.db_dr_restore import (
    AzureDbDrRestoreAdapter,
    AzureDbDrRestoreAdapterConfig,
)
from aiopspilot.shared.providers.db_dr import (
    DbDrError,
    DbRestoreConfig,
    DbRestoreHandle,
)
from aiopspilot.shared.providers.testing.workload_identity import (
    StaticWorkloadIdentity,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


_AUDIENCE = "https://management.azure.com/.default"
_TOKEN = "test-token-abc"  # noqa: S105 — deterministic test literal

_SUB = "00000000-0000-0000-0000-000000000001"
_SOURCE_REF = (
    f"/subscriptions/{_SUB}/resourceGroups/rg-source/"
    "providers/Microsoft.DBforPostgreSQL/flexibleServers/src-server"
)
_TARGET_REF = (
    f"/subscriptions/{_SUB}/resourceGroups/rg-restore-1/"
    "providers/Microsoft.DBforPostgreSQL/flexibleServers/restored-1"
)
_TARGET_FQDN = "restored-1.postgres.database.azure.com"


async def _noop_sleep(_seconds: float) -> None:
    return None


def _identity() -> StaticWorkloadIdentity:
    return StaticWorkloadIdentity(audience=_AUDIENCE, token=_TOKEN)


def _client(handler: httpx.MockTransport) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=handler, base_url="https://mock-arm.local")


def _adapter(
    client: httpx.AsyncClient,
    *,
    config: AzureDbDrRestoreAdapterConfig | None = None,
    sleep: Callable[[float], object] | None = None,
) -> AzureDbDrRestoreAdapter:
    return AzureDbDrRestoreAdapter(
        identity=_identity(),
        http_client=client,
        config=config or AzureDbDrRestoreAdapterConfig(poll_interval_seconds=0),
        sleep=_noop_sleep if sleep is None else sleep,  # type: ignore[arg-type]
    )


def _config(
    *,
    experiment_id: str = "exp-1",
    target_server_name: str = "restored-1",
    target_resource_group: str = "rg-restore-1",
    target_location: str = "koreacentral",
    source_ref: str = _SOURCE_REF,
    point_in_time_utc: datetime | None = None,
) -> DbRestoreConfig:
    return DbRestoreConfig(
        experiment_id=experiment_id,
        source_ref=source_ref,
        target_server_name=target_server_name,
        target_resource_group=target_resource_group,
        target_location=target_location,
        point_in_time_utc=point_in_time_utc,
    )


def _final_body(*, state: str = "Ready") -> dict[str, object]:
    return {
        "id": _TARGET_REF,
        "name": "restored-1",
        "properties": {
            "fullyQualifiedDomainName": _TARGET_FQDN,
            "state": state,
        },
    }


# ---------------------------------------------------------------------------
# Construction guards
# ---------------------------------------------------------------------------


def test_zero_timeout_is_rejected() -> None:
    with pytest.raises(ValueError, match="timeout_seconds MUST be > 0"):
        AzureDbDrRestoreAdapter(
            identity=_identity(),
            http_client=httpx.AsyncClient(),
            config=AzureDbDrRestoreAdapterConfig(timeout_seconds=0),
        )


def test_zero_poll_budget_is_rejected() -> None:
    with pytest.raises(ValueError, match="max_poll_seconds MUST be > 0"):
        AzureDbDrRestoreAdapter(
            identity=_identity(),
            http_client=httpx.AsyncClient(),
            config=AzureDbDrRestoreAdapterConfig(max_poll_seconds=0),
        )


def test_negative_poll_interval_is_rejected() -> None:
    with pytest.raises(ValueError, match="poll_interval_seconds MUST be >= 0"):
        AzureDbDrRestoreAdapter(
            identity=_identity(),
            http_client=httpx.AsyncClient(),
            config=AzureDbDrRestoreAdapterConfig(poll_interval_seconds=-1),
        )


def test_tiny_error_body_cap_is_rejected() -> None:
    with pytest.raises(ValueError, match="max_error_body_bytes MUST be >= 64"):
        AzureDbDrRestoreAdapter(
            identity=_identity(),
            http_client=httpx.AsyncClient(),
            config=AzureDbDrRestoreAdapterConfig(max_error_body_bytes=32),
        )


# ---------------------------------------------------------------------------
# Isolation invariant
# ---------------------------------------------------------------------------


async def test_restore_refuses_same_rg_as_source() -> None:
    async with _client(httpx.MockTransport(lambda _r: httpx.Response(500))) as client:
        adapter = _adapter(client)
        cfg = _config(target_resource_group="rg-source")  # equals source RG
        with pytest.raises(DbDrError, match="isolation"):
            await adapter.restore(cfg)


async def test_restore_refuses_source_ref_without_resource_group() -> None:
    async with _client(httpx.MockTransport(lambda _r: httpx.Response(500))) as client:
        adapter = _adapter(client)
        cfg = _config(source_ref="/subscriptions/x/providers/Microsoft.Fake/foo/bar")
        with pytest.raises(DbDrError, match="resourceGroups"):
            await adapter.restore(cfg)


async def test_restore_refuses_source_ref_without_subscription_id() -> None:
    async with _client(httpx.MockTransport(lambda _r: httpx.Response(500))) as client:
        adapter = _adapter(client)
        cfg = _config(source_ref="/resourceGroups/rg-x/providers/Microsoft.Fake/foo/bar")
        with pytest.raises(DbDrError, match="subscriptions"):
            await adapter.restore(cfg)


# ---------------------------------------------------------------------------
# Happy path — synchronous 201 + resource GET
# ---------------------------------------------------------------------------


async def test_synchronous_restore_returns_handle_with_endpoint() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.method == "POST":
            return httpx.Response(201, json={"id": _TARGET_REF})
        return httpx.Response(200, json=_final_body(state="Ready"))

    async with _client(httpx.MockTransport(handler)) as client:
        adapter = _adapter(client)
        handle = await adapter.restore(_config())

    assert handle.target_ref == _TARGET_REF
    assert handle.endpoint == _TARGET_FQDN
    assert handle.resource_group == "rg-restore-1"
    assert handle.source_ref == _SOURCE_REF

    # Wire assertions on the POST.
    post = seen[0]
    assert post.method == "POST"
    assert post.headers["Authorization"] == f"Bearer {_TOKEN}"
    assert post.url.path.endswith(
        "/providers/Microsoft.DBforPostgreSQL/flexibleServers/restored-1/restore"
    )
    assert post.url.params["api-version"] == "2024-08-01"
    body = post.read().decode("utf-8")
    assert '"createMode":"PointInTimeRestore"' in body
    assert '"sourceServerResourceId":"' in body
    assert '"location":"koreacentral"' in body


async def test_point_in_time_is_serialized_as_iso_utc() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.method == "POST":
            return httpx.Response(201, json={"id": _TARGET_REF})
        return httpx.Response(200, json=_final_body())

    moment = datetime(2026, 7, 6, 12, 34, 56, tzinfo=UTC)
    async with _client(httpx.MockTransport(handler)) as client:
        adapter = _adapter(client)
        await adapter.restore(_config(point_in_time_utc=moment))

    body = seen[0].read().decode("utf-8")
    assert '"pointInTimeUTC":"2026-07-06T12:34:56Z"' in body


async def test_naive_point_in_time_is_treated_as_utc() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.method == "POST":
            return httpx.Response(201, json={"id": _TARGET_REF})
        return httpx.Response(200, json=_final_body())

    naive = datetime(2026, 7, 6, 12, 34, 56)  # noqa: DTZ001 — deliberate for test
    async with _client(httpx.MockTransport(handler)) as client:
        adapter = _adapter(client)
        await adapter.restore(_config(point_in_time_utc=naive))

    body = seen[0].read().decode("utf-8")
    assert '"pointInTimeUTC":"2026-07-06T12:34:56Z"' in body


# ---------------------------------------------------------------------------
# LRO happy path — 202 + polls resolve to Succeeded
# ---------------------------------------------------------------------------


async def test_lro_polls_until_succeeded_via_azure_async_operation_header() -> None:
    lro_url = "https://mock-arm.local/subscriptions/x/operations/op-42?api-version=2024-08-01"
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(f"{request.method} {request.url.path}")
        if request.method == "POST":
            return httpx.Response(
                202,
                headers={"Azure-AsyncOperation": lro_url},
            )
        # First GET → poll URL; second GET → final resource URL.
        if request.url.path.endswith("/operations/op-42"):
            # First poll returns InProgress; second returns Succeeded.
            poll_calls = [c for c in calls if "op-42" in c]
            state = "InProgress" if len(poll_calls) == 1 else "Succeeded"
            return httpx.Response(200, json={"status": state})
        return httpx.Response(200, json=_final_body())

    async with _client(httpx.MockTransport(handler)) as client:
        adapter = _adapter(client)
        handle = await adapter.restore(_config())

    assert handle.target_ref == _TARGET_REF
    # At least one polling GET happened before the final resource GET.
    poll_calls = [c for c in calls if "op-42" in c]
    assert len(poll_calls) >= 2


async def test_lro_uses_location_header_when_no_azure_async_operation() -> None:
    location_url = "https://mock-arm.local/subscriptions/x/operations/loc-1?api-version=2024-08-01"
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(f"{request.method} {request.url.path}")
        if request.method == "POST":
            return httpx.Response(202, headers={"Location": location_url})
        if request.url.path.endswith("/operations/loc-1"):
            return httpx.Response(200, json={"status": "Succeeded"})
        return httpx.Response(200, json=_final_body())

    async with _client(httpx.MockTransport(handler)) as client:
        adapter = _adapter(client)
        handle = await adapter.restore(_config())

    assert handle.endpoint == _TARGET_FQDN
    assert any("loc-1" in s for s in seen)


async def test_lro_treats_202_poll_as_in_progress() -> None:
    lro_url = "https://mock-arm.local/subscriptions/x/operations/pending?api-version=2024-08-01"
    poll_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal poll_count
        if request.method == "POST":
            return httpx.Response(202, headers={"Azure-AsyncOperation": lro_url})
        if request.url.path.endswith("/operations/pending"):
            poll_count += 1
            if poll_count < 2:
                return httpx.Response(202)  # LRO not settled yet
            return httpx.Response(200, json={"status": "Succeeded"})
        return httpx.Response(200, json=_final_body())

    async with _client(httpx.MockTransport(handler)) as client:
        adapter = _adapter(client)
        handle = await adapter.restore(_config())

    assert handle.target_ref == _TARGET_REF
    assert poll_count == 2


async def test_lro_reads_provisioning_state_when_status_absent() -> None:
    lro_url = "https://mock-arm.local/subscriptions/x/operations/nested?api-version=2024-08-01"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(202, headers={"Azure-AsyncOperation": lro_url})
        if request.url.path.endswith("/operations/nested"):
            return httpx.Response(
                200,
                json={"properties": {"provisioningState": "Succeeded"}},
            )
        return httpx.Response(200, json=_final_body())

    async with _client(httpx.MockTransport(handler)) as client:
        adapter = _adapter(client)
        handle = await adapter.restore(_config())

    assert handle.target_ref == _TARGET_REF


# ---------------------------------------------------------------------------
# Fail-closed on partial / failed restore
# ---------------------------------------------------------------------------


async def test_lro_failed_terminal_state_raises() -> None:
    lro_url = "https://mock-arm.local/subscriptions/x/operations/bad?api-version=2024-08-01"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(202, headers={"Azure-AsyncOperation": lro_url})
        return httpx.Response(200, json={"status": "Failed"})

    async with _client(httpx.MockTransport(handler)) as client:
        adapter = _adapter(client)
        with pytest.raises(DbDrError, match="non-success"):
            await adapter.restore(_config())


async def test_lro_cancelled_state_raises() -> None:
    lro_url = "https://mock-arm.local/subscriptions/x/operations/cx?api-version=2024-08-01"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(202, headers={"Azure-AsyncOperation": lro_url})
        return httpx.Response(200, json={"status": "Cancelled"})

    async with _client(httpx.MockTransport(handler)) as client:
        adapter = _adapter(client)
        with pytest.raises(DbDrError, match="non-success"):
            await adapter.restore(_config())


async def test_lro_timeout_exceeds_budget_raises() -> None:
    lro_url = "https://mock-arm.local/subscriptions/x/operations/slow?api-version=2024-08-01"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(202, headers={"Azure-AsyncOperation": lro_url})
        return httpx.Response(200, json={"status": "InProgress"})

    async with _client(httpx.MockTransport(handler)) as client:
        # tiny budget + zero poll interval so the loop exits quickly.
        adapter = _adapter(
            client,
            config=AzureDbDrRestoreAdapterConfig(
                max_poll_seconds=0.5,
                poll_interval_seconds=1,  # elapsed jumps to 1 → exceeds 0.5 budget
            ),
        )
        with pytest.raises(DbDrError, match="did not complete within"):
            await adapter.restore(_config())


async def test_submit_202_without_status_header_raises() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(202)  # no header, no body

    async with _client(httpx.MockTransport(handler)) as client:
        adapter = _adapter(client)
        with pytest.raises(DbDrError, match="without an LRO status header"):
            await adapter.restore(_config())


async def test_submit_4xx_raises_with_trimmed_error_body() -> None:
    long_body = "X" * 5000

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text=long_body)

    async with _client(httpx.MockTransport(handler)) as client:
        adapter = _adapter(client)
        with pytest.raises(DbDrError) as excinfo:
            await adapter.restore(_config())
    msg = str(excinfo.value)
    assert "HTTP 400" in msg
    # Trimmed with ellipsis marker; must not contain the full 5000-char body.
    assert "…" in msg
    assert msg.count("X") <= 512


async def test_submit_transport_error_raises() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("cannot connect")

    async with _client(httpx.MockTransport(handler)) as client:
        adapter = _adapter(client)
        with pytest.raises(DbDrError, match="restore submit failed"):
            await adapter.restore(_config())


async def test_poll_4xx_raises() -> None:
    lro_url = "https://mock-arm.local/subscriptions/x/operations/err?api-version=2024-08-01"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(202, headers={"Azure-AsyncOperation": lro_url})
        return httpx.Response(403, text="Forbidden")

    async with _client(httpx.MockTransport(handler)) as client:
        adapter = _adapter(client)
        with pytest.raises(DbDrError, match="HTTP 403"):
            await adapter.restore(_config())


async def test_poll_transport_error_raises() -> None:
    lro_url = "https://mock-arm.local/subscriptions/x/operations/xx?api-version=2024-08-01"

    call = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call
        call += 1
        if request.method == "POST":
            return httpx.Response(202, headers={"Azure-AsyncOperation": lro_url})
        raise httpx.ReadTimeout("timed out")

    async with _client(httpx.MockTransport(handler)) as client:
        adapter = _adapter(client)
        with pytest.raises(DbDrError, match="restore request failed"):
            await adapter.restore(_config())


# ---------------------------------------------------------------------------
# Final resource GET — extraction edge cases
# ---------------------------------------------------------------------------


async def test_final_resource_get_missing_id_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(201, json={})
        return httpx.Response(200, json={"properties": {"fullyQualifiedDomainName": _TARGET_FQDN}})

    async with _client(httpx.MockTransport(handler)) as client:
        adapter = _adapter(client)
        with pytest.raises(DbDrError, match="no resource id"):
            await adapter.restore(_config())


async def test_final_resource_get_missing_fqdn_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(201, json={})
        return httpx.Response(200, json={"id": _TARGET_REF, "properties": {}})

    async with _client(httpx.MockTransport(handler)) as client:
        adapter = _adapter(client)
        with pytest.raises(DbDrError, match="fully-qualified domain name"):
            await adapter.restore(_config())


async def test_final_resource_get_non_success_state_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(201, json={})
        return httpx.Response(200, json=_final_body(state="Disabled"))

    async with _client(httpx.MockTransport(handler)) as client:
        adapter = _adapter(client)
        with pytest.raises(DbDrError, match="non-success state"):
            await adapter.restore(_config())


async def test_final_resource_get_non_json_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(201, json={})
        return httpx.Response(200, text="<html>error</html>")

    async with _client(httpx.MockTransport(handler)) as client:
        adapter = _adapter(client)
        with pytest.raises(DbDrError, match="non-JSON"):
            await adapter.restore(_config())


async def test_final_resource_get_non_object_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(201, json={})
        return httpx.Response(200, json=["not-an-object"])

    async with _client(httpx.MockTransport(handler)) as client:
        adapter = _adapter(client)
        with pytest.raises(DbDrError, match="non-object payload"):
            await adapter.restore(_config())


async def test_final_resource_get_4xx_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(201, json={})
        return httpx.Response(500, text="oops")

    async with _client(httpx.MockTransport(handler)) as client:
        adapter = _adapter(client)
        with pytest.raises(DbDrError, match="HTTP 500"):
            await adapter.restore(_config())


async def test_ready_state_is_accepted() -> None:
    # Azure PG Flexible reports state=Ready on a healthy provisioned
    # server; the adapter treats Ready as success (belt-and-suspenders
    # with the LRO Succeeded state).
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(201, json={})
        return httpx.Response(200, json=_final_body(state="Ready"))

    async with _client(httpx.MockTransport(handler)) as client:
        adapter = _adapter(client)
        handle = await adapter.restore(_config())
    assert handle.endpoint == _TARGET_FQDN


async def test_provisioning_state_succeeded_is_accepted() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(201, json={})
        return httpx.Response(
            200,
            json={
                "id": _TARGET_REF,
                "properties": {
                    "fullyQualifiedDomainName": _TARGET_FQDN,
                    "provisioningState": "Succeeded",
                },
            },
        )

    async with _client(httpx.MockTransport(handler)) as client:
        adapter = _adapter(client)
        handle = await adapter.restore(_config())
    assert handle.target_ref == _TARGET_REF


# ---------------------------------------------------------------------------
# Teardown
# ---------------------------------------------------------------------------


def _handle() -> DbRestoreHandle:
    return DbRestoreHandle(
        experiment_id="exp-1",
        source_ref=_SOURCE_REF,
        target_ref=_TARGET_REF,
        endpoint=_TARGET_FQDN,
        resource_group="rg-restore-1",
        created_at=datetime(2026, 7, 6, tzinfo=UTC),
    )


async def test_teardown_deletes_target_resource_group() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(202)

    async with _client(httpx.MockTransport(handler)) as client:
        adapter = _adapter(client)
        await adapter.teardown(_handle())

    assert len(seen) == 1
    req = seen[0]
    assert req.method == "DELETE"
    assert req.url.path.endswith("/resourceGroups/rg-restore-1")
    assert req.url.params["api-version"] == "2021-04-01"
    assert req.headers["Authorization"] == f"Bearer {_TOKEN}"


@pytest.mark.parametrize("code", [200, 202, 204, 404])
async def test_teardown_accepts_success_and_not_found(code: int) -> None:
    def handler(_r: httpx.Request) -> httpx.Response:
        return httpx.Response(code)

    async with _client(httpx.MockTransport(handler)) as client:
        adapter = _adapter(client)
        await adapter.teardown(_handle())  # must not raise


async def test_teardown_other_error_raises() -> None:
    def handler(_r: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="server error")

    async with _client(httpx.MockTransport(handler)) as client:
        adapter = _adapter(client)
        with pytest.raises(DbDrError, match="HTTP 500"):
            await adapter.teardown(_handle())


async def test_teardown_transport_error_raises() -> None:
    def handler(_r: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("dns fail")

    async with _client(httpx.MockTransport(handler)) as client:
        adapter = _adapter(client)
        with pytest.raises(DbDrError, match="teardown request failed"):
            await adapter.teardown(_handle())


async def test_teardown_rejects_target_ref_without_subscription() -> None:
    async with _client(httpx.MockTransport(lambda _r: httpx.Response(500))) as client:
        adapter = _adapter(client)
        h = DbRestoreHandle(
            experiment_id="exp-1",
            source_ref=_SOURCE_REF,
            target_ref="/no/subs/here",
            endpoint="e",
            resource_group="rg-x",
            created_at=datetime(2026, 7, 6, tzinfo=UTC),
        )
        with pytest.raises(DbDrError, match="subscriptions"):
            await adapter.teardown(h)


# ---------------------------------------------------------------------------
# Small helper reachability — error trim path
# ---------------------------------------------------------------------------


async def test_short_error_body_is_not_trimmed() -> None:
    def handler(_r: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="tiny")

    async with _client(httpx.MockTransport(handler)) as client:
        adapter = _adapter(client)
        with pytest.raises(DbDrError, match="tiny") as excinfo:
            await adapter.restore(_config())
    assert "…" not in str(excinfo.value)


# ---------------------------------------------------------------------------
# LRO poll body — parser edge cases (empty / non-JSON / non-dict / no state)
# ---------------------------------------------------------------------------


async def test_lro_poll_empty_body_is_treated_as_in_progress_then_settles() -> None:
    lro_url = "https://mock-arm.local/subscriptions/x/operations/emp?api-version=2024-08-01"
    call = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call
        if request.method == "POST":
            return httpx.Response(202, headers={"Azure-AsyncOperation": lro_url})
        if request.url.path.endswith("/operations/emp"):
            call += 1
            if call == 1:
                # Empty body on a 200 — no state extractable; treat as pending.
                return httpx.Response(200)
            return httpx.Response(200, json={"status": "Succeeded"})
        return httpx.Response(200, json=_final_body())

    async with _client(httpx.MockTransport(handler)) as client:
        adapter = _adapter(client)
        handle = await adapter.restore(_config())
    assert handle.target_ref == _TARGET_REF
    assert call == 2


async def test_lro_poll_non_json_body_is_treated_as_in_progress() -> None:
    lro_url = "https://mock-arm.local/subscriptions/x/operations/nj?api-version=2024-08-01"
    call = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call
        if request.method == "POST":
            return httpx.Response(202, headers={"Azure-AsyncOperation": lro_url})
        if request.url.path.endswith("/operations/nj"):
            call += 1
            if call == 1:
                return httpx.Response(200, text="<html>not json</html>")
            return httpx.Response(200, json={"status": "Succeeded"})
        return httpx.Response(200, json=_final_body())

    async with _client(httpx.MockTransport(handler)) as client:
        adapter = _adapter(client)
        handle = await adapter.restore(_config())
    assert handle.target_ref == _TARGET_REF


async def test_lro_poll_array_body_is_treated_as_in_progress() -> None:
    lro_url = "https://mock-arm.local/subscriptions/x/operations/arr?api-version=2024-08-01"
    call = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call
        if request.method == "POST":
            return httpx.Response(202, headers={"Azure-AsyncOperation": lro_url})
        if request.url.path.endswith("/operations/arr"):
            call += 1
            if call == 1:
                return httpx.Response(200, json=["not", "an", "object"])
            return httpx.Response(200, json={"status": "Succeeded"})
        return httpx.Response(200, json=_final_body())

    async with _client(httpx.MockTransport(handler)) as client:
        adapter = _adapter(client)
        handle = await adapter.restore(_config())
    assert handle.target_ref == _TARGET_REF


async def test_lro_poll_body_without_state_field_is_treated_as_in_progress() -> None:
    lro_url = "https://mock-arm.local/subscriptions/x/operations/nostate?api-version=2024-08-01"
    call = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call
        if request.method == "POST":
            return httpx.Response(202, headers={"Azure-AsyncOperation": lro_url})
        if request.url.path.endswith("/operations/nostate"):
            call += 1
            if call == 1:
                # Body with no ``status`` and properties.provisioningState of a
                # non-string type — falls through to the "keep polling" branch.
                return httpx.Response(200, json={"properties": {"provisioningState": 42}})
            return httpx.Response(200, json={"status": "Succeeded"})
        return httpx.Response(200, json=_final_body())

    async with _client(httpx.MockTransport(handler)) as client:
        adapter = _adapter(client)
        handle = await adapter.restore(_config())
    assert handle.target_ref == _TARGET_REF
