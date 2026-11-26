"""Verified operational state-transition FunctionType query tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fdai.core.ontology_platform.functions import FunctionInvocationContext
from fdai.core.ontology_platform.models import (
    ObjectSelector,
    ObjectSelectorKind,
    ObjectSetDefinition,
    ObjectSetMaterialization,
    ObjectSetTruncationReason,
)
from fdai.core.ontology_platform.query_gateway import (
    ObjectSetRedactionSummary,
    SecuredObjectSetQueryReceipt,
    SecuredObjectSetQueryResult,
    _projected_result_digest,
)
from fdai.core.ontology_platform.state_transitions import (
    OperationalStateTransition,
    StateTransitionAuthority,
    StateTransitionLane,
    StateTransitionRead,
    resource_state_transitions_function,
    resource_state_transitions_function_type,
)
from fdai.shared.contracts.models import CeilingRole
from fdai.shared.ontology.release import build_ontology_release
from fdai.shared.providers.ontology_instance import OntologyGraphSnapshot, OntologyObjectRecord

NOW = datetime(2026, 9, 8, 7, 0, tzinfo=UTC)


class _Reader:
    def __init__(self, result: StateTransitionRead) -> None:
        self.result = result
        self.calls = 0

    async def read(self, **_kwargs: object) -> StateTransitionRead:
        self.calls += 1
        return self.result


def _query_result(*, complete: bool) -> SecuredObjectSetQueryResult:
    declaration = resource_state_transitions_function_type()
    release = build_ontology_release(function_types=(declaration,))
    definition = ObjectSetDefinition(
        selector=ObjectSelector(kind=ObjectSelectorKind.OBJECT_TYPE, name="Resource"),
        as_of=NOW,
        purpose="operations-review",
        limit=1000,
    )
    materialization = ObjectSetMaterialization(
        definition=definition,
        graph=OntologyGraphSnapshot(
            objects=(
                OntologyObjectRecord(
                    id="resource-a",
                    object_type="Resource",
                    properties={"name": "database-a", "type": "postgresql-server"},
                ),
            ),
            links=(),
            truncated=not complete,
        ),
        concrete_types=("Resource",),
        truncated=not complete,
        truncation_reason=(None if complete else ObjectSetTruncationReason.RESULT_LIMIT),
    )
    return SecuredObjectSetQueryResult(
        materialization=materialization,
        receipt=SecuredObjectSetQueryReceipt(
            ontology_release=release.ref(),
            projected_result_digest=_projected_result_digest(materialization),
            purpose="operations-review",
            caller_role="reader",
            observation_cutoff=NOW,
            as_of_skew_seconds=0,
            returned_object_count=1,
            returned_link_count=0,
            complete=complete,
            truncated=not complete,
            truncation_reason=(None if complete else ObjectSetTruncationReason.RESULT_LIMIT),
            redactions=ObjectSetRedactionSummary(
                objects_with_redactions=0,
                redacted_identity_count=0,
                access_scope_count=0,
                purpose_binding_count=0,
                undeclared_property_count=0,
                links_with_redactions=0,
                redacted_link_property_count=0,
                removed_link_count=0,
            ),
        ),
    )


def _transition() -> OperationalStateTransition:
    return OperationalStateTransition.create(
        idempotency_key="resource-a:state:1",
        subject_ref="resource-a",
        subject_type="Resource",
        state_type="resource.operational_state",
        from_state="ready",
        to_state="updating",
        lane=StateTransitionLane.OBSERVED,
        authority=StateTransitionAuthority.PROVIDER,
        effective_at=NOW - timedelta(minutes=5),
        evidence_cutoff=NOW - timedelta(minutes=4),
        recorded_at=NOW - timedelta(minutes=3),
        source_identity="provider:inventory",
        source_revision="generation-example",
        producer_id="huginn.resource-state",
        producer_version="1.0.0",
        freshness_ceiling_seconds=600,
        completeness_basis_points=10_000,
        evidence_refs=("evidence:resource-a",),
    )


async def test_incomplete_scope_preserves_verified_positive_transition() -> None:
    reader = _Reader(
        StateTransitionRead(
            transitions=(_transition(),),
            coverage=(),
            complete=True,
            limitation=None,
        )
    )
    release = build_ontology_release(function_types=(resource_state_transitions_function_type(),))
    evaluate = resource_state_transitions_function(release, reader=reader)

    result = await evaluate(
        {
            "query_result": _query_result(complete=False).model_dump(mode="json"),
            "state_types": ["resource.operational_state"],
            "to_states": ["updating"],
            "start_at": (NOW - timedelta(hours=1)).isoformat(),
            "end_at": NOW.isoformat(),
            "known_at": NOW.isoformat(),
            "limit": 20,
        },
        FunctionInvocationContext(
            caller_agent="Bragi",
            caller_role=CeilingRole.READER,
            purposes=("operations-review",),
        ),
    )

    assert reader.calls == 1
    assert result["complete"] is False
    assert result["truncation_reason"] == "resource_scope_incomplete"
    assert [row["values"]["subject_name"] for row in result["rows"]] == ["database-a"]
    assert result["rows"][0]["values"]["conflict_free"] is True
