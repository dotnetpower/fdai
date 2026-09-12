"""Replay-safe, authority-free recording of authenticated measurement sources."""

from __future__ import annotations

from fdai_service_contracts.metric_observation import MetricObservationV1
from fdai_service_contracts.ontology_query import content_digest

from fdai.shared.providers.state_store import StateStore

MAX_METRIC_REVISIONS = 64


class MetricObservationConflictError(ValueError):
    """A source contradicts an immutable record or the current correction head."""


class MetricObservationRecorder:
    """Persist bounded correction chains through the StateStore audit transaction.

    Only producer-owned source adapters call this recorder; validating a wire model
    does not authenticate its source. Each event and metric has one immutable source
    binding. Atomic revision checks prevent competing corrections and mixed sources.
    The stored projection may advance, but every observation stays in append-only audit.
    """

    def __init__(self, store: StateStore) -> None:
        self._store = store

    async def record(self, observation: MetricObservationV1) -> bool:
        """Return whether new evidence was recorded; reject conflicts without writes."""

        observation = MetricObservationV1.model_validate(observation.model_dump(mode="json"))
        identity = content_digest(
            {"event_id": observation.event_id, "metric_id": observation.metric_id}
        )
        key = f"measurement:metric:{identity.removeprefix('sha256:')}"
        current = await self._store.read_state(key)
        history: list[str] = []
        revision = 0
        if current is not None:
            previous = MetricObservationV1.model_validate(current["observation"])
            if (
                previous.source_id != observation.source_id
                or previous.source_record_id != observation.source_record_id
                or previous.synthetic != observation.synthetic
                or previous.mode != observation.mode
                or previous.arm != observation.arm
                or previous.measurement_protocol_digest != observation.measurement_protocol_digest
                or previous.source_revision != observation.source_revision
            ):
                raise MetricObservationConflictError("metric source binding changed")
            history = list(current["observation_ids"])
            if observation.observation_id in history:
                return False
            if observation.supersedes_observation_id != previous.observation_id:
                raise MetricObservationConflictError("metric correction is not the current head")
            if (
                observation.observed_at < previous.observed_at
                or observation.recorded_at < previous.recorded_at
            ):
                raise MetricObservationConflictError("metric correction timestamps moved backward")
            revision = int(current["revision"])
        elif observation.supersedes_observation_id is not None:
            raise MetricObservationConflictError("metric correction predecessor is missing")
        if len(history) >= MAX_METRIC_REVISIONS:
            raise MetricObservationConflictError("metric correction limit exceeded")

        payload = observation.model_dump(mode="json")
        state = {
            "revision": revision + 1,
            "observation": payload,
            "observation_ids": [*history, observation.observation_id],
        }
        audit = observation.to_audit_entry()
        if current is None:
            created = await self._store.write_state_with_audit_if_absent(key, state, audit)
        else:
            created = await self._store.compare_and_set_state_with_audit(
                key, state, expected_revision=revision, audit_entry=audit
            )
        if created:
            return True
        winner = await self._store.read_state(key)
        if winner is not None and observation.observation_id in winner["observation_ids"]:
            return False
        raise MetricObservationConflictError(
            "metric observation changed during concurrent recording"
        )
