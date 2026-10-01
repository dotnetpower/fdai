"""Loki - Chaos (Wave 5 behavior).

Loki schedules chaos experiments with a bounded blast_radius and
NEVER auto-executes. Every proposed experiment routes through Forseti
and Var as an HIL action; Loki merely emits the proposal.

Blast-radius accounting is deterministic: no matter how many
proposals come in per unit time, the cumulative in-flight target count
is capped by :pyattr:`blast_radius_cap`.
"""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from fdai.agents._framework.base import Agent
from fdai.agents._framework.bus import PantheonBus
from fdai.agents._framework.loki_adversarial import (
    MAX_GENERATED_SCENARIOS,
    ChaosScenarioGenerator,
    audit_payload,
    frozen_corpus_key,
    validate_candidate,
)
from fdai.agents._framework.loki_constants import (
    _CHAOS_EVIDENCE_FIELDS as _CHAOS_EVIDENCE_FIELDS,
)
from fdai.agents._framework.loki_constants import (
    _CHAOS_OUTBOX_PREFIX as _CHAOS_OUTBOX_PREFIX,
)
from fdai.agents._framework.loki_constants import (
    _DEFAULT_RESERVATION_TTL as _DEFAULT_RESERVATION_TTL,
)
from fdai.agents._framework.loki_constants import (
    _HELD_PREFIX as _HELD_PREFIX,
)
from fdai.agents._framework.loki_constants import (
    _MAX_CHAOS_IDENTIFIER_CHARS as _MAX_CHAOS_IDENTIFIER_CHARS,
)
from fdai.agents._framework.loki_constants import (
    _MAX_CHAOS_TARGETS as _MAX_CHAOS_TARGETS,
)
from fdai.agents._framework.loki_constants import (
    _MAX_HELD_PROPOSALS as _MAX_HELD_PROPOSALS,
)
from fdai.agents._framework.loki_constants import (
    _MAX_RESILIENCE_SCORES as _MAX_RESILIENCE_SCORES,
)
from fdai.agents._framework.loki_constants import (
    _RESILIENCE_PREFIX as _RESILIENCE_PREFIX,
)
from fdai.agents._framework.loki_constants import (
    _SAFE_CLOSURE_STATES as _SAFE_CLOSURE_STATES,
)
from fdai.agents._framework.loki_experiment_runtime import (
    LokiExperimentRuntimeMixin,
)
from fdai.agents._framework.loki_experiment_runtime import (
    _digest as _digest,
)
from fdai.agents._framework.loki_reservations import LokiReservationJournal
from fdai.agents._framework.loki_resilience import (
    RESILIENCE_SCORE_EVENT,
    resilience_score_candidate,
)
from fdai.agents._framework.loki_runtime_records import (
    ChaosProposal,
    _Reservation,
)
from fdai.agents._framework.loki_schedule_runtime import (
    _SCHEDULED_PREFIX as _SCHEDULED_PREFIX,
)
from fdai.agents._framework.loki_schedule_runtime import (
    LokiScheduleRuntimeMixin,
)
from fdai.agents._framework.loki_scheduling import (
    ChaosScheduleConfig,
)
from fdai.agents._framework.loki_status_runtime import LokiStatusRuntimeMixin
from fdai.agents._framework.pantheon import _LOKI
from fdai.agents._framework.producer_auth import require_topic_owner
from fdai.agents._framework.specialist_ingress import (
    CHAOS_SCHEDULE_EVENT,
    parse_chaos_schedule,
)
from fdai.shared.providers.state_store import StateStore

#: Cap on the retained proposal log. Loki appends one entry per proposal for
#: the process lifetime; the log is only read for recent-accepted diagnostics,
#: so a bounded ring is sufficient and stops an unbounded leak on a
#: long-running chaos scheduler.
_MAX_PROPOSALS = 1_000
_ADVERSARIAL_PREFIX = "pantheon/loki/adversarial-scenarios/"


