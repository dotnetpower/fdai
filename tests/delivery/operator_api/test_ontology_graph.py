"""Integration tests for the ``/ontology/graph`` GET route."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest
from starlette.testclient import TestClient

from fdai.core.rbac.resolver import RoleResolver
from fdai.delivery.operator_api.auth import build_authenticator
from fdai.delivery.operator_api.main import OperatorApiConfig, build_app
from fdai.delivery.operator_api.read_model import InMemoryConsoleReadModel
from fdai.delivery.operator_api.routes.chat_inventory_compiler import compile_inventory_query
from fdai.delivery.operator_api.routes.chat_inventory_ontology import (
    inventory_query_function_type,
    project_inventory_function_result,
)
from fdai.rule_catalog.schema.action_type import load_action_type_catalog
from fdai.rule_catalog.schema.link_type import load_link_type_catalog
from fdai.rule_catalog.schema.object_type import load_object_type_catalog
from fdai.shared.contracts.models import (
    OntologyActionType,
    OntologyLinkType,
    OntologyObjectType,
)
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.providers.testing.state_store import InMemoryStateStore

REPO_ROOT = Path(__file__).resolve().parents[3]
OBJECT_TYPES_ROOT = REPO_ROOT / "rule-catalog" / "vocabulary" / "object-types"
LINK_TYPES_ROOT = REPO_ROOT / "rule-catalog" / "vocabulary" / "link-types"
ACTION_TYPES_ROOT = REPO_ROOT / "rule-catalog" / "action-types"


@pytest.fixture(autouse=True)
def _dev_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FDAI_OPERATOR_API_DEV_MODE", "1")


def _catalog() -> tuple[
    tuple[OntologyObjectType, ...],
    tuple[OntologyLinkType, ...],
    tuple[OntologyActionType, ...],
]:
    registry = PackageResourceSchemaRegistry()
    objects = load_object_type_catalog(OBJECT_TYPES_ROOT, schema_registry=registry)
    links = load_link_type_catalog(LINK_TYPES_ROOT, schema_registry=registry, object_types=objects)
    actions = load_action_type_catalog(ACTION_TYPES_ROOT, schema_registry=registry)
    return objects, links, actions


def _client(*, wire_ontology: bool, status_store: InMemoryStateStore | None = None) -> TestClient:
    objects, links, actions = _catalog() if wire_ontology else ((), (), ())
    resolver = cast(RoleResolver, lambda claims: None)
    auth = build_authenticator(verifier=lambda t: {"oid": "u"}, resolver=resolver)
    app = build_app(
        authenticator=auth,
        read_model=InMemoryConsoleReadModel(),
        config=OperatorApiConfig(
            dev_mode=True,
            ontology_object_types=tuple(objects),
            ontology_link_types=tuple(links),
            ontology_action_types=tuple(actions),
            ontology_function_types=(inventory_query_function_type(),),
            operating_model_status_reader=status_store,
        ),
    )
    return TestClient(app)


def test_ontology_graph_returns_mermaid_and_counts() -> None:
    client = _client(wire_ontology=True)
    resp = client.get("/ontology/graph")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["mermaid"].startswith("classDiagram\n")
    assert body["object_type_count"] >= 4
    assert body["link_type_count"] >= 5
    assert body["action_type_count"] >= 1
    assert "Resource" in body["object_types"]
    assert "contains" in body["link_types"]
    action = next(item for item in body["action_types"] if item["name"] == "ops.scale-out")
    assert action["default_mode"] == "shadow"
    assert action["rollback_contract"] == "state_forward_only"
    assert action["stop_conditions"]
    issue = next(item for item in body["nodes"] if item["name"] == "Issue")
    assert issue["lifecycle"]["owner"] == "Saga"
    assert issue["lifecycle"]["creation"][0]["source_refs"]
    assert issue["lifecycle"]["deduplication"]["strategy"] == "deterministic fingerprint"
    assert body["operating_model"] == {"status": "unavailable"}
    platform = body["ontology_platform"]
    assert platform["release_digest"].startswith("sha256:")
    assert platform["mutation_authority"] is False
    assert platform["write_surface"] == "typed_proposal"
    assert "ops.scale-out" in platform["action_types"]
    assert "inventory.select_resources" in platform["functions"]


@pytest.mark.parametrize("status", ("matched", "partial"))
def test_inventory_function_contract_accepts_bounded_runtime_projection(status: str) -> None:
    from jsonschema import Draft202012Validator

    query = compile_inventory_query("VM list")
    assert query is not None
    runtime_result = {
        "status": status,
        "query": query.to_dict(),
        "matched_count": 1,
        "resources": [
            {
                "id": "must-not-cross-function-boundary",
                "name": "vm-a",
                "type": "compute.vm",
                "status": "running",
                "unknown_runtime_metadata": "must-not-cross-function-boundary",
            }
        ],
        "query_source": "current_state",
        "freshness": "fresh",
        "unknown_runtime_metadata": "must-not-cross-function-boundary",
    }

    projected = project_inventory_function_result(runtime_result)

    Draft202012Validator(inventory_query_function_type().output_schema).validate(projected)
    assert projected == {
        "status": status,
        "query": runtime_result["query"],
        "matched_count": 1,
        "resource_preview_truncated": False,
        "resources": [{"name": "vm-a", "type": "compute.vm", "status": "running"}],
    }


def test_inventory_function_contract_accepts_unavailable_runtime_projection() -> None:
    from jsonschema import Draft202012Validator

    projected = project_inventory_function_result(
        {
            "status": "unavailable",
            "reason": "provider_unavailable",
            "query_source": "current_state",
        }
    )

    Draft202012Validator(inventory_query_function_type().output_schema).validate(projected)
    assert projected == {
        "status": "unavailable",
        "query": None,
        "reason": "provider_unavailable",
    }


def test_inventory_function_projection_rejects_invalid_query() -> None:
    with pytest.raises(ValueError, match="output_schema"):
        project_inventory_function_result(
            {
                "status": "unavailable",
                "reason": "provider_unavailable",
                "query": {"source": "current", "unknown": "not-allowed"},
            }
        )


def test_inventory_function_projection_rejects_invalid_semantic_candidate() -> None:
    with pytest.raises(ValueError, match="output_schema"):
        project_inventory_function_result(
            {
                "status": "clarification",
                "reason": "inventory_semantic_confirmation_required",
                "query": None,
                "resource_types": ["compute.vm"],
                "semantic_candidates": [
                    {
                        "kind": "state",
                        "concept_id": "running",
                        "score": 0.9,
                        "catalog_digest": "not-a-digest",
                        "target_ref": {},
                        "input_digest": "not-a-digest",
                        "candidate_digest": "not-a-digest",
                        "labels": {"en": "Running"},
                        "authority": "candidate_only",
                    }
                ],
            }
        )


@pytest.mark.parametrize(
    "resources, matched_count",
    (
        ([object()], 1),
        ([{"name": f"vm-{index}", "type": "compute.vm"} for index in range(41)], 41),
    ),
)
def test_inventory_function_projection_rejects_lossy_resource_evidence(
    resources: list[object],
    matched_count: int,
) -> None:
    query = compile_inventory_query("VM list")
    assert query is not None

    with pytest.raises(ValueError, match="resource|matched_count"):
        project_inventory_function_result(
            {
                "status": "matched",
                "query": query.to_dict(),
                "matched_count": matched_count,
                "resources": resources,
            }
        )


def test_inventory_function_projection_marks_bounded_resource_preview() -> None:
    query = compile_inventory_query("VM list")
    assert query is not None

    projected = project_inventory_function_result(
        {
            "status": "matched",
            "query": query.to_dict(),
            "matched_count": 41,
            "resources": [{"name": f"vm-{index}", "type": "compute.vm"} for index in range(40)],
        }
    )

    assert projected["matched_count"] == 41
    assert projected["resource_preview_truncated"] is True
    assert len(projected["resources"]) == 40


def test_inventory_function_projection_preserves_scheduled_shutdown_fields() -> None:
    query = compile_inventory_query(
        "오늘 저녁에 꺼지는 vm은?",
        now=datetime(2026, 8, 5, 3, 0, tzinfo=UTC),
    )
    assert query is not None

    projected = project_inventory_function_result(
        {
            "status": "matched",
            "query": query.to_dict(),
            "matched_count": 1,
            "resources": [
                {
                    "name": "vm-example",
                    "type": "compute.vm",
                    "status": "scheduled_shutdown",
                    "resource_group": "rg-example",
                    "scheduled_shutdown_at": "2026-08-05T19:00:00+09:00",
                    "scheduled_shutdown_time_zone": "Korea Standard Time",
                }
            ],
        }
    )

    assert projected["resources"][0]["scheduled_shutdown_at"] == ("2026-08-05T19:00:00+09:00")
    assert projected["resources"][0]["scheduled_shutdown_time_zone"] == ("Korea Standard Time")


def test_inventory_function_projection_rejects_matched_result_without_query() -> None:
    with pytest.raises(ValueError, match="requires a query"):
        project_inventory_function_result(
            {
                "status": "matched",
                "query": None,
                "matched_count": 0,
                "resources": [],
            }
        )


def test_inventory_function_projection_rejects_mixed_malformed_candidates() -> None:
    with pytest.raises(ValueError, match="semantic candidate"):
        project_inventory_function_result(
            {
                "status": "clarification",
                "reason": "inventory_semantic_confirmation_required",
                "query": None,
                "resource_types": ["compute.vm"],
                "semantic_candidates": [{}, object()],
            }
        )


def test_ontology_graph_returns_bounded_operating_model_status() -> None:
    import asyncio

    status_store = InMemoryStateStore()
    asyncio.run(
        status_store.write_state(
            "operating-model:status",
            {
                "schema_version": "1.0.0",
                "status": "projected",
                "source_revision": "revision-1",
                "object_count": 9,
                "link_count": 12,
                "secret": "must-not-leak",
            },
        )
    )

    body = _client(wire_ontology=True, status_store=status_store).get("/ontology/graph").json()

    assert body["operating_model"] == {
        "schema_version": "1.0.0",
        "status": "projected",
        "source_revision": "revision-1",
        "object_count": 9,
        "link_count": 12,
    }


def test_slim_mode_omits_properties() -> None:
    client = _client(wire_ontology=True)
    verbose = client.get("/ontology/graph").json()
    slim = client.get("/ontology/graph", params={"include_properties": "false"}).json()
    assert len(slim["mermaid"]) < len(verbose["mermaid"])
    assert slim["object_type_count"] == verbose["object_type_count"]


def test_property_limit_rejects_zero() -> None:
    client = _client(wire_ontology=True)
    resp = client.get("/ontology/graph", params={"property_limit": "0"})
    assert resp.status_code == 400


def test_property_limit_rejects_non_int() -> None:
    client = _client(wire_ontology=True)
    resp = client.get("/ontology/graph", params={"property_limit": "abc"})
    assert resp.status_code == 400


def test_route_absent_when_ontology_not_configured() -> None:
    client = _client(wire_ontology=False)
    resp = client.get("/ontology/graph")
    assert resp.status_code == 404


def test_route_is_get_only() -> None:
    client = _client(wire_ontology=True)
    resp = client.post("/ontology/graph")
    assert resp.status_code == 405
