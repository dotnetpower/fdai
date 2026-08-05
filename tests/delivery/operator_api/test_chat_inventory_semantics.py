from __future__ import annotations

from types import SimpleNamespace

import pytest

import fdai.delivery.operator_api.routes.chat_inventory_semantics as inventory_semantics
from fdai.delivery.operator_api.routes.chat_inventory_query import (
    InventoryField,
    InventoryOperator,
    InventoryPredicate,
    InventoryQuery,
    InventoryQueryKind,
    InventoryQuerySource,
    inventory_query_matches,
)
from fdai.delivery.operator_api.routes.chat_inventory_semantics import (
    SemanticInventoryStatusError,
    ground_inventory_status_query,
    merge_semantic_inventory_status,
    merge_semantic_inventory_status_query,
)
from fdai.rule_catalog.schema.inventory_query_language import (
    QueryEvidenceAuthority,
    QueryValues,
)


def _vm_query() -> InventoryQuery:
    return InventoryQuery(
        source=InventoryQuerySource.CURRENT,
        kind=InventoryQueryKind.LIST,
        predicates=(
            InventoryPredicate(
                InventoryField.RESOURCE_TYPE,
                InventoryOperator.EQ,
                "compute.vm",
            ),
        ),
    )


def _database_query() -> InventoryQuery:
    return InventoryQuery(
        source=InventoryQuerySource.CURRENT,
        kind=InventoryQueryKind.LIST,
        predicates=(
            InventoryPredicate(
                InventoryField.RESOURCE_TYPE,
                InventoryOperator.IN,
                ("mysql-server", "postgresql-server", "sql-database"),
            ),
        ),
    )


def test_semantic_status_merge_applies_ontology_suppression() -> None:
    merged = merge_semantic_inventory_status_query(
        _vm_query(),
        {
            "predicates": [
                {
                    "field": "status",
                    "operator": "in",
                    "value": ["inactive", "running"],
                }
            ]
        },
    )

    assert merged is not None
    status = next(predicate for predicate in merged["predicates"] if predicate["field"] == "status")
    assert status["value"] == ["stopped", "deallocated"]


def test_semantic_status_merge_uses_resource_category_values() -> None:
    merged = merge_semantic_inventory_status_query(
        _database_query(),
        {"predicates": [{"field": "status", "operator": "eq", "value": "inactive"}]},
    )

    assert merged is not None
    status = next(predicate for predicate in merged["predicates"] if predicate["field"] == "status")
    assert status["value"] == ["stopped", "deallocated", "paused"]


def test_semantic_status_merge_preserves_bounded_negation() -> None:
    merged = merge_semantic_inventory_status_query(
        _vm_query(),
        {"predicates": [{"field": "status", "operator": "not_in", "value": ["inactive"]}]},
    )

    assert merged is not None
    status = next(predicate for predicate in merged["predicates"] if predicate["field"] == "status")
    assert status == {
        "field": "status",
        "operator": "not_in",
        "value": ["stopped", "deallocated"],
    }


def test_negated_status_grounding_excludes_provider_status_forms() -> None:
    query = InventoryQuery(
        source=InventoryQuerySource.CURRENT,
        kind=InventoryQueryKind.LIST,
        predicates=(
            *_vm_query().predicates,
            InventoryPredicate(
                InventoryField.STATUS,
                InventoryOperator.NOT_IN,
                ("stopped", "deallocated"),
            ),
        ),
    )
    resources = (
        {"type": "compute.vm", "status": "VM running"},
        {"type": "compute.vm", "status": "VM stopped"},
        {"type": "compute.vm", "status": "PowerState/deallocated"},
    )

    grounded = ground_inventory_status_query(query, resources)

    status = grounded.predicates[-1]
    assert status.operator is InventoryOperator.NOT_IN
    assert status.value == ("vm stopped", "powerstate deallocated")
    assert inventory_query_matches(grounded, resources[0])
    assert not inventory_query_matches(grounded, resources[1])
    assert not inventory_query_matches(grounded, resources[2])


def test_status_grounding_ignores_unselected_resource_types() -> None:
    query = InventoryQuery(
        source=InventoryQuerySource.CURRENT,
        kind=InventoryQueryKind.LIST,
        predicates=(
            *_vm_query().predicates,
            InventoryPredicate(
                InventoryField.STATUS,
                InventoryOperator.EQ,
                "running",
            ),
        ),
    )
    resources = (
        {"type": "compute.vm", "status": "VM running"},
        *(
            {"type": f"synthetic.type-{index}", "status": f"Type-{index} running"}
            for index in range(20)
        ),
    )

    grounded = ground_inventory_status_query(query, resources)

    status = next(
        predicate for predicate in grounded.predicates if predicate.field is InventoryField.STATUS
    )
    assert status.operator is InventoryOperator.EQ
    assert status.value == "vm running"


@pytest.mark.parametrize("observed", ("not_running", "Not running", "Stopped running"))
def test_status_grounding_rejects_negated_or_contradictory_suffixes(observed: str) -> None:
    query = InventoryQuery(
        source=InventoryQuerySource.CURRENT,
        kind=InventoryQueryKind.LIST,
        predicates=(
            *_vm_query().predicates,
            InventoryPredicate(
                InventoryField.STATUS,
                InventoryOperator.EQ,
                "running",
            ),
        ),
    )

    grounded = ground_inventory_status_query(
        query,
        ({"type": "compute.vm", "status": observed},),
    )

    assert grounded == query


