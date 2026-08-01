"""Allowlisted Microsoft Graph human role-group membership provisioner."""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from typing import Final
from urllib.parse import urlparse

import httpx

from fdai.shared.providers.human_access import (
    HumanAccessOperation,
    HumanAccessOutcome,
    HumanAccessPlan,
    HumanAccessReceipt,
)
from fdai.shared.providers.workload_identity import WorkloadIdentity

_GRAPH_SCOPE: Final[str] = "https://graph.microsoft.com/.default"
_DEFAULT_BASE_URL: Final[str] = "https://graph.microsoft.com/v1.0"
_RETRYABLE: Final[frozenset[int]] = frozenset({429, 502, 503, 504})


@dataclass(frozen=True, slots=True)
class EntraHumanAccessProvisioner:
    client: httpx.AsyncClient
    identity: WorkloadIdentity
    allowed_group_ids: frozenset[str]
    base_url: str = _DEFAULT_BASE_URL
    max_attempts: int = 3
    verification_attempts: int = 3
    verification_delay_seconds: float = 0.25

    def __post_init__(self) -> None:
        parsed = urlparse(self.base_url)
        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or parsed.username
            or parsed.password
            or parsed.path.rstrip("/") != "/v1.0"
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("human access Graph base_url MUST be an HTTPS v1.0 URL")
        if not self.allowed_group_ids or any(not item.strip() for item in self.allowed_group_ids):
            raise ValueError("allowed_group_ids MUST contain non-empty group ids")
        if self.max_attempts < 1 or self.max_attempts > 5:
            raise ValueError("max_attempts MUST be between 1 and 5")
        if self.verification_attempts < 1 or self.verification_attempts > 10:
            raise ValueError("verification_attempts MUST be between 1 and 10")
        if not 0 <= self.verification_delay_seconds <= 5:
            raise ValueError("verification_delay_seconds MUST be between 0 and 5")

    async def apply(self, plan: HumanAccessPlan) -> HumanAccessReceipt:
        self._require_allowed(plan.group_id)
        headers = await self._headers()
        await self._validate_target(plan, headers=headers)
        if await self._membership(plan, headers=headers) is plan.desired_membership:
            return _receipt(plan, HumanAccessOutcome.ALREADY_APPLIED)
        try:
            if plan.operation is HumanAccessOperation.GRANT:
                await self._request(
                    "POST",
                    f"/groups/{plan.group_id}/members/$ref",
                    headers=headers,
                    json_body={
                        "@odata.id": (
                            f"{self.base_url.rstrip('/')}/directoryObjects/{plan.subject_id}"
                        )
                    },
                )
            else:
                await self._request(
                    "DELETE",
                    f"/groups/{plan.group_id}/members/{plan.subject_id}/$ref",
                    headers=headers,
                )
        except httpx.HTTPStatusError as exc:
            race_status = 400 if plan.operation is HumanAccessOperation.GRANT else 404
            if (
                exc.response.status_code == race_status
                and await self._membership(plan, headers=headers) is plan.desired_membership
            ):
                return _receipt(plan, HumanAccessOutcome.ALREADY_APPLIED)
            raise
        return _receipt(plan, HumanAccessOutcome.APPLIED)

    async def verify(self, plan: HumanAccessPlan) -> bool:
        self._require_allowed(plan.group_id)
        headers = await self._headers()
        for attempt in range(self.verification_attempts):
            membership = await self._membership(plan, headers=headers)
            if membership is plan.desired_membership:
                return True
            if attempt + 1 < self.verification_attempts and self.verification_delay_seconds:
                await asyncio.sleep(self.verification_delay_seconds)
        return False

    async def rollback(self, plan: HumanAccessPlan) -> HumanAccessReceipt:
        inverse = HumanAccessPlan(
            case_id=plan.case_id,
            subject_id=plan.subject_id,
            group_id=plan.group_id,
            operation=(
                HumanAccessOperation.REVOKE
                if plan.desired_membership
                else HumanAccessOperation.GRANT
            ),
            idempotency_key=f"{plan.idempotency_key}:rollback",
        )
        receipt = await self.apply(inverse)
        return HumanAccessReceipt(
            HumanAccessOutcome.ROLLED_BACK,
            receipt.receipt_ref,
            receipt.digest,
        )

    def _require_allowed(self, group_id: str) -> None:
        if group_id not in self.allowed_group_ids:
            raise PermissionError("human access target group is not allowlisted")

    async def _headers(self) -> dict[str, str]:
        token = await self.identity.get_token(_GRAPH_SCOPE)
        return {"Authorization": f"Bearer {token.token}"}

    async def _validate_target(self, plan: HumanAccessPlan, *, headers: dict[str, str]) -> None:
        user = await self._request(
            "GET",
            f"/users/{plan.subject_id}?$select=id,accountEnabled",
            headers=headers,
        )
        user_payload = user.json()
        if user_payload.get("id") != plan.subject_id or (
            plan.operation is HumanAccessOperation.GRANT
            and user_payload.get("accountEnabled") is not True
        ):
            raise ValueError("human access target user is missing or inactive")
        group = await self._request(
            "GET",
            f"/groups/{plan.group_id}?$select=id,securityEnabled,groupTypes,isAssignableToRole",
            headers=headers,
        )
        group_payload = group.json()
        if (
            group_payload.get("id") != plan.group_id
            or group_payload.get("securityEnabled") is not True
        ):
            raise ValueError("human access target is not the expected security group")
        is_assignable_to_role = group_payload.get("isAssignableToRole")
        group_types = group_payload.get("groupTypes")
        if not isinstance(is_assignable_to_role, bool) or not isinstance(group_types, list):
            raise ValueError("human access target group classification is incomplete")
        if not all(isinstance(group_type, str) for group_type in group_types):
            raise ValueError("human access target group classification is invalid")
        if is_assignable_to_role:
            raise PermissionError("role-assignable groups are not supported for routine access")
        if "DynamicMembership" in group_types:
            raise PermissionError("dynamic groups are not supported for routine access")

    async def _membership(self, plan: HumanAccessPlan, *, headers: dict[str, str]) -> bool:
        try:
            response = await self._request(
                "GET",
                f"/groups/{plan.group_id}/members/{plan.subject_id}?$select=id",
                headers=headers,
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return False
            raise
        if response.json().get("id") != plan.subject_id:
            raise ValueError("human access membership response did not match the target subject")
        return True

    async def _request(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str],
        json_body: dict[str, str] | None = None,
    ) -> httpx.Response:
        url = f"{self.base_url.rstrip('/')}{path}"
        for attempt in range(self.max_attempts):
            response = await self.client.request(method, url, headers=headers, json=json_body)
            if response.status_code not in _RETRYABLE or attempt + 1 >= self.max_attempts:
                response.raise_for_status()
                return response
            await asyncio.sleep(_retry_seconds(response.headers.get("retry-after"), attempt))
        raise RuntimeError("Microsoft Graph human access request exhausted without a response")


def _retry_seconds(value: str | None, attempt: int) -> float:
    fallback = min(0.25 * pow(2.0, attempt), 2.0)
    if value is None:
        return fallback
    try:
        retry_after = float(value)
        return min(max(fallback, retry_after), 2.0)
    except ValueError:
        return fallback


def _receipt(plan: HumanAccessPlan, outcome: HumanAccessOutcome) -> HumanAccessReceipt:
    canonical = json.dumps(
        {
            "case_id": plan.case_id,
            "subject_id": plan.subject_id,
            "group_id": plan.group_id,
            "operation": plan.operation.value,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return HumanAccessReceipt(outcome, f"entra-group-membership:{digest}", digest)


__all__ = ["EntraHumanAccessProvisioner"]
