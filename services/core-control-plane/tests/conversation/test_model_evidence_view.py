"""Model evidence views expose only reviewed evidence cells."""

from __future__ import annotations

from fdai.core.conversation.model_evidence_view import model_evidence_view_from_tables
from fdai.core.ontology_platform.query_values import QueryRow, QueryTable
from fdai_service_contracts.ontology_query import EvidenceAuthority

RELEASE_DIGEST = "sha256:" + "a" * 64


def test_model_evidence_view_excludes_hidden_endpoints_and_unreviewed_fields() -> None:
    view = model_evidence_view_from_tables(
        (
            QueryTable(
                rows=(
                    QueryRow.from_values(
                        "link-1",
                        {
                            "from_id": "hidden-endpoint",
                            "to_id": "visible-endpoint",
                            "link_type": "depends_on",
                            "verified": True,
                            "verification_method": "inventory_graph",
                            "authority": "server_inventory_graph",
                            "effective_time": "2026-10-01T00:00:00Z",
                            "freshness_ceiling": "PT5M",
                            "completeness": "complete",
                            "provider_body": {"secret": "do-not-send"},
                        },
                    ),
                    QueryRow.from_values(
                        "resource-1",
                        {
                            "name": "visible-name",
                            "status": "running",
                            "resource_id": "hidden-resource-id",
                            "provider_body": {"raw": "do-not-send"},
                            "handle_ref": "OpaqueHandleRef0123456789abcdefABCDEF",
                            "snapshot_cells": {"name": "retained"},
                        },
                    ),
                ),
                complete=True,
            ),
        ),
        authorities=(EvidenceAuthority.SERVER_INVENTORY_GRAPH,),
        release_digest=RELEASE_DIGEST,
    )
    payload = view.as_payload()
    encoded = view.canonical_json()

    assert payload["release_digest"] == RELEASE_DIGEST
    assert "hidden-endpoint" not in encoded
    assert "visible-endpoint" not in encoded
    assert "depends_on" not in encoded
    assert "provider_body" not in encoded
    assert "hidden-resource-id" not in encoded
    assert "handle_ref" not in encoded
    assert "snapshot_cells" not in encoded
    assert "visible-name" in encoded
    assert "server_inventory_graph" in encoded
    assert "inventory_graph" in encoded


def test_an_object_set_row_lifts_reviewed_properties_but_never_the_provider_bag() -> None:
    view = model_evidence_view_from_tables(
        (
            QueryTable(
                rows=(
                    QueryRow.from_values(
                        "vm-1",
                        {
                            "id": "/subscriptions/hidden/vm-1",
                            "object_type": "Resource",
                            "properties": {
                                "name": "vm-app-01",
                                "type": "compute.vm",
                                "location": "koreacentral",
                                "parent_id": "/subscriptions/hidden/rg",
                                "properties": {"admin_password": "do-not-send"},
                            },
                        },
                    ),
                ),
                complete=True,
            ),
        ),
        authorities=(EvidenceAuthority.SERVER_INVENTORY_GRAPH,),
        release_digest=RELEASE_DIGEST,
    )

    (row,) = view.as_payload()["rows"]  # type: ignore[misc]
    assert row["cells"] == {  # type: ignore[index]
        "location": "koreacentral",
        "name": "vm-app-01",
        "object_type": "Resource",
        "type": "compute.vm",
    }
    encoded = view.canonical_json()
    assert "do-not-send" not in encoded
    assert "/subscriptions/hidden" not in encoded