def test_semantic_status_merge_rejects_aggregate_value_overflow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    states = {
        "state-a": QueryValues(
            terms=("state a",),
            values=tuple(f"a-{index}" for index in range(9)),
        ),
        "state-b": QueryValues(
            terms=("state b",),
            values=tuple(f"b-{index}" for index in range(9)),
        ),
    }
    monkeypatch.setattr(
        inventory_semantics,
        "default_inventory_query_language_resolver",
        lambda: SimpleNamespace(registry=SimpleNamespace(states=states)),
    )

    with pytest.raises(SemanticInventoryStatusError):
        merge_semantic_inventory_status_query(
            _vm_query(),
            {
                "predicates": [
                    {
                        "field": "status",
                        "operator": "in",
                        "value": ["state-a", "state-b"],
                    }
                ]
            },
        )


@pytest.mark.parametrize(
    "evidence",
    (
        {},
        {"result": None},
        {"result": {"query": "invalid"}},
        {"result": {"query": {"source": "current"}}},
    ),
)
def test_semantic_status_evidence_merge_rejects_malformed_query(
    evidence: dict[str, object],
) -> None:
    assert merge_semantic_inventory_status(evidence, {"predicates": []}) is None


def test_semantic_status_evidence_merge_accepts_verified_query() -> None:
    merged = merge_semantic_inventory_status(
        {"result": {"query": _vm_query().to_dict()}},
        {"predicates": [{"field": "status", "operator": "eq", "value": "running"}]},
    )

    assert merged is not None
    assert merged["predicates"][-1]["value"] == "running"


@pytest.mark.parametrize(
    "arguments",
    (
        {},
        {"predicates": "invalid"},
        {"predicates": []},
        {"predicates": [{"field": "name", "operator": "eq", "value": "vm"}]},
    ),
)
def test_semantic_status_merge_ignores_missing_status_candidate(
    arguments: dict[str, object],
) -> None:
    assert merge_semantic_inventory_status_query(_vm_query(), arguments) is None


def test_semantic_status_merge_preserves_existing_status() -> None:
    query = InventoryQuery(
        source=InventoryQuerySource.CURRENT,
        kind=InventoryQueryKind.LIST,
        predicates=(
            *_vm_query().predicates,
            InventoryPredicate(InventoryField.STATUS, InventoryOperator.EQ, "stopped"),
        ),
    )

    assert (
        merge_semantic_inventory_status_query(
            query,
            {"predicates": [{"field": "status", "operator": "eq", "value": "running"}]},
        )
        is None
    )


def test_semantic_status_merge_rejects_ambiguous_status_predicates() -> None:
    with pytest.raises(SemanticInventoryStatusError, match="ambiguous"):
        merge_semantic_inventory_status_query(
            _vm_query(),
            {
                "predicates": [
                    {"field": "status", "operator": "eq", "value": "running"},
                    {"field": "status", "operator": "eq", "value": "stopped"},
                ]
            },
        )


@pytest.mark.parametrize(
    "predicate",
    (
        {"field": "status", "operator": "contains", "value": "running"},
        {"field": "status", "operator": "in", "value": ["running", 1]},
        {"field": "status", "operator": "eq", "value": "not_ready"},
    ),
)
def test_semantic_status_merge_rejects_unsupported_candidate(
    predicate: dict[str, object],
) -> None:
    with pytest.raises(SemanticInventoryStatusError, match="invalid"):
        merge_semantic_inventory_status_query(_vm_query(), {"predicates": [predicate]})


def test_semantic_status_merge_rejects_normalized_empty_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    states = {
        "blank": SimpleNamespace(
            suppresses=(),
            evidence_authority=QueryEvidenceAuthority.CURRENT_INVENTORY,
            values=("   ",),
            category_values={},
        )
    }
    monkeypatch.setattr(
        inventory_semantics,
        "default_inventory_query_language_resolver",
        lambda: SimpleNamespace(registry=SimpleNamespace(states=states)),
    )

    with pytest.raises(SemanticInventoryStatusError, match="invalid"):
        merge_semantic_inventory_status_query(
            _vm_query(),
            {"predicates": [{"field": "status", "operator": "eq", "value": "blank"}]},
        )


def test_status_grounding_requires_one_canonical_status_predicate() -> None:
    assert ground_inventory_status_query(_vm_query(), ()) == _vm_query()
    unsupported = InventoryQuery(
        source=InventoryQuerySource.CURRENT,
        kind=InventoryQueryKind.LIST,
        predicates=(
            *_vm_query().predicates,
            InventoryPredicate(InventoryField.STATUS, InventoryOperator.EQ, "alive"),
        ),
    )
    assert ground_inventory_status_query(unsupported, ()) == unsupported


def test_status_grounding_handles_exact_and_provider_status_forms() -> None:
    query = InventoryQuery(
        source=InventoryQuerySource.CURRENT,
        kind=InventoryQueryKind.LIST,
        predicates=(
            *_vm_query().predicates,
            InventoryPredicate(InventoryField.STATUS, InventoryOperator.EQ, "running"),
        ),
    )

    grounded = ground_inventory_status_query(
        query,
        (
            {"type": "compute.vm", "status": "running"},
            {"type": "compute.vm", "status": "PowerState/running"},
        ),
    )

    status = grounded.predicates[-1]
    assert status.operator is InventoryOperator.IN
    assert status.value == ("running", "powerstate running")


def test_semantic_status_merge_uses_default_values_for_mixed_categories() -> None:
    query = InventoryQuery(
        source=InventoryQuerySource.CURRENT,
        kind=InventoryQueryKind.LIST,
        predicates=(
            InventoryPredicate(
                InventoryField.RESOURCE_TYPE,
                InventoryOperator.IN,
                ("compute.vm", "sql-database"),
            ),
        ),
    )

    merged = merge_semantic_inventory_status_query(
        query,
        {"predicates": [{"field": "status", "operator": "eq", "value": "inactive"}]},
    )

    assert merged is not None
    assert merged["predicates"][-1]["value"] == ["stopped", "deallocated"]
