"""Bounded correction-aware rebuilding of inert scalar challenger candidates."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime

from fdai.core.assurance_twin.effect_model import (
    EffectModel,
    EffectModelStatus,
    update_challenger,
)
from fdai.shared.contracts.models import ResponseOutcome

MAX_REBUILD_RECORDS = 1024


@dataclass(frozen=True, slots=True)
class FeedbackRebuildCandidate:
    """Replay evidence, not a model activation or an execution instruction."""

    model: EffectModel
    source_digests: tuple[str, ...]
    input_manifest_digest: str
    accepted_episodes: int
    held_episodes: int
    as_of: datetime
    replay_order: tuple[str, ...]
    execution_authority: bool = field(default=False, init=False)
    promotion_authority: bool = field(default=False, init=False)


def latest_feedback_revisions(
    outcomes: tuple[ResponseOutcome, ...], *, as_of: datetime
) -> tuple[ResponseOutcome, ...]:
    if as_of.tzinfo is None:
        raise ValueError("feedback rebuild as-of time MUST be timezone-aware")
    if len(outcomes) > MAX_REBUILD_RECORDS:
        raise ValueError("feedback rebuild input exceeds its bounded record limit")
    chains: dict[str, dict[int, ResponseOutcome]] = {}
    idempotency_owners: dict[str, str] = {}
    prediction_owners: dict[tuple[str, str | None], str] = {}
    for outcome in outcomes:
        if outcome.recorded_at > as_of:
            continue
        if outcome.schema_version != "1.1.0" or outcome.outcome_revision is None:
            raise ValueError("feedback rebuild requires explicitly versioned outcomes")
        identity = str(outcome.outcome_id)
        owner = idempotency_owners.setdefault(outcome.idempotency_key, identity)
        if owner != identity:
            raise ValueError("feedback rebuild idempotency key is bound to another outcome")
        prediction = (str(outcome.action_id), outcome.prediction_id)
        owner = prediction_owners.setdefault(prediction, identity)
        if owner != identity:
            raise ValueError("feedback rebuild prediction identity is bound to another outcome")
        chain = chains.setdefault(str(outcome.outcome_id), {})
        existing = chain.get(outcome.outcome_revision)
        if existing is not None and existing.revision_digest != outcome.revision_digest:
            raise ValueError("feedback rebuild contains a conflicting immutable outcome revision")
        chain[outcome.outcome_revision] = outcome
    latest: list[ResponseOutcome] = []
    for chain in chains.values():
        previous: ResponseOutcome | None = None
        previous_revision = 0
        for revision, outcome in sorted(chain.items()):
            if previous is None:
                if revision != 1 or outcome.previous_revision_digest is not None:
                    raise ValueError("feedback rebuild outcome predecessor is missing")
            elif (
                revision != previous_revision + 1
                or outcome.previous_revision_digest != previous.revision_digest
                or outcome.event_id != previous.event_id
                or outcome.action_id != previous.action_id
                or outcome.action_type_id != previous.action_type_id
                or outcome.target_digest != previous.target_digest
                or outcome.decision != previous.decision
                or outcome.execution_mode != previous.execution_mode
                or outcome.prediction_id != previous.prediction_id
                or outcome.prediction_snapshot != previous.prediction_snapshot
                or outcome.predicted_at != previous.predicted_at
                or outcome.observation_deadline != previous.observation_deadline
                or outcome.metric != previous.metric
                or outcome.recorded_at < previous.recorded_at
            ):
                raise ValueError("feedback rebuild outcome lineage is invalid")
            previous = outcome
            previous_revision = revision
        if previous is not None:
            latest.append(previous)
    return tuple(sorted(latest, key=lambda item: (item.recorded_at, str(item.outcome_id))))


def rebuild_feedback(
    *,
    seed: EffectModel,
    outcomes: tuple[ResponseOutcome, ...],
    as_of: datetime,
    complete: bool,
    replay_order: tuple[str, ...] = (),
) -> FeedbackRebuildCandidate:
    """Replay a complete fixed source set without subtracting non-reversible statistics."""
    if not complete:
        raise ValueError("feedback rebuild requires complete authoritative source coverage")
    if seed.status is not EffectModelStatus.CHALLENGER:
        raise ValueError("feedback rebuild MUST NOT replace an active model")
    latest = latest_feedback_revisions(outcomes, as_of=as_of)
    as_of = as_of.astimezone(UTC)
    groups: dict[str, list[ResponseOutcome]] = {}
    unavailable = 0
    for outcome in latest:
        snapshot = outcome.prediction_snapshot
        if snapshot is None:
            if not outcome.scorable:
                unavailable += 1
                continue
            raise ValueError("feedback rebuild requires frozen prediction provenance")
        groups.setdefault(snapshot.independence_key, []).append(outcome)
    by_id = {str(item.outcome_id): item for item in latest}
    if len(replay_order) != len(set(replay_order)) or any(
        identity not in by_id for identity in replay_order
    ):
        raise ValueError("feedback rebuild replay order is incomplete or conflicting")
    initial_times = {
        str(item.outcome_id): item.recorded_at
        for item in outcomes
        if item.outcome_revision == 1 and item.recorded_at <= as_of
    }
    selected: dict[str, ResponseOutcome] = {}
    for identity in replay_order:
        item = by_id[identity]
        if item.prediction_snapshot is None:
            continue
        group = item.prediction_snapshot.independence_key
        if group in selected:
            raise ValueError("feedback rebuild replay order repeats an independent episode")
        selected[group] = item
    for group, items in groups.items():
        if group in selected:
            continue
        ordered = sorted(
            items, key=lambda item: (initial_times[str(item.outcome_id)], str(item.outcome_id))
        )
        selected[group] = next(
            (
                item
                for item in ordered
                if update_challenger(seed, item, learning_cutoff=seed.learned_through).accepted
            ),
            ordered[0],
        )
    priority = {identity: position for position, identity in enumerate(replay_order)}
    ordered_selected = sorted(
        selected.values(),
        key=lambda item: (
            priority.get(str(item.outcome_id), len(priority)),
            initial_times[str(item.outcome_id)],
            str(item.outcome_id),
        ),
    )
    rebuilt = seed
    accepted = 0
    held = unavailable
    for item in ordered_selected:
        update = update_challenger(rebuilt, item, learning_cutoff=seed.learned_through)
        if update.accepted:
            rebuilt = update.model
            accepted += 1
        else:
            held += 1
    source_digests = tuple(
        sorted({item.revision_digest for item in outcomes if item.recorded_at <= as_of})
    )
    seed_values = asdict(seed)
    seed_values["learned_at"] = seed.learned_at.astimezone(UTC).isoformat()
    seed_values["learned_through"] = seed.learned_through.astimezone(UTC).isoformat()
    for field_name in ("bias_correction", "mean_absolute_error", "interval_radius"):
        value = float(seed_values[field_name])
        seed_values[field_name] = 0.0 if value == 0.0 else value
    manifest = {
        "source_digests": source_digests,
        "seed": seed_values,
        "as_of": as_of.isoformat(),
        "replay_order": [str(item.outcome_id) for item in ordered_selected],
    }
    digest = hashlib.sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()
    return FeedbackRebuildCandidate(
        rebuilt,
        source_digests,
        digest,
        accepted,
        held,
        as_of,
        tuple(str(item.outcome_id) for item in ordered_selected),
    )
