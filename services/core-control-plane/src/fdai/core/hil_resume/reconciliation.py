"""Independent effect-reconciliation submission for resumed HIL actions."""

from __future__ import annotations

import logging

from fdai.core.executor import ExecutionResult
from fdai.core.executor.direct_api import DirectApiExecutionResult
from fdai.core.executor.tool_call import ToolCallExecutionResult
from fdai.core.ontology_platform.reconciliation_producer import (
    EffectReconciliationRequestSink,
    ReconciliationRequestProduction,
    ReconciliationRequestProductionStatus,
)
from fdai.shared.contracts.execution_outcomes import execution_outcome_may_have_effect
from fdai.shared.contracts.models import Action

_LOGGER = logging.getLogger(__name__)


async def produce_effect_reconciliation_request(
    sink: EffectReconciliationRequestSink | None,
    *,
    action: Action,
    result: ExecutionResult | DirectApiExecutionResult | ToolCallExecutionResult,
    correlation_id: str,
) -> ReconciliationRequestProduction | None:
    """Submit a potentially effective dispatch for independent closure."""

    if not execution_outcome_may_have_effect(result.outcome):
        return None
    if sink is None:
        return ReconciliationRequestProduction(
            ReconciliationRequestProductionStatus.HELD,
            "request_sink_unavailable",
        )
    try:
        return await sink(
            action,
            result.outcome.value,
            getattr(result, "receipt_ref", None) or getattr(result, "pr_ref", None),
            correlation_id=correlation_id,
        )
    except Exception:  # noqa: BLE001 - dispatch truth remains pending
        _LOGGER.warning(
            "hil_effect_reconciliation_request_failed",
            extra={"action_type": action.action_type},
            exc_info=True,
        )
        return ReconciliationRequestProduction(
            ReconciliationRequestProductionStatus.HELD,
            "request_publication_failed",
        )


__all__ = ["produce_effect_reconciliation_request"]
