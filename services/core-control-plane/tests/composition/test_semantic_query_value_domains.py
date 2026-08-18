"""Shipped resource-type vocabulary as a planner value domain."""

from __future__ import annotations

from pathlib import Path

import yaml
from fdai.composition.semantic_query_value_domains import resource_type_value_domains
from fdai.rule_catalog.schema.resource_type import load_resource_type_registry_from_mapping

REPO_ROOT = Path(__file__).resolve().parents[4]
CATALOG = REPO_ROOT / "rule-catalog" / "vocabulary" / "resource-types.yaml"


def _domain() -> object:
    registry = load_resource_type_registry_from_mapping(
        yaml.safe_load(CATALOG.read_text(encoding="utf-8"))
    )
    domains = resource_type_value_domains(registry)
    assert len(domains) == 1
    return domains[0]


def test_shipped_vocabulary_binds_every_declared_resource_type() -> None:
    registry = load_resource_type_registry_from_mapping(
        yaml.safe_load(CATALOG.read_text(encoding="utf-8"))
    )
    domain = _domain()

    assert domain.object_type == "Resource"
    assert domain.property_name == "type"
    assert set(domain.values) == {entry.id for entry in registry.types}
    assert domain.values == tuple(sorted(domain.values))


def test_shipped_vocabulary_exposes_a_bilingual_database_group() -> None:
    domain = _domain()

    database = next(group for group in domain.groups if group.id == "database")

    assert set(database.values) == {
        "cache",
        "mysql-server",
        "nosql-database",
        "postgresql-server",
        "redis-enterprise",
        "sql-database",
    }
    assert "database" in database.terms
    assert "db" in database.terms
    assert "데이터베이스" in database.terms


def test_shipped_vocabulary_groups_stay_inside_the_declared_value_set() -> None:
    domain = _domain()

    declared = set(domain.values)
    assert domain.groups
    assert all(set(group.values) <= declared for group in domain.groups)
    assert all(group.values == tuple(sorted(group.values)) for group in domain.groups)


def test_shipped_vocabulary_exposes_each_type_request_term() -> None:
    """A subtype word an operator types MUST select that subtype alone.

    Without a single-value group a planner that cannot invent an operand falls
    back to an existence predicate over the whole ObjectType.
    """
    registry = load_resource_type_registry_from_mapping(
        yaml.safe_load(CATALOG.read_text(encoding="utf-8"))
    )
    domain = _domain()
    by_id = {group.id: group for group in domain.groups}

    for entry in registry.types:
        if not entry.query_terms or entry.id not in by_id:
            continue
        group = by_id[entry.id]
        assert group.values == (entry.id,)
        assert set(entry.query_terms) <= set(group.terms)

    resource_group = by_id["resource-group"]
    assert resource_group.values == ("resource-group",)
    assert "resource group" in resource_group.terms
    assert "리소스그룹" in resource_group.terms
