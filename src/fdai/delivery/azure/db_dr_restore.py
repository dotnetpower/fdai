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
  :class:`~fdai.shared.providers.db_dr.DbRestoreAdapter`
  Protocol seam.
- No ``azure-identity`` / ``DefaultAzureCredential`` - identity flows
  exclusively through
  :class:`~fdai.shared.providers.workload_identity.WorkloadIdentity`.
- HTTP transport is an injected :class:`httpx.AsyncClient`; tests hand
  it a client backed by :class:`httpx.MockTransport`. Production wires
  a long-lived shared client at the composition root.

Wire contract (v1)
------------------

+---------------------------------+-----------------------------------------------+
| Operation                       | REST path                                     |
+=================================+===============================================+
| target RG conditional create    | ``PUT /subscriptions/.../resourceGroups/{rg}``|
| ``restore`` submit              | ``POST /subscriptions/.../resourceGroups/     |
|                                 | {target_rg}/providers/Microsoft.DBforPostgreSQL|
|                                 | /flexibleServers/{name}/restore``             |
| ``restore`` LRO poll            | ``GET  {Azure-AsyncOperation | Location}``    |
| ``restore`` final resource GET  | ``GET  .../flexibleServers/{name}``           |
| ``teardown``                    | ``DELETE .../resourceGroups/{target_rg}``     |
| teardown LRO + absence verify   | ``GET {status_url}`` then ``GET {target_rg}`` |
+---------------------------------+-----------------------------------------------+

Fail-closed rules
-----------------

- Any non-2xx submit → :class:`DbDrError`.
- LRO polling ends on any state that is neither ``Succeeded`` nor a
  known in-progress marker (``InProgress`` / ``Accepted`` /
  ``Running`` / ``Provisioning``) - a non-terminal + unrecognized
  value is treated as failure so a partial restore never returns a
  handle.
- ``teardown`` swallows 404 (already deleted) but every other 4xx/5xx
  raises so an operator sees the failure in the audit log.
- The adapter acquires target-RG ownership only from a conditional create
    that returns 201. Existing groups are rejected and are never deleted.
    Restore failures and cancellation clean up only an owned group.

Isolation invariant
-------------------

