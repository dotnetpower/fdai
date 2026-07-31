"""ResourceTypeRegistry loader tests + invariants on the shipped vocabulary."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from fdai.rule_catalog.schema.resource_type import (
    ResourceTypeCategory,
    ResourceTypeRegistry,
    ResourceTypeRegistryError,
    load_resource_type_registry_from_mapping,
    resolve_azure_resource_type,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
VOCAB_YAML = REPO_ROOT / "rule-catalog" / "vocabulary" / "resource-types.yaml"


def _shipped() -> ResourceTypeRegistry:
    raw = yaml.safe_load(VOCAB_YAML.read_text(encoding="utf-8"))
    return load_resource_type_registry_from_mapping(raw)


def test_shipped_vocabulary_loads() -> None:
    registry = _shipped()
    assert registry.schema_version == "1.0.0"
    assert len(registry.types) >= 20  # P1 coverage target for 3 verticals


def test_shipped_vocabulary_has_no_duplicate_ids() -> None:
    registry = _shipped()
    ids = [t.id for t in registry.types]
    assert len(ids) == len(set(ids)), "duplicate resource_type id"


def test_shipped_vocabulary_covers_three_verticals() -> None:
    registry = _shipped()
    ids = registry.ids()

    # Change Safety anchors
    assert "object-storage" in ids
    assert "kubernetes-cluster" in ids
    # Cost Governance anchors
    assert "compute.vm-scale-set" in ids
    assert "resource-group" in ids
    # Resilience anchors
    assert "postgresql-server" in ids
    assert "sql-database" in ids
    assert "nosql-database" in ids


def test_shipped_vocabulary_covers_common_azure_inventory_types() -> None:
    registry = _shipped()

    assert {
        "compute.web-app",
        "compute.function",
        "workflow.logic-app",
        "network.nsg",
        "network.firewall",
        "data-collection-rule",
    } <= registry.ids()
    for type_id in (
        "compute.web-app",
        "compute.function",
        "workflow.logic-app",
        "network.nsg",
        "network.firewall",
        "data-collection-rule",
    ):
        assert registry.get(type_id).query_terms


def test_shared_web_arm_type_resolves_by_kind() -> None:
    registry = _shipped()

    assert (
        resolve_azure_resource_type(
            registry,
            arm_type="Microsoft.Web/sites",
            kind="functionapp,linux",
        )
        == "compute.function"
    )
    assert (
        resolve_azure_resource_type(
            registry,
            arm_type="Microsoft.Web/sites",
            kind="app,linux",
        )
        == "compute.web-app"
    )
    assert (
        resolve_azure_resource_type(
            registry,
            arm_type="Microsoft.Web/sites",
        )
        is None
    )


@pytest.mark.parametrize("token", ["function app", "function/app", "함수앱"])
def test_azure_kind_tokens_reject_non_machine_tokens(token: str) -> None:
    payload = {
        "schema_version": "1.0.0",
        "version": "0.0.1",
        "types": [
            {
                "id": "compute.function",
                "category": "compute",
                "description": "Function",
                "azure_arm_type": "Microsoft.Web/sites",
                "azure_kind_tokens": [token],
            }
        ],
    }

    with pytest.raises(ResourceTypeRegistryError):
        load_resource_type_registry_from_mapping(payload)


def test_shared_arm_type_rejects_duplicate_kind_token() -> None:
    payload = {
        "schema_version": "1.0.0",
        "version": "0.0.1",
        "types": [
            {
                "id": "compute.one",
                "category": "compute",
                "description": "one",
                "azure_arm_type": "Microsoft.Example/widgets",
                "azure_kind_tokens": ["app"],
            },
            {
                "id": "compute.two",
                "category": "compute",
                "description": "two",
                "azure_arm_type": "Microsoft.Example/widgets",
                "azure_kind_tokens": ["app"],
            },
        ],
    }

    with pytest.raises(ResourceTypeRegistryError, match="kind token"):
        load_resource_type_registry_from_mapping(payload)


def test_duplicate_query_term_is_rejected() -> None:
    payload = {
        "schema_version": "1.0.0",
        "version": "0.0.1",
        "types": [
            {
                "id": "compute.one",
                "category": "compute",
                "description": "one",
                "query_terms": ["shared term"],
            },
            {
                "id": "compute.two",
                "category": "compute",
                "description": "two",
                "query_terms": ["Shared  Term"],
            },
        ],
    }

    with pytest.raises(ResourceTypeRegistryError, match="query term is shared"):
        load_resource_type_registry_from_mapping(payload)


def test_category_query_term_cannot_shadow_concrete_type_term() -> None:
    payload = {
        "schema_version": "1.0.0",
        "version": "0.0.1",
        "category_query_terms": {"database": ["db"]},
        "types": [
            {
                "id": "postgresql-server",
                "category": "database",
                "description": "PostgreSQL",
                "query_terms": ["DB"],
            }
        ],
    }

    with pytest.raises(ResourceTypeRegistryError, match="category query term"):
        load_resource_type_registry_from_mapping(payload)


def test_typical_parents_reference_only_registered_ids() -> None:
    registry = _shipped()
    ids = registry.ids()
    for entry in registry.types:
        for parent in entry.typical_parents:
            assert parent in ids, (
                f"{entry.id}: typical_parent {parent!r} is not a registered resource_type"
            )


def test_loader_rejects_unknown_typical_parent() -> None:
    payload = {
        "schema_version": "1.0.0",
        "version": "0.0.1",
        "types": [
            {
                "id": "compute.vm",
                "category": "compute",
                "description": "Virtual machine",
                "typical_parents": ["missing-parent"],
            }
        ],
    }

    with pytest.raises(ResourceTypeRegistryError, match="unknown typical_parent"):
        load_resource_type_registry_from_mapping(payload)


def test_loader_rejects_typical_parent_cycle() -> None:
    payload = {
        "schema_version": "1.0.0",
        "version": "0.0.1",
        "types": [
            {
                "id": "compute.one",
                "category": "compute",
                "description": "one",
                "typical_parents": ["compute.two"],
            },
            {
                "id": "compute.two",
                "category": "compute",
                "description": "two",
                "typical_parents": ["compute.one"],
            },
        ],
    }

    with pytest.raises(ResourceTypeRegistryError, match="typical_parent cycle"):
        load_resource_type_registry_from_mapping(payload)


def test_only_subscription_has_no_parents() -> None:
    """`subscription` is the graph root; everyone else `contains`-descends from it."""
    registry = _shipped()
    rootless = [t.id for t in registry.types if not t.typical_parents]
    assert rootless == ["subscription"], (
        "only `subscription` may have zero typical parents; found: " + repr(rootless)
    )


def test_azure_arm_type_present_or_explicitly_null() -> None:
    """A `null` azure_arm_type is a design choice, not an oversight."""
    registry = _shipped()
    # P1 target list is all Azure-mappable.
    for entry in registry.types:
        assert entry.azure_arm_type is not None, (
            f"{entry.id}: azure_arm_type MUST be set for P1 (Azure is the implemented target)"
        )


def test_duplicate_id_is_rejected() -> None:
    payload = {
        "schema_version": "1.0.0",
        "version": "0.0.1",
        "types": [
            {
                "id": "compute.vm",
                "category": "compute",
                "description": "one",
            },
            {
                "id": "compute.vm",
                "category": "compute",
                "description": "two",
            },
        ],
    }
    with pytest.raises(ResourceTypeRegistryError) as info:
        load_resource_type_registry_from_mapping(payload)
    assert any("duplicate" in issue.message for issue in info.value.issues)


def test_canonical_ids_must_have_distinct_query_surfaces() -> None:
    payload = {
        "schema_version": "1.0.0",
        "version": "0.0.1",
        "types": [
            {
                "id": "compute.vm",
                "category": "compute",
                "description": "one",
            },
            {
                "id": "compute-vm",
                "category": "compute",
                "description": "two",
            },
        ],
    }

    with pytest.raises(ResourceTypeRegistryError, match="canonical query surface"):
        load_resource_type_registry_from_mapping(payload)


def test_missing_required_field_is_rejected() -> None:
    payload = {
        "schema_version": "1.0.0",
        "version": "0.0.1",
        "types": [
            {
                "id": "compute.vm",
                # missing category
                "description": "one",
            }
        ],
    }
    with pytest.raises(ResourceTypeRegistryError) as info:
        load_resource_type_registry_from_mapping(payload)
    joined = " ".join(f"{i.key}: {i.message}" for i in info.value.issues).lower()
    assert "category" in joined


def test_invalid_id_pattern_is_rejected() -> None:
    payload = {
        "schema_version": "1.0.0",
        "version": "0.0.1",
        "types": [
            {
                "id": "Compute.VM",  # uppercase disallowed
                "category": "compute",
                "description": "x",
            }
        ],
    }
    with pytest.raises(ResourceTypeRegistryError):
        load_resource_type_registry_from_mapping(payload)


def test_schema_version_must_match_bundled_schema() -> None:
    payload = {
        "schema_version": "2.0.0",
        "version": "0.0.1",
        "types": [
            {
                "id": "compute.vm",
                "category": "compute",
                "description": "Virtual machine",
            }
        ],
    }

    with pytest.raises(ResourceTypeRegistryError, match="schema_version"):
        load_resource_type_registry_from_mapping(payload)


def test_get_and_iter_agree_with_ids() -> None:
    registry = _shipped()
    seen_ids: list[str] = []
    for entry in registry:
        seen_ids.append(entry.id)
        assert registry.get(entry.id).id == entry.id
    assert set(seen_ids) == registry.ids()


def test_get_missing_raises_key_error() -> None:
    registry = _shipped()
    with pytest.raises(KeyError):
        registry.get("does-not-exist")


def test_loaded_registry_nested_collections_are_immutable() -> None:
    registry = _shipped()

    with pytest.raises(TypeError):
        registry.category_query_terms[ResourceTypeCategory.DATABASE] = ("mutated",)
    with pytest.raises(AttributeError):
        registry.get("compute.vm").typical_parents.append("subscription")
