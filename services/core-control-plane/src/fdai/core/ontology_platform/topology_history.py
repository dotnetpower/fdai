"""Bitemporal append-only topology materialization and deterministic diffs."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from fdai.shared.providers.ontology_instance import (
    OntologyGraphSnapshot,
    OntologyLinkRecord,
    OntologyObjectRecord,
    normalize_json_value,
)

_MAX_BATCHES = 1_000
_MAX_REVISIONS = 20_000


@dataclass(frozen=True, slots=True)
class TopologyObjectRevision:
    """One append-only object upsert or tombstone with event and record time."""

    object_id: str
    object_type: str
    properties_json: str
    effective_at: datetime
    recorded_at: datetime
    deleted: bool
    evidence_ref: str

    def __post_init__(self) -> None:
        _identity(self.object_id, "object_id")
        _identity(self.object_type, "object_type")
        _times(self.effective_at, self.recorded_at)
        _identity(self.evidence_ref, "evidence_ref", maximum=512)
        properties = _parse_object(self.properties_json, "object properties")
        if _canonical_json(properties) != self.properties_json:
            raise ValueError("topology object properties_json MUST be canonical")
        if self.deleted and properties:
            raise ValueError("topology object tombstone MUST NOT carry properties")

    @classmethod
    def upsert(
        cls,
        record: OntologyObjectRecord,
        *,
        effective_at: datetime,
        recorded_at: datetime,
        evidence_ref: str,
    ) -> TopologyObjectRevision:
        properties = normalize_json_value(
            record.properties,
            path=f"topology_object.{record.id}",
        )
        return cls(
            object_id=record.id,
            object_type=record.object_type,
            properties_json=_canonical_json(properties),
            effective_at=effective_at,
            recorded_at=recorded_at,
            deleted=False,
            evidence_ref=evidence_ref,
        )


@dataclass(frozen=True, slots=True)
class TopologyLinkRevision:
    """One append-only typed relationship upsert or tombstone."""

    from_id: str
    from_type: str
    link_type: str
    to_id: str
    to_type: str
    properties_json: str
    effective_at: datetime
    recorded_at: datetime
    deleted: bool
    evidence_ref: str

    def __post_init__(self) -> None:
        for name, value in (
            ("from_id", self.from_id),
            ("from_type", self.from_type),
            ("link_type", self.link_type),
            ("to_id", self.to_id),
            ("to_type", self.to_type),
        ):
            _identity(value, name)
        _times(self.effective_at, self.recorded_at)
        _identity(self.evidence_ref, "evidence_ref", maximum=512)
        properties = _parse_object(self.properties_json, "link properties")
        if _canonical_json(properties) != self.properties_json:
            raise ValueError("topology link properties_json MUST be canonical")
        if self.deleted and properties:
            raise ValueError("topology link tombstone MUST NOT carry properties")

    @property
    def key(self) -> tuple[str, str, str]:
        return self.from_id, self.link_type, self.to_id


@dataclass(frozen=True, slots=True)
class TopologyRevisionBatch:
    """One retained provider generation or delta in append-only record order."""

    revision_id: str
    provider_generation_ref: str
    effective_at: datetime
    recorded_at: datetime
    complete_snapshot: bool
    object_revisions: tuple[TopologyObjectRevision, ...] = ()
    link_revisions: tuple[TopologyLinkRevision, ...] = ()

    def __post_init__(self) -> None:
        _identity(self.revision_id, "revision_id")
        _identity(self.provider_generation_ref, "provider_generation_ref", maximum=512)
        _times(self.effective_at, self.recorded_at)
        if len(self.object_revisions) + len(self.link_revisions) > _MAX_REVISIONS:
            raise ValueError(f"topology revision batch exceeds {_MAX_REVISIONS} records")
        if any(item.recorded_at != self.recorded_at for item in self.object_revisions):
            raise ValueError("topology object recorded_at MUST match its batch")
        if any(item.recorded_at != self.recorded_at for item in self.link_revisions):
            raise ValueError("topology link recorded_at MUST match its batch")


@dataclass(frozen=True, slots=True)
class TopologyGraphAt:
    """One graph materialized at event time using evidence known at record time."""

    as_of: datetime
    known_at: datetime
    graph: OntologyGraphSnapshot
    complete: bool
    revision_ids: tuple[str, ...]
    provider_generation_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    digest: str


@dataclass(frozen=True, slots=True)
class TopologyDiff:
    """Content-addressed before/after topology change set."""

    before_digest: str
    after_digest: str
    added_object_ids: tuple[str, ...]
    removed_object_ids: tuple[str, ...]
    changed_object_ids: tuple[str, ...]
    added_link_keys: tuple[str, ...]
    removed_link_keys: tuple[str, ...]
    changed_link_keys: tuple[str, ...]
    complete: bool
    evidence_refs: tuple[str, ...]
    digest: str


class TopologyHistoryReader(Protocol):
    """Read bounded append-only revisions visible at one record-time cutoff."""

    async def read(
        self,
        *,
        as_of: datetime,
        known_at: datetime,
    ) -> Sequence[TopologyRevisionBatch]: ...


def graph_at(
    batches: Sequence[TopologyRevisionBatch],
    *,
    as_of: datetime,
    known_at: datetime,
) -> TopologyGraphAt:
    """Materialize a bounded graph without rewriting an earlier known-at view."""

    _aware(as_of, "as_of")
    _aware(known_at, "known_at")
    if as_of > known_at:
        raise ValueError("topology as_of MUST NOT exceed known_at")
    if len(batches) > _MAX_BATCHES:
        raise ValueError(f"topology history exceeds {_MAX_BATCHES} batches")
    eligible = tuple(
        sorted(
            (
                batch
                for batch in batches
                if batch.effective_at <= as_of and batch.recorded_at <= known_at
            ),
            key=lambda item: (item.recorded_at, item.revision_id),
        )
    )
    duplicate_ids = [item.revision_id for item in eligible]
    if len(duplicate_ids) != len(set(duplicate_ids)):
        raise ValueError("topology revision ids MUST be unique")
    baseline_index = max(
        (index for index, item in enumerate(eligible) if item.complete_snapshot),
        default=None,
    )
    selected = eligible[baseline_index:] if baseline_index is not None else eligible
    objects: dict[str, TopologyObjectRevision] = {}
    links: dict[tuple[str, str, str], TopologyLinkRevision] = {}
    for batch in selected:
        if batch.complete_snapshot:
            objects.clear()
            links.clear()
        for object_revision in sorted(
            batch.object_revisions,
            key=lambda item: (item.effective_at, item.object_id, item.recorded_at),
        ):
            prior = objects.get(object_revision.object_id)
            if object_revision.effective_at <= as_of and (
                prior is None
                or (object_revision.effective_at, object_revision.recorded_at)
                >= (prior.effective_at, prior.recorded_at)
            ):
                objects[object_revision.object_id] = object_revision
        for link_revision in sorted(
            batch.link_revisions,
            key=lambda item: (item.effective_at, item.key, item.recorded_at),
        ):
            prior_link = links.get(link_revision.key)
            if link_revision.effective_at <= as_of and (
                prior_link is None
                or (link_revision.effective_at, link_revision.recorded_at)
                >= (prior_link.effective_at, prior_link.recorded_at)
            ):
                links[link_revision.key] = link_revision
    materialized_objects = tuple(
        OntologyObjectRecord(
            id=item.object_id,
            object_type=item.object_type,
            properties=_parse_object(item.properties_json, "object properties"),
        )
        for item in sorted(objects.values(), key=lambda item: item.object_id)
        if not item.deleted
    )
    object_ids = {item.id for item in materialized_objects}
    materialized_links = tuple(
        OntologyLinkRecord(
            from_id=item.from_id,
            link_type=item.link_type,
            to_id=item.to_id,
            properties=_parse_object(item.properties_json, "link properties"),
        )
        for item in sorted(links.values(), key=lambda item: item.key)
        if not item.deleted and item.from_id in object_ids and item.to_id in object_ids
    )
    graph = OntologyGraphSnapshot(objects=materialized_objects, links=materialized_links)
    evidence_refs = [
        item.evidence_ref for item in sorted(objects.values(), key=lambda item: item.object_id)
    ]
    evidence_refs.extend(
        item.evidence_ref for item in sorted(links.values(), key=lambda item: item.key)
    )
    refs = tuple(dict.fromkeys(evidence_refs))
    body = {
        "as_of": as_of.astimezone(UTC).isoformat(),
        "known_at": known_at.astimezone(UTC).isoformat(),
        "objects": [
            {
                "id": item.id,
                "object_type": item.object_type,
                "properties": item.properties,
                "revision": item.revision,
            }
            for item in graph.objects
        ],
        "links": [
            {
                "from_id": item.from_id,
                "link_type": item.link_type,
                "to_id": item.to_id,
                "properties": item.properties,
            }
            for item in graph.links
        ],
        "complete": baseline_index is not None,
        "revision_ids": [item.revision_id for item in selected],
        "provider_generation_refs": [item.provider_generation_ref for item in selected],
        "evidence_refs": refs,
    }
    return TopologyGraphAt(
        as_of=as_of,
        known_at=known_at,
        graph=graph,
        complete=baseline_index is not None,
        revision_ids=tuple(item.revision_id for item in selected),
        provider_generation_refs=tuple(item.provider_generation_ref for item in selected),
        evidence_refs=refs,
        digest=_digest(body),
    )


def topology_diff(before: TopologyGraphAt, after: TopologyGraphAt) -> TopologyDiff:
    """Return deterministic object and relationship changes between two retained views."""

    before_objects = {item.id: item for item in before.graph.objects}
    after_objects = {item.id: item for item in after.graph.objects}
    before_links = {_link_key(item): item for item in before.graph.links}
    after_links = {_link_key(item): item for item in after.graph.links}
    added_object_ids = tuple(sorted(after_objects.keys() - before_objects.keys()))
    removed_object_ids = tuple(sorted(before_objects.keys() - after_objects.keys()))
    changed_object_ids = tuple(
        sorted(
            key
            for key in before_objects.keys() & after_objects.keys()
            if before_objects[key] != after_objects[key]
        )
    )
    added_link_keys = tuple(sorted(after_links.keys() - before_links.keys()))
    removed_link_keys = tuple(sorted(before_links.keys() - after_links.keys()))
    changed_link_keys = tuple(
        sorted(
            key
            for key in before_links.keys() & after_links.keys()
            if before_links[key] != after_links[key]
        )
    )
    complete = before.complete and after.complete
    evidence_refs = tuple(dict.fromkeys((*before.evidence_refs, *after.evidence_refs)))
    body = {
        "before_digest": before.digest,
        "after_digest": after.digest,
        "added_object_ids": added_object_ids,
        "removed_object_ids": removed_object_ids,
        "changed_object_ids": changed_object_ids,
        "added_link_keys": added_link_keys,
        "removed_link_keys": removed_link_keys,
        "changed_link_keys": changed_link_keys,
        "complete": complete,
        "evidence_refs": evidence_refs,
    }
    return TopologyDiff(
        before_digest=before.digest,
        after_digest=after.digest,
        added_object_ids=added_object_ids,
        removed_object_ids=removed_object_ids,
        changed_object_ids=changed_object_ids,
        added_link_keys=added_link_keys,
        removed_link_keys=removed_link_keys,
        changed_link_keys=changed_link_keys,
        complete=complete,
        evidence_refs=evidence_refs,
        digest=_digest(body),
    )


def _link_key(record: OntologyLinkRecord) -> str:
    return f"{record.from_id}|{record.link_type}|{record.to_id}"


def _parse_object(value: str, name: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{name} MUST contain JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"{name} MUST contain an object")
    return parsed


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def _digest(value: object) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _identity(value: str, name: str, *, maximum: int = 256) -> None:
    if not value or len(value) > maximum:
        raise ValueError(f"{name} MUST be bounded and non-empty")


def _aware(value: datetime, name: str) -> None:
    if value.tzinfo is None:
        raise ValueError(f"topology {name} MUST be timezone-aware")


def _times(effective_at: datetime, recorded_at: datetime) -> None:
    _aware(effective_at, "effective_at")
    _aware(recorded_at, "recorded_at")


__all__ = [
    "TopologyDiff",
    "TopologyGraphAt",
    "TopologyHistoryReader",
    "TopologyLinkRevision",
    "TopologyObjectRevision",
    "TopologyRevisionBatch",
    "graph_at",
    "topology_diff",
]
