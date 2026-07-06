"""Azure PostgreSQL Flexible PITR restore adapter for :class:`DbRestoreAdapter`.

Realizes the DB restore Protocol against the Azure PostgreSQL Flexible
Server REST surface. The adapter creates a new (isolated) server in a
fresh resource group by POSTing to the ``restore`` sub-resource with
the source server id + point-in-time; it fails closed on any partial
restore signal and idempotently tears the restored environment down
by deleting its resource group.

Design boundaries
-----------------

- ``core/`` never imports this module; it lives under
  ``delivery/azure/`` and is bound at the composition root through the
  :class:`~aiopspilot.shared.providers.db_dr.DbRestoreAdapter`
  Protocol seam.
- No ``azure-identity`` / ``DefaultAzureCredential`` — identity flows
  exclusively through
  :class:`~aiopspilot.shared.providers.workload_identity.WorkloadIdentity`.
- HTTP transport is an injected :class:`httpx.AsyncClient`; tests hand
  it a client backed by :class:`httpx.MockTransport`. Production wires
  a long-lived shared client at the composition root.

Wire contract (v1)
------------------

+---------------------------------+-----------------------------------------------+
| Operation                       | REST path                                     |
+=================================+===============================================+
| ``restore`` submit              | ``POST /subscriptions/.../resourceGroups/     |
|                                 | {target_rg}/providers/Microsoft.DBforPostgreSQL|
|                                 | /flexibleServers/{name}/restore``             |
| ``restore`` LRO poll            | ``GET  {Azure-AsyncOperation | Location}``    |
| ``restore`` final resource GET  | ``GET  .../flexibleServers/{name}``           |
| ``teardown``                    | ``DELETE .../resourceGroups/{target_rg}``     |
+---------------------------------+-----------------------------------------------+

Fail-closed rules
-----------------

- Any non-2xx submit → :class:`DbDrError`.
- LRO polling ends on any state that is neither ``Succeeded`` nor a
  known in-progress marker (``InProgress`` / ``Accepted`` /
  ``Running`` / ``Provisioning``) — a non-terminal + unrecognized
  value is treated as failure so a partial restore never returns a
  handle.
- ``teardown`` swallows 404 (already deleted) but every other 4xx/5xx
  raises so an operator sees the failure in the audit log.

Isolation invariant
-------------------

The adapter refuses to submit a restore whose ``target_resource_group``
equals the source's resource group inferred from ``source_ref``. This
is a belt-and-suspenders check — the P3 orchestrator MUST also ensure
the target is not production before invoking the adapter.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

import httpx

from aiopspilot.shared.providers.db_dr import (
    DbDrError,
    DbRestoreAdapter,
    DbRestoreConfig,
    DbRestoreHandle,
)
from aiopspilot.shared.providers.workload_identity import WorkloadIdentity

_DEFAULT_AUDIENCE: Final[str] = "https://management.azure.com/.default"
_DEFAULT_API_VERSION: Final[str] = "2024-08-01"
_DEFAULT_TIMEOUT_SECONDS: Final[float] = 30.0
_DEFAULT_MAX_POLL_SECONDS: Final[float] = 1800.0
_DEFAULT_POLL_INTERVAL_SECONDS: Final[float] = 10.0
_DEFAULT_MAX_ERROR_BODY_BYTES: Final[int] = 512

_SUCCEEDED_STATES: Final[frozenset[str]] = frozenset({"succeeded", "success", "completed"})
_IN_PROGRESS_STATES: Final[frozenset[str]] = frozenset(
    {"inprogress", "in progress", "accepted", "running", "provisioning", "creating"}
)
"""LRO states that mean "keep polling". Anything outside this set and
outside :data:`_SUCCEEDED_STATES` is treated as a partial-restore
failure — the adapter never guesses at "probably fine"."""

_PHASE: Final[str] = "restore"

# Provider identifier for Azure PG Flexible Server; used to build the
# teardown RG path and to sanity-check the source ARM id.
_PG_PROVIDER_SEGMENT: Final[str] = "/providers/Microsoft.DBforPostgreSQL/flexibleServers/"


@dataclass(frozen=True, slots=True)
class AzureDbDrRestoreAdapterConfig:
    """Configuration for the Azure PG Flexible PITR restore adapter.

    Every value has a documented default so the composition root only
    needs to supply what a fork wants to override.
    """

    audience: str = _DEFAULT_AUDIENCE
    """OIDC audience requested from :class:`WorkloadIdentity`."""

    api_version: str = _DEFAULT_API_VERSION
    """API version pin for the PG Flexible REST surface."""

    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS
    """Per-HTTP-request timeout applied to every call."""

    max_poll_seconds: float = _DEFAULT_MAX_POLL_SECONDS
    """Overall budget for LRO polling of the restore operation."""

    poll_interval_seconds: float = _DEFAULT_POLL_INTERVAL_SECONDS
    """Sleep between LRO polls. Tests override to ``0`` for speed."""

    max_error_body_bytes: int = _DEFAULT_MAX_ERROR_BODY_BYTES
    """Cap on the vendor error snippet embedded in :class:`DbDrError`."""


class AzureDbDrRestoreAdapter(DbRestoreAdapter):
    """Azure PG Flexible implementation of :class:`DbRestoreAdapter`."""

    def __init__(
        self,
        *,
        identity: WorkloadIdentity,
        http_client: httpx.AsyncClient,
        config: AzureDbDrRestoreAdapterConfig | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        cfg = config or AzureDbDrRestoreAdapterConfig()
        if cfg.timeout_seconds <= 0:
            raise ValueError("timeout_seconds MUST be > 0")
        if cfg.max_poll_seconds <= 0:
            raise ValueError("max_poll_seconds MUST be > 0")
        if cfg.poll_interval_seconds < 0:
            raise ValueError("poll_interval_seconds MUST be >= 0")
        if cfg.max_error_body_bytes < 64:
            raise ValueError("max_error_body_bytes MUST be >= 64")
        self._identity: Final[WorkloadIdentity] = identity
        self._http: Final[httpx.AsyncClient] = http_client
        self._config: Final[AzureDbDrRestoreAdapterConfig] = cfg
        self._sleep: Final[Callable[[float], Awaitable[None]]] = sleep or asyncio.sleep

    # ------------------------------------------------------------------
    # DbRestoreAdapter Protocol
    # ------------------------------------------------------------------

    async def restore(self, config: DbRestoreConfig) -> DbRestoreHandle:
        _validate_isolation(config)

        subscription_id = _extract_subscription_id(
            config.source_ref, phase=_PHASE, experiment_id=config.experiment_id
        )
        submit_url = self._restore_submit_url(
            subscription_id=subscription_id,
            target_rg=config.target_resource_group,
            target_name=config.target_server_name,
        )
        payload = _build_restore_payload(config)
        headers = await self._auth_headers()

        submit_response = await self._post(
            url=submit_url,
            headers=headers,
            json_body=payload,
            experiment_id=config.experiment_id,
        )

        if submit_response.status_code >= 400:
            raise DbDrError(
                f"restore submit returned HTTP {submit_response.status_code}: "
                f"{self._trim(submit_response.text)}",
                experiment_id=config.experiment_id,
                phase=_PHASE,
                status_code=submit_response.status_code,
            )

        # A synchronous 200/201 with a resource body finishes here.
        # A 202 hands us an LRO endpoint to poll.
        status_url = submit_response.headers.get(
            "Azure-AsyncOperation"
        ) or submit_response.headers.get("Location")
        if submit_response.status_code == 202 or status_url:
            if status_url is None:
                raise DbDrError(
                    "restore submit returned 202 without an LRO status header",
                    experiment_id=config.experiment_id,
                    phase=_PHASE,
                    status_code=submit_response.status_code,
                )
            await self._poll_until_terminal(
                status_url=status_url,
                experiment_id=config.experiment_id,
            )

        # After the LRO settles the source of truth is the resource GET.
        resource_url = self._resource_url(
            subscription_id=subscription_id,
            target_rg=config.target_resource_group,
            target_name=config.target_server_name,
        )
        target_ref, endpoint = await self._fetch_final_resource(
            url=resource_url,
            experiment_id=config.experiment_id,
        )
        return DbRestoreHandle(
            experiment_id=config.experiment_id,
            source_ref=config.source_ref,
            target_ref=target_ref,
            endpoint=endpoint,
            resource_group=config.target_resource_group,
            created_at=datetime.now(tz=UTC),
        )

    async def teardown(self, handle: DbRestoreHandle) -> None:
        subscription_id = _extract_subscription_id(
            handle.target_ref, phase="teardown", experiment_id=handle.experiment_id
        )
        url = self._resource_group_url(
            subscription_id=subscription_id, resource_group=handle.resource_group
        )
        headers = await self._auth_headers()

        response = await self._delete(
            url=url,
            headers=headers,
            experiment_id=handle.experiment_id,
        )

        # 200 / 202 / 204 → accepted; 404 → already gone (idempotent).
        if response.status_code in (200, 202, 204, 404):
            return
        raise DbDrError(
            f"teardown returned HTTP {response.status_code}: {self._trim(response.text)}",
            experiment_id=handle.experiment_id,
            phase="teardown",
            status_code=response.status_code,
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _poll_until_terminal(self, *, status_url: str, experiment_id: str) -> None:
        deadline = self._config.max_poll_seconds
        elapsed = 0.0
        interval = self._config.poll_interval_seconds
        headers = await self._auth_headers()

        while True:
            response = await self._get(
                url=status_url,
                headers=headers,
                experiment_id=experiment_id,
            )
            if response.status_code == 202:
                state: str | None = None
            elif response.status_code >= 400:
                raise DbDrError(
                    f"restore poll returned HTTP {response.status_code}: "
                    f"{self._trim(response.text)}",
                    experiment_id=experiment_id,
                    phase=_PHASE,
                    status_code=response.status_code,
                )
            else:
                state = _extract_state(response)

            if state is not None:
                lowered = state.lower()
                if lowered in _SUCCEEDED_STATES:
                    return
                if lowered not in _IN_PROGRESS_STATES:
                    # Fail-closed: an unknown terminal state MUST NOT
                    # be treated as success. Partial restores land
                    # here.
                    raise DbDrError(
                        f"restore ended in non-success state {state!r}",
                        experiment_id=experiment_id,
                        phase=_PHASE,
                    )

            if elapsed >= deadline:
                raise DbDrError(
                    f"restore did not complete within {deadline}s",
                    experiment_id=experiment_id,
                    phase=_PHASE,
                )
            await self._sleep(interval)
            elapsed += interval

    async def _fetch_final_resource(self, *, url: str, experiment_id: str) -> tuple[str, str]:
        headers = await self._auth_headers()
        response = await self._get(
            url=url,
            headers=headers,
            experiment_id=experiment_id,
        )
        if response.status_code >= 400:
            raise DbDrError(
                f"restore resource GET returned HTTP {response.status_code}: "
                f"{self._trim(response.text)}",
                experiment_id=experiment_id,
                phase=_PHASE,
                status_code=response.status_code,
            )
        try:
            body = response.json()
        except ValueError as exc:
            raise DbDrError(
                "restore resource GET returned non-JSON body",
                experiment_id=experiment_id,
                phase=_PHASE,
            ) from exc

        if not isinstance(body, dict):
            raise DbDrError(
                "restore resource GET returned a non-object payload",
                experiment_id=experiment_id,
                phase=_PHASE,
            )
        target_ref = body.get("id")
        if not isinstance(target_ref, str) or not target_ref:
            raise DbDrError(
                "restore resource GET returned no resource id",
                experiment_id=experiment_id,
                phase=_PHASE,
            )
        properties = body.get("properties")
        endpoint: str | None = None
        if isinstance(properties, dict):
            candidate = properties.get("fullyQualifiedDomainName")
            if isinstance(candidate, str) and candidate:
                endpoint = candidate
        if endpoint is None:
            raise DbDrError(
                "restore resource GET returned no fully-qualified domain name",
                experiment_id=experiment_id,
                phase=_PHASE,
            )
        # Also confirm the substrate reports Succeeded as its
        # provisioning state; a Ready endpoint with a non-Succeeded
        # state is a partial restore.
        if isinstance(properties, dict):
            state = properties.get("state") or properties.get("provisioningState")
            if isinstance(state, str) and state.lower() not in _SUCCEEDED_STATES.union({"ready"}):
                raise DbDrError(
                    f"restore resource reports non-success state {state!r}",
                    experiment_id=experiment_id,
                    phase=_PHASE,
                )
        return target_ref, endpoint

    async def _auth_headers(self) -> dict[str, str]:
        token = await self._identity.get_token(self._config.audience)
        return {
            "Authorization": f"Bearer {token.token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def _post(
        self,
        *,
        url: str,
        headers: dict[str, str],
        json_body: dict[str, object],
        experiment_id: str,
    ) -> httpx.Response:
        try:
            return await self._http.post(
                url,
                headers=headers,
                json=json_body,
                timeout=self._config.timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise DbDrError(
                f"restore submit failed: {exc.__class__.__name__}",
                experiment_id=experiment_id,
                phase=_PHASE,
            ) from exc

    async def _get(
        self,
        *,
        url: str,
        headers: dict[str, str],
        experiment_id: str,
    ) -> httpx.Response:
        try:
            return await self._http.get(
                url,
                headers=headers,
                timeout=self._config.timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise DbDrError(
                f"restore request failed: {exc.__class__.__name__}",
                experiment_id=experiment_id,
                phase=_PHASE,
            ) from exc

    async def _delete(
        self,
        *,
        url: str,
        headers: dict[str, str],
        experiment_id: str,
    ) -> httpx.Response:
        try:
            return await self._http.delete(
                url,
                headers=headers,
                timeout=self._config.timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise DbDrError(
                f"teardown request failed: {exc.__class__.__name__}",
                experiment_id=experiment_id,
                phase="teardown",
            ) from exc

    def _restore_submit_url(self, *, subscription_id: str, target_rg: str, target_name: str) -> str:
        path = (
            f"/subscriptions/{subscription_id}/resourceGroups/{target_rg}"
            f"{_PG_PROVIDER_SEGMENT}{target_name}/restore"
        )
        return f"{path}?api-version={self._config.api_version}"

    def _resource_url(self, *, subscription_id: str, target_rg: str, target_name: str) -> str:
        path = (
            f"/subscriptions/{subscription_id}/resourceGroups/{target_rg}"
            f"{_PG_PROVIDER_SEGMENT}{target_name}"
        )
        return f"{path}?api-version={self._config.api_version}"

    def _resource_group_url(self, *, subscription_id: str, resource_group: str) -> str:
        # RG-level API uses a different (older) api-version envelope;
        # 2021-04-01 is the long-lived stable version and works for
        # DELETE across every Azure region we target.
        return (
            f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}"
            f"?api-version=2021-04-01"
        )

    def _trim(self, text: str) -> str:
        cap = self._config.max_error_body_bytes
        raw = text.replace("\n", " ")
        if len(raw) <= cap:
            return raw
        return raw[:cap] + "…"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _validate_isolation(config: DbRestoreConfig) -> None:
    """Refuse a config whose target RG equals the source RG.

    Belt-and-suspenders: the P3 orchestrator MUST enforce isolation
    upstream, but the adapter reasserts it before mutating any
    substrate so an accidental misconfiguration never restores over
    the source.
    """
    source_rg = _extract_resource_group(config.source_ref)
    if source_rg is None:
        raise DbDrError(
            "source_ref did not contain a resourceGroups segment",
            experiment_id=config.experiment_id,
            phase=_PHASE,
        )
    if source_rg.lower() == config.target_resource_group.lower():
        raise DbDrError(
            "target_resource_group MUST NOT equal the source resource group (isolation)",
            experiment_id=config.experiment_id,
            phase=_PHASE,
        )


def _extract_subscription_id(resource_ref: str, *, phase: str, experiment_id: str) -> str:
    """Pull the subscription id out of an ARM path like
    ``/subscriptions/<id>/resourceGroups/...``.

    Raises :class:`DbDrError` on a malformed reference so a caller
    cannot silently build a nonsense URL.
    """
    parts = resource_ref.strip().split("/")
    # Expected shape: ["", "subscriptions", "<id>", "resourceGroups", ...]
    for i, seg in enumerate(parts):
        if seg == "subscriptions" and i + 1 < len(parts) and parts[i + 1]:
            return parts[i + 1]
    raise DbDrError(
        "resource reference did not contain a subscriptions segment",
        experiment_id=experiment_id,
        phase=phase,
    )


def _extract_resource_group(resource_ref: str) -> str | None:
    parts = resource_ref.strip().split("/")
    for i, seg in enumerate(parts):
        if seg.lower() == "resourcegroups" and i + 1 < len(parts) and parts[i + 1]:
            return parts[i + 1]
    return None


def _build_restore_payload(config: DbRestoreConfig) -> dict[str, object]:
    """Serialize the restore POST body.

    ``createMode`` is fixed to ``PointInTimeRestore`` — the adapter
    only supports PITR restore; a full-copy restore would land here as
    a separate ``createMode`` value under an intentional contract diff.
    """
    properties: dict[str, object] = {
        "createMode": "PointInTimeRestore",
        "sourceServerResourceId": config.source_ref,
    }
    if config.point_in_time_utc is not None:
        # ISO 8601 with a trailing Z per the Azure convention.
        moment = config.point_in_time_utc
        if moment.tzinfo is None:
            # Treat naive as UTC — the DbRestoreConfig doc says UTC.
            moment = moment.replace(tzinfo=UTC)
        properties["pointInTimeUTC"] = moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"location": config.target_location, "properties": properties}


def _extract_state(response: httpx.Response) -> str | None:
    """Read the LRO state string from a poll response body."""
    if not response.content:
        return None
    try:
        body = response.json()
    except ValueError:
        return None
    if not isinstance(body, dict):
        return None
    state = body.get("status")
    if isinstance(state, str):
        return state
    properties = body.get("properties")
    if isinstance(properties, dict):
        candidate = properties.get("provisioningState") or properties.get("state")
        if isinstance(candidate, str):
            return candidate
    return None


__all__ = [
    "AzureDbDrRestoreAdapter",
    "AzureDbDrRestoreAdapterConfig",
]
