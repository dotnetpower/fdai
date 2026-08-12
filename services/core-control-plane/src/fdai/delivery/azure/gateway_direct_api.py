"""Governed DirectApiExecutor over the development operations Function App."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from fdai.shared.contracts.models import Mode
from fdai.shared.providers.direct_api import (
    DirectApiAuthenticationError,
    DirectApiError,
    DirectApiOutcome,
    DirectApiPermissionDeniedError,
    DirectApiPreconditionError,
    DirectApiPromotionError,
    DirectApiReceipt,
    DirectApiRequest,
)
from fdai.shared.providers.workload_identity import WorkloadIdentity

_MAX_RESPONSE_BYTES = 262_144
_ACTION_OPERATIONS = {
    "ops.start-vm": "azure.compute.vm.start",
    "ops.deallocate-vm": "azure.compute.vm.deallocate",
    "ops.scale-out": "azure.compute.vmss.scale",
    "ops.upsert-network-rule": "azure.network.nsg.rule.upsert",
    "ops.delete-network-rule": "azure.network.nsg.rule.delete",
}


@dataclass(frozen=True, slots=True)
class AzureGatewayDirectApiConfig:
    base_url: str
    audience: str
    timeout_seconds: float = 30.0
    poll_interval_seconds: float = 1.0
    max_poll_attempts: int = 30

    def __post_init__(self) -> None:
        parsed = urlparse(self.base_url)
        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("gateway direct-api base_url MUST be an HTTPS origin")
        if not self.audience or len(self.audience) > 256:
            raise ValueError("gateway direct-api audience MUST be bounded")
        if not 0.1 <= self.timeout_seconds <= 120:
            raise ValueError("gateway direct-api timeout_seconds MUST be in [0.1, 120]")
        if not 0 <= self.poll_interval_seconds <= 30:
            raise ValueError("gateway direct-api poll_interval_seconds MUST be in [0, 30]")
        if not 1 <= self.max_poll_attempts <= 120:
            raise ValueError("gateway direct-api max_poll_attempts MUST be in [1, 120]")


class AzureGatewayDirectApiExecutor:
    """Translate governed direct-API requests into registered gateway operations."""

    def __init__(
        self,
        *,
        config: AzureGatewayDirectApiConfig,
        identity: WorkloadIdentity,
        http_client: httpx.AsyncClient,
    ) -> None:
        self._config = config
        self._identity = identity
        self._http = http_client

    async def execute(self, request: DirectApiRequest) -> DirectApiReceipt:
        if request.mode is Mode.ENFORCE and "enforce" not in request.labels:
            raise DirectApiPromotionError(
                "enforce-mode gateway call requires an explicit enforce label"
            )
        operation_id = _ACTION_OPERATIONS.get(request.action_type_name)
        if operation_id is None:
            raise DirectApiPreconditionError(
                f"gateway has no registered operation for {request.action_type_name}"
            )
        arguments = _arguments(
            operation_id,
            request.arguments,
            resource_ref=request.resource_ref,
        )
        safety = _safety(request)
        plan = await self._invoke(
            "azure.operation.plan",
            {
                "operation_id": operation_id,
                "arguments": arguments,
                "safety": safety,
            },
        )
        plan_result = _result(plan, expected_operation="azure.operation.plan")
        receipt = plan_result.get("dry_run_receipt")
        if not isinstance(receipt, str) or not receipt:
            raise DirectApiError("invalid_response", "gateway plan omitted dry_run_receipt")
        if request.mode is Mode.SHADOW:
            return DirectApiReceipt(
                outcome=DirectApiOutcome.SUCCEEDED,
                receipt_ref=f"gateway-plan:{request.action_id}",
                detail="shadow plan verified; no mutation submitted",
            )

        mutation_safety = dict(safety)
        mutation_safety["dry_run_receipt"] = receipt
        response = await self._invoke(operation_id, {**arguments, "safety": mutation_safety})
        body = _validated_body(response, expected_operation=operation_id)
        status = body.get("status")
        if status == "succeeded":
            return _success_receipt(request)
        if status != "submitted":
            return DirectApiReceipt(
                outcome=DirectApiOutcome.FAILED,
                receipt_ref=f"gateway:{request.idempotency_key}",
                rollback_succeeded=False,
                detail="gateway mutation returned a non-terminal status",
            )
        return await self._poll_until_terminal(request)

    async def _poll_until_terminal(self, request: DirectApiRequest) -> DirectApiReceipt:
        for _attempt in range(self._config.max_poll_attempts):
            if self._config.poll_interval_seconds:
                await asyncio.sleep(self._config.poll_interval_seconds)
            response = await self._invoke(
                "azure.operation.status",
                {"idempotency_key": request.idempotency_key},
            )
            body = _validated_body(response, expected_operation="azure.operation.status")
            status = body.get("status")
            if status == "succeeded":
                return _success_receipt(request)
            if status == "failed":
                return DirectApiReceipt(
                    outcome=DirectApiOutcome.FAILED,
                    receipt_ref=f"gateway:{request.idempotency_key}",
                    rollback_succeeded=False,
                    detail="Azure long-running operation failed",
                )
            if status != "running":
                raise DirectApiError("invalid_response", "gateway status was not recognized")
        return DirectApiReceipt(
            outcome=DirectApiOutcome.FAILED,
            receipt_ref=f"gateway:{request.idempotency_key}",
            rollback_succeeded=False,
            detail="Azure long-running operation exceeded the polling budget",
        )

    async def _invoke(
        self,
        operation_id: str,
        payload: Mapping[str, object],
    ) -> Mapping[str, object]:
        try:
            token = await self._identity.get_token(self._config.audience)
        except Exception as exc:  # noqa: BLE001 - identity boundary is provider-owned
            raise DirectApiAuthenticationError(
                "operations gateway identity token acquisition failed"
            ) from exc
        try:
            async with self._http.stream(
                "POST",
                f"{self._config.base_url.rstrip('/')}/api/v1/operations/{operation_id}",
                headers={"Authorization": f"Bearer {token.token}"},
                json=payload,
                timeout=self._config.timeout_seconds,
            ) as response:
                status_code = response.status_code
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    content.extend(chunk)
                    if len(content) > _MAX_RESPONSE_BYTES:
                        raise DirectApiError(
                            "invalid_response",
                            "operations gateway response was too large",
                        )
        except httpx.HTTPError as exc:
            raise DirectApiError("transport", "operations gateway request failed") from exc
        if status_code == 401:
            raise DirectApiAuthenticationError("operations gateway rejected authentication")
        if status_code == 403:
            raise DirectApiPermissionDeniedError("operations gateway denied the executor")
        try:
            body = json.loads(content)
        except (ValueError, json.JSONDecodeError) as exc:
            raise DirectApiError(
                "invalid_response", "operations gateway response was not JSON"
            ) from exc
        if not isinstance(body, Mapping):
            raise DirectApiError(
                "invalid_response", "operations gateway response was not an object"
            )
        if status_code == 409:
            raise DirectApiPreconditionError("operations gateway precondition failed")
        if status_code >= 400:
            raise DirectApiError(
                "gateway",
                f"operations gateway returned HTTP {status_code}",
            )
        return body


def _arguments(
    operation_id: str,
    raw: Mapping[str, object],
    *,
    resource_ref: str,
) -> dict[str, object]:
    required: tuple[str, ...]
    if operation_id == "azure.compute.vmss.scale":
        return _vmss_scale_arguments(raw, resource_ref=resource_ref)
    if operation_id.startswith("azure.compute.vm."):
        required = ("resource_group", "vm_name")
    elif operation_id == "azure.network.nsg.rule.delete":
        required = ("resource_group", "nsg_name", "rule_name")
    else:
        required = ("resource_group", "nsg_name", "rule_name", "rule")
    arguments: dict[str, object] = {}
    for key in required:
        if key not in raw:
            raise DirectApiPreconditionError(f"gateway argument {key} is required")
        arguments[key] = raw[key]
    return arguments


def _vmss_scale_arguments(
    raw: Mapping[str, object],
    *,
    resource_ref: str,
) -> dict[str, object]:
    target_ref = raw.get("target_resource_ref")
    replica_count = raw.get("replica_count")
    if not isinstance(target_ref, str) or target_ref != resource_ref:
        raise DirectApiPreconditionError(
            "scale-out target_resource_ref must match the action resource"
        )
    parts = target_ref.strip("/").split("/")
    if (
        len(parts) != 8
        or parts[0].casefold() != "subscriptions"
        or parts[2].casefold() != "resourcegroups"
        or parts[4].casefold() != "providers"
        or parts[5].casefold() != "microsoft.compute"
        or parts[6].casefold() != "virtualmachinescalesets"
        or not parts[1]
        or not parts[3]
        or not parts[7]
    ):
        raise DirectApiPreconditionError(
            "scale-out target_resource_ref must identify one Azure VM Scale Set"
        )
    if (
        not isinstance(replica_count, int)
        or isinstance(replica_count, bool)
        or not 1 <= replica_count <= 1000
    ):
        raise DirectApiPreconditionError("scale-out replica_count must be in [1, 1000]")
    return {
        "resource_group": parts[3],
        "vmss_name": parts[7],
        "target_resource_ref": target_ref,
        "replica_count": replica_count,
    }


def _safety(request: DirectApiRequest) -> dict[str, object]:
    required = ("audit_ref", "stop_condition", "rollback_ref", "max_resources")
    missing = [key for key in required if not request.metadata.get(key)]
    if missing:
        raise DirectApiPreconditionError(
            f"gateway safety metadata is missing: {', '.join(missing)}"
        )
    try:
        max_resources = int(request.metadata["max_resources"])
    except ValueError as exc:
        raise DirectApiPreconditionError("gateway max_resources must be an integer") from exc
    return {
        "idempotency_key": request.idempotency_key,
        "audit_ref": request.metadata["audit_ref"],
        "stop_condition": request.metadata["stop_condition"],
        "rollback_ref": request.metadata["rollback_ref"],
        "max_resources": max_resources,
    }


def _validated_body(
    body: Mapping[str, object],
    *,
    expected_operation: str,
) -> Mapping[str, object]:
    if body.get("operation_id") != expected_operation:
        raise DirectApiError("invalid_response", "gateway response operation did not match")
    if not isinstance(body.get("status"), str):
        raise DirectApiError("invalid_response", "gateway response status was missing")
    return body


def _result(body: Mapping[str, object], *, expected_operation: str) -> Mapping[str, object]:
    validated = _validated_body(body, expected_operation=expected_operation)
    result = validated.get("result")
    if validated.get("status") != "succeeded" or not isinstance(result, Mapping):
        raise DirectApiError("invalid_response", "gateway plan did not succeed")
    return result


def _success_receipt(request: DirectApiRequest) -> DirectApiReceipt:
    return DirectApiReceipt(
        outcome=DirectApiOutcome.SUCCEEDED,
        receipt_ref=f"gateway:{request.idempotency_key}",
        detail="gateway mutation completed",
    )


__all__ = ["AzureGatewayDirectApiConfig", "AzureGatewayDirectApiExecutor"]
