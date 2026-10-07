"""Dry-run change set against a current-state snapshot.

The snapshot has the same shape as the Hub's reported state: an installation-owned ``digest``,
the schema revision, and each Entity's Release id, artifact digests, and health. The Hub echoes
the snapshot ``digest`` into the Plan as ``source_state_digest``.

Until the workload render story (#1946) exists, the desired state of each Plan Entity is the
target Release id and the image digests of the signed Release. Nothing here talks to Kubernetes
or Azure; the change set is a description, never an apply.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal

from fdai_deployment_cli.contracts import canonical_bytes
from fdai_deployment_cli.lifecycle_plan import LifecyclePlan

from fdai_lifecycle_agent.inputs import VerifiedRelease
from fdai_lifecycle_agent.strict_json import load_json, read_limited

_MAX_STATE_BYTES = 1024 * 1024
_STATE_KEYS = frozenset({"digest", "schema_revision", "entities", "observed_at"})
_ENTITY_KEYS = frozenset({"release_id", "artifact_digests", "health"})
_STATE_DIGEST = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_ARTIFACT_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z", re.ASCII)

type ChangeAction = Literal["create", "update", "unchanged"]


class Health(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class EntityState:
    release_id: str
    artifact_digests: frozenset[str]
    health: Health = Health.UNKNOWN


@dataclass(frozen=True, slots=True)
class CurrentState:
    """Observed lifecycle state of the installation's Entities."""

    digest: str
    schema_revision: int
    entities: Mapping[str, EntityState]
    observed_at: datetime

    def __post_init__(self) -> None:
        if _STATE_DIGEST.fullmatch(self.digest) is None:
            raise ValueError("current state digest MUST be 64 lowercase hex characters")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("current state observed_at MUST include timezone information")


@dataclass(frozen=True, slots=True)
class EntityChange:
    entity_id: str
    action: ChangeAction


@dataclass(frozen=True, slots=True)
class ChangeSet:
    """The change the agent would make for one Plan, in Entity order. Never applied."""

    plan_type: str
    changes: tuple[EntityChange, ...]

    @property
    def entity_ids(self) -> frozenset[str]:
        return frozenset(change.entity_id for change in self.changes)

    def sanitized_summary(self) -> str:
        """Counts only, as compact JSON. Entity ids, digests, and identifiers stay local."""

        counts = {action: 0 for action in ("create", "update", "unchanged")}
        for change in self.changes:
            counts[change.action] += 1
        document = {"plan_type": self.plan_type, "entity_count": len(self.changes), **counts}
        return canonical_bytes(document).decode("ascii")


type ChangeSetCalculator = Callable[[LifecyclePlan, VerifiedRelease, CurrentState], ChangeSet]


def compute_change_set(
    plan: LifecyclePlan, release: VerifiedRelease, current: CurrentState
) -> ChangeSet:
    """Compare each Plan Entity with the target Release. An Entity is unchanged when it already
    runs the target Release id with images from that Release. Entities outside the Plan are left
    untouched, so this computation never produces a delete."""

    changes: list[EntityChange] = []
    for entity_id in sorted(plan.entity_ids):
        observed = current.entities.get(entity_id)
        action: ChangeAction
        if observed is None:
            action = "create"
        elif (
            observed.release_id == plan.target_release_id
            and observed.artifact_digests <= release.artifact_digests
        ):
            action = "unchanged"
        else:
            action = "update"
        changes.append(EntityChange(entity_id=entity_id, action=action))
    return ChangeSet(plan_type=plan.plan_type, changes=tuple(changes))


def load_current_state(path: Path) -> CurrentState:
    """Load a strict current-state snapshot or raise ``ValueError``."""

    try:
        raw = read_limited(path, limit=_MAX_STATE_BYTES, label="current state")
    except OSError as error:
        raise ValueError(f"current state is unreadable: {type(error).__name__}") from error
    return parse_current_state(load_json(raw, label="current state"))


def parse_current_state(document: object) -> CurrentState:
    if not isinstance(document, dict) or set(document) != _STATE_KEYS:
        raise ValueError(
            "current state MUST contain digest, schema_revision, entities, observed_at"
        )
    digest, revision, raw_entities = (
        document["digest"],
        document["schema_revision"],
        document["entities"],
    )
    if not isinstance(digest, str):
        raise ValueError("current state digest MUST be a string")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise ValueError("current state schema_revision MUST be a non-negative integer")
    if not isinstance(raw_entities, dict):
        raise ValueError("current state entities MUST be an object")
    entities = {str(entity_id): _parse_entity(record) for entity_id, record in raw_entities.items()}
    observed_at = document["observed_at"]
    if not isinstance(observed_at, str):
        raise ValueError("current state observed_at MUST be a string")
    try:
        observed = datetime.fromisoformat(observed_at)
    except ValueError as error:
        raise ValueError("current state observed_at MUST be ISO 8601") from error
    return CurrentState(
        digest=digest, schema_revision=revision, entities=entities, observed_at=observed
    )


def _parse_entity(record: object) -> EntityState:
    if not isinstance(record, dict) or set(record) != _ENTITY_KEYS:
        raise ValueError("current state entity MUST contain release_id, artifact_digests, health")
    release_id, artifacts, health = (
        record["release_id"],
        record["artifact_digests"],
        record["health"],
    )
    if not isinstance(release_id, str) or not release_id:
        raise ValueError("current state release_id MUST be a non-empty string")
    if not isinstance(artifacts, list) or not all(
        isinstance(item, str) and _ARTIFACT_DIGEST.fullmatch(item) for item in artifacts
    ):
        raise ValueError("current state artifact_digests MUST be sha256:<hex> strings")
    if health not in Health:
        raise ValueError("current state health is unsupported")
    return EntityState(
        release_id=release_id, artifact_digests=frozenset(artifacts), health=Health(health)
    )
