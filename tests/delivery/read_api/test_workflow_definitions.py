from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from starlette.applications import Starlette
from starlette.testclient import TestClient

from fdai.core.workflow.definition import build_workflow_definition
from fdai.delivery.read_api.routes.workflow_definitions import (
    WorkflowDefinitionRoutesConfig,
    make_workflow_definition_routes,
)
from fdai.rule_catalog.schema.action_type import load_action_type_catalog
from fdai.rule_catalog.schema.workflow import load_workflow_catalog
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.providers.testing.workflow_definition import (
    InMemoryWorkflowBindingStore,
    InMemoryWorkflowDefinitionStore,
)
from fdai.shared.providers.workflow_definition import (
    WorkflowLifecycle,
    WorkflowOrigin,
    WorkflowVisibility,
)

ROOT = Path(__file__).resolve().parents[3]
NOW = datetime(2026, 7, 16, 7, 0, tzinfo=UTC)


def _fixture(*, projector: object | None = None) -> tuple[TestClient, str]:
    registry = PackageResourceSchemaRegistry()
    actions = load_action_type_catalog(
        ROOT / "rule-catalog" / "action-types", schema_registry=registry
    )
    workflows = load_workflow_catalog(
        ROOT / "rule-catalog" / "workflows",
        schema_registry=registry,
        action_type_names={item.name for item in actions},
    )
    action_map = {item.name: item for item in actions}
    definition = build_workflow_definition(
        workflows[0],
        action_types=action_map,
        origin=WorkflowOrigin.UPSTREAM,
        visibility=WorkflowVisibility.GLOBAL,
        lifecycle=WorkflowLifecycle.SHADOW,
        created_at=NOW,
        source_ref="git:catalog",
    )
    config = WorkflowDefinitionRoutesConfig(
        definitions=InMemoryWorkflowDefinitionStore((definition,)),
        bindings=InMemoryWorkflowBindingStore(),
        schema_registry=registry,
        action_types=tuple(actions),
        ontology_projector=projector,  # type: ignore[arg-type]
    )

    async def authorize(_request) -> str:
        return "principal-a"

    app = Starlette(
        routes=list(make_workflow_definition_routes(config=config, authorize=authorize))
    )
    return TestClient(app), definition.definition_id


def test_catalog_groups_builtin_definition() -> None:
    client, _ = _fixture()
    payload = client.get("/workflows/definitions").json()
    assert payload["counts"]["built_in"] == 1
    assert payload["counts"]["mine"] == 0


def test_binding_requires_confirmation_and_uses_authenticated_principal() -> None:
    client, definition_id = _fixture()
    body = {
        "definition_id": definition_id,
        "trigger": "schedule",
        "cron_expression": "0 7 * * *",
        "timezone": "Asia/Seoul",
        "principal_id": "principal-b",
    }
    assert client.post("/workflows/bindings", json=body).status_code == 409
    response = client.post("/workflows/bindings", json={**body, "confirmed": True})
    assert response.status_code == 201
    assert response.json()["principal_id"] == "principal-a"
    assert response.json()["enabled"] is False
    duplicate = client.post("/workflows/bindings", json={**body, "confirmed": True})
    assert duplicate.status_code == 409
    assert "equivalent" in duplicate.text


def test_binding_trigger_fields_are_complete_and_mutually_exclusive() -> None:
    client, definition_id = _fixture()
    base = {"confirmed": True, "definition_id": definition_id}

    missing_schedule = client.post(
        "/workflows/bindings",
        json={**base, "trigger": "schedule", "cron_expression": "0 7 * * *"},
    )
    assert missing_schedule.status_code == 400
    assert "requires cron_expression and timezone" in missing_schedule.text

    mixed_signal = client.post(
        "/workflows/bindings",
        json={
            **base,
            "trigger": "signal",
            "signal_type": "object.event",
            "timezone": "UTC",
        },
    )
    assert mixed_signal.status_code == 400
    assert "MUST NOT declare schedule fields" in mixed_signal.text

    polluted_deck_open = client.post(
        "/workflows/bindings",
        json={**base, "trigger": "deck_open", "signal_type": "object.event"},
    )
    assert polluted_deck_open.status_code == 400
    assert "MUST NOT declare schedule or signal fields" in polluted_deck_open.text


def test_projection_failure_does_not_reverse_committed_binding_mutations() -> None:
    projector = MagicMock()
    projector.project_workflow_binding = AsyncMock(side_effect=RuntimeError("projection down"))
    projector.delete = AsyncMock(side_effect=RuntimeError("projection down"))
    client, definition_id = _fixture(projector=projector)
    body = {
        "confirmed": True,
        "definition_id": definition_id,
        "trigger": "schedule",
        "cron_expression": "0 7 * * *",
        "timezone": "Asia/Seoul",
    }

    created = client.post("/workflows/bindings", json=body)
    assert created.status_code == 201
    binding_id = created.json()["binding_id"]
    assert [
        item["binding_id"] for item in client.get("/workflows/definitions").json()["bindings"]
    ] == [binding_id]

    assert client.delete(f"/workflows/bindings/{binding_id}").status_code == 204
    assert client.get("/workflows/definitions").json()["bindings"] == []


def test_custom_definition_cannot_reference_unknown_action_type() -> None:
    client, _ = _fixture()
    response = client.post(
        "/workflows/definitions",
        json={
            "confirmed": True,
            "workflow": {
                "schema_version": "1.0.0",
                "name": "user.invalid-action",
                "version": "1.0.0",
                "trigger": {"kind": "signal", "signal_type": "object.event"},
                "default_mode": "shadow",
                "promotion_gate": {
                    "min_shadow_days": 1,
                    "min_samples": 1,
                    "min_accuracy": 1.0,
                    "max_policy_escapes": 0,
                },
                "steps": [{"id": "run", "action_type_ref": "missing.action"}],
            },
        },
    )
    assert response.status_code == 422
    assert "unknown ActionType" in response.text


def test_draft_definition_cannot_be_bound() -> None:
    client, _ = _fixture()
    document = {
        "schema_version": "1.0.0",
        "name": "user.draft",
        "version": "1.0.0",
        "trigger": {"kind": "signal", "signal_type": "object.event"},
        "default_mode": "shadow",
        "promotion_gate": {
            "min_shadow_days": 1,
            "min_samples": 1,
            "min_accuracy": 1.0,
            "max_policy_escapes": 0,
        },
        "steps": [{"id": "run", "action_type_ref": "tool.run-investigation"}],
    }
    created = client.post(
        "/workflows/definitions",
        json={"confirmed": True, "workflow": document},
    )
    assert created.status_code == 201
    definition_id = created.json()["definition"]["definition_id"]

    bound = client.post(
        "/workflows/bindings",
        json={
            "confirmed": True,
            "definition_id": definition_id,
            "trigger": "deck_open",
        },
    )

    assert bound.status_code == 409
    assert "not runnable" in bound.text