class Loki(
    LokiExperimentRuntimeMixin,
    LokiScheduleRuntimeMixin,
    LokiStatusRuntimeMixin,
    Agent,
):
    """Wave-5 Loki: chaos scheduler with blast-radius cap."""

    def __init__(
        self,
        *,
        bus: PantheonBus | None = None,
        blast_radius_cap: int = 3,
        state_store: StateStore | None = None,
        clock: Callable[[], datetime] | None = None,
        reservation_ttl: timedelta = _DEFAULT_RESERVATION_TTL,
        recurring_schedule: ChaosScheduleConfig | None = None,
        scenario_generator: ChaosScenarioGenerator | None = None,
        scenario_corpus: tuple[ChaosScheduleConfig, ...] = (),
    ) -> None:
        super().__init__(spec=_LOKI)
        if reservation_ttl <= timedelta(0):
            raise ValueError("reservation_ttl MUST be positive")
        self.bus = bus
        self._cap = blast_radius_cap
        self._clock: Callable[[], datetime] = clock or (lambda: datetime.now(tz=UTC))
        self._reservation_ttl = reservation_ttl
        self._in_flight_targets: set[str] = set()
        self._reservations: dict[str, _Reservation] = {}
        self._publishing_experiments: set[str] = set()
        self._reservation_journal = (
            LokiReservationJournal(state_store, blast_radius_cap=blast_radius_cap)
            if state_store is not None
            else None
        )
        self._state_store = state_store
        self.proposals: deque[ChaosProposal] = deque(maxlen=_MAX_PROPOSALS)
        self._held_proposals: deque[ChaosProposal] = deque(maxlen=_MAX_HELD_PROPOSALS)
        self._resilience_scores: dict[str, tuple[float, str]] = {}
        self._blast_radius_attempts = 0
        self._blast_radius_adherent_attempts = 0
        self._resilience_experiment_scores: dict[str, dict[str, float]] = {}
        self._reservation_lock = asyncio.Lock()
        self._publication_locks: dict[str, asyncio.Lock] = {}
        self._publication_lock_refs: dict[str, int] = {}
        self._recurring_schedule = recurring_schedule
        self._scenario_generator = scenario_generator
        self._scenario_corpus = {frozen_corpus_key(item): item for item in scenario_corpus}
        self._proposal_queue_managed_externally = True

    def bind_bus(self, bus: PantheonBus) -> None:
        self.bus = bus

    def bind_recurring_schedule(self, schedule: ChaosScheduleConfig | None) -> None:
        self._recurring_schedule = schedule

    def bind_scenario_generator(self, generator: ChaosScenarioGenerator | None) -> None:
        self._scenario_generator = generator

    async def on_typed_message(self, topic: str, payload: dict[str, Any]) -> None:
        if topic == "object.action-run":
            await self._release_from_action_run(payload)
            return
        if topic != "object.event":
            self.record_behavior("typed_message:ignored")
            return
        event_type = str(payload.get("event_type") or "")
        owner_behavior = (
            "chaos_schedule:invalid_producer"
            if event_type == CHAOS_SCHEDULE_EVENT
            else "resilience_score:invalid"
        )
        if require_topic_owner(self, topic, payload, behavior=owner_behavior):
            return
        if payload.get("event_type") == RESILIENCE_SCORE_EVENT:
            candidate = resilience_score_candidate(payload)
            if candidate is None:
                self.record_behavior("resilience_score:invalid")
                return
            if not await self._remember_resilience_score(candidate):
                return
            if await self._publish_proposal("object.resilience-score", candidate):
                self.record_behavior("resilience_score:published")
            return
        if payload.get("event_type") != CHAOS_SCHEDULE_EVENT:
            self.record_behavior("chaos_schedule:ignored_event")
            return
        signal = parse_chaos_schedule(payload)
        if signal is None:
            self.record_behavior("chaos_schedule:invalid")
            return
        self.record_behavior("chaos_schedule:accepted")
        await self.propose_experiment(
            experiment_id=signal.experiment_id,
            action_type=signal.action_type,
            targets=signal.targets,
            correlation_id=signal.correlation_id,
        )

    # ---- experiment scheduling ----------------------------------------

    def _now(self) -> datetime:
        current = self._clock()
        if current.tzinfo is None or current.utcoffset() is None:
            raise ValueError("Loki clock MUST return a timezone-aware datetime")
        return current

    async def run_adversarial_generation(self, *, design_ref: str) -> int:
        """Run the explicitly invoked off-path generator and retain inert candidates."""

        if self._scenario_generator is None:
            self.record_behavior("adversarial_scenario:generator_unbound")
            return 0
        candidates = tuple(await self._scenario_generator.generate_scenarios(design_ref))[
            :MAX_GENERATED_SCENARIOS
        ]
        accepted = 0
        for candidate in candidates:
            result = validate_candidate(candidate, frozen_corpus=self._scenario_corpus)
            payload = audit_payload(candidate, design_ref=design_ref, result=result)
            if self.bus is None:
                self.record_behavior("adversarial_scenario:publication_unavailable")
                continue
            if not await self._publish_proposal("object.chaos-experiment", payload):
                self.record_behavior("adversarial_scenario:audit_unpublished")
                continue
            if result == "accepted":
                self._scenario_corpus[frozen_corpus_key(candidate.schedule)] = candidate.schedule
                accepted += 1
                if self._state_store is not None:
                    await self._state_store.write_state(
                        f"{_ADVERSARIAL_PREFIX}{_digest(candidate.scenario_id)}",
                        {
                            "schema_version": "1.0.0",
                            "revision": 1,
                            "scenario_id": candidate.scenario_id,
                            "schedule_id": candidate.schedule.schedule_id,
                            "state": "accepted_inert",
                            "design_ref": design_ref,
                        },
                    )
            self.record_behavior(f"adversarial_scenario:{result}")
        if not candidates:
            self.record_behavior("adversarial_scenario:empty")
        return accepted


__all__ = ["Loki", "ChaosProposal"]
