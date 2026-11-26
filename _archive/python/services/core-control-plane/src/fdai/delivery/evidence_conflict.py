"""Durable append-only history and CAS current projection for evidence conflicts."""

from __future__ import annotations

from collections.abc import Mapping

from fdai.core.ontology_platform.evidence_conflict import (
    EvidenceConflictRevision,
    EvidenceConflictStatus,
)
from fdai.shared.providers.event_bus import EventBus
from fdai.shared.providers.state_store import StateStore

_HISTORY_PREFIX = "runtime:evidence-conflict:revision:"
_CURRENT_PREFIX = "runtime:evidence-conflict:current:"
_MAX_CURRENT_CONFLICTS = 1_000


class EvidenceConflictProjectionError(RuntimeError):
    """The current projection rejected a stale, conflicting, or racing revision."""


class StateStoreEvidenceConflictProjection:
    """Muninn-owned durable history and current index."""

    def __init__(self, store: StateStore) -> None:
        self._store = store

    async def append(self, revision: EvidenceConflictRevision) -> bool:
        """Append one revision and atomically advance its exact slot."""

        history_key = f"{_HISTORY_PREFIX}{revision.revision_ref}"
        history = revision.model_dump(mode="json")
        created = await self._store.write_state_with_audit_if_absent(
            history_key,
            history,
            {
                "action_kind": "evidence_conflict.revision_appended",
                "actor": "Muninn",
                "conflict_id": revision.id,
                "revision_ref": revision.revision_ref,
                "status": revision.status.value,
            },
        )
        if not created:
            existing_history = await self._store.read_state(history_key)
            if existing_history is None or dict(existing_history) != history:
                raise EvidenceConflictProjectionError("evidence-conflict revision identity changed")
        current_key = f"{_CURRENT_PREFIX}{revision.slot_ref}"
        current = await self._store.read_state(current_key)
        if current is None:
            if revision.supersedes_revision_ref is not None:
                raise EvidenceConflictProjectionError(
                    "first evidence-conflict revision MUST NOT supersede another revision"
                )
            record = _current_record(revision, state_revision=1)
            if await self._store.write_state_with_audit_if_absent(
                current_key,
                record,
                _current_audit(revision),
            ):
                return created
            current = await self._store.read_state(current_key)
        if current is None:
            raise EvidenceConflictProjectionError(
                "evidence-conflict current projection disappeared"
            )
        parsed, state_revision = _parse_current(current)
        if parsed.revision_ref == revision.revision_ref:
            return created
        if revision.supersedes_revision_ref != parsed.revision_ref:
            raise EvidenceConflictProjectionError(
                "evidence-conflict revision does not supersede current state"
            )
        updated = _current_record(revision, state_revision=state_revision + 1)
        advanced = await self._store.compare_and_set_state_with_audit(
            current_key,
            updated,
            expected_revision=state_revision,
            audit_entry=_current_audit(revision),
        )
        if not advanced:
            raise EvidenceConflictProjectionError(
                "evidence-conflict current projection changed concurrently"
            )
        return created

    async def current(self, slot_ref: str) -> EvidenceConflictRevision | None:
        """Read one exact current slot."""

        raw = await self._store.read_state(f"{_CURRENT_PREFIX}{slot_ref}")
        return None if raw is None else _parse_current(raw)[0]

    async def active_for(
        self,
        *,
        target_ref: str,
        semantic_refs: frozenset[str],
    ) -> tuple[EvidenceConflictRevision, ...]:
        """Return unresolved current conflicts intersecting exact semantic requirements."""

        rows = await self._store.read_states(_CURRENT_PREFIX, limit=_MAX_CURRENT_CONFLICTS)
        matched: list[EvidenceConflictRevision] = []
        for row in rows:
            revision, _ = _parse_current(row)
            if (
                revision.status is EvidenceConflictStatus.ACTIVE
                and revision.target_ref == target_ref
                and semantic_refs.intersection(revision.semantic_refs)
            ):
                matched.append(revision)
        return tuple(sorted(matched, key=lambda item: item.slot_ref))


class EventBusEvidenceConflictCandidatePublisher:
    """Publish deterministic candidates through Huginn's typed event ingress."""

    def __init__(self, *, event_bus: EventBus, topic: str) -> None:
        if not topic.strip():
            raise ValueError("evidence-conflict candidate topic MUST be non-empty")
        self._event_bus = event_bus
        self._topic = topic

    async def publish(self, revision: EvidenceConflictRevision) -> None:
        """Publish one replay-stable candidate keyed by its exact conflict slot."""

        await self._event_bus.publish(
            self._topic,
            revision.slot_ref,
            {
                "producer_principal": "Huginn",
                "correlation_id": revision.slot_ref,
                "idempotency_key": revision.revision_ref,
                "event_id": f"event:{revision.revision_ref}",
                "event_type": "evidence.conflict.candidate.v1",
                "detected_at": revision.evidence_cutoff.isoformat(),
                "resource_id": revision.target_ref,
                "attributes": {
                    field: value
                    for field, value in revision.model_dump(mode="json").items()
                    if field
                    not in {
                        "schema_version",
                        "id",
                        "slot_ref",
                        "revision_ref",
                        "producer_principal",
                        "execution_authority",
                        "mutation_authority",
                    }
                },
            },
        )


def _current_record(
    revision: EvidenceConflictRevision,
    *,
    state_revision: int,
) -> dict[str, object]:
    return {
        "kind": "evidence_conflict.current",
        "revision": state_revision,
        "conflict": revision.model_dump(mode="json"),
    }


def _current_audit(revision: EvidenceConflictRevision) -> dict[str, object]:
    return {
        "action_kind": "evidence_conflict.current_advanced",
        "actor": "Muninn",
        "conflict_id": revision.id,
        "revision_ref": revision.revision_ref,
        "status": revision.status.value,
    }


def _parse_current(
    value: Mapping[str, object],
) -> tuple[EvidenceConflictRevision, int]:
    state_revision = value.get("revision")
    if (
        value.get("kind") != "evidence_conflict.current"
        or isinstance(state_revision, bool)
        or not isinstance(state_revision, int)
        or state_revision < 1
    ):
        raise EvidenceConflictProjectionError("evidence-conflict current record is malformed")
    try:
        revision = EvidenceConflictRevision.model_validate(value.get("conflict"))
    except ValueError as exc:
        raise EvidenceConflictProjectionError(
            "evidence-conflict current revision is malformed"
        ) from exc
    return revision, state_revision


__all__ = [
    "EventBusEvidenceConflictCandidatePublisher",
    "EvidenceConflictProjectionError",
    "StateStoreEvidenceConflictProjection",
]
