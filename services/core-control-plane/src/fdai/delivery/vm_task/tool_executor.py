"""ToolExecutor bridge for the ``tool.run-python-on-vm`` ActionType."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from fdai.shared.contracts.models import Mode
from fdai.shared.providers.tool import (
    ToolCallOutcome,
    ToolCallReceipt,
    ToolCallRequest,
    ToolError,
    ToolExecutor,
    ToolPromotionError,
)
from fdai.shared.providers.vm_task import (
    PythonTaskArtifactStore,
    VmTaskRequest,
    VmTaskRunner,
    VmTaskStatus,
    VmTaskTargetResolver,
    validate_python_task_artifact_ref,
)

_ACTION_TYPE = "tool.run-python-on-vm"
_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class VmPythonToolExecutorConfig:
    poll_interval_seconds: float = 2.0
    max_wait_seconds: float = 86_460.0

    def __post_init__(self) -> None:
        if self.poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds MUST be positive")
        if self.max_wait_seconds <= 0:
            raise ValueError("max_wait_seconds MUST be positive")


class VmPythonToolExecutor(ToolExecutor):
    """Resolve an artifact and target, then plan or run it through VmTaskRunner."""

    def __init__(
        self,
        *,
        artifacts: PythonTaskArtifactStore,
        targets: VmTaskTargetResolver,
        runner: VmTaskRunner,
        config: VmPythonToolExecutorConfig | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._artifacts = artifacts
        self._targets = targets
        self._runner = runner
        self._config = config or VmPythonToolExecutorConfig()
        self._monotonic = monotonic
        self._sleep = sleep
        self._receipts: dict[str, ToolCallReceipt] = {}

    async def execute(self, request: ToolCallRequest) -> ToolCallReceipt:
        if request.action_type_name != _ACTION_TYPE:
            raise ToolError("unknown_tool", f"unsupported tool {request.action_type_name!r}")
        if request.mode is Mode.ENFORCE and "enforce" not in request.labels:
            raise ToolPromotionError("enforce VM task requires the explicit enforce label")
        prior = self._receipts.get(request.idempotency_key)
        if prior is not None:
            return ToolCallReceipt(
                outcome=ToolCallOutcome.ALREADY_APPLIED,
                receipt_ref=prior.receipt_ref,
                already_existed=True,
                detail=prior.detail,
            )
        try:
            artifact_ref = validate_python_task_artifact_ref(
                _argument(request, "artifact_ref", max_length=256)
            )
        except ValueError as exc:
            raise ToolError("arguments", str(exc)) from exc
        target_ref = _argument(request, "target_resource_ref", max_length=2_048)
        try:
            task = await self._artifacts.get(artifact_ref)
            target = await self._targets.resolve(target_ref)
        except LookupError as exc:
            raise ToolError("precondition", str(exc)) from exc
        vm_request = VmTaskRequest(
            idempotency_key=request.idempotency_key,
            task=task,
            target=target,
            dry_run=request.mode is Mode.SHADOW,
        )
        vm_receipt = await self._runner.run(vm_request)
        if request.mode is Mode.ENFORCE and not vm_receipt.status.terminal:
            vm_receipt = await self._wait_for_terminal(vm_receipt.run_ref)
        receipt = _tool_receipt(vm_receipt)
        if receipt.outcome in {ToolCallOutcome.SUCCEEDED, ToolCallOutcome.ALREADY_APPLIED}:
            self._receipts[request.idempotency_key] = receipt
        return receipt

    async def _wait_for_terminal(self, run_ref: str):  # type: ignore[no-untyped-def]
        deadline = self._monotonic() + self._config.max_wait_seconds
        try:
            while self._monotonic() < deadline:
                await self._sleep(self._config.poll_interval_seconds)
                try:
                    receipt = await self._runner.status(run_ref)
                except Exception:  # noqa: BLE001 - remote run fails closed
                    try:
                        return await self._runner.cancel(run_ref)
                    except Exception as cancel_exc:  # noqa: BLE001 - cancellation unconfirmed
                        raise ToolError(
                            "polling",
                            "VM task status failed and cancellation could not be confirmed",
                        ) from cancel_exc
                if receipt.status.terminal:
                    return receipt
        except asyncio.CancelledError:
            try:
                await asyncio.shield(self._runner.cancel(run_ref))
            except Exception:  # noqa: BLE001 - preserve caller cancellation
                _LOGGER.warning(
                    "vm_task_cancel_after_local_cancellation_failed",
                    exc_info=True,
                )
            raise
        return await self._runner.cancel(run_ref)


def _argument(request: ToolCallRequest, name: str, *, max_length: int) -> str:
    value = request.arguments.get(name)
    if not isinstance(value, str) or not value or len(value) > max_length:
        raise ToolError("arguments", f"{name} MUST be a bounded non-empty string")
    return value


def _tool_receipt(receipt) -> ToolCallReceipt:  # type: ignore[no-untyped-def]
    if receipt.status in {VmTaskStatus.PLANNED, VmTaskStatus.SUCCEEDED}:
        outcome = ToolCallOutcome.SUCCEEDED
        rollback_succeeded = None
    elif receipt.status is VmTaskStatus.CANCELLED:
        outcome = ToolCallOutcome.STOPPED
        rollback_succeeded = True
    else:
        outcome = ToolCallOutcome.FAILED
        rollback_succeeded = False
    return ToolCallReceipt(
        outcome=outcome,
        receipt_ref=receipt.run_ref,
        already_existed=receipt.already_existed,
        rollback_succeeded=rollback_succeeded,
        detail=receipt.detail,
    )


__all__ = ["VmPythonToolExecutor", "VmPythonToolExecutorConfig"]