The adapter refuses to submit a restore whose ``target_resource_group``
equals the source's resource group inferred from ``source_ref``. This
is a belt-and-suspenders check - the P3 orchestrator MUST also ensure
the target is not production before invoking the adapter.
"""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final
from uuid import UUID

import httpx

from fdai.shared.providers.db_dr import (
    DbDrError,
    DbRestoreAdapter,
    DbRestoreConfig,
    DbRestoreHandle,
)
from fdai.shared.providers.workload_identity import WorkloadIdentity

from .arm_url_policy import ArmUrlPolicy, ArmUrlPolicyError
from .db_dr_restore_http import (
    DB_DR_PHASE as _PHASE,
)
from .db_dr_restore_http import (
    PG_PROVIDER_SEGMENT as _PG_PROVIDER_SEGMENT,
)
from .db_dr_restore_http import (
    AzureDbDrRestoreHttpMixin,
)

_DEFAULT_AUDIENCE: Final[str] = "https://management.azure.com/.default"
_DEFAULT_API_VERSION: Final[str] = "2024-08-01"
_DEFAULT_TIMEOUT_SECONDS: Final[float] = 30.0
_DEFAULT_MAX_POLL_SECONDS: Final[float] = 1800.0
_DEFAULT_POLL_INTERVAL_SECONDS: Final[float] = 10.0
_DEFAULT_MAX_ERROR_BODY_BYTES: Final[int] = 512
_DEFAULT_TEARDOWN_RETRY_ATTEMPTS: Final[int] = 5
_DEFAULT_TEARDOWN_RETRY_INTERVAL_SECONDS: Final[float] = 30.0

_SUCCEEDED_STATES: Final[frozenset[str]] = frozenset({"succeeded", "success", "completed"})
_IN_PROGRESS_STATES: Final[frozenset[str]] = frozenset(
    {"inprogress", "in progress", "accepted", "running", "provisioning", "creating"}
)
"""LRO states that mean "keep polling". Anything outside this set and
outside :data:`_SUCCEEDED_STATES` is treated as a partial-restore
failure - the adapter never guesses at "probably fine"."""

_PG_SERVER_NAME = re.compile(r"^[a-z0-9](?:[a-z0-9-]{1,61}[a-z0-9])$")
_LOCATION_NAME = re.compile(r"^[a-z0-9]+$")
_DNS_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$", re.IGNORECASE)


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

    teardown_retry_attempts: int = _DEFAULT_TEARDOWN_RETRY_ATTEMPTS
    """Maximum DELETE attempts for 408, 429, and 5xx teardown responses."""

    teardown_retry_interval_seconds: float = _DEFAULT_TEARDOWN_RETRY_INTERVAL_SECONDS
    """Linear delay between transient teardown attempts."""


class AzureDbDrRestoreAdapter(
    AzureDbDrRestoreHttpMixin[AzureDbDrRestoreAdapterConfig], DbRestoreAdapter
):
    """Azure PG Flexible implementation of :class:`DbRestoreAdapter`."""

    def __init__(
        self,
        *,
        identity: WorkloadIdentity,
        http_client: httpx.AsyncClient,
        config: AzureDbDrRestoreAdapterConfig | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
        monotonic: Callable[[], float] | None = None,
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
        if not 1 <= cfg.teardown_retry_attempts <= 10:
            raise ValueError("teardown_retry_attempts MUST be in [1, 10]")
        if cfg.teardown_retry_interval_seconds < 0:
            raise ValueError("teardown_retry_interval_seconds MUST be >= 0")
        self._url_policy = ArmUrlPolicy.from_client(http_client)
        self._identity = identity
        self._http = http_client
        self._config = cfg
        self._sleep: Final[Callable[[float], Awaitable[None]]] = sleep or asyncio.sleep
        self._monotonic: Final[Callable[[], float]] = monotonic or time.monotonic

    # ------------------------------------------------------------------
    # DbRestoreAdapter Protocol
    # ------------------------------------------------------------------

    async def restore(self, config: DbRestoreConfig) -> DbRestoreHandle:
        _validate_restore_config(config)
        _validate_isolation(config)

        subscription_id = _extract_subscription_id(
            config.source_ref, phase=_PHASE, experiment_id=config.experiment_id
        )
        target_ref = self._resource_url(
            subscription_id=subscription_id,
            target_rg=config.target_resource_group,
            target_name=config.target_server_name,
        ).split("?", maxsplit=1)[0]
        provisional_handle = DbRestoreHandle(
            experiment_id=config.experiment_id,
            source_ref=config.source_ref,
            target_ref=target_ref,
            endpoint="pending.invalid",
            resource_group=config.target_resource_group,
            created_at=datetime.now(tz=UTC),
        )
        create_task = asyncio.create_task(
            self._create_target_resource_group(
                subscription_id=subscription_id,
                config=config,
            )
        )
        try:
            await asyncio.shield(create_task)
        except asyncio.CancelledError as cancelled:
            try:
                await create_task
            except Exception:
                raise cancelled from None
            cleanup_task = asyncio.create_task(self.teardown(provisional_handle))
            try:
                await asyncio.shield(cleanup_task)
            except asyncio.CancelledError:
                await cleanup_task
            except Exception as cleanup_exc:
                raise cleanup_exc from cancelled
            raise
        try:
            return await self._restore_owned_environment(
                config=config,
                subscription_id=subscription_id,
            )
        except BaseException as exc:
            cleanup_task = asyncio.create_task(self.teardown(provisional_handle))
            try:
                await asyncio.shield(cleanup_task)
            except asyncio.CancelledError:
                await cleanup_task
                raise
            except Exception as cleanup_exc:
                if isinstance(exc, asyncio.CancelledError):
                    raise cleanup_exc from exc
                raise DbDrError(
                    "restore failed and owned target cleanup also failed",
                    experiment_id=config.experiment_id,
                    phase=_PHASE,
                ) from cleanup_exc
            raise

    async def _restore_owned_environment(
        self,
        *,
        config: DbRestoreConfig,
        subscription_id: str,
    ) -> DbRestoreHandle:
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
                status_url=self._validate_lro_url(
                    status_url,
                    experiment_id=config.experiment_id,
                ),
                experiment_id=config.experiment_id,
            )

        # After the LRO settles the source of truth is the resource GET.
        resource_url = self._resource_url(
            subscription_id=subscription_id,
            target_rg=config.target_resource_group,
            target_name=config.target_server_name,
        )
        expected_target_ref = resource_url.split("?", maxsplit=1)[0]
        target_ref, endpoint = await self._fetch_final_resource(
            url=resource_url,
            experiment_id=config.experiment_id,
            expected_target_ref=expected_target_ref,
            target_server_name=config.target_server_name,
        )
        return DbRestoreHandle(
            experiment_id=config.experiment_id,
            source_ref=config.source_ref,
            target_ref=target_ref,
            endpoint=endpoint,
            resource_group=config.target_resource_group,
            created_at=datetime.now(tz=UTC),
        )

    async def _create_target_resource_group(
        self,
        *,
        subscription_id: str,
        config: DbRestoreConfig,
    ) -> None:
        url = self._resource_group_url(
            subscription_id=subscription_id,
            resource_group=config.target_resource_group,
        )
        headers = await self._auth_headers()
        headers["If-None-Match"] = "*"
        response = await self._put(
            url=url,
            headers=headers,
            json_body={
                "location": config.target_location,
                "tags": {"managed-by": "fdai", "purpose": "dr-drill"},
            },
            experiment_id=config.experiment_id,
        )
        if response.status_code == 201:
            return
        if response.status_code in (200, 409, 412):
            raise DbDrError(
                "target resource group already exists; ownership was not acquired",
                experiment_id=config.experiment_id,
                phase=_PHASE,
                status_code=response.status_code,
            )
        raise DbDrError(
            f"target resource group create returned HTTP {response.status_code}: "
            f"{self._trim(response.text)}",
            experiment_id=config.experiment_id,
            phase=_PHASE,
            status_code=response.status_code,
        )

    async def teardown(self, handle: DbRestoreHandle) -> None:
        try:
            ArmUrlPolicy.validate_resource_ref(handle.target_ref)
            _validate_arm_segment("resource_group", handle.resource_group, max_chars=90)
        except ArmUrlPolicyError as exc:
            raise DbDrError(
                str(exc),
                experiment_id=handle.experiment_id,
                phase="teardown",
            ) from exc
        subscription_id = _extract_subscription_id(
            handle.target_ref, phase="teardown", experiment_id=handle.experiment_id
        )
        url = self._resource_group_url(
            subscription_id=subscription_id, resource_group=handle.resource_group
        )
        headers = await self._auth_headers()

        for attempt in range(1, self._config.teardown_retry_attempts + 1):
            response = await self._delete(
                url=url,
                headers=headers,
                experiment_id=handle.experiment_id,
            )
            if response.status_code in (200, 202, 204, 404):
                if response.status_code == 202:
                    status_url = response.headers.get(
                        "Azure-AsyncOperation"
                    ) or response.headers.get("Location")
                    if status_url is None:
                        raise DbDrError(
                            "teardown returned 202 without an LRO status header",
                            experiment_id=handle.experiment_id,
                            phase="teardown",
                            status_code=202,
                        )
                    await self._poll_until_terminal(
                        status_url=self._validate_lro_url(
                            status_url,
                            experiment_id=handle.experiment_id,
                        ),
                        experiment_id=handle.experiment_id,
                    )
                    await self._verify_resource_group_deleted(
                        url=url,
                        headers=headers,
                        experiment_id=handle.experiment_id,
                    )
                return
            transient = response.status_code in (408, 429) or response.status_code >= 500
            if not transient or attempt == self._config.teardown_retry_attempts:
                raise DbDrError(
                    f"teardown returned HTTP {response.status_code}: {self._trim(response.text)}",
                    experiment_id=handle.experiment_id,
                    phase="teardown",
                    status_code=response.status_code,
                )
            await self._sleep(self._config.teardown_retry_interval_seconds)

    async def _verify_resource_group_deleted(
        self,
        *,
        url: str,
        headers: dict[str, str],
        experiment_id: str,
    ) -> None:
        response = await self._get(
            url=url,
            headers=headers,
            experiment_id=experiment_id,
        )
        if response.status_code == 404:
            return
        raise DbDrError(
            f"teardown completed but target resource group still returned HTTP "
            f"{response.status_code}",
            experiment_id=experiment_id,
            phase="teardown",
            status_code=response.status_code,
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _poll_until_terminal(self, *, status_url: str, experiment_id: str) -> None:
        deadline = self._config.max_poll_seconds
        synthetic_elapsed = 0.0
        started = self._monotonic()
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

            if response.status_code != 202 and state is None:
                raise DbDrError(
                    "restore poll returned no valid status",
                    experiment_id=experiment_id,
                    phase=_PHASE,
                )

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

            elapsed = max(synthetic_elapsed, self._monotonic() - started)
            if elapsed >= deadline:
                raise DbDrError(
                    f"restore did not complete within {deadline}s",
                    experiment_id=experiment_id,
                    phase=_PHASE,
                )
            await self._sleep(interval)
            synthetic_elapsed += interval

    async def _fetch_final_resource(
        self,
        *,
        url: str,
        experiment_id: str,
        expected_target_ref: str,
        target_server_name: str,
    ) -> tuple[str, str]:
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
        if target_ref.casefold() != expected_target_ref.casefold():
            raise DbDrError(
                "restore resource GET returned an unexpected resource id",
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
        _validate_restored_fqdn(
            endpoint,
            target_server_name=target_server_name,
            experiment_id=experiment_id,
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


def _validate_restore_config(config: DbRestoreConfig) -> None:
    try:
        ArmUrlPolicy.validate_resource_ref(config.source_ref)
    except ArmUrlPolicyError as exc:
        raise DbDrError(
            str(exc),
            experiment_id=config.experiment_id,
            phase=_PHASE,
        ) from exc
    if _PG_PROVIDER_SEGMENT not in config.source_ref:
        raise DbDrError(
            "source_ref MUST identify a PostgreSQL Flexible Server",
            experiment_id=config.experiment_id,
            phase=_PHASE,
        )
    source_name = config.source_ref.rsplit(_PG_PROVIDER_SEGMENT, maxsplit=1)[1]
    if "/" in source_name or not _PG_SERVER_NAME.fullmatch(source_name):
        raise DbDrError(
            "source_ref contains an invalid PostgreSQL server name",
            experiment_id=config.experiment_id,
            phase=_PHASE,
        )
    try:
        _validate_arm_segment(
            "target_resource_group",
            config.target_resource_group,
            max_chars=90,
        )
        _validate_postgres_server_name(config.target_server_name)
    except ArmUrlPolicyError as exc:
        raise DbDrError(
            str(exc),
            experiment_id=config.experiment_id,
            phase=_PHASE,
        ) from exc
    if not _LOCATION_NAME.fullmatch(config.target_location):
        raise DbDrError(
            "target_location MUST be a lowercase Azure region identifier",
            experiment_id=config.experiment_id,
            phase=_PHASE,
        )
    if config.point_in_time_utc is not None and (
        config.point_in_time_utc.tzinfo is None or config.point_in_time_utc.utcoffset() is None
    ):
        raise DbDrError(
            "point_in_time_utc MUST be timezone-aware",
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
            candidate = parts[i + 1]
            try:
                parsed = UUID(candidate)
            except ValueError as exc:
                raise DbDrError(
                    "resource reference contained an invalid subscription id",
                    experiment_id=experiment_id,
                    phase=phase,
                ) from exc
            if str(parsed) != candidate.casefold():
                raise DbDrError(
                    "resource reference subscription id MUST be canonical",
                    experiment_id=experiment_id,
                    phase=phase,
                )
            return candidate
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

    ``createMode`` is fixed to ``PointInTimeRestore`` - the adapter
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


def _validate_arm_segment(name: str, value: str, *, max_chars: int) -> None:
    if (
        not value
        or value != value.strip()
        or len(value) > max_chars
        or value.endswith(".")
        or any(character in value for character in "/\\?#")
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise ArmUrlPolicyError(f"{name} is not a valid Azure resource path segment")


def _validate_postgres_server_name(value: str) -> None:
    if not _PG_SERVER_NAME.fullmatch(value):
        raise ArmUrlPolicyError(
            "target_server_name MUST be a 3-63 character lowercase PostgreSQL server name"
        )


def _validate_restored_fqdn(
    value: str,
    *,
    target_server_name: str,
    experiment_id: str,
) -> None:
    labels = value.rstrip(".").split(".")
    if (
        value != value.strip()
        or len(value) > 253
        or len(labels) < 2
        or labels[0].casefold() != target_server_name.casefold()
        or any(not _DNS_LABEL.fullmatch(label) for label in labels)
    ):
        raise DbDrError(
            "restore resource GET returned an invalid target FQDN",
            experiment_id=experiment_id,
            phase=_PHASE,
        )


__all__ = [
    "AzureDbDrRestoreAdapter",
    "AzureDbDrRestoreAdapterConfig",
]
