"""Azure PostgreSQL point-in-time restore adapter for governed DB-DR drills."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final
from urllib.parse import urlparse

import httpx

from fdai.shared.providers.db_dr import (
    DbDrError,
    DbRestoreConfig,
    DbRestoreHandle,
)
from fdai.shared.providers.workload_identity import WorkloadIdentity

_SOURCE_REF = re.compile(
    r"^/subscriptions/(?P<subscription>[0-9a-fA-F-]{36})"
    r"/resourceGroups/(?P<resource_group>[A-Za-z0-9._()-]{1,90})"
    r"/providers/Microsoft\.DBforPostgreSQL/flexibleServers/"
    r"(?P<server>[A-Za-z0-9-]{3,63})$",
    re.IGNORECASE,
)
_ALLOWED_MANAGEMENT_HOSTS: Final[frozenset[str]] = frozenset(
    {
        "management.azure.com",
        "management.azure.us",
        "management.chinacloudapi.cn",
        "management.microsoftazure.de",
    }
)
_TERMINAL_FAILURES: Final[frozenset[str]] = frozenset({"Canceled", "Failed", "Deleted"})


@dataclass(frozen=True, slots=True)
class AzurePostgresRestoreSettings:
    """Bound one restore adapter to an approved Azure management origin."""

    management_endpoint: str = "https://management.azure.com"
    audience: str = "https://management.azure.com/.default"
    api_version: str = "2024-08-01"
    poll_interval_seconds: float = 15.0
    max_poll_attempts: int = 180
    request_timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        parsed = urlparse(self.management_endpoint)
        if (
            parsed.scheme != "https"
            or parsed.hostname not in _ALLOWED_MANAGEMENT_HOSTS
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ValueError(
                "management_endpoint MUST be an approved Azure management HTTPS origin"
            )
        if not self.audience.strip() or not self.api_version.strip():
            raise ValueError("Azure restore audience and api_version MUST be non-empty")
        if self.poll_interval_seconds < 0:
            raise ValueError("poll_interval_seconds MUST be >= 0")
        if self.max_poll_attempts < 1 or self.request_timeout_seconds <= 0:
            raise ValueError("Azure restore polling bounds MUST be positive")


class AzurePostgresRestoreAdapter:
    """Restore and tear down one isolated PostgreSQL Flexible Server."""

    def __init__(
        self,
        *,
        identity: WorkloadIdentity,
        http_client: httpx.AsyncClient,
        settings: AzurePostgresRestoreSettings | None = None,
    ) -> None:
        self._identity = identity
        self._http = http_client
        self._settings = settings or AzurePostgresRestoreSettings()

    async def restore(self, config: DbRestoreConfig) -> DbRestoreHandle:
        """Create a point-in-time restore and return only after it succeeds."""

        source = _parse_source(config)
        target_ref = (
            f"/subscriptions/{source['subscription']}"
            f"/resourceGroups/{config.target_resource_group}"
            "/providers/Microsoft.DBforPostgreSQL/flexibleServers/"
            f"{config.target_server_name}"
        )
        body: dict[str, object] = {
            "location": config.target_location,
            "properties": {
                "createMode": "PointInTimeRestore",
                "sourceServerResourceId": config.source_ref,
                **(
                    {"pointInTimeUTC": config.point_in_time_utc.astimezone(UTC).isoformat()}
                    if config.point_in_time_utc is not None
                    else {}
                ),
            },
        }
        created = False
        try:
            response = await self._request("PUT", target_ref, json=body)
            if response.status_code not in {200, 201, 202}:
                raise _error(
                    config,
                    "Azure PostgreSQL restore request was rejected",
                    phase="restore",
                    status_code=response.status_code,
                )
            created = True
            endpoint = await self._wait_for_restore(config=config, target_ref=target_ref)
        except Exception as exc:
            if created:
                try:
                    await self._delete_target(
                        experiment_id=config.experiment_id,
                        target_ref=target_ref,
                    )
                except DbDrError as cleanup_exc:
                    raise _error(
                        config,
                        "Azure PostgreSQL restore failed and partial target teardown failed",
                        phase="restore",
                    ) from cleanup_exc
            if isinstance(exc, DbDrError):
                raise
            raise _error(
                config,
                "Azure PostgreSQL restore transport failed",
                phase="restore",
            ) from exc
        return DbRestoreHandle(
            experiment_id=config.experiment_id,
            source_ref=config.source_ref,
            target_ref=target_ref,
            endpoint=endpoint,
            resource_group=config.target_resource_group,
            created_at=datetime.now(UTC),
        )

    async def teardown(self, handle: DbRestoreHandle) -> None:
        """Delete the restored server; an already absent target is a success."""

        await self._delete_target(
            experiment_id=handle.experiment_id,
            target_ref=handle.target_ref,
        )

    async def _wait_for_restore(
        self,
        *,
        config: DbRestoreConfig,
        target_ref: str,
    ) -> str:
        for _ in range(self._settings.max_poll_attempts):
            response = await self._request("GET", target_ref)
            if response.status_code == 404:
                await asyncio.sleep(self._settings.poll_interval_seconds)
                continue
            if response.status_code != 200:
                raise _error(
                    config,
                    "Azure PostgreSQL restore status read failed",
                    phase="restore",
                    status_code=response.status_code,
                )
            try:
                payload = response.json()
                properties = payload["properties"]
                state = str(properties["state"])
            except (KeyError, TypeError, ValueError) as exc:
                raise _error(
                    config,
                    "Azure PostgreSQL restore returned malformed status",
                    phase="restore",
                ) from exc
            if state == "Ready":
                endpoint = str(properties.get("fullyQualifiedDomainName") or "").strip()
                if not endpoint:
                    raise _error(
                        config,
                        "Azure PostgreSQL restore omitted its endpoint",
                        phase="restore",
                    )
                return endpoint
            if state in _TERMINAL_FAILURES:
                raise _error(
                    config,
                    "Azure PostgreSQL restore reached a terminal failure",
                    phase="restore",
                )
            await asyncio.sleep(self._settings.poll_interval_seconds)
        raise _error(
            config,
            "Azure PostgreSQL restore exceeded its polling deadline",
            phase="restore",
        )

    async def _delete_target(self, *, experiment_id: str, target_ref: str) -> None:
        response = await self._request("DELETE", target_ref)
        if response.status_code == 404:
            return
        if response.status_code not in {200, 202, 204}:
            raise DbDrError(
                "Azure PostgreSQL teardown request was rejected",
                experiment_id=experiment_id,
                phase="teardown",
                status_code=response.status_code,
            )
        for _ in range(self._settings.max_poll_attempts):
            observed = await self._request("GET", target_ref)
            if observed.status_code == 404:
                return
            if observed.status_code != 200:
                raise DbDrError(
                    "Azure PostgreSQL teardown status read failed",
                    experiment_id=experiment_id,
                    phase="teardown",
                    status_code=observed.status_code,
                )
            await asyncio.sleep(self._settings.poll_interval_seconds)
        raise DbDrError(
            "Azure PostgreSQL teardown exceeded its polling deadline",
            experiment_id=experiment_id,
            phase="teardown",
        )

    async def _request(
        self,
        method: str,
        resource_ref: str,
        *,
        json: dict[str, object] | None = None,
    ) -> httpx.Response:
        token = await self._identity.get_token(self._settings.audience)
        return await self._http.request(
            method,
            f"{self._settings.management_endpoint.rstrip('/')}{resource_ref}",
            params={"api-version": self._settings.api_version},
            headers={"Authorization": f"Bearer {token.token}"},
            json=json,
            timeout=self._settings.request_timeout_seconds,
        )


def _parse_source(config: DbRestoreConfig) -> dict[str, str]:
    match = _SOURCE_REF.fullmatch(config.source_ref)
    if match is None:
        raise _error(
            config,
            "source_ref MUST identify one Azure PostgreSQL Flexible Server",
            phase="configuration",
        )
    values = match.groupdict()
    if values["resource_group"].casefold() == config.target_resource_group.casefold():
        raise _error(
            config,
            "DB-DR target resource group MUST differ from the source group",
            phase="configuration",
        )
    return values


def _error(
    config: DbRestoreConfig,
    message: str,
    *,
    phase: str,
    status_code: int | None = None,
) -> DbDrError:
    return DbDrError(
        message,
        experiment_id=config.experiment_id,
        phase=phase,
        status_code=status_code,
    )


__all__ = [
    "AzurePostgresRestoreAdapter",
    "AzurePostgresRestoreSettings",
]
