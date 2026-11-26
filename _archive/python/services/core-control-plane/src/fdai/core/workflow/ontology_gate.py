"""Gate a workflow step on a receipt-bound ontology function reading.

A workflow ``gate_ref`` of the form ``ontology-function:<function_name>`` asks the
ontology read path whether a deterministic predicate holds for the Process target.
The reading can only keep a gate shut or let the shared decision-evidence admission
decide: a missing, incomplete, stale, mismatched, or unreceipted reading closes the
gate, and a satisfied reading never grants execution authority by itself. Wrap this
evaluator with ``AdmittedWorkflowGuardEvaluator`` so an open gate still requires the
shared admission.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from fdai.core.workflow.workflow_runtime import (
    WorkflowContextualGuardEvaluator,
    WorkflowGuardEvaluator,
)

ONTOLOGY_FUNCTION_GATE_PREFIX = "ontology-function:"
_DIGEST_PREFIX = "sha256:"


@dataclass(frozen=True, slots=True)
class OntologyGateReading:
    """One bounded predicate result returned by the ontology read path."""

    function_ref: str
    satisfied: bool
    complete: bool
    observed_at: datetime
    receipt_digest: str


class OntologyGateReader(Protocol):
    async def read(
        self,
        *,
        function_ref: str,
        target_ref: str,
        at: datetime,
    ) -> OntologyGateReading | None:
        """Return the reading for one function and target, or None when unavailable."""
        ...


@dataclass(frozen=True, slots=True)
class OntologyFunctionGateEvaluator:
    """Open an ``ontology-function:`` gate only for a complete, fresh, receipted reading."""

    reader: OntologyGateReader
    max_reading_age: timedelta
    fallback: WorkflowContextualGuardEvaluator | WorkflowGuardEvaluator | None = None

    def __post_init__(self) -> None:
        if self.max_reading_age <= timedelta(0):
            raise ValueError("ontology gate max_reading_age MUST be positive")

    async def evaluate_context(
        self,
        *,
        rule_id: str,
        step_id: str,
        process_id: str,
        target_resource_id: str,
        at: datetime,
    ) -> bool:
        if not rule_id.startswith(ONTOLOGY_FUNCTION_GATE_PREFIX):
            return await self._delegate(
                rule_id=rule_id,
                step_id=step_id,
                process_id=process_id,
                target_resource_id=target_resource_id,
                at=at,
            )
        function_ref = rule_id.removeprefix(ONTOLOGY_FUNCTION_GATE_PREFIX)
        if not function_ref:
            return False
        reading = await self.reader.read(
            function_ref=function_ref,
            target_ref=target_resource_id,
            at=at,
        )
        return self._opens(reading, function_ref=function_ref, at=at)

    async def _delegate(
        self,
        *,
        rule_id: str,
        step_id: str,
        process_id: str,
        target_resource_id: str,
        at: datetime,
    ) -> bool:
        fallback = self.fallback
        if fallback is None:
            return False
        if isinstance(fallback, WorkflowContextualGuardEvaluator):
            result = await fallback.evaluate_context(
                rule_id=rule_id,
                step_id=step_id,
                process_id=process_id,
                target_resource_id=target_resource_id,
                at=at,
            )
        else:
            result = await fallback.evaluate(
                rule_id=rule_id, step_id=step_id, process_id=process_id
            )
        return result is True

    def _opens(
        self,
        reading: OntologyGateReading | None,
        *,
        function_ref: str,
        at: datetime,
    ) -> bool:
        if reading is None or reading.function_ref != function_ref:
            return False
        if reading.satisfied is not True or reading.complete is not True:
            return False
        if not reading.receipt_digest.startswith(_DIGEST_PREFIX):
            return False
        if reading.observed_at.tzinfo is None or at.tzinfo is None:
            return False
        age = at - reading.observed_at
        return timedelta(0) <= age <= self.max_reading_age


__all__ = [
    "ONTOLOGY_FUNCTION_GATE_PREFIX",
    "OntologyFunctionGateEvaluator",
    "OntologyGateReader",
    "OntologyGateReading",
]
