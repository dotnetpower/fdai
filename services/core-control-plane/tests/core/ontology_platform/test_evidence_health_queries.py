"""Sanitized ontology evidence-health query tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from fdai.core.ontology_platform.evidence_health_queries import (
    ONTOLOGY_EVIDENCE_HEALTH_FUNCTION_NAME,
    OntologyEvidenceHealthRead,
    OntologyEvidenceHealthSnapshot,
    ontology_evidence_health_function,
    ontology_evidence_health_function_type,
)
from fdai.core.ontology_platform.functions import (
    FunctionInvocationContext,
    OntologyFunctionRegistry,
)
from fdai.shared.contracts.models import CeilingRole, OntologyObjectType, PropertyDecl, PropertyType
from fdai.shared.ontology.release import build_ontology_release

NOW = datetime(2026, 8, 19, 12, tzinfo=UTC)


class _Reader:
    def __init__(self, result: OntologyEvidenceHealthRead) -> None:
        self.result = result

    async def read(self, *, object_type: str, ontology_release_digest: str):
        assert object_type == "Resource"
        assert ontology_release_digest.startswith("sha256:")
        return self.result


def _runtime(result: OntologyEvidenceHealthRead):
    resource = OntologyObjectType(
        schema_version="1.0.0",
        name="Resource",
        version="1.0.0",
        key="id",
        properties={"id": PropertyDecl(type=PropertyType.STRING, required=True)},
    )
    function_type = ontology_evidence_health_function_type()
    release = build_ontology_release(object_types=(resource,), function_types=(function_type,))
    snapshot = result.snapshot
    if snapshot is not None:
        result = OntologyEvidenceHealthRead(
            snapshot=replace(snapshot, ontology_release_digest=release.digest)
        )
    registry = OntologyFunctionRegistry(release=release)
    registry.register_contextual(
        function_type,
        ontology_evidence_health_function(
            release,
            object_type_names=frozenset({"Resource"}),
            reader=_Reader(result),
            now=lambda: NOW,
        ),
    )
    return registry


def _context() -> FunctionInvocationContext:
    return FunctionInvocationContext(
        caller_agent="Bragi",
        caller_role=CeilingRole.READER,
        purposes=("operations-review",),
    )


async def test_verified_zero_is_available_and_distinct_from_unavailable() -> None:
    snapshot = OntologyEvidenceHealthSnapshot(
        source_kind="inventory",
        source_alias="active-inventory",
        generation="generation-1",
        ontology_release_digest="sha256:" + "0" * 64,
        observed_at=NOW - timedelta(seconds=5),
        recorded_at=NOW - timedelta(seconds=4),
        freshness_ceiling_seconds=60,
        complete=True,
        truncated=False,
        synthetic=False,
        conflicts=(),
        drop_reasons=(),
        visible_instance_count=0,
        visible_link_count=0,
        evidence_refs=("inventory:generation-1",),
    )
    available = await _runtime(OntologyEvidenceHealthRead(snapshot=snapshot)).invoke(
        ONTOLOGY_EVIDENCE_HEALTH_FUNCTION_NAME,
        {"object_type": "Resource"},
        context=_context(),
    )
    unavailable = await _runtime(
        OntologyEvidenceHealthRead(snapshot=None, unavailable_reason="source_not_ready")
    ).invoke(
        ONTOLOGY_EVIDENCE_HEALTH_FUNCTION_NAME,
        {"object_type": "Resource"},
        context=_context(),
    )

    available_values = available["rows"][0]["values"]
    unavailable_values = unavailable["rows"][0]["values"]
    assert available_values["availability"] == "available"
    assert available_values["visible_instance_count"] == 0
    assert available_values["complete"] is True
    assert unavailable_values["availability"] == "unavailable"
    assert unavailable_values["visible_instance_count"] is None
    assert unavailable["truncation_reason"] == "source_unavailable"
