"""Azure Chaos Studio + Site Recovery adapter for :class:`DrExperimentRunner`.

Realizes the DR experiment Protocol for Azure. The adapter dispatches
on :class:`DrExperimentKind` and speaks the ARM REST surface directly
under a bearer token issued by the injected
:class:`~aiopspilot.shared.providers.workload_identity.WorkloadIdentity`.

Design boundaries
-----------------

- ``core/`` never imports this module; it lives under
  ``delivery/azure/`` and is bound at the composition root through the
  :class:`~aiopspilot.shared.providers.dr_experiment.DrExperimentRunner`
  Protocol seam.
- No ``azure-identity`` / ``DefaultAzureCredential`` — identity flows
  exclusively through :class:`WorkloadIdentity`.
- HTTP transport is an injected :class:`httpx.AsyncClient`; tests hand
  it a client backed by :class:`httpx.MockTransport`. Production wires
  a long-lived shared client at the composition root.

Wire contract (v1)
------------------

+---------------------------------+----------------------------------------------+
| Operation                       | REST path                                    |
+=================================+==============================================+
| Chaos ``start``                 | ``POST {provider_ref}/start``                |
| Chaos ``check``                 | ``GET  {status_url}`` (LRO Location header)  |
| Chaos ``rollback``              | ``POST {provider_ref}/cancel``               |
| Site Recovery ``start``         | ``POST {provider_ref}/plannedFailover``      |
| Site Recovery ``check``         | ``GET  {status_url}`` (LRO Location header)  |
| Site Recovery ``rollback``      | ``POST {provider_ref}/plannedFailoverCleanup`` |
+---------------------------------+----------------------------------------------+

All operations honor a per-request timeout from
:class:`AzureDrExperimentAdapterConfig.timeout_seconds`. LRO polling is
one-shot per :meth:`check` call by design — the P3 scheduler owns the
poll cadence and stop-condition timing, not this adapter.

Safety invariants
-----------------

- **Fail-closed**: any non-2xx response, timeout, or malformed body
  raises :class:`DrRunnerError`; the caller escalates to HIL.
- **Rollback idempotency**: ``rollback`` on an already-cancelled or
  never-started run returns silently on 200/204/404 — a 4xx that
  indicates the experiment never existed is not a rollback failure.
- **Bounded error bodies**: response text is truncated before it is
  embedded in the raised error, so an oversized vendor error page
  cannot flood the audit log.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

import httpx

from aiopspilot.core.verticals.resilience import DrExperiment
from aiopspilot.shared.providers.dr_experiment import (
    DrExperimentKind,
    DrExperimentRunner,
    DrRunHandle,
    DrRunnerError,
    DrRunStatus,
)
from aiopspilot.shared.providers.workload_identity import WorkloadIdentity

_DEFAULT_AUDIENCE: Final[str] = "https://management.azure.com/.default"
_DEFAULT_CHAOS_API_VERSION: Final[str] = "2024-01-01"
_DEFAULT_SITE_RECOVERY_API_VERSION: Final[str] = "2024-04-01"
_DEFAULT_TIMEOUT_SECONDS: Final[float] = 30.0
_DEFAULT_MAX_ERROR_BODY_BYTES: Final[int] = 512


@dataclass(frozen=True, slots=True)
class AzureDrExperimentAdapterConfig:
    """Configuration for the Azure DR / Chaos runner adapter.

    Every value has a documented default so the composition root only
    needs to supply what a fork wants to override.
    """

    audience: str = _DEFAULT_AUDIENCE
    """OIDC audience requested from :class:`WorkloadIdentity`.

    Azure ARM uses ``https://management.azure.com/.default``; other
    clouds (Azure Government, Azure China) override this.
    """

    chaos_api_version: str = _DEFAULT_CHAOS_API_VERSION
    """API version pin for the Chaos Studio REST surface.

    Bumping this is an intentional, reviewable change (contract diff),
    never a mid-flight upgrade.
    """

    site_recovery_api_version: str = _DEFAULT_SITE_RECOVERY_API_VERSION
    """API version pin for the Site Recovery REST surface."""

    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS
    """Per-HTTP-request timeout applied to start / check / rollback."""

    max_error_body_bytes: int = _DEFAULT_MAX_ERROR_BODY_BYTES
    """Cap on the vendor error snippet embedded in :class:`DrRunnerError`."""


# Statuses that Chaos Studio and Site Recovery LRO endpoints return in
# their ``status`` / ``properties.provisioningState`` fields. The mapping
# is intentionally conservative — an unknown vendor value maps to
# :class:`DrRunStatus.RUNNING` so the caller keeps polling instead of
# treating novelty as failure. Vendor changes must be reviewed and
# added here explicitly.
_SUCCEEDED_STATES: Final[frozenset[str]] = frozenset({"succeeded", "success", "completed"})
_FAILED_STATES: Final[frozenset[str]] = frozenset({"failed", "error", "faulted"})
_STOPPED_STATES: Final[frozenset[str]] = frozenset({"cancelled", "canceled", "stopped", "aborted"})


class AzureDrExperimentAdapter(DrExperimentRunner):
    """Azure implementation of :class:`DrExperimentRunner`."""

    def __init__(
        self,
        *,
        identity: WorkloadIdentity,
        http_client: httpx.AsyncClient,
        config: AzureDrExperimentAdapterConfig | None = None,
    ) -> None:
        cfg = config or AzureDrExperimentAdapterConfig()
        if cfg.timeout_seconds <= 0:
            raise ValueError("timeout_seconds MUST be > 0")
        if cfg.max_error_body_bytes < 64:
            raise ValueError("max_error_body_bytes MUST be >= 64")
        self._identity: Final[WorkloadIdentity] = identity
        self._http: Final[httpx.AsyncClient] = http_client
        self._config: Final[AzureDrExperimentAdapterConfig] = cfg

    # ------------------------------------------------------------------
    # DrExperimentRunner Protocol
    # ------------------------------------------------------------------

    async def start(self, experiment: DrExperiment) -> DrRunHandle:
        if experiment.provider_ref is None:
            raise DrRunnerError(
                "provider_ref is required to start an Azure DR experiment",
                experiment_id=experiment.experiment_id,
                kind=_infer_kind(experiment),
            )

        kind = _infer_kind(experiment)
        url = self._start_url(provider_ref=experiment.provider_ref, kind=kind)
        headers = await self._auth_headers()

        try:
            response = await self._http.post(
                url,
                headers=headers,
                timeout=self._config.timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise DrRunnerError(
                f"start request failed: {exc.__class__.__name__}",
                experiment_id=experiment.experiment_id,
                kind=kind,
            ) from exc

        if response.status_code >= 400:
            raise DrRunnerError(
                f"start returned HTTP {response.status_code}: {self._trim(response.text)}",
                experiment_id=experiment.experiment_id,
                kind=kind,
                status_code=response.status_code,
            )

        run_id, status_url = _extract_run_pointers(
            response=response, provider_ref=experiment.provider_ref
        )
        return DrRunHandle(
            experiment_id=experiment.experiment_id,
            kind=kind,
            provider_ref=experiment.provider_ref,
            run_id=run_id,
            started_at=datetime.now(tz=UTC),
            status_url=status_url,
        )

    async def check(self, handle: DrRunHandle) -> DrRunStatus:
        # The LRO Location URL is authoritative when present; otherwise
        # we fall back to a GET on the experiment resource itself
        # (Site Recovery synchronous completion + Chaos Studio unit
        # tests that don't emit a Location).
        url = handle.status_url or self._resource_url(
            provider_ref=handle.provider_ref, kind=handle.kind
        )
        headers = await self._auth_headers()

        try:
            response = await self._http.get(
                url,
                headers=headers,
                timeout=self._config.timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise DrRunnerError(
                f"check request failed: {exc.__class__.__name__}",
                experiment_id=handle.experiment_id,
                kind=handle.kind,
            ) from exc

        if response.status_code == 202:
            # Still in progress — the runtime substrate has not settled
            # the LRO yet.
            return DrRunStatus.RUNNING
        if response.status_code >= 400:
            raise DrRunnerError(
                f"check returned HTTP {response.status_code}: {self._trim(response.text)}",
                experiment_id=handle.experiment_id,
                kind=handle.kind,
                status_code=response.status_code,
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise DrRunnerError(
                "check returned non-JSON body",
                experiment_id=handle.experiment_id,
                kind=handle.kind,
            ) from exc

        return _map_state(payload)

    async def rollback(self, handle: DrRunHandle) -> None:
        url = self._rollback_url(provider_ref=handle.provider_ref, kind=handle.kind)
        headers = await self._auth_headers()

        try:
            response = await self._http.post(
                url,
                headers=headers,
                timeout=self._config.timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise DrRunnerError(
                f"rollback request failed: {exc.__class__.__name__}",
                experiment_id=handle.experiment_id,
                kind=handle.kind,
            ) from exc

        # 200 / 202 / 204 → rollback accepted / already completed.
        # 404 → the run never materialized on the substrate; rollback is
        # trivially idempotent so we swallow it. Any other 4xx / 5xx is
        # a real failure and MUST surface so the caller can escalate.
        if response.status_code in (200, 202, 204, 404):
            return
        raise DrRunnerError(
            f"rollback returned HTTP {response.status_code}: {self._trim(response.text)}",
            experiment_id=handle.experiment_id,
            kind=handle.kind,
            status_code=response.status_code,
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _auth_headers(self) -> dict[str, str]:
        token = await self._identity.get_token(self._config.audience)
        return {
            "Authorization": f"Bearer {token.token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _start_url(self, *, provider_ref: str, kind: DrExperimentKind) -> str:
        if kind is DrExperimentKind.CHAOS:
            return self._compose_url(
                provider_ref=provider_ref,
                suffix="/start",
                api_version=self._config.chaos_api_version,
            )
        return self._compose_url(
            provider_ref=provider_ref,
            suffix="/plannedFailover",
            api_version=self._config.site_recovery_api_version,
        )

    def _rollback_url(self, *, provider_ref: str, kind: DrExperimentKind) -> str:
        if kind is DrExperimentKind.CHAOS:
            return self._compose_url(
                provider_ref=provider_ref,
                suffix="/cancel",
                api_version=self._config.chaos_api_version,
            )
        return self._compose_url(
            provider_ref=provider_ref,
            suffix="/plannedFailoverCleanup",
            api_version=self._config.site_recovery_api_version,
        )

    def _resource_url(self, *, provider_ref: str, kind: DrExperimentKind) -> str:
        api_version = (
            self._config.chaos_api_version
            if kind is DrExperimentKind.CHAOS
            else self._config.site_recovery_api_version
        )
        return self._compose_url(provider_ref=provider_ref, suffix="", api_version=api_version)

    @staticmethod
    def _compose_url(*, provider_ref: str, suffix: str, api_version: str) -> str:
        # ``provider_ref`` is a full ARM id starting with ``/`` — the
        # ARM control plane is contacted at
        # ``https://management.azure.com`` unless the client has a
        # different ``base_url``. We hand a relative path off to
        # :class:`httpx.AsyncClient` so a mock transport can inspect
        # the URL without needing the host.
        base = provider_ref.rstrip("/") + suffix
        # Preserve any pre-existing query string on the caller side.
        separator = "&" if "?" in base else "?"
        return f"{base}{separator}api-version={api_version}"

    def _trim(self, text: str) -> str:
        cap = self._config.max_error_body_bytes
        raw = text.replace("\n", " ")
        if len(raw) <= cap:
            return raw
        return raw[:cap] + "…"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _infer_kind(experiment: DrExperiment) -> DrExperimentKind:
    """Derive the target substrate from the ARM id in ``provider_ref``.

    Chaos Studio ids contain ``/providers/Microsoft.Chaos/experiments/``;
    Site Recovery Recovery Plan ids contain
    ``/providers/Microsoft.RecoveryServices/vaults/.../replicationRecoveryPlans/``.
    Anything else defaults to ``CHAOS`` so an ambiguous input still gets
    a deterministic dispatch — the alternative (an exception) would
    surface as a runner failure that :class:`DrScheduler.run` cannot
    distinguish from an auth / transport error.
    """
    ref = experiment.provider_ref or ""
    if "/providers/Microsoft.RecoveryServices/" in ref:
        return DrExperimentKind.SITE_RECOVERY_TEST_FAILOVER
    return DrExperimentKind.CHAOS


def _extract_run_pointers(*, response: httpx.Response, provider_ref: str) -> tuple[str, str | None]:
    """Read ``run_id`` + LRO status URL from a ``start`` response.

    Azure LRO responses (HTTP 201/202) include an ``Azure-AsyncOperation``
    header pointing to a status endpoint. When the body also carries an
    ``id`` (Chaos Studio ``StartOperationResult``) we use it as the
    ``run_id``; otherwise we fall back to a deterministic composite
    based on the experiment's ARM id + response header, so a subsequent
    ``check`` can still recognize the run.
    """
    status_url = response.headers.get("Azure-AsyncOperation") or response.headers.get("Location")
    body_id: str | None = None
    if response.content:
        try:
            body = response.json()
        except ValueError:
            body = None
        if isinstance(body, dict):
            candidate = body.get("id") or body.get("name")
            if isinstance(candidate, str) and candidate:
                body_id = candidate

    if body_id is not None:
        return body_id, status_url
    if status_url is not None:
        return status_url, status_url
    # Synchronous 200 without a body id and without an LRO header. Use
    # the ARM id itself as the run identifier — the ``check`` fallback
    # queries the resource directly.
    return provider_ref, None


def _map_state(payload: object) -> DrRunStatus:
    """Reduce a Chaos / ASR LRO payload to a :class:`DrRunStatus`.

    Two shapes are supported:

    - Chaos Studio ``ExperimentExecutionDetails`` — ``status`` field.
    - Site Recovery LRO envelope — ``status`` field with the same
      enumeration; the resource-level GET uses
      ``properties.provisioningState`` instead.

    An unknown value maps to :class:`DrRunStatus.RUNNING` — the caller
    keeps polling; treating novelty as failure would over-rollback.
    """
    if not isinstance(payload, dict):
        return DrRunStatus.RUNNING
    state = payload.get("status")
    if not isinstance(state, str):
        properties = payload.get("properties")
        if isinstance(properties, dict):
            state = properties.get("provisioningState")
    if not isinstance(state, str):
        return DrRunStatus.RUNNING
    lowered = state.lower()
    if lowered in _SUCCEEDED_STATES:
        return DrRunStatus.SUCCEEDED
    if lowered in _FAILED_STATES:
        return DrRunStatus.FAILED
    if lowered in _STOPPED_STATES:
        return DrRunStatus.STOPPED
    return DrRunStatus.RUNNING


__all__ = [
    "AzureDrExperimentAdapter",
    "AzureDrExperimentAdapterConfig",
]
