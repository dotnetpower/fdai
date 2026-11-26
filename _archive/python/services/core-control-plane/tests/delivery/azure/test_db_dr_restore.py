from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
from fdai.delivery.azure.db_dr_restore import (
    AzurePostgresRestoreAdapter,
    AzurePostgresRestoreSettings,
)
from fdai.shared.providers.db_dr import DbDrError, DbRestoreConfig, DbRestoreHandle
from fdai.shared.providers.testing.workload_identity import StaticWorkloadIdentity

_AUDIENCE = "https://management.azure.com/.default"
_SOURCE = (
    "/subscriptions/00000000-0000-0000-0000-000000000000"
    "/resourceGroups/rg-source"
    "/providers/Microsoft.DBforPostgreSQL/flexibleServers/psql-source"
)


def _config() -> DbRestoreConfig:
    return DbRestoreConfig(
        experiment_id="experiment-1",
        source_ref=_SOURCE,
        target_server_name="psql-drill-08311025",
        target_resource_group="rg-drill",
        target_location="koreacentral",
        point_in_time_utc=datetime(2026, 8, 31, 1, tzinfo=UTC),
    )


def _settings() -> AzurePostgresRestoreSettings:
    return AzurePostgresRestoreSettings(
        poll_interval_seconds=0,
        max_poll_attempts=2,
    )


async def test_restore_waits_for_ready_and_teardown_waits_for_absence() -> None:
    methods: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        if request.method == "PUT":
            return httpx.Response(202)
        if request.method == "GET" and methods.count("GET") == 1:
            return httpx.Response(
                200,
                json={
                    "properties": {
                        "state": "Ready",
                        "fullyQualifiedDomainName": "psql-drill.postgres.database.azure.com",
                    }
                },
            )
        if request.method == "DELETE":
            return httpx.Response(202)
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = AzurePostgresRestoreAdapter(
            identity=StaticWorkloadIdentity(audience=_AUDIENCE),
            http_client=client,
            settings=_settings(),
        )
        handle = await adapter.restore(_config())
        await adapter.teardown(handle)

    assert handle.endpoint == "psql-drill.postgres.database.azure.com"
    assert methods == ["PUT", "GET", "DELETE", "GET"]


async def test_partial_restore_failure_attempts_target_teardown() -> None:
    methods: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        if request.method == "PUT":
            return httpx.Response(202)
        if request.method == "GET" and methods.count("GET") == 1:
            return httpx.Response(200, json={"properties": {"state": "Failed"}})
        if request.method == "DELETE":
            return httpx.Response(202)
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = AzurePostgresRestoreAdapter(
            identity=StaticWorkloadIdentity(audience=_AUDIENCE),
            http_client=client,
            settings=_settings(),
        )
        with pytest.raises(DbDrError, match="terminal failure"):
            await adapter.restore(_config())

    assert methods == ["PUT", "GET", "DELETE", "GET"]


async def test_teardown_failure_is_not_reported_as_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "DELETE"
        return httpx.Response(500)

    handle = DbRestoreHandle(
        experiment_id="experiment-1",
        source_ref=_SOURCE,
        target_ref=(
            "/subscriptions/00000000-0000-0000-0000-000000000000"
            "/resourceGroups/rg-drill"
            "/providers/Microsoft.DBforPostgreSQL/flexibleServers/psql-drill"
        ),
        endpoint="psql-drill.postgres.database.azure.com",
        resource_group="rg-drill",
        created_at=datetime(2026, 8, 31, tzinfo=UTC),
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = AzurePostgresRestoreAdapter(
            identity=StaticWorkloadIdentity(audience=_AUDIENCE),
            http_client=client,
            settings=_settings(),
        )
        with pytest.raises(DbDrError, match="teardown request was rejected"):
            await adapter.teardown(handle)


async def test_restore_rejects_source_target_group_reuse_without_http() -> None:
    config = _config()
    reused = DbRestoreConfig(
        experiment_id=config.experiment_id,
        source_ref=config.source_ref,
        target_server_name=config.target_server_name,
        target_resource_group="RG-SOURCE",
        target_location=config.target_location,
        point_in_time_utc=config.point_in_time_utc,
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _request: httpx.Response(500))
    ) as client:
        adapter = AzurePostgresRestoreAdapter(
            identity=StaticWorkloadIdentity(audience=_AUDIENCE),
            http_client=client,
            settings=_settings(),
        )
        with pytest.raises(DbDrError, match="MUST differ"):
            await adapter.restore(reused)
