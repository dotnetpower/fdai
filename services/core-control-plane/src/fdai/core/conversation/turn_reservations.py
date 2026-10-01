"""Reserve each turn stage's worst case before dispatch, so no stage starves a later one.

A reservation plan lists every stage a path can run, including conditional ones, with its
worst case. Before a stage's call is sent, the ledger charges the call and checks that every
mandatory stage still ahead keeps its own worst case; otherwise the stage holds with the
typed `budget_reserved_exceeded` reason before any call. A failed call keeps its charge, a
completed one is reconciled to its measured usage, and a cancelled turn reserves nothing.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Callable, Iterable, Mapping
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field, replace
from enum import StrEnum

BUDGET_RESERVED_EXCEEDED = "budget_reserved_exceeded"
TURN_CANCELLED = "turn_cancelled"


class TurnStage(StrEnum):
    PREFLIGHT = "preflight"
    JUDGMENT = "judgment"
    FORM = "form"
    BLIND_REVIEW = "blind_review"
    CONCEPT_CHOOSER = "concept_chooser"
    DIRECTION_READER = "direction_reader"
    AMBIGUITY_READER = "ambiguity_reader"
    FRAME = "frame"
    PLAN = "plan"
    ANSWER_AUTHOR = "answer_author"
    ANSWER_REGENERATION = "answer_regeneration"
    ENTAILMENT_REVIEW = "entailment_review"
    CHUNK_SYNTHESIS = "chunk_synthesis"


# Reviewed call labels the model adapters already record, mapped to their stage.
CALL_STAGES = {
    "conversation-preflight": TurnStage.PREFLIGHT,
    "semantic-judgment": TurnStage.JUDGMENT,
    "semantic-question-form": TurnStage.FORM,
    "semantic-constraint-extraction": TurnStage.BLIND_REVIEW,
    "semantic-concept-selection": TurnStage.CONCEPT_CHOOSER,
    "semantic-direction-check": TurnStage.DIRECTION_READER,
    "semantic-ambiguity-check": TurnStage.AMBIGUITY_READER,
    "frame": TurnStage.FRAME,
    "frame_recovery": TurnStage.FRAME,
    "plan": TurnStage.PLAN,
    "plan_recovery": TurnStage.PLAN,
}


@dataclass(frozen=True, slots=True)
class StageCost:
    """Resource use in every reserved dimension; cost is in micro-USD when priced."""

    calls: int = 0
    input_bytes: int = 0
    output_tokens: int = 0
    wall_seconds: float = 0.0
    cost_microusd: int = 0
    read_rows: int = 0

    def __post_init__(self) -> None:
        if min(self.calls, self.input_bytes, self.output_tokens, self.cost_microusd) < 0:
            raise ValueError("stage cost MUST NOT be negative")
        if self.wall_seconds < 0 or self.read_rows < 0:
            raise ValueError("stage cost MUST NOT be negative")

    def __add__(self, other: StageCost) -> StageCost:
        return StageCost(
            self.calls + other.calls,
            self.input_bytes + other.input_bytes,
            self.output_tokens + other.output_tokens,
            self.wall_seconds + other.wall_seconds,
            self.cost_microusd + other.cost_microusd,
            self.read_rows + other.read_rows,
        )

    def fits(self, capacity: StageCost) -> bool:
        return (
            self.calls <= capacity.calls
            and self.input_bytes <= capacity.input_bytes
            and self.output_tokens <= capacity.output_tokens
            and self.wall_seconds <= capacity.wall_seconds
            and self.cost_microusd <= capacity.cost_microusd
            and self.read_rows <= capacity.read_rows
        )


@dataclass(frozen=True, slots=True)
class PlannedStage:
    """One stage the path can run: its worst case per call, call limit, and condition."""

    stage: TurnStage
    worst: StageCost
    max_calls: int = 1
    conditional: bool = False

    def __post_init__(self) -> None:
        if not 1 <= self.max_calls <= 64 or self.worst.calls != 1:
            raise ValueError("a planned stage reserves one call at a time, at most 64 times")


@dataclass(frozen=True, slots=True)
class ReservationPlan:
    """Every stage of one path, in dispatch order."""

    stages: tuple[PlannedStage, ...]

    def __post_init__(self) -> None:
        names = [item.stage for item in self.stages]
        if len(names) != len(set(names)):
            raise ValueError("a reservation plan names each stage once")

    def planned(self, stage: TurnStage) -> PlannedStage | None:
        return next((item for item in self.stages if item.stage is stage), None)

    def ahead(self, stage: TurnStage) -> tuple[PlannedStage, ...]:
        names = [item.stage for item in self.stages]
        return self.stages[names.index(stage) + 1 :] if stage in names else ()


class TurnReservationHeldError(RuntimeError):
    """A stage could not reserve its worst case; no call was sent."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(slots=True)
