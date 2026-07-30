"""All-before-write projection of an approved operating model snapshot."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from fdai.shared.contracts.models import OntologyLinkType, OntologyObjectType
from fdai.shared.providers.ontology_instance import OntologyInstanceStore
from fdai.shared.providers.operating_model import OperatingModelSnapshot
from fdai.shared.providers.testing import InMemoryOntologyInstanceStore


@dataclass(frozen=True, slots=True)
class OperatingModelProjectionResult:
    source_revision: str
    object_count: int
    link_count: int


class OperatingModelProjector:
    """Validate the complete graph before applying records to the real store."""

    def __init__(
        self,
        *,
        store: OntologyInstanceStore,
        object_types: Sequence[OntologyObjectType],
        link_types: Sequence[OntologyLinkType],
    ) -> None:
        self._store = store
        self._object_types = tuple(object_types)
        self._link_types = tuple(link_types)

    async def project(
        self,
        snapshot: OperatingModelSnapshot,
        *,
        previous_object_ids: Sequence[str] = (),
        previous_link_keys: Sequence[tuple[str, str, str]] = (),
    ) -> OperatingModelProjectionResult:
        validator = InMemoryOntologyInstanceStore(
            object_types=self._object_types,
            link_types=self._link_types,
        )
        for record in snapshot.objects:
            await validator.upsert_object(record)
        for link in snapshot.links:
            await validator.upsert_link(link)

        await self._store.replace_subgraph(
            objects=snapshot.objects,
            links=snapshot.links,
            previous_object_ids=previous_object_ids,
            previous_link_keys=previous_link_keys,
        )
        return OperatingModelProjectionResult(
            source_revision=snapshot.source_revision,
            object_count=len(snapshot.objects),
            link_count=len(snapshot.links),
        )


__all__ = ["OperatingModelProjectionResult", "OperatingModelProjector"]
