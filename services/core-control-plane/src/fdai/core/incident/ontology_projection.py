"""Project canonical Incident state into the current ontology read model."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from fdai.shared.contracts.models import Incident
from fdai.shared.providers.ontology_instance import (
    OntologyInstanceStore,
    OntologyInstanceValidationError,
    OntologyObjectRecord,
    normalize_object_record,
)


class IncidentOntologyProjector:
    """Maintain one idempotent current-state object per durable Incident."""

    def __init__(self, *, store: OntologyInstanceStore) -> None:
        self._store = store

    async def project(
        self,
        incident: Incident,
        *,
        updated_at: datetime,
    ) -> OntologyObjectRecord:
        """Upsert one audit-backed Incident without manufacturing revisions on replay."""
        incident_id = str(incident.incident_id)
        candidate = normalize_object_record(
            OntologyObjectRecord(
                id=incident_id,
                object_type="Incident",
                properties={
                    "id": incident_id,
                    "correlation_id": incident_id,
                    "status": incident.state.value,
                    "severity": incident.severity.value,
                    "opened_at": incident.opened_at,
                    "updated_at": updated_at,
                },
            )
        )
        current = await self._store.get_object(incident_id)
        if current is not None:
            if current.object_type != candidate.object_type:
                raise OntologyInstanceValidationError(
                    f"incident ontology object {incident_id!r} has conflicting type"
                )
            if current.properties == candidate.properties:
                return current
            candidate = replace(candidate, revision=current.revision)
        expected_revision = current.revision if current is not None else 0
        try:
            return await self._store.upsert_object(
                candidate,
                expected_revision=expected_revision,
            )
        except OntologyInstanceValidationError:
            latest = await self._store.get_object(incident_id)
            if latest is not None and latest.properties == candidate.properties:
                return latest
            raise


__all__ = ["IncidentOntologyProjector"]