class StageReservation:
    """One reserved call: the worst case charged and the request actually sent."""

    stage: TurnStage
    charged: StageCost
    request: StageCost
    started: float
    status: str = "reserved"
    actual: StageCost | None = None
    ended_at: float | None = None


@dataclass(slots=True)
class TurnReservationLedger:
    """One turn's capacity, its plan, and every reservation, held or charged."""

    capacity: StageCost
    plan: ReservationPlan
    clock: Callable[[], float] = time.monotonic
    records: list[StageReservation] = field(default_factory=list)
    holds: list[str] = field(default_factory=list)
    cancelled: bool = False

    @property
    def spent(self) -> StageCost:
        return _sum(record.charged for record in self.records)

    def remaining(self) -> StageCost:
        spent = self.spent
        return StageCost(
            max(self.capacity.calls - spent.calls, 0),
            max(self.capacity.input_bytes - spent.input_bytes, 0),
            max(self.capacity.output_tokens - spent.output_tokens, 0),
            max(self.capacity.wall_seconds - spent.wall_seconds, 0.0),
            max(self.capacity.cost_microusd - spent.cost_microusd, 0),
            max(self.capacity.read_rows - spent.read_rows, 0),
        )

    def reserve(self, stage: TurnStage, request: StageCost | None = None) -> StageReservation:
        """Charge one call of ``stage`` at its worst case, or raise the typed hold."""

        if self.cancelled:
            raise self._hold(TURN_CANCELLED)
        planned = self.plan.planned(stage)
        if planned is None:
            raise self._hold(f"{BUDGET_RESERVED_EXCEEDED}:{stage.value}:unplanned")
        if sum(1 for item in self.records if item.stage is stage) >= planned.max_calls:
            raise self._hold(f"{BUDGET_RESERVED_EXCEEDED}:{stage.value}:calls")
        sent = request if request is not None else planned.worst
        charge = _at_least(sent, planned.worst)
        # Every mandatory stage still ahead and not yet started keeps its own worst case.
        started = {item.stage for item in self.records}
        ahead = _sum(
            item.worst
            for item in self.plan.ahead(stage)
            if not item.conditional and item.stage not in started
        )
        if not (self.spent + charge + ahead).fits(self.capacity):
            raise self._hold(f"{BUDGET_RESERVED_EXCEEDED}:{stage.value}")
        record = StageReservation(stage, charge, sent, self.clock())
        self.records.append(record)
        return record

    def reconcile(self, record: StageReservation, output_tokens: int | None = None) -> None:
        """Charge what the completed call used; usage above the reservation stays charged."""

        if record.status != "reserved":
            raise ValueError("a reservation is reconciled or failed once")
        record.ended_at = self.clock()
        elapsed = max(record.ended_at - record.started, 0.0)
        tokens = output_tokens if output_tokens is not None else record.request.output_tokens
        actual = replace(record.request, output_tokens=tokens, wall_seconds=elapsed)
        record.actual = actual
        overrun = not actual.fits(record.charged)
        record.charged = _at_least(actual, record.charged) if overrun else actual
        record.status = "overrun" if overrun else "reconciled"

    def fail(self, record: StageReservation) -> None:
        """Keep a failed call's whole reservation charged."""

        if record.status == "reserved":
            record.ended_at = self.clock()
            record.status = "failed"

    def cancel(self) -> None:
        self.cancelled = True

    def _hold(self, reason: str) -> TurnReservationHeldError:
        self.holds.append(reason)
        return TurnReservationHeldError(reason)


def _sum(costs: Iterable[StageCost]) -> StageCost:
    total = StageCost()
    for cost in costs:
        total = total + cost
    return total


def _at_least(value: StageCost, floor: StageCost) -> StageCost:
    return StageCost(
        max(value.calls, floor.calls),
        max(value.input_bytes, floor.input_bytes),
        max(value.output_tokens, floor.output_tokens),
        max(value.wall_seconds, floor.wall_seconds),
        max(value.cost_microusd, floor.cost_microusd),
        max(value.read_rows, floor.read_rows),
    )


# Reviewed per-call worst cases: the request bytes an adapter may send, the output tokens it
# may request, and its stage timeout.
_FORM_CALL = StageCost(1, 64 * 1024, 4096, 20.0)
_READER_CALL = StageCost(1, 32 * 1024, 1024, 20.0)
_PLANNER_CALL = StageCost(1, 96 * 1024, 4096, 20.0)


# Each pass settles at most this many directional relations, each with a first reader and
# at most one tie-break; it mirrors `semantic_reasoning_direction.MAX_DIRECTION_QUESTIONS`.
DIRECTION_QUESTIONS_PER_PASS = 4
# The blind review reads twice at most (once more without context) and re-extracts once.
_REVIEW_CALLS = 4


