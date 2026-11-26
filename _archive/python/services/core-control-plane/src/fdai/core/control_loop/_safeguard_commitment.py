"""Workflow safeguard pre-bundle commitment before executor selection.

A workflow-driven action MUST be bound to its exact safeguard pre-bundle
commitment before any executor is selected, so a later dispatch cannot invent
a different commitment for the same step. An unavailable coordinator or a
failed binding blocks the dispatch instead of proceeding unbound.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping

from fdai.core.executor.safeguard_lifecycle_coordinator import SafeguardLifecycleCoordinator
from fdai.shared.contracts.models import Action, ExecutionPath, OntologyActionType

_LOGGER = logging.getLogger("fdai.core.control_loop.orchestrator")


class ControlLoopSafeguardCommitmentMixin:
    """Bind one workflow action to its safeguard pre-bundle commitment."""

    _action_types_by_name: Mapping[str, OntologyActionType]
    _safeguard_lifecycle_coordinator: SafeguardLifecycleCoordinator | None

    async def _prepare_workflow_safeguard_commitment(
        self,
        *,
        action: Action,
        correlation_id: str,
    ) -> str | None:
        """Persist the exact workflow commitment before selecting an executor."""

        if action.workflow_action is None:
            return None
        coordinator = self._safeguard_lifecycle_coordinator
        if coordinator is None:
            return "workflow safeguard pre-bundle coordinator is unavailable"
        action_type = self._action_types_by_name.get(action.action_type)
        execution_path = (
            action_type.execution_path
            if action_type is not None and action_type.execution_path is not None
            else ExecutionPath.PR_NATIVE
        )
        try:
            await coordinator.prepare_pre_bundle_commitment(
                action=action,
                execution_path=execution_path,
                correlation_id=correlation_id,
            )
        except Exception as exc:  # noqa: BLE001 - missing commitment blocks dispatch
            _LOGGER.warning(
                "workflow_pre_bundle_commitment_failed",
                extra={
                    "action_type": action.action_type,
                    "error_kind": type(exc).__name__,
                },
            )
            return f"workflow safeguard pre-bundle commitment failed: {type(exc).__name__}"
        return None


__all__ = ["ControlLoopSafeguardCommitmentMixin"]
