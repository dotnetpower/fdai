"""Ontology-native workflow primitives (Items 1-6).

Provides:
1. ``ObjectSetWorkflowInput``: binds a complete, non-truncated ``ObjectSet`` snapshot to a
   workflow run without accepting incomplete or unverified member sets.
2. ``ForEachObjectSetRunner``: bounded fan-out execution across ``ObjectSet`` members with
   concurrency limits and partial-failure isolation.
3. ``StepOutputContext`` and ``resolve_step_output_params``: receipt-bound substitution of
   ``${step.<step_id>.output.<field>}`` tokens from prior ``OntologyFunction`` outputs.
4. ``evaluate_ontology_decision_branch``: deterministic routing for ``kind: decision`` steps
   over receipted ontology function outputs and declared ``outcomes``.
5. ``OntologyConditionTriggerEvaluator``: edge-triggered state-condition firing over an
   ``ObjectSet`` with idempotent deduplication keys.
6. ``OntologyOwnershipApprovalResolver``: dynamic approval routing across
   ``Resource <- workload_runs_on <- Workload <- implemented_by <- BusinessService ->
   service_owned_by -> Ownership``.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

from fdai_service_contracts.ontology_query import content_digest

from fdai.shared.providers.ontology_instance import (
    OntologyGraphSnapshot,
    OntologyInstanceStore,
)

_STEP_OUTPUT_TOKEN: Final = re.compile(
    r"^\$\{step\.([a-zA-Z0-9_-]{1,64})\.output\.([a-zA-Z0-9_]{1,64})\}$"
)
_DIGEST_PREFIX: Final = "sha256:"
_MAX_OBJECT_SET_MEMBERS: Final = 256
_SERVICE_OWNERSHIP_LINKS: Final = (
    "workload_runs_on",
    "workload_depends_on",
    "implemented_by",
    "service_owned_by",
)


@dataclass(frozen=True, slots=True)
class ObjectSetWorkflowInput:
    """Item 1: Validated, complete ObjectSet bound as a workflow target set."""

    object_type: str
    member_ids: tuple[str, ...]
    source_generation: str
    receipt_digest: str

    @classmethod
    def from_snapshot(
        cls,
        snapshot: OntologyGraphSnapshot,
        *,
        object_type: str,
        receipt_digest: str,
        max_members: int = _MAX_OBJECT_SET_MEMBERS,
    ) -> ObjectSetWorkflowInput:
        if not object_type.strip():
            raise ValueError("ObjectSetWorkflowInput.object_type MUST be non-empty")
        if not receipt_digest.startswith(_DIGEST_PREFIX) or len(receipt_digest) != 71:
            raise ValueError("ObjectSetWorkflowInput.receipt_digest MUST be SHA-256")
        if not snapshot.source_complete or snapshot.truncated:
            raise ValueError("ObjectSetWorkflowInput requires a complete, non-truncated snapshot")
        if not 1 <= max_members <= _MAX_OBJECT_SET_MEMBERS:
            raise ValueError("max_members is outside the bounded limit")
        members = tuple(
            sorted({obj.id for obj in snapshot.objects if obj.object_type == object_type})
        )
        if not members:
            raise ValueError("ObjectSetWorkflowInput requires at least one matching member")
        if len(members) > max_members:
            raise ValueError("ObjectSetWorkflowInput exceeds max_members")
        return cls(
            object_type=object_type,
            member_ids=members,
            source_generation=snapshot.source_generation or "unversioned",
            receipt_digest=receipt_digest,
        )


@dataclass(frozen=True, slots=True)
class MemberFanOutOutcome:
    """Per-member execution result from ``ForEachObjectSetRunner``."""

    member_id: str
    succeeded: bool
    result: object | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class FanOutBatchReceipt:
    """Item 2: Deterministic summary and digest for a bounded ObjectSet fan-out."""

    source_receipt_digest: str
    outcomes: tuple[MemberFanOutOutcome, ...]
    succeeded_count: int
    failed_count: int
    batch_digest: str


class ForEachObjectSetRunner:
    """Item 2: Execute a workflow action/step over an ObjectSet with concurrency & isolation."""

    def __init__(self, *, max_concurrency: int = 8, fail_fast: bool = False) -> None:
        if not 1 <= max_concurrency <= 64:
            raise ValueError("max_concurrency MUST be in 1..64")
        self._max_concurrency = max_concurrency
        self._fail_fast = fail_fast

    async def run(
        self,
        object_set: ObjectSetWorkflowInput,
        handler: Callable[[str], Awaitable[object]],
    ) -> FanOutBatchReceipt:
        semaphore = asyncio.Semaphore(self._max_concurrency)
        outcomes: list[MemberFanOutOutcome] = []
        abort = False

        async def _run_one(member_id: str) -> MemberFanOutOutcome:
            nonlocal abort
            async with semaphore:
                if abort:
                    return MemberFanOutOutcome(
                        member_id=member_id,
                        succeeded=False,
                        error="aborted_by_fail_fast",
                    )
                try:
                    res = await handler(member_id)
                    return MemberFanOutOutcome(member_id=member_id, succeeded=True, result=res)
                except Exception as exc:  # noqa: BLE001
                    if self._fail_fast:
                        abort = True
                    return MemberFanOutOutcome(
                        member_id=member_id,
                        succeeded=False,
                        error=f"{type(exc).__name__}:{exc}",
                    )

        if self._fail_fast:
            for member_id in object_set.member_ids:
                outcomes.append(await _run_one(member_id))
        else:
            outcomes = list(await asyncio.gather(*(_run_one(m) for m in object_set.member_ids)))
        ordered = tuple(sorted(outcomes, key=lambda item: item.member_id))
        succ = sum(1 for item in ordered if item.succeeded)
        fail = len(ordered) - succ
        digest = content_digest(
            {
                "source_receipt_digest": object_set.receipt_digest,
                "outcomes": [
                    {"member_id": o.member_id, "succeeded": o.succeeded, "error": o.error}
                    for o in ordered
                ],
            }
        )
        return FanOutBatchReceipt(
            source_receipt_digest=object_set.receipt_digest,
            outcomes=ordered,
            succeeded_count=succ,
            failed_count=fail,
            batch_digest=digest,
        )


@dataclass(frozen=True, slots=True)
class StepFunctionOutput:
    """Item 3: Receipt-bound output of a workflow ontology function step."""

    step_id: str
    function_ref: str
    receipt_digest: str
    values: Mapping[str, str | int | float | bool]

    def __post_init__(self) -> None:
        if not self.step_id.strip() or not self.function_ref.strip():
            raise ValueError("StepFunctionOutput identifiers MUST be non-empty")
        if not self.receipt_digest.startswith(_DIGEST_PREFIX) or len(self.receipt_digest) != 71:
            raise ValueError("StepFunctionOutput.receipt_digest MUST be SHA-256")


def resolve_step_output_params(
    params: Mapping[str, str | int | float | bool],
    outputs: Mapping[str, StepFunctionOutput],
) -> dict[str, str | int | float | bool]:
    """Item 3: Substitute ``${step.<id>.output.<field>}`` tokens with typed scalar values."""

    resolved: dict[str, str | int | float | bool] = {}
    for key, raw_val in params.items():
        if not isinstance(raw_val, str) or not raw_val.startswith("${step."):
            resolved[key] = raw_val
            continue
        match = _STEP_OUTPUT_TOKEN.fullmatch(raw_val)
        if match is None:
            raise ValueError(f"Malformed step output token in param {key!r}: {raw_val!r}")
        step_id, field_name = match.group(1), match.group(2)
        step_out = outputs.get(step_id)
        if step_out is None:
            raise LookupError(f"Referenced step output {step_id!r} is missing or unreceipted")
        if field_name not in step_out.values:
            raise KeyError(f"Field {field_name!r} is absent from step {step_id!r} output")
        val = step_out.values[field_name]
        if not isinstance(val, (str, int, float, bool)):
            raise TypeError(f"Step output field {field_name!r} MUST be a scalar")
        resolved[key] = val
    return resolved


def evaluate_ontology_decision_branch(
    *,
    declared_outcomes: tuple[str, ...],
    step_output: StepFunctionOutput,
    field_name: str,
    value_to_outcome: Mapping[str, str],
) -> str:
    """Item 4: Route a ``kind: decision`` step to one declared outcome from function output."""

    if not declared_outcomes:
        raise ValueError("decision step MUST declare non-empty outcomes")
    if step_output.values.get("complete") is False:
        raise ValueError("decision step cannot branch on an incomplete ontology reading")
    if field_name not in step_output.values:
        raise KeyError(f"decision field {field_name!r} is absent from step {step_output.step_id!r}")
    observed_key = str(step_output.values[field_name])
    chosen = value_to_outcome.get(observed_key)
    if chosen is None or chosen not in declared_outcomes:
        raise ValueError(f"decision value {observed_key!r} does not map to a declared outcome")
    return chosen


@dataclass(frozen=True, slots=True)
class ConditionTriggerFiring:
    """Item 5: Edge-triggered workflow firing event for one ObjectSet member."""

    trigger_id: str
    member_id: str
    idempotency_key: str
    fired_at: datetime
    reading_receipt_digest: str


class OntologyConditionTriggerEvaluator:
    """Item 5: Fire once on False->True edge when an ontology condition holds."""

    def __init__(self, *, trigger_id: str) -> None:
        if not trigger_id.strip():
            raise ValueError("trigger_id MUST be non-empty")
        self._trigger_id = trigger_id
        self._active_members: set[str] = set()

    def evaluate_transition(
        self,
        *,
        member_id: str,
        condition_satisfied: bool,
        complete: bool,
        receipt_digest: str,
        observed_at: datetime,
    ) -> ConditionTriggerFiring | None:
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ValueError("ConditionTrigger observed_at MUST be timezone-aware")
        if not receipt_digest.startswith(_DIGEST_PREFIX):
            return None
        effective = condition_satisfied is True and complete is True
        if not effective:
            self._active_members.discard(member_id)
            return None
        if member_id in self._active_members:
            return None
        self._active_members.add(member_id)
        idem = content_digest(
            {
                "trigger_id": self._trigger_id,
                "member_id": member_id,
                "receipt_digest": receipt_digest,
                "fired_at": observed_at.astimezone(UTC).isoformat(),
            }
        )
        return ConditionTriggerFiring(
            trigger_id=self._trigger_id,
            member_id=member_id,
            idempotency_key=f"cond-trigger:{idem}",
            fired_at=observed_at,
            reading_receipt_digest=receipt_digest,
        )


@dataclass(frozen=True, slots=True)
class ResolvedOwnershipApprovers:
    """Item 6: Dynamically resolved owners and escalation contacts from the ontology graph."""

    target_resource_ref: str
    service_refs: tuple[str, ...]
    owner_refs: tuple[str, ...]
    escalation_refs: tuple[str, ...]


class OntologyOwnershipApprovalResolver:
    """Item 6: Resolve active Ownership records for a Resource via its BusinessServices."""

    def __init__(self, store: OntologyInstanceStore) -> None:
        self._store = store

    async def resolve(
        self, *, target_resource_ref: str, at: datetime
    ) -> ResolvedOwnershipApprovers | None:
        if at.tzinfo is None or at.utcoffset() is None:
            raise ValueError("Ownership resolution timestamp MUST be timezone-aware")
        target = await self._store.get_object(target_resource_ref)
        if target is None or target.object_type != "Resource":
            return None
        graph = await self._store.traverse(
            root_ids=(target_resource_ref,),
            root_object_types=("Resource",),
            link_types=_SERVICE_OWNERSHIP_LINKS,
            direction="both",
            max_depth=4,
            limit=500,
        )
        if not graph.source_complete or graph.truncated:
            return None
        objects = {obj.id: obj for obj in graph.objects}
        workloads = {
            link.from_id
            for link in graph.links
            if link.link_type == "workload_runs_on" and link.to_id == target_resource_ref
        }
        services = sorted(
            {
                link.from_id
                for link in graph.links
                if link.link_type == "implemented_by"
                and link.to_id in workloads
                and _in_effect(objects.get(link.from_id), at)
            }
        )
        if not services:
            return None
        ownership_ids = sorted(
            {
                link.to_id
                for link in graph.links
                if link.link_type == "service_owned_by" and link.from_id in services
            }
        )
        owners: list[str] = []
        escalations: list[str] = []
        for oid in ownership_ids:
            record = objects.get(oid)
            if record is None or record.object_type != "Ownership" or not _in_effect(record, at):
                continue
            owner_ref = str(record.properties.get("owner_ref") or "").strip()
            esc_ref = str(record.properties.get("escalation_ref") or "").strip()
            if owner_ref:
                owners.append(owner_ref)
            if esc_ref:
                escalations.append(esc_ref)
        if not owners:
            return None
        return ResolvedOwnershipApprovers(
            target_resource_ref=target_resource_ref,
            service_refs=tuple(services),
            owner_refs=tuple(dict.fromkeys(owners)),
            escalation_refs=tuple(dict.fromkeys(escalations)),
        )


def _in_effect(record: Any, at: datetime) -> bool:
    if record is None:
        return False
    props = record.properties
    eff_from = _parse_dt(props.get("effective_from"))
    eff_to = _parse_dt(props.get("effective_to"))
    if eff_from is not None and eff_from > at:
        return False
    return eff_to is None or eff_to > at


def _parse_dt(val: object) -> datetime | None:
    if isinstance(val, datetime):
        return val if val.tzinfo is not None else None
    if isinstance(val, str):
        try:
            parsed = datetime.fromisoformat(val)
            return parsed if parsed.tzinfo is not None else None
        except ValueError:
            return None
    return None


__all__ = [
    "ConditionTriggerFiring",
    "FanOutBatchReceipt",
    "ForEachObjectSetRunner",
    "MemberFanOutOutcome",
    "ObjectSetWorkflowInput",
    "OntologyConditionTriggerEvaluator",
    "OntologyOwnershipApprovalResolver",
    "ResolvedOwnershipApprovers",
    "StepFunctionOutput",
    "evaluate_ontology_decision_branch",
    "resolve_step_output_params",
]
