"""Back a workflow ``ontology-function:`` gate with the ontology function registry.

The reader invokes one reviewed read-only FunctionType for the Process target and maps its
bounded result to a receipt-bound gate reading. Gate arguments come from reviewed deployment
configuration, never from the workflow or a model. A function that is not configured, any
invocation failure, or a result that does not state a boolean ``gate_satisfied``, a boolean
``complete`` and a timezone-aware ``observed_at`` produces no reading, which keeps the gate
shut.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from fdai.core.workflow.ontology_gate import OntologyGateReading

from .functions import FunctionInvocationContext, OntologyFunctionRegistry, ontology_function_digest

GATE_TARGET_EVIDENCE_PREFIX = "gate-target:"
GATE_CALLER_AGENT = "WorkflowGate"

_LOGGER = logging.getLogger(__name__)


class GateTargetAnchorResolver:
    """Resolve the Process target from the server-built gate invocation context."""

    async def resolve(self, context: FunctionInvocationContext) -> str | None:
        targets = [
            item.removeprefix(GATE_TARGET_EVIDENCE_PREFIX)
            for item in context.evidence_refs
            if item.startswith(GATE_TARGET_EVIDENCE_PREFIX)
        ]
        if len(targets) != 1 or not targets[0]:
            return None
        return targets[0]


class RegistryOntologyGateReader:
    """Read one configured ontology function as a gate reading."""

    def __init__(
        self,
        *,
        registry: OntologyFunctionRegistry,
        gate_arguments: Mapping[str, Mapping[str, Any]],
        purposes: tuple[str, ...],
    ) -> None:
        if not purposes:
            raise ValueError("gate reader purposes MUST be non-empty")
        self._registry = registry
        self._arguments = {name: dict(args) for name, args in gate_arguments.items()}
        self._purposes = purposes

    async def read(
        self,
        *,
        function_ref: str,
        target_ref: str,
        at: datetime,
    ) -> OntologyGateReading | None:
        del at
        arguments = self._arguments.get(function_ref)
        if arguments is None or not target_ref:
            return None
        context = FunctionInvocationContext(
            caller_agent=GATE_CALLER_AGENT,
            purposes=self._purposes,
            evidence_refs=(f"{GATE_TARGET_EVIDENCE_PREFIX}{target_ref}",),
        )
        try:
            result, receipt = await self._registry.invoke_with_receipt(
                function_ref, arguments, context=context
            )
        except (KeyError, LookupError, PermissionError, TimeoutError, TypeError, ValueError):
            _LOGGER.info("ontology gate function %s produced no reading", function_ref)
            return None
        if not isinstance(result, Mapping):
            return None
        satisfied = result.get("gate_satisfied")
        complete = result.get("complete")
        observed = result.get("observed_at")
        if not isinstance(satisfied, bool) or not isinstance(complete, bool):
            return None
        if not isinstance(observed, str):
            return None
        try:
            observed_at = datetime.fromisoformat(observed)
        except ValueError:
            return None
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            return None
        return OntologyGateReading(
            function_ref=function_ref,
            satisfied=satisfied,
            complete=complete,
            observed_at=observed_at,
            receipt_digest=ontology_function_digest(
                {
                    "invocation_id": receipt.invocation_id,
                    "output_digest": receipt.output_digest,
                }
            ),
        )


__all__ = [
    "GATE_CALLER_AGENT",
    "GATE_TARGET_EVIDENCE_PREFIX",
    "GateTargetAnchorResolver",
    "RegistryOntologyGateReader",
]
