"""Evidence-bound copy-on-write ontology scenario branches."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

from fdai.core.operational_context import OperationalEvidenceBundle
from fdai.shared.contracts.models import OntologyLinkType, OntologyObjectType
from fdai.shared.providers.ontology_instance import (
    OntologyGraphSnapshot,
    OntologyLinkRecord,
    OntologyObjectRecord,
)
from fdai.shared.providers.testing import InMemoryOntologyInstanceStore

_BRANCH_ID = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
_MAX_CHANGES = 10_000


@dataclass(frozen=True, slots=True)
class OntologyScenarioChangeSet:
    """Bounded immutable overlay operations for one scenario materialization."""

    upsert_objects: tuple[OntologyObjectRecord, ...] = ()
    delete_object_ids: tuple[str, ...] = ()
    upsert_links: tuple[OntologyLinkRecord, ...] = ()
    delete_link_keys: tuple[tuple[str, str, str], ...] = ()

    def __post_init__(self) -> None:
        change_count = sum(
            len(items)
            for items in (
                self.upsert_objects,
                self.delete_object_ids,
                self.upsert_links,
                self.delete_link_keys,
            )
        )
        if change_count > _MAX_CHANGES:
            raise ValueError("ontology scenario change set exceeds its bound")
        upsert_ids = [item.id for item in self.upsert_objects]
        if len(upsert_ids) != len(set(upsert_ids)):
            raise ValueError("ontology scenario object upserts MUST be unique")
        if len(self.delete_object_ids) != len(set(self.delete_object_ids)):
            raise ValueError("ontology scenario object deletes MUST be unique")
        if set(upsert_ids) & set(self.delete_object_ids):
            raise ValueError("ontology scenario cannot upsert and delete the same object")
        upsert_link_keys = [_link_key(item) for item in self.upsert_links]
        if len(upsert_link_keys) != len(set(upsert_link_keys)):
            raise ValueError("ontology scenario link upserts MUST be unique")
        if len(self.delete_link_keys) != len(set(self.delete_link_keys)):
            raise ValueError("ontology scenario link deletes MUST be unique")
        if set(upsert_link_keys) & set(self.delete_link_keys):
            raise ValueError("ontology scenario cannot upsert and delete the same link")


@dataclass(frozen=True, slots=True)
class OntologyScenarioResult:
    """Validated branch graph and replay identity with no production authority."""

    branch_id: str
    base_digest: str
    evidence_bundle_digest: str
    scenario_digest: str
    graph: OntologyGraphSnapshot
    production_write: bool = False
    mutation_authority: bool = False
    execution_authority: bool = False
    promotion_required: bool = True


class OntologyScenarioBranch:
    """Materialize a copy-on-write overlay against one exact evidence bundle."""

    def __init__(
        self,
        *,
        branch_id: str,
        evidence_bundle: OperationalEvidenceBundle,
        base: OntologyGraphSnapshot,
        object_types: tuple[OntologyObjectType, ...],
        link_types: tuple[OntologyLinkType, ...],
    ) -> None:
        if _BRANCH_ID.fullmatch(branch_id) is None:
            raise ValueError("ontology scenario branch_id is invalid")
        self._branch_id = branch_id
        self._evidence_bundle = evidence_bundle
        self._base = base
        self._object_types = object_types
        self._link_types = link_types
        self._base_digest = _graph_digest(base)

    async def materialize(self, changes: OntologyScenarioChangeSet) -> OntologyScenarioResult:
        """Validate and return one branch graph without receiving a production store."""

        objects = {item.id: item for item in self._base.objects}
        links = {_link_key(item): item for item in self._base.links}
        for object_id in changes.delete_object_ids:
            objects.pop(object_id, None)
        for link_key in changes.delete_link_keys:
            links.pop(link_key, None)
        for object_record in changes.upsert_objects:
            objects[object_record.id] = object_record
        for link_record in changes.upsert_links:
            links[_link_key(link_record)] = link_record
        graph = OntologyGraphSnapshot(
            objects=tuple(objects[key] for key in sorted(objects)),
            links=tuple(links[key] for key in sorted(links)),
        )
        validator = InMemoryOntologyInstanceStore(
            object_types=self._object_types,
            link_types=self._link_types,
        )
        for object_record in graph.objects:
            await validator.upsert_object(object_record)
        for link_record in graph.links:
            await validator.upsert_link(link_record)
        scenario_digest = _scenario_digest(
            branch_id=self._branch_id,
            base_digest=self._base_digest,
            evidence_bundle_digest=self._evidence_bundle.digest,
            graph=graph,
        )
        return OntologyScenarioResult(
            branch_id=self._branch_id,
            base_digest=self._base_digest,
            evidence_bundle_digest=self._evidence_bundle.digest,
            scenario_digest=scenario_digest,
            graph=graph,
        )


def _link_key(record: OntologyLinkRecord) -> tuple[str, str, str]:
    return record.from_id, record.link_type, record.to_id


def _scenario_digest(
    *,
    branch_id: str,
    base_digest: str,
    evidence_bundle_digest: str,
    graph: OntologyGraphSnapshot,
) -> str:
    payload = {
        "branch_id": branch_id,
        "base_digest": base_digest,
        "evidence_bundle_digest": evidence_bundle_digest,
        "graph_digest": _graph_digest(graph),
        "production_write": False,
        "mutation_authority": False,
        "execution_authority": False,
        "promotion_required": True,
    }
    return _digest(payload)


def _graph_digest(graph: OntologyGraphSnapshot) -> str:
    payload = {
        "objects": [
            {
                "id": item.id,
                "object_type": item.object_type,
                "properties": dict(item.properties),
                "revision": item.revision,
            }
            for item in sorted(graph.objects, key=lambda record: record.id)
        ],
        "links": [
            {
                "from_id": item.from_id,
                "link_type": item.link_type,
                "to_id": item.to_id,
                "properties": dict(item.properties),
            }
            for item in sorted(graph.links, key=_link_key)
        ],
    }
    return _digest(payload)


def _digest(value: object) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


__all__ = [
    "OntologyScenarioBranch",
    "OntologyScenarioChangeSet",
    "OntologyScenarioResult",
]
