from __future__ import annotations

from fdai.core.conversation.semantic_planning_value_filters import stated_value_filters


def _resource_descriptor() -> dict[str, object]:
    return {
        "kind": "object",
        "name": "Resource",
        "properties": {
            "type": {
                "value_groups": [
                    {
                        "id": "database",
                        "values": ["postgresql-server", "sql-server"],
                        "terms": ["database"],
                    },
                    {
                        "id": "postgresql-server",
                        "values": ["postgresql-server"],
                        "terms": ["postgresql"],
                    },
                    {
                        "id": "resource-group",
                        "values": ["resource-group"],
                        "terms": ["resource group", "리소스 그룹"],
                    },
                    {
                        "id": "sql-server",
                        "values": ["sql-server"],
                        "terms": ["sql server", "sql 서버"],
                    },
                ]
            }
        },
    }


def test_typed_target_disambiguates_output_field_resource_type_term() -> None:
    filters = stated_value_filters(
        "현재 구독의 Azure Database for PostgreSQL 서버 목록을 보여줘.",
        (_resource_descriptor(),),
        preferred_terms=("PostgreSQL",),
    )

    assert filters == {("Resource", "type"): ("postgresql-server",)}


def test_mixed_language_term_still_matches_korean_suffix() -> None:
    filters = stated_value_filters(
        "현재 구독의 SQL 서버를 보여줘.",
        (_resource_descriptor(),),
    )

    assert filters == {("Resource", "type"): ("sql-server",)}


def test_ambiguous_resource_types_without_typed_target_remain_ungrounded() -> None:
    filters = stated_value_filters(
        "PostgreSQL 서버와 리소스 그룹을 보여줘.",
        (_resource_descriptor(),),
    )

    assert filters == {}


def test_typed_output_facet_disambiguates_resource_type_term() -> None:
    filters = stated_value_filters(
        "PostgreSQL 서버를 이름과 리소스 그룹과 함께 보여줘.",
        (_resource_descriptor(),),
        excluded_values=frozenset({"resource-group"}),
    )

    assert filters == {("Resource", "type"): ("postgresql-server",)}


def _compute_descriptor() -> dict[str, object]:
    return {
        "kind": "object",
        "name": "Resource",
        "properties": {
            "type": {
                "value_groups": [
                    {
                        "id": "compute.vm",
                        "values": ["compute.vm"],
                        "terms": ["virtual machine", "vm", "가상머신"],
                    },
                    {
                        "id": "compute.vm-scale-set",
                        "values": ["compute.vm-scale-set"],
                        "terms": ["virtual machine scale set", "vmss", "가상 머신 확장 집합"],
                    },
                    {
                        "id": "container-registry",
                        "values": ["container-registry"],
                        "terms": ["container registry"],
                    },
                    {
                        "id": "kubernetes-cluster",
                        "values": ["kubernetes-cluster"],
                        "terms": ["aks", "kubernetes cluster"],
                    },
                ]
            }
        },
    }


def test_longer_stated_term_owns_the_span_of_a_contained_term() -> None:
    filters = stated_value_filters(
        "Show me all virtual machine scale sets",
        (_compute_descriptor(),),
        preferred_terms=("virtual machine scale sets",),
    )

    assert filters == {("Resource", "type"): ("compute.vm-scale-set",)}


def test_regular_english_plural_and_sentence_punctuation_state_a_term() -> None:
    descriptors = (_compute_descriptor(),)

    assert stated_value_filters("List the container registries.", descriptors) == {
        ("Resource", "type"): ("container-registry",)
    }
    assert stated_value_filters("Show VMs.", descriptors) == {("Resource", "type"): ("compute.vm",)}


def test_term_inside_a_resource_identifier_states_no_type() -> None:
    descriptors = (_compute_descriptor(),)

    assert stated_value_filters("aks-prod-01 시작해줘", descriptors) == {}
    assert stated_value_filters("vm_batch.worker 상태", descriptors) == {}
    assert stated_value_filters("AKS 클러스터 목록", descriptors) == {
        ("Resource", "type"): ("kubernetes-cluster",)
    }


def test_canonical_value_preference_selects_its_own_group() -> None:
    filters = stated_value_filters(
        "현재 구독의 Azure Database for PostgreSQL 서버 목록을 이름, 리소스 그룹과 함께 보여줘.",
        (_resource_descriptor(),),
        preferred_terms=("Resource", "postgresql-server"),
    )

    assert filters == {("Resource", "type"): ("postgresql-server",)}
