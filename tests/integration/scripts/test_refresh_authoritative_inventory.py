from __future__ import annotations

import importlib.util
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts/deployment/local/refresh-authoritative-inventory.py"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("refresh_authoritative_inventory", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_refresh_binds_projection_to_loaded_ontology_release() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "ontology_release_digest=ontology.build_release().digest" in source
    assert "relationship_mapping_catalog=load_provider_relationship_mapping_catalog(" in source


def test_operator_projection_is_bounded_and_filters_unsupported_links() -> None:
    module = _module()
    payload = module._operator_inventory_payload(
        snapshot_at=datetime(2026, 8, 10, 12, 0, tzinfo=UTC),
        resource_rows=[
            {
                "resource_id": "scope/resource-group/example",
                "resource_type": "resource-group",
                "props": {"name": "example"},
            },
            {
                "resource_id": "scope/resource-group/example/vnet/one",
                "resource_type": "network.vnet",
                "props": {"name": "one", "status": "Ready"},
            },
            {
                "resource_id": "scope/resource-group/example/vnet/two",
                "resource_type": "network.vnet",
                "props": {"name": "two", "status": "Ready"},
            },
        ],
        link_rows=[
            {
                "from_id": "scope/resource-group/example",
                "link_type": "contains",
                "to_id": "scope/resource-group/example/vnet/one",
            },
            {
                "from_id": "scope/resource-group/example/vnet/one",
                "link_type": "peered_with",
                "to_id": "scope/resource-group/example/vnet/two",
            },
            {
                "from_id": "scope/resource-group/example/vnet/two",
                "link_type": "peered_with",
                "to_id": "scope/resource-group/example/vnet/missing",
            },
        ],
    )

    assert payload["source"] == "azure-cli-local"
    assert payload["truncated"] is False
    assert payload["links"] == [
        {
            "source": "scope/resource-group/example",
            "target": "scope/resource-group/example/vnet/one",
            "type": "contains",
        },
        {
            "source": "scope/resource-group/example/vnet/one",
            "target": "scope/resource-group/example/vnet/two",
            "type": "peered_with",
        },
    ]
    resources = payload["resources"]
    assert isinstance(resources, list)
    assert resources[1]["parent_id"] == "scope/resource-group/example"
    assert resources[1]["status"] == "Ready"
    assert payload["included_link_types"] == [
        "contains",
        "attached_to",
        "depends_on",
        "peered_with",
    ]