def shadow_reservation_plan(
    *, form_passes: int, repairs_per_pass: int, concept_calls: int
) -> ReservationPlan:
    """Return the shadow's stages, each sized to every call the shadow can reach."""

    passes = form_passes + 1  # The review repair pass runs the stages once more.
    form_calls = form_passes * (1 + repairs_per_pass) + 1
    direction_calls = passes * DIRECTION_QUESTIONS_PER_PASS * 2
    return ReservationPlan(
        (
            PlannedStage(TurnStage.FORM, _FORM_CALL, max_calls=min(form_calls, 64)),
            PlannedStage(
                TurnStage.BLIND_REVIEW, _READER_CALL, max_calls=_REVIEW_CALLS, conditional=True
            ),
            PlannedStage(
                TurnStage.CONCEPT_CHOOSER,
                _READER_CALL,
                max_calls=max(min(concept_calls, 64), 1),
                conditional=True,
            ),
            PlannedStage(
                TurnStage.DIRECTION_READER,
                _READER_CALL,
                max_calls=min(direction_calls, 64),
                conditional=True,
            ),
            PlannedStage(TurnStage.AMBIGUITY_READER, _READER_CALL, max_calls=1, conditional=True),
        )
    )


def semantic_reservation_plan() -> ReservationPlan:
    """Return the current path's stages, including the conditional answer stages."""

    return ReservationPlan(
        (
            PlannedStage(TurnStage.PREFLIGHT, _READER_CALL, conditional=True),
            PlannedStage(TurnStage.JUDGMENT, _PLANNER_CALL, max_calls=2),
            PlannedStage(TurnStage.FRAME, _PLANNER_CALL, max_calls=2),
            PlannedStage(TurnStage.PLAN, _PLANNER_CALL, max_calls=2),
            PlannedStage(TurnStage.ANSWER_AUTHOR, _PLANNER_CALL, conditional=True),
            PlannedStage(TurnStage.ANSWER_REGENERATION, _PLANNER_CALL, conditional=True),
            PlannedStage(TurnStage.ENTAILMENT_REVIEW, _READER_CALL, conditional=True),
            PlannedStage(TurnStage.CHUNK_SYNTHESIS, _READER_CALL, conditional=True),
        )
    )


def plan_capacity(plan: ReservationPlan) -> StageCost:
    """Return the capacity that holds every stage at its call limit and worst case."""

    total = StageCost()
    for item in plan.stages:
        for _ in range(item.max_calls):
            total = total + item.worst
    return total


_LEDGER: ContextVar[TurnReservationLedger | None] = ContextVar("turn_reservations", default=None)


@asynccontextmanager
async def bind_turn_reservations(ledger: TurnReservationLedger) -> AsyncIterator[None]:
    """Bind one ledger to the calls made in this context; it reserves nothing afterwards."""

    token = _LEDGER.set(ledger)
    try:
        yield
    finally:
        _LEDGER.reset(token)
        ledger.cancel()


def current_ledger() -> TurnReservationLedger | None:
    """Return the ledger bound to this context, if any."""

    return _LEDGER.get()


def reserve_call(label: str, *, input_bytes: int, output_tokens: int) -> StageReservation | None:
    """Reserve one physical model request under the bound ledger, if one is bound."""

    ledger = _LEDGER.get()
    stage = CALL_STAGES.get(label)
    if ledger is None or stage is None:
        return None
    return ledger.reserve(stage, StageCost(1, input_bytes, output_tokens))


def reconcile_call(record: StageReservation | None, usage: Mapping[str, int] | None) -> None:
    """Reconcile a completed call with its measured completion tokens, when reported."""

    ledger = _LEDGER.get()
    if record is None or ledger is None or record.status != "reserved":
        return
    output = (usage or {}).get("completion_tokens")
    ledger.reconcile(record, output if isinstance(output, int) and output >= 0 else None)


def fail_call(record: StageReservation | None) -> None:
    ledger = _LEDGER.get()
    if record is not None and ledger is not None:
        ledger.fail(record)


__all__ = [
    "BUDGET_RESERVED_EXCEEDED",
    "CALL_STAGES",
    "TURN_CANCELLED",
    "PlannedStage",
    "ReservationPlan",
    "StageCost",
    "StageReservation",
    "TurnReservationHeldError",
    "TurnReservationLedger",
    "TurnStage",
    "bind_turn_reservations",
    "current_ledger",
    "fail_call",
    "plan_capacity",
    "reconcile_call",
    "reserve_call",
    "semantic_reservation_plan",
    "shadow_reservation_plan",
]
