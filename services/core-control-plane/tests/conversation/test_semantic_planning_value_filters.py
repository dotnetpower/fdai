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
