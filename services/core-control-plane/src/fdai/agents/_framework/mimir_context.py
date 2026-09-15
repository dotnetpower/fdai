"""Mimir-owned context policy transitions and current-case review guards."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime
from typing import Any

from fdai_service_contracts.test_context import TestContextCommand

from fdai.agents._framework.bus import PantheonBus
from fdai.core.case_history import CaseHistoryMaterializer
from fdai.core.operational_context.test_context_commands import TestContextCommandHandler
from fdai.core.operational_learning.case_review import require_current_candidate_cases


class MimirContextMixin:
    """Keep context review distinct from rule promotion and execution authority."""

    bus: PantheonBus | None
    _clock: Callable[[], datetime]
    _test_context_commands: TestContextCommandHandler | None = None
    _case_history: CaseHistoryMaterializer | None = None

    def bind_case_history(self, materializer: CaseHistoryMaterializer) -> None:
        """Bind the current source reader for scoped operational learning reviews."""
        if self._case_history is not None:
            raise RuntimeError("Mimir case history is already bound")
        self._case_history = materializer

    async def _require_current_candidate_cases(self, candidate: dict[str, Any]) -> None:
        await require_current_candidate_cases(
            candidate, materializer=self._case_history, clock=self._clock
        )

    def bind_test_context_commands(self, handler: TestContextCommandHandler) -> None:
        """Bind reviewed context policy persistence without changing catalog authority."""
        if self._test_context_commands is not None:
            raise RuntimeError("Mimir context command handler is already bound")
        self._test_context_commands = handler

    async def _test_context_message(
        self, topic: str, payload: dict[str, Any], record_behavior: Callable[[str], None]
    ) -> bool:
        context_proposal = (
            topic == "object.event" and payload.get("event_type") == "test_context.command.v1"
        )
        context_review = topic == "object.approval" and payload.get("kind") == "test_context_review"
        if not (context_proposal or context_review):
            return False
        if payload.get("producer_principal") != ("Var" if context_review else "Huginn"):
            raise PermissionError("test context command has the wrong topic owner")
        command = payload.get("command") if context_review else payload.get("attributes")
        if not isinstance(command, dict):
            raise ValueError("test context command is malformed")
        typed_command = TestContextCommand.model_validate(command)
        if context_proposal and typed_command.request.operation != "propose":
            return True
        if self._test_context_commands is None or self.bus is None:
            raise RuntimeError("Mimir test context dependencies are unavailable")
        async with asyncio.timeout(5):
            result = await self._test_context_commands.transition(
                command, reviewed_by_var=context_review
            )
            await self.bus.publish("Mimir", "object.policy", result)
        record_behavior("test_context:revision_published")
        return True
