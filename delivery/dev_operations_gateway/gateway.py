"""Bounded development operations gateway for private Azure resources."""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from collections.abc import Awaitable, Callable, Mapping
from typing import TYPE_CHECKING

import httpx

from delivery.dev_operations_gateway.gateway_arm import ArmClient, _ArmSubmission
from delivery.dev_operations_gateway.gateway_contracts import (
    _EXECUTOR_VERTICAL_ORDER,
    _MUTATION_OPERATIONS,
    _OPERATION_VERTICALS,
    GatewayConfig,
    GatewayError,
    GatewayPrincipal,
    ManagedIdentityTokenProvider,
    PrivateProbe,
    TokenProvider,
)
from delivery.dev_operations_gateway.gateway_resources import (
    GatewayResourceOperations,
    _bounded,
)

if TYPE_CHECKING:
    from delivery.dev_operations_gateway.idempotency import (
        IdempotencyError,
        IdempotencyLedger,
    )
elif __package__:
    from .idempotency import IdempotencyError, IdempotencyLedger
else:
    from idempotency import IdempotencyError, IdempotencyLedger


class OperationsGateway:
    def __init__(
        self,
        *,
        config: GatewayConfig,
        reader_token_provider: TokenProvider,
        executor_token_provider: TokenProvider,
        http_client: httpx.AsyncClient,
        idempotency_ledger: IdempotencyLedger | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._config = config
        self._reader_tokens = reader_token_provider
        self._executor_tokens = executor_token_provider
        self._http = http_client
        self._idempotency = idempotency_ledger
        self._arm_client = ArmClient(
            config=config,
            reader_token_provider=reader_token_provider,
            executor_token_provider=executor_token_provider,
            http_client=http_client,
            sleep=sleep,
        )
        self._resources = GatewayResourceOperations(
            config=config,
            reader_token_provider=reader_token_provider,
            http_client=http_client,
            arm_client=self._arm_client,
        )

    async def invoke(
        self,
        operation_id: str,
        payload: Mapping[str, object],
        principal: GatewayPrincipal,
    ) -> Mapping[str, object]:
        self._authorize_read(principal)
        if operation_id == "azure.operation.plan":
            if not self._config.mutations_enabled:
                raise GatewayError(404, "operation_not_found", "operation is not registered")
            return await self._operation_plan(payload, principal)
        if operation_id == "azure.operation.status":
            if not self._config.mutations_enabled:
                raise GatewayError(404, "operation_not_found", "operation is not registered")
            return await self._operation_status(payload, principal)
        handlers = {
            "azure.network.nsg.read": self._resources._read_nsg,
            "azure.network.peering.read": self._resources._read_peerings,
            "azure.private.http.probe": self._resources._probe_private_endpoint,
            "azure.network.nsg.rule.upsert": self._resources._upsert_nsg_rule,
            "azure.network.nsg.rule.delete": self._resources._delete_nsg_rule,
            "azure.compute.vm.start": self._resources._start_vm,
            "azure.compute.vm.deallocate": self._resources._deallocate_vm,
            "azure.compute.vmss.scale": self._resources._scale_vmss,
            "azure.resource.tags.read": self._resources._read_resource_tag,
            "azure.resource.tags.merge": self._resources._merge_resource_tag,
        }
        handler = handlers.get(operation_id)
        if handler is None:
            raise GatewayError(404, "operation_not_found", "operation is not registered")
        mutation = operation_id in _MUTATION_OPERATIONS
        if mutation and not self._config.mutations_enabled:
            raise GatewayError(404, "operation_not_found", "operation is not registered")
        if not mutation:
            result = await handler(payload)
            return {"operation_id": operation_id, "status": "succeeded", "result": result}

        idempotency_key, dry_run_receipt = self._authorize_mutation(
            operation_id,
            principal,
            payload,
        )
        if self._idempotency is None:
            raise GatewayError(
                503,
                "idempotency_unavailable",
                "mutation idempotency ledger is unavailable",
            )
        request_digest = _request_digest(operation_id, payload)
        try:
            replay = await self._idempotency.begin(idempotency_key, request_digest)
        except IdempotencyError as exc:
            raise GatewayError(exc.status_code, exc.code, str(exc)) from exc
        if replay is not None:
            return _public_response(replay)
        try:
            await self._idempotency.consume_dry_run(
                dry_run_receipt,
                _mutation_digest(operation_id, payload),
            )
        except IdempotencyError as exc:
            try:
                await self._idempotency.abort(idempotency_key, request_digest)
            except IdempotencyError as abort_error:
                exc.add_note(f"idempotency claim cleanup also failed: {abort_error.code}")
            raise GatewayError(exc.status_code, exc.code, str(exc)) from exc
        resource_key = self._resources._mutation_resource_key(operation_id, payload)
        try:
            lease_id = await self._idempotency.acquire_resource(resource_key)
        except IdempotencyError as exc:
            try:
                await self._idempotency.abort(idempotency_key, request_digest)
            except IdempotencyError as abort_error:
                exc.add_note(f"idempotency claim cleanup also failed: {abort_error.code}")
            raise GatewayError(exc.status_code, exc.code, str(exc)) from exc
        try:
            lease_transferred = False
            try:
                result = await handler(payload)
            except Exception as exc:
                try:
                    await self._idempotency.abort(idempotency_key, request_digest)
                except IdempotencyError as abort_error:
                    exc.add_note(f"idempotency claim cleanup also failed: {abort_error.code}")
                raise
            if isinstance(result, _ArmSubmission):
                response: dict[str, object] = {
                    "operation_id": operation_id,
                    "status": "submitted",
                    "result": {
                        "accepted": True,
                        "status": "submitted",
                        "_provider_operation_url": result.status_url,
                        "_resource_key": resource_key,
                        "_lease_id": lease_id,
                    },
                }
                lease_transferred = True
            else:
                response = {
                    "operation_id": operation_id,
                    "status": "succeeded",
                    "result": result,
                }
            await self._idempotency.complete(idempotency_key, request_digest, response)
        except IdempotencyError as exc:
            raise GatewayError(exc.status_code, exc.code, str(exc)) from exc
        finally:
            active_error = sys.exception()
            if not lease_transferred:
                try:
                    await self._idempotency.release_resource(resource_key, lease_id)
                except IdempotencyError as release_error:
                    if active_error is not None:
                        active_error.add_note(
                            f"resource lease cleanup also failed: {release_error.code}"
                        )
                    else:
                        raise GatewayError(
                            release_error.status_code,
                            release_error.code,
                            str(release_error),
                        ) from release_error
        return _public_response(response)

    async def _operation_status(
        self,
        payload: Mapping[str, object],
        principal: GatewayPrincipal,
    ) -> Mapping[str, object]:
        if self._idempotency is None:
            raise GatewayError(503, "idempotency_unavailable", "operation ledger is unavailable")
        target_operation = _bounded(payload, "operation_id", maximum=128)
        self._authorize_executor(principal, target_operation)
        idempotency_key = _bounded(payload, "idempotency_key", maximum=512)
        try:
            record = await self._idempotency.lookup(idempotency_key)
        except IdempotencyError as exc:
            raise GatewayError(exc.status_code, exc.code, str(exc)) from exc
        recorded_operation = record.get("operation_id")
        if not isinstance(recorded_operation, str):
            raise GatewayError(503, "idempotency_unavailable", "operation identity is missing")
        if recorded_operation != target_operation:
            raise GatewayError(
                409,
                "operation_identity_conflict",
                "operation status identity does not match the durable record",
            )
        result = record.get("result")
        if record.get("status") in {"succeeded", "failed"} and isinstance(result, Mapping):
            provider_status = result.get("provider_status")
            return {
                "operation_id": "azure.operation.status",
                "status": record["status"],
                "result": {
                    "provider_status": provider_status,
                    "status": record["status"],
                },
            }
        status_url = result.get("_provider_operation_url") if isinstance(result, Mapping) else None
        resource_key = result.get("_resource_key") if isinstance(result, Mapping) else None
        lease_id = result.get("_lease_id") if isinstance(result, Mapping) else None
        if not isinstance(status_url, str):
            raise GatewayError(409, "operation_not_async", "operation has no asynchronous status")
        if not isinstance(resource_key, str) or not isinstance(lease_id, str):
            raise GatewayError(503, "idempotency_unavailable", "operation lease state is missing")
        try:
            await self._idempotency.renew_resource(resource_key, lease_id)
        except IdempotencyError as exc:
            raise GatewayError(exc.status_code, exc.code, str(exc)) from exc
        provider_status = await self._arm_client.poll_status(status_url)
        normalized = _normalize_provider_status(provider_status)
        if normalized in {"succeeded", "failed"}:
            terminal_response = {
                "operation_id": record.get("operation_id", "azure.operation.status"),
                "status": normalized,
                "result": {"provider_status": provider_status, "status": normalized},
            }
            try:
                await self._idempotency.update_response(idempotency_key, terminal_response)
                await self._idempotency.release_resource(resource_key, lease_id)
            except IdempotencyError as exc:
                raise GatewayError(exc.status_code, exc.code, str(exc)) from exc
        return {
            "operation_id": "azure.operation.status",
            "status": normalized,
            "result": {"provider_status": provider_status, "status": normalized},
        }

    async def _operation_plan(
        self,
        payload: Mapping[str, object],
        principal: GatewayPrincipal,
    ) -> Mapping[str, object]:
        if self._idempotency is None:
            raise GatewayError(503, "idempotency_unavailable", "operation ledger is unavailable")
        target_operation = _bounded(payload, "operation_id", maximum=128)
        self._authorize_executor(principal, target_operation)
        arguments = payload.get("arguments")
        if not isinstance(arguments, Mapping):
            raise GatewayError(400, "payload_invalid", "plan arguments MUST be an object")
        safety = payload.get("safety")
        if not isinstance(safety, Mapping):
            raise GatewayError(400, "safety_missing", "plan safety envelope is required")
        if target_operation not in _MUTATION_OPERATIONS:
            raise GatewayError(404, "operation_not_found", "mutation operation is not registered")
        self._resources._validate_mutation_payload(target_operation, arguments)
        self._validate_safety(safety, require_dry_run_receipt=False)
        await self._resources._preflight_mutation(target_operation, arguments)
        try:
            receipt = await self._idempotency.issue_dry_run(
                _mutation_digest(target_operation, {**arguments, "safety": safety})
            )
        except IdempotencyError as exc:
            raise GatewayError(exc.status_code, exc.code, str(exc)) from exc
        return {
            "operation_id": "azure.operation.plan",
            "status": "succeeded",
            "result": {
                "target_operation": target_operation,
                "status": "planned",
                "dry_run_receipt": receipt,
                "expires_in_seconds": 300,
            },
        }

    def _authorize_read(self, principal: GatewayPrincipal) -> None:
        if (
            self._config.contributor_group_id not in principal.groups
            and not principal.roles.intersection({"Contributor", "Approver", "Owner"})
            and principal.object_id not in self._config.executor_principal_ids
        ):
            raise GatewayError(403, "forbidden", "Contributor access is required")

    def _authorize_mutation(
        self,
        operation_id: str,
        principal: GatewayPrincipal,
        payload: Mapping[str, object],
    ) -> tuple[str, str]:
        self._authorize_executor(principal, operation_id)
        safety = payload.get("safety")
        if not isinstance(safety, Mapping):
            raise GatewayError(400, "safety_missing", "mutation safety envelope is required")
        self._validate_safety(safety, require_dry_run_receipt=True)
        return str(safety["idempotency_key"]), str(safety["dry_run_receipt"])

    def _validate_safety(
        self,
        safety: Mapping[str, object],
        *,
        require_dry_run_receipt: bool,
    ) -> None:
        if safety.get("max_resources") != 1:
            raise GatewayError(400, "blast_radius_invalid", "max_resources MUST equal 1")
        required_fields = [
            "idempotency_key",
            "audit_ref",
            "stop_condition",
            "rollback_ref",
        ]
        if require_dry_run_receipt:
            required_fields.append("dry_run_receipt")
        for field in required_fields:
            value = safety.get(field)
            if not isinstance(value, str) or not value.strip() or len(value) > 512:
                raise GatewayError(400, "safety_invalid", f"safety.{field} MUST be bounded")

    def _authorize_executor(
        self,
        principal: GatewayPrincipal,
        operation_id: str,
    ) -> None:
        vertical = _OPERATION_VERTICALS.get(operation_id)
        if vertical is None:
            raise GatewayError(404, "operation_not_found", "mutation operation is not registered")
        expected_index = _EXECUTOR_VERTICAL_ORDER.index(vertical)
        if principal.object_id != self._config.executor_principal_ids[expected_index]:
            raise GatewayError(
                403,
                "executor_vertical_denied",
                "Thor executor identity is not authorized for this operation vertical",
            )


def _request_digest(operation_id: str, payload: Mapping[str, object]) -> str:
    try:
        encoded = json.dumps(
            {"operation_id": operation_id, "payload": payload},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise GatewayError(400, "payload_invalid", "request body MUST contain JSON values") from exc
    return hashlib.sha256(encoded).hexdigest()


def _mutation_digest(operation_id: str, payload: Mapping[str, object]) -> str:
    bound_payload = dict(payload)
    safety = payload.get("safety")
    if isinstance(safety, Mapping):
        bound_payload["safety"] = {
            key: value for key, value in safety.items() if key != "dry_run_receipt"
        }
    return _request_digest(operation_id, bound_payload)


def _public_response(response: Mapping[str, object]) -> Mapping[str, object]:
    result = response.get("result")
    if not isinstance(result, Mapping) or not any(str(key).startswith("_") for key in result):
        return dict(response)
    public_result = dict(result)
    for key in tuple(public_result):
        if str(key).startswith("_"):
            public_result.pop(key, None)
    public_response = dict(response)
    public_response["result"] = public_result
    return public_response


def _normalize_provider_status(status: str) -> str:
    normalized = status.casefold()
    if normalized in {"succeeded", "success", "completed"}:
        return "succeeded"
    if normalized in {"failed", "canceled", "cancelled"}:
        return "failed"
    return "running"


__all__ = [
    "GatewayConfig",
    "GatewayError",
    "GatewayPrincipal",
    "ManagedIdentityTokenProvider",
    "OperationsGateway",
    "PrivateProbe",
]
