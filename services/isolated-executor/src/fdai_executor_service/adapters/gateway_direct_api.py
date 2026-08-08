"""Governed direct-API adapter for the Executor operations gateway."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx
from fdai_service_contracts.executor import (
    DirectApiAuthenticationError,
    DirectApiError,
    DirectApiOutcome,
    DirectApiPermissionDeniedError,
    DirectApiPreconditionError,
    DirectApiPromotionError,
    DirectApiReceipt,
    DirectApiRequest,
    Mode,
    WorkloadIdentity,
)

_MAX_RESPONSE_BYTES = 262_144
_ACTION_OPERATIONS = {
    "ops.start-vm": "azure.compute.vm.start",
    "ops.deallocate-vm": "azure.compute.vm.deallocate",
    "ops.upsert-network-rule": "azure.network.nsg.rule.upsert",
    "ops.delete-network-rule": "azure.network.nsg.rule.delete",
}
_ACTION_IDENTITY_REFS = {
    "ops.start-vm": "identity/resilience",
    "ops.deallocate-vm": "identity/finops",
    "ops.upsert-network-rule": "identity/change",
    "ops.delete-network-rule": "identity/change",
}
_EXECUTOR_IDENTITY_REFS = frozenset({"identity/change", "identity/resilience", "identity/finops"})


@dataclass(frozen=True, slots=True)
class AzureGatewayDirectApiConfig:
    """Bounded HTTPS and polling settings for the operations gateway."""

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
    """Plan then dispatch allowlisted operations using the Executor identity."""

    def __init__(
        self,
        *,
        config: AzureGatewayDirectApiConfig,
        identities: Mapping[str, WorkloadIdentity],
        http_client: httpx.AsyncClient,
    ) -> None:
        unknown_refs = set(identities) - _EXECUTOR_IDENTITY_REFS
        if not identities or unknown_refs:
            raise ValueError("gateway executor identities MUST use registered identity refs")
        self._config = config
        self._identities = dict(identities)
        self._http = http_client

    async def execute(self, request: DirectApiRequest) -> DirectApiReceipt:
        """Validate promotion and safety metadata before gateway dispatch."""

        identity, operation_id, arguments, safety = self._request_context(request)
        if request.mode is Mode.ENFORCE:
            existing = await self._existing_operation_receipt(request, identity=identity)
            if existing is not None:
                return existing
        plan = await self._invoke(
            "azure.operation.plan",
            {"operation_id": operation_id, "arguments": arguments, "safety": safety},
            identity=identity,
        )
        plan_result = _result(plan, expected_operation="azure.operation.plan")
        dry_run_receipt = plan_result.get("dry_run_receipt")
        if not isinstance(dry_run_receipt, str) or not dry_run_receipt:
            raise DirectApiError("invalid_response", "gateway plan omitted dry_run_receipt")
        if request.mode is Mode.SHADOW:
            return DirectApiReceipt(
                outcome=DirectApiOutcome.SUCCEEDED,
                receipt_ref=f"gateway-plan:{request.action_id}",
                detail="shadow plan verified; no mutation submitted",
            )

        mutation_safety = dict(safety)
        mutation_safety["dry_run_receipt"] = dry_run_receipt
        response = await self._invoke(
            operation_id,
            {**arguments, "safety": mutation_safety},
            identity=identity,
        )
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
        return await self._poll_until_terminal(request, identity=identity)

    async def operation_status(
        self,
        request: DirectApiRequest,
    ) -> DirectApiReceipt | None:
        """Return durable gateway status without planning or dispatching a mutation."""

        identity, _operation_id, _arguments_value, _safety_value = self._request_context(request)
        if request.mode is not Mode.ENFORCE:
            return None
        return await self._existing_operation_receipt(request, identity=identity)

    def _request_context(
        self,
        request: DirectApiRequest,
    ) -> tuple[WorkloadIdentity, str, dict[str, object], dict[str, object]]:
        if request.mode is Mode.ENFORCE and "enforce" not in request.labels:
            raise DirectApiPromotionError(
                "enforce-mode gateway call requires an explicit enforce label"
            )
        identity_ref = request.metadata.get("executor_identity_ref")
        identity = self._identities.get(identity_ref or "")
        if identity is None:
            raise DirectApiPreconditionError(
                "gateway request requires a registered executor_identity_ref"
            )
        required_identity_ref = _ACTION_IDENTITY_REFS.get(request.action_type_name)
        if required_identity_ref is not None and identity_ref != required_identity_ref:
            raise DirectApiPreconditionError(
                f"{request.action_type_name} requires its registered vertical identity"
            )
        operation_id = _ACTION_OPERATIONS.get(request.action_type_name)
        if operation_id is None:
            raise DirectApiPreconditionError(
                f"gateway has no registered operation for {request.action_type_name}"
            )
        arguments = _arguments(operation_id, request.arguments)
        safety = _safety(request)
        return identity, operation_id, arguments, safety

    async def _existing_operation_receipt(
        self,
        request: DirectApiRequest,
        *,
        identity: WorkloadIdentity,
    ) -> DirectApiReceipt | None:
        operation_id = _ACTION_OPERATIONS.get(request.action_type_name)
        if operation_id is None:
            raise DirectApiPreconditionError(
                f"gateway has no registered operation for {request.action_type_name}"
            )
        response = await self._invoke(
            "azure.operation.status",
            {
                "idempotency_key": request.idempotency_key,
                "operation_id": operation_id,
            },
            identity=identity,
            not_found_code="idempotency_not_found",
        )
        body = _validated_body(response, expected_operation="azure.operation.status")
        status = body.get("status")
        if status == "not_found":
            return None
        if status == "succeeded":
            return _success_receipt(request, already_applied=True)
        if status == "running":
            return await self._poll_until_terminal(
                request,
                identity=identity,
                already_applied=True,
            )
        if status == "failed":
            return DirectApiReceipt(
                outcome=DirectApiOutcome.FAILED,
                receipt_ref=f"gateway:{request.idempotency_key}",
                rollback_succeeded=False,
                detail="previous Azure long-running operation failed",
            )
        raise DirectApiError("invalid_response", "gateway status was not recognized")

    async def _poll_until_terminal(
        self,
        request: DirectApiRequest,
        *,
        identity: WorkloadIdentity,
        already_applied: bool = False,
    ) -> DirectApiReceipt:
        for _attempt in range(self._config.max_poll_attempts):
            if self._config.poll_interval_seconds:
                await asyncio.sleep(self._config.poll_interval_seconds)
            response = await self._invoke(
                "azure.operation.status",
                {
                    "idempotency_key": request.idempotency_key,
                    "operation_id": _ACTION_OPERATIONS[request.action_type_name],
                },
                identity=identity,
            )
            body = _validated_body(response, expected_operation="azure.operation.status")
            status = body.get("status")
            if status == "succeeded":
                return _success_receipt(request, already_applied=already_applied)
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
        *,
        identity: WorkloadIdentity,
        not_found_code: str | None = None,
    ) -> Mapping[str, object]:
        try:
            token = await identity.get_token(self._config.audience)
        except Exception as exc:  # noqa: BLE001 - identity provider boundary
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
        if status_code == 404 and not_found_code is not None and body.get("code") == not_found_code:
            return {"operation_id": operation_id, "status": "not_found"}
        if status_code == 409:
            raise DirectApiPreconditionError("operations gateway precondition failed")
        if status_code >= 400:
            raise DirectApiError("gateway", f"operations gateway returned HTTP {status_code}")
        return body


def _arguments(operation_id: str, raw: Mapping[str, object]) -> dict[str, object]:
    required: tuple[str, ...]
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


def _success_receipt(
    request: DirectApiRequest,
    *,
    already_applied: bool = False,
) -> DirectApiReceipt:
    return DirectApiReceipt(
        outcome=(
            DirectApiOutcome.ALREADY_APPLIED if already_applied else DirectApiOutcome.SUCCEEDED
        ),
        receipt_ref=f"gateway:{request.idempotency_key}",
        detail=(
            "durable gateway status confirms mutation already applied"
            if already_applied
            else "gateway mutation completed"
        ),
    )


__all__ = ["AzureGatewayDirectApiConfig", "AzureGatewayDirectApiExecutor"]
