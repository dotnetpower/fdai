"""Verified collection-state FunctionType tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml
from fdai.core.ontology_platform.functions import (
    FunctionInvocationContext,
    OntologyFunctionRegistry,
)
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
from fdai.core.ontology_platform.resource_state_queries import (
    RESOURCE_STATE_FUNCTION_NAME,
    RESOURCE_STATE_MEASURE_TERMS,
    RESOURCE_STATE_OBSERVED_CONCEPT,
    RESOURCE_STATE_QUERY_CONCEPTS,
    resource_state_function_type,
    resource_state_inventory_function,
)
from fdai.shared.contracts.models import CeilingRole
from fdai.shared.ontology.release import build_ontology_release
from fdai.shared.providers.ontology_instance import OntologyGraphSnapshot, OntologyObjectRecord
from fdai.shared.providers.state_evidence import (
    STATE_FACT_METADATA_PROPERTY,
    StateFactAuthority,
    StateFactLane,
    StateFactMetadata,
)
from fdai_service_contracts.recorded_resource_state import (
    AVAILABILITY_ESTABLISHES_RUNNING_RESOURCE_TYPES,
    OPERATIONAL_STATE_SOURCE_PATHS_BY_RESOURCE_TYPE,
    PROVIDER_OPERATIONAL_STATE_NOT_EXPOSED_RESOURCE_TYPES,
    UNREACHABLE_OPERATIONAL_STATES_BY_RESOURCE_TYPE,
)

_REPO_ROOT = Path(__file__).resolve().parents[5]
NOW = datetime(2026, 8, 21, 11, 0, tzinfo=UTC)


def _state_fact(*, observed_at: datetime) -> dict[str, object]:
    return StateFactMetadata(
        lane=StateFactLane.OBSERVED,
        authority=StateFactAuthority.PROVIDER,
        source_identity="inventory-provider",
        source_revision="generation-example",
        effective_at=observed_at,
        recorded_at=observed_at,
        evidence_cutoff=observed_at,
        freshness_ceiling_seconds=3600,
        completeness=1.0,
        synthetic=False,
        evidence_refs=("inventory-generation:generation-example",),
    ).to_mapping()


def _resource(
    name: str,
    state: str | None,
    *,
    observed_at: datetime | None = None,
    legacy_flat_metadata: bool = False,
    resource_group: str | None = None,
    region: str | None = None,
    legacy_scope_keys: bool = False,
) -> OntologyObjectRecord:
    provider: dict[str, object] = {}
    if state is not None:
        provider["state"] = state
    if observed_at is not None:
        state_fact = _state_fact(observed_at=observed_at)
        provider[STATE_FACT_METADATA_PROPERTY] = (
            state_fact if legacy_flat_metadata else {"state": state_fact}
        )
    if resource_group is not None:
        provider["resourceGroup" if legacy_scope_keys else "resource_group"] = resource_group
    if region is not None:
        provider["location" if legacy_scope_keys else "region"] = region
    return OntologyObjectRecord(
        id=f"resource-{name}",
        object_type="Resource",
        properties={
            "id": f"resource-{name}",
            "name": name,
            "type": "postgresql-server",
            "properties": provider,
        },
    )


def _query_result(
    objects: tuple[OntologyObjectRecord, ...],
    *,
    complete: bool = True,
    source_incomplete_reason: str | None = None,
) -> SecuredObjectSetQueryResult:
    declaration = resource_state_function_type()
    release = build_ontology_release(function_types=(declaration,))
    # A source gap is incomplete without truncation; otherwise incompleteness is a result limit.
    truncated = not complete and source_incomplete_reason is None
    definition = ObjectSetDefinition(
        selector=ObjectSelector(kind=ObjectSelectorKind.OBJECT_TYPE, name="Resource"),
        as_of=NOW,
        purpose="operations-review",
        limit=1000,
    )
    materialization = ObjectSetMaterialization(
        definition=definition,
        graph=(
            OntologyGraphSnapshot(
                objects=objects,
                links=(),
                source_complete=False,
                source_incomplete_reason=source_incomplete_reason,
            )
            if source_incomplete_reason is not None
            else OntologyGraphSnapshot(objects=objects, links=(), truncated=not complete)
        ),
        concrete_types=("Resource",),
        truncated=truncated,
        truncation_reason=(ObjectSetTruncationReason.RESULT_LIMIT if truncated else None),
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
            returned_object_count=len(objects),
            returned_link_count=0,
            complete=complete,
            truncated=truncated,
            truncation_reason=(ObjectSetTruncationReason.RESULT_LIMIT if truncated else None),
            source_complete=source_incomplete_reason is None,
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


async def _invoke(
    query_result: SecuredObjectSetQueryResult,
    *,
    concepts: tuple[str, ...],
    list_members: bool = False,
) -> dict[str, object]:
    declaration = resource_state_function_type()
    release = build_ontology_release(function_types=(declaration,))
    registry = OntologyFunctionRegistry(release=release)
    registry.register_contextual(
        declaration,
        resource_state_inventory_function(release),
    )
    result = await registry.invoke(
        RESOURCE_STATE_FUNCTION_NAME,
        {
            "query_result": query_result.model_dump(mode="json"),
            "state_concepts": list(concepts),
            **({"list_members": True} if list_members else {}),
        },
        context=FunctionInvocationContext(
            caller_agent="Bragi",
            caller_role=CeilingRole.READER,
            purposes=("operations-review",),
        ),
    )
    assert isinstance(result, dict)
    return result


def test_state_function_declares_canonical_measure_concepts() -> None:
    declaration = resource_state_function_type()

    assert declaration.version == "1.3.0"
    assert declaration.output_schema["x-fdai-measure-concepts"] == list(
        RESOURCE_STATE_QUERY_CONCEPTS
    )
    assert declaration.output_schema["x-fdai-measure-value-groups"] == [
        {"concept": concept, "terms": list(RESOURCE_STATE_MEASURE_TERMS[concept])}
        for concept in RESOURCE_STATE_QUERY_CONCEPTS
    ]


async def test_state_function_returns_only_requested_verified_states() -> None:
    observed_at = NOW - timedelta(minutes=5)
    result = await _invoke(
        _query_result(
            (
                _resource(
                    "database-a",
                    "PowerState/stopped",
                    observed_at=observed_at,
                    resource_group="group-a",
                    region="region-a",
                ),
                _resource("database-b", "Running", observed_at=observed_at),
                _resource("database-c", "Paused", observed_at=observed_at),
            )
        ),
        concepts=("resource_state.stopped",),
    )

    assert result["complete"] is True
    assert result["truncation_reason"] is None
    rows = result["rows"]
    assert isinstance(rows, list)
    assert len(rows) == 1
    values = rows[0]["values"]
    assert values["name"] == "database-a"
    assert values["resource_group"] == "group-a"
    assert values["region"] == "region-a"
    assert values["state_concept"] == "resource_state.stopped"
    assert values["source_observed_at"] == observed_at.isoformat()
    assert values["execution_authority"] is False


async def test_state_function_marks_unavailable_scope_fields_explicitly() -> None:
    observed_at = NOW - timedelta(minutes=5)
    result = await _invoke(
        _query_result((_resource("database-a", "Ready", observed_at=observed_at),)),
        concepts=(RESOURCE_STATE_OBSERVED_CONCEPT,),
    )

    values = result["rows"][0]["values"]
    assert values["resource_group"] is None
    assert values["region"] is None


async def test_state_function_normalizes_legacy_provider_scope_fields() -> None:
    observed_at = NOW - timedelta(minutes=5)
    result = await _invoke(
        _query_result(
            (
                _resource(
                    "database-a",
                    "Ready",
                    observed_at=observed_at,
                    resource_group="group-a",
                    region="region-a",
                    legacy_scope_keys=True,
                ),
            )
        ),
        concepts=(RESOURCE_STATE_OBSERVED_CONCEPT,),
    )

    values = result["rows"][0]["values"]
    assert values["resource_group"] == "group-a"
    assert values["region"] == "region-a"


async def test_state_function_returns_every_recognized_observed_state() -> None:
    observed_at = NOW - timedelta(minutes=5)
    result = await _invoke(
        _query_result(
            (
                _resource("database-a", "Stopped", observed_at=observed_at),
                _resource("database-b", "Running", observed_at=observed_at),
                _resource("database-c", "Paused", observed_at=observed_at),
            )
        ),
        concepts=(RESOURCE_STATE_OBSERVED_CONCEPT,),
    )

    assert result["complete"] is True
    assert result["truncation_reason"] is None
    rows = result["rows"]
    assert isinstance(rows, list)
    assert [row["values"]["state_concept"] for row in rows] == [
        "resource_state.stopped",
        "resource_state.running",
        "resource_state.paused",
    ]


async def test_state_function_accepts_legacy_flat_state_metadata() -> None:
    observed_at = NOW - timedelta(minutes=5)
    result = await _invoke(
        _query_result(
            (
                _resource(
                    "database-a",
                    "Stopped",
                    observed_at=observed_at,
                    legacy_flat_metadata=True,
                ),
            )
        ),
        concepts=("resource_state.stopped",),
    )

    rows = result["rows"]
    assert isinstance(rows, list)
    assert [row["values"]["name"] for row in rows] == ["database-a"]


async def test_state_function_prefers_concrete_filter_over_observed_sentinel() -> None:
    observed_at = NOW - timedelta(minutes=5)
    result = await _invoke(
        _query_result(
            (
                _resource("database-a", "Stopped", observed_at=observed_at),
                _resource("database-b", "Running", observed_at=observed_at),
            )
        ),
        concepts=(RESOURCE_STATE_OBSERVED_CONCEPT, "resource_state.stopped"),
    )

    rows = result["rows"]
    assert isinstance(rows, list)
    assert [row["values"]["name"] for row in rows] == ["database-a"]


async def test_state_function_preserves_unclassified_observed_state() -> None:
    result = await _invoke(
        _query_result(
            (_resource("database-a", "Updating", observed_at=NOW - timedelta(minutes=5)),)
        ),
        concepts=(RESOURCE_STATE_OBSERVED_CONCEPT,),
    )

    assert result["complete"] is True
    assert result["truncation_reason"] is None
    rows = result["rows"]
    assert isinstance(rows, list)
    assert rows[0]["values"]["observed_state"] == "Updating"
    assert rows[0]["values"]["state_concept"] == RESOURCE_STATE_OBSERVED_CONCEPT


async def test_state_function_does_not_infer_specific_state_from_unclassified_value() -> None:
    result = await _invoke(
        _query_result(
            (_resource("database-a", "Updating", observed_at=NOW - timedelta(minutes=5)),)
        ),
        concepts=("resource_state.running",),
    )

    assert result == {
        "complete": True,
        "rows": [],
        "truncation_reason": None,
    }


async def test_state_function_preserves_matches_but_marks_missing_state_incomplete() -> None:
    observed_at = NOW - timedelta(minutes=5)
    result = await _invoke(
        _query_result(
            (
                _resource("database-a", "Stopped", observed_at=observed_at),
                _resource("database-b", None),
            )
        ),
        concepts=("resource_state.stopped",),
    )

    assert result["complete"] is False
    assert result["truncation_reason"] == (
        "resource_state_evidence_incomplete+resource_state_not_reported"
    )
    rows = result["rows"]
    assert isinstance(rows, list)
    assert len(rows) == 1


def _typed(record: OntologyObjectRecord, resource_type: str) -> OntologyObjectRecord:
    return replace(record, properties={**record.properties, "type": resource_type})


async def test_a_type_whose_provider_hides_state_names_that_cause() -> None:
    observed_at = NOW - timedelta(minutes=5)
    hidden = _typed(_resource("cosmos-a", None), "nosql-database")
    result = await _invoke(
        _query_result((_resource("database-a", "Running", observed_at=observed_at), hidden)),
        concepts=("resource_state.running",),
    )

    # Running is a state the type can hold, so the table stays partial and names why.
    assert result["complete"] is False
    assert result["truncation_reason"] == (
        "resource_state_evidence_incomplete+provider_operational_state_not_exposed"
    )
    assert [row["values"]["name"] for row in result["rows"]] == ["database-a"]


async def test_a_state_the_type_never_reaches_settles_an_unobserved_resource() -> None:
    observed_at = NOW - timedelta(minutes=5)
    result = await _invoke(
        _query_result(
            (
                _resource("database-a", "Stopped", observed_at=observed_at),
                _typed(_resource("cosmos-a", None), "nosql-database"),
                _typed(_resource("redis-a", None), "cache"),
            )
        ),
        concepts=("resource_state.stopped", "resource_state.deallocated"),
    )

    # Neither type has a stop or deallocate operation, so neither can match the filter.
    assert result == {**result, "complete": True, "truncation_reason": None}
    assert [row["values"]["name"] for row in result["rows"]] == ["database-a"]


async def test_an_observed_state_wins_over_the_lifecycle_declaration() -> None:
    observed_at = NOW - timedelta(minutes=5)
    observed = _typed(_resource("cosmos-a", "Stopped", observed_at=observed_at), "nosql-database")
    result = await _invoke(_query_result((observed,)), concepts=("resource_state.stopped",))

    assert result["complete"] is True
    assert [row["values"]["name"] for row in result["rows"]] == ["cosmos-a"]


async def test_list_mode_keeps_an_unobserved_resource_unverified_despite_the_declaration() -> None:
    result = await _invoke(
        _query_result((_typed(_resource("cosmos-a", None), "nosql-database"),)),
        concepts=(RESOURCE_STATE_OBSERVED_CONCEPT,),
        list_members=True,
    )

    assert result["complete"] is False
    assert result["rows"][0]["values"]["state_status"] == "unknown_incomplete"


def _serving(name: str, resource_type: str, availability: str, *, observed_at: datetime):
    record = _typed(_resource(name, None), resource_type)
    provider = {
        **record.properties["properties"],
        "availabilityState": availability,
        STATE_FACT_METADATA_PROPERTY: {"availabilityState": _state_fact(observed_at=observed_at)},
    }
    return replace(record, properties={**record.properties, "properties": provider})


async def test_fresh_availability_establishes_running_for_a_running_only_lifecycle() -> None:
    fresh = NOW - timedelta(minutes=5)
    result = await _invoke(
        _query_result(
            (
                _resource("database-a", "Running", observed_at=fresh),
                _serving("cosmos-a", "nosql-database", "Available", observed_at=fresh),
            )
        ),
        concepts=("resource_state.running",),
    )

    # A Cosmos DB account has no steady state but running, so serving means running.
    assert result["complete"] is True
    rows = {row["values"]["name"]: row["values"] for row in result["rows"]}
    assert set(rows) == {"database-a", "cosmos-a"}
    assert rows["cosmos-a"]["state_concept"] == "resource_state.running"
    assert rows["cosmos-a"]["observed_state"] == "Available"
    assert rows["cosmos-a"]["state_basis"] == "availability_on_running_only_lifecycle"
    assert "state_basis" not in rows["database-a"]


@pytest.mark.parametrize(
    ("availability", "age", "resource_type"),
    [
        ("Unavailable", timedelta(minutes=5), "nosql-database"),
        ("Degraded", timedelta(minutes=5), "nosql-database"),
        ("Available", timedelta(hours=3), "nosql-database"),
        ("Available", timedelta(minutes=5), "postgresql-server"),
    ],
)
async def test_availability_establishes_nothing_else(
    availability: str, age: timedelta, resource_type: str
) -> None:
    serving = _serving("target-a", resource_type, availability, observed_at=NOW - age)
    result = await _invoke(_query_result((serving,)), concepts=("resource_state.running",))

    # Another value, a stale fact, or a type with other steady states stays unverified.
    assert result["complete"] is False
    assert result["rows"] == []


async def test_list_mode_reports_an_availability_established_running_member() -> None:
    serving = _serving("cosmos-a", "nosql-database", "Available", observed_at=NOW)
    result = await _invoke(
        _query_result((serving,)),
        concepts=(RESOURCE_STATE_OBSERVED_CONCEPT,),
        list_members=True,
    )

    assert result["complete"] is True
    [row] = result["rows"]
    assert row["values"]["state_status"] == "observed"
    assert row["values"]["state_concept"] == "resource_state.running"


def test_running_only_lifecycles_also_declare_every_other_steady_state_unreachable() -> None:
    for resource_type in AVAILABILITY_ESTABLISHES_RUNNING_RESOURCE_TYPES:
        assert {"stopped", "deallocated", "paused"} <= (
            UNREACHABLE_OPERATIONAL_STATES_BY_RESOURCE_TYPE[resource_type]
        )


def test_lifecycle_declarations_cover_only_unobservable_types_with_reviewed_mappings() -> None:
    vocabulary = _REPO_ROOT / "rule-catalog" / "vocabulary" / "resource-types.yaml"
    registry = yaml.safe_load(vocabulary.read_text(encoding="utf-8"))
    arm_types = {item["id"]: item.get("azure_arm_type") for item in registry["types"]}
    reviewed = {
        "nosql-database": "Microsoft.DocumentDB/databaseAccounts",
        "cache": "Microsoft.Cache/redis",
    }

    # A new provider mapping may add an engine that can stop, so the pairing is pinned.
    assert set(UNREACHABLE_OPERATIONAL_STATES_BY_RESOURCE_TYPE) == set(reviewed)
    for resource_type, arm_type in reviewed.items():
        assert arm_types[resource_type] == arm_type
        assert resource_type in PROVIDER_OPERATIONAL_STATE_NOT_EXPOSED_RESOURCE_TYPES
        assert resource_type not in OPERATIONAL_STATE_SOURCE_PATHS_BY_RESOURCE_TYPE


async def test_state_function_preserves_verified_matches_from_incomplete_scope() -> None:
    observed_at = NOW - timedelta(minutes=5)
    result = await _invoke(
        _query_result(
            (_resource("database-a", "Stopped", observed_at=observed_at),),
            complete=False,
        ),
        concepts=("resource_state.stopped",),
    )

    assert result["complete"] is False
    assert result["truncation_reason"] == "resource_scope_incomplete"
    rows = result["rows"]
    assert isinstance(rows, list)
    assert [row["values"]["name"] for row in rows] == ["database-a"]


async def test_state_function_keeps_the_typed_source_reason_beside_the_scope_gap() -> None:
    observed_at = NOW - timedelta(minutes=5)
    result = await _invoke(
        _query_result(
            (_resource("database-a", "Stopped", observed_at=observed_at),),
            complete=False,
            source_incomplete_reason="inventory_observation_pending",
        ),
        concepts=("resource_state.stopped",),
    )

    # The answer can then say why the scope is incomplete, not only that it is.
    assert result["complete"] is False
    assert result["truncation_reason"] == (
        "resource_scope_incomplete+inventory_observation_pending"
    )


async def test_list_mode_returns_one_row_per_resource_with_a_typed_unknown_reason() -> None:
    observed_at = NOW - timedelta(minutes=5)
    stale = NOW - timedelta(hours=3)
    result = await _invoke(
        _query_result(
            (
                _resource("database-a", "Stopped", observed_at=observed_at),
                _resource("database-b", None),
                _resource("database-c", "Running"),
                _resource("database-d", "Running", observed_at=stale),
            )
        ),
        concepts=(RESOURCE_STATE_OBSERVED_CONCEPT,),
        list_members=True,
    )

    rows = {row["values"]["name"]: row["values"] for row in result["rows"]}
    assert set(rows) == {"database-a", "database-b", "database-c", "database-d"}
    assert rows["database-a"]["state_status"] == "observed"
    assert rows["database-a"]["state_concept"] == "resource_state.stopped"
    assert {
        name: rows[name]["unknown_reason"] for name in ("database-b", "database-c", "database-d")
    } == {
        "database-b": "state_not_reported",
        "database-c": "state_metadata_missing",
        "database-d": "state_stale",
    }
    for name in ("database-b", "database-c", "database-d"):
        assert rows[name]["state_status"] == "unknown_incomplete"
        assert rows[name]["state_concept"] is None
        assert rows[name]["observed_state"] is None
    # Every Resource is listed, but unverified members keep the table incomplete.
    assert result["complete"] is False
    assert result["truncation_reason"] == (
        "resource_state_evidence_incomplete+resource_state_not_reported+resource_state_stale"
    )


async def test_list_mode_only_lists_the_observed_concept_and_filter_mode_is_unchanged() -> None:
    observed_at = NOW - timedelta(minutes=5)
    query = _query_result(
        (_resource("database-a", "Stopped", observed_at=observed_at), _resource("database-b", None))
    )

    with pytest.raises(Exception, match="list mode"):
        await _invoke(query, concepts=("resource_state.stopped",), list_members=True)
    filtered = await _invoke(query, concepts=(RESOURCE_STATE_OBSERVED_CONCEPT,))

    assert [row["values"]["name"] for row in filtered["rows"]] == ["database-a"]
    assert "state_status" not in filtered["rows"][0]["values"]
