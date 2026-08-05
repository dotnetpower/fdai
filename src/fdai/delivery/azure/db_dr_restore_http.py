"""HTTP, authentication, and ARM URL helpers for database DR restore."""

from __future__ import annotations

from typing import Protocol

import httpx

from fdai.shared.providers.db_dr import DbDrError
from fdai.shared.providers.workload_identity import WorkloadIdentity

from .arm_url_policy import ArmUrlPolicy, ArmUrlPolicyError

DB_DR_PHASE = "restore"
PG_PROVIDER_SEGMENT = "/providers/Microsoft.DBforPostgreSQL/flexibleServers/"


class _DbDrHttpConfig(Protocol):
    @property
    def audience(self) -> str: ...

    @property
    def api_version(self) -> str: ...

    @property
    def timeout_seconds(self) -> float: ...

    @property
    def max_error_body_bytes(self) -> int: ...


class AzureDbDrRestoreHttpMixin[ConfigT: _DbDrHttpConfig]:
    """Provide bounded Azure REST calls and server-owned restore URLs."""

    _url_policy: ArmUrlPolicy
    _identity: WorkloadIdentity
    _http: httpx.AsyncClient
    _config: ConfigT

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
                phase=DB_DR_PHASE,
            ) from exc

    async def _put(
        self,
        *,
        url: str,
        headers: dict[str, str],
        json_body: dict[str, object],
        experiment_id: str,
    ) -> httpx.Response:
        try:
            return await self._http.put(
                url,
                headers=headers,
                json=json_body,
                timeout=self._config.timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise DbDrError(
                f"target resource group create failed: {exc.__class__.__name__}",
                experiment_id=experiment_id,
                phase=DB_DR_PHASE,
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
                phase=DB_DR_PHASE,
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

    def _restore_submit_url(
        self,
        *,
        subscription_id: str,
        target_rg: str,
        target_name: str,
    ) -> str:
        path = (
            f"/subscriptions/{subscription_id}/resourceGroups/{target_rg}"
            f"{PG_PROVIDER_SEGMENT}{target_name}/restore"
        )
        return f"{path}?api-version={self._config.api_version}"

    def _resource_url(
        self,
        *,
        subscription_id: str,
        target_rg: str,
        target_name: str,
    ) -> str:
        path = (
            f"/subscriptions/{subscription_id}/resourceGroups/{target_rg}"
            f"{PG_PROVIDER_SEGMENT}{target_name}"
        )
        return f"{path}?api-version={self._config.api_version}"

    def _resource_group_url(self, *, subscription_id: str, resource_group: str) -> str:
        return (
            f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}"
            f"?api-version=2021-04-01"
        )

    def _trim(self, text: str) -> str:
        cap = self._config.max_error_body_bytes
        raw = text.replace("\n", " ")
        if len(raw) <= cap:
            return raw
        return raw[:cap] + "..."

    def _validate_lro_url(self, value: str, *, experiment_id: str) -> str:
        try:
            return self._url_policy.validate_lro_url(value)
        except ArmUrlPolicyError as exc:
            raise DbDrError(
                str(exc),
                experiment_id=experiment_id,
                phase=DB_DR_PHASE,
            ) from exc


__all__ = ["AzureDbDrRestoreHttpMixin", "DB_DR_PHASE", "PG_PROVIDER_SEGMENT"]
