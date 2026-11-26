"""In-memory command runner for shadow plans and deterministic tests."""

from __future__ import annotations

import hashlib

from fdai.shared.providers.command_runner import (
    CommandPlan,
    CommandReceipt,
    CommandRunner,
    CommandStatus,
)


class RecordingCommandRunner(CommandRunner):
    """Record live plans, while keeping dry-run plans as real no-ops."""

    def __init__(self) -> None:
        self.calls: list[CommandPlan] = []
        self._receipts: dict[str, CommandReceipt] = {}

    async def execute(self, plan: CommandPlan) -> CommandReceipt:
        digest = hashlib.sha256(plan.idempotency_key.encode("utf-8")).hexdigest()[:24]
        if plan.dry_run:
            return CommandReceipt(
                status=CommandStatus.PLANNED,
                receipt_ref=f"command-plan:{plan.command_id}:{digest}",
            )
        prior = self._receipts.get(plan.idempotency_key)
        if prior is not None:
            return CommandReceipt(
                status=CommandStatus.ALREADY_APPLIED,
                receipt_ref=prior.receipt_ref,
                exit_code=prior.exit_code,
                already_existed=True,
            )
        self.calls.append(plan)
        receipt = CommandReceipt(
            status=CommandStatus.SUCCEEDED,
            receipt_ref=f"command:{plan.command_id}:{digest}",
            exit_code=0,
        )
        self._receipts[plan.idempotency_key] = receipt
        return receipt


__all__ = ["RecordingCommandRunner"]
