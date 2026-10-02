from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml
from fdai_operator_service.families.workflow import (
    build_workflow_family_routes,
)
from fdai_operator_service.family_adapters import PostgresWorkflowAdapters
from fdai_service_contracts import OperatorPrincipal, OperatorRole
from fdai_service_contracts.schema import PackageResourceSchemaRegistry
from fdai_service_contracts.workflow_catalog import WorkflowCatalogError, load_workflow_from_mapping
from fdai_service_contracts.workflow_catalog.validation_context import (
    WORKFLOW_VALIDATION_CONTEXT_PROJECTION_KEY,
    WorkflowValidationContext,
)
from starlette.applications import Starlette
from starlette.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts/deployment/local/materialize-authoritative-catalogs.py"
WORKFLOWS_ROOT = REPO_ROOT / "rule-catalog/workflows"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("materialize_authoritative_catalogs", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _context_projection() -> dict[str, object]:
    module = _module()
    snapshots = module.catalog_snapshots(REPO_ROOT)
    return dict(snapshots[module.WORKFLOW_VALIDATION_CONTEXT_KEY])


class _ValidationStore:
    def __init__(self, state: dict[str, object] | None) -> None:
        self.state = state

    async def read_state(self, key: str) -> dict[str, object] | None:
        assert key == WORKFLOW_VALIDATION_CONTEXT_PROJECTION_KEY
        return self.state


class _UnusedProposalWriter:
    async def submit(self, proposal: object) -> object:
        raise AssertionError(f"validation must not submit proposals: {proposal!r}")


async def _authorize(*_args: object) -> OperatorPrincipal:
    return OperatorPrincipal("operator", frozenset({OperatorRole.OWNER}))


def _client(state: dict[str, object] | None) -> TestClient:
    adapter = PostgresWorkflowAdapters(_ValidationStore(state))  # type: ignore[arg-type]
    routes = build_workflow_family_routes(
        authorize=_authorize,  # type: ignore[arg-type]
        read_store=adapter,
        proposal_writer=_UnusedProposalWriter(),  # type: ignore[arg-type]
    )
    return TestClient(Starlette(routes=list(routes)))


def _yaml_mapping(path: Path) -> dict[str, Any]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    return raw


def _direct_result(
    raw: dict[str, Any],
    context: WorkflowValidationContext,
) -> tuple[bool, list[dict[str, str]]]:
    try:
        load_workflow_from_mapping(
            raw,
            schema_registry=PackageResourceSchemaRegistry(),
            action_type_names=set(context.action_type_names),
            rule_ids=set(context.rule_ids),
            signal_types=context.signal_types,
            workflow_trigger_events=context.workflow_trigger_events,
            origin="draft",
        )
    except WorkflowCatalogError as exc:
        return False, [{"key": issue.key, "message": issue.message} for issue in exc.issues]
    return True, []


def _draft_mutations(base: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    schema_violation = dict(base)
    schema_violation.pop("name")

    duplicate_step = {**base, "steps": [dict(base["steps"][0]), dict(base["steps"][0])]}
    duplicate_step["steps"][1]["id"] = duplicate_step["steps"][0]["id"]

    unresolved_failure = {**base, "steps": [dict(base["steps"][0])]}
    unresolved_failure["steps"][0]["on_failure"] = "missing_step"

    unknown_action = {**base, "steps": [dict(base["steps"][0])]}
    unknown_action["steps"][0]["action_type_ref"] = "ops.unknown-action"

    unknown_guard = {**base, "steps": [dict(base["steps"][0])]}
    unknown_guard["steps"][0]["guard_rule_ref"] = "unknown.rule"

    unknown_signal = {**base, "trigger": dict(base["trigger"])}
    unknown_signal["trigger"]["signal_type"] = "workflow.unknown.signal"

    return (
        schema_violation,
        duplicate_step,
        unresolved_failure,
        unknown_action,
        unknown_guard,
        unknown_signal,
    )


def test_operator_validate_matches_shared_loader_for_catalog_and_invalid_drafts() -> None:
    projection = _context_projection()
    context = WorkflowValidationContext.model_validate(
        {key: value for key, value in projection.items() if key != "_revision"}
    )
    client = _client(projection)
    raw_workflows = [_yaml_mapping(path) for path in sorted(WORKFLOWS_ROOT.glob("*.yaml"))]
    drafts = [*raw_workflows, *_draft_mutations(raw_workflows[0])]

    for draft in drafts:
        expected_valid, expected_issues = _direct_result(draft, context)
        response = client.post("/workflows/validate", json=draft)
        body = response.json()

        assert response.status_code == 200
        assert body["valid"] is expected_valid
        assert body["issues"] == expected_issues
        if expected_valid:
            assert isinstance(body["yaml_preview"], str) and body["yaml_preview"].strip()
        else:
            assert body["yaml_preview"] is None


def test_operator_validate_returns_issue_when_context_missing() -> None:
    response = _client(None).post("/workflows/validate", json={"schema_version": "1.0.0"})

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "valid": False,
        "issues": [
            {
                "key": "validation_context_unavailable",
                "message": "Workflow validation context projection is unavailable",
            }
        ],
        "yaml_preview": None,
    }


def test_operator_validate_returns_issue_when_context_stale() -> None:
    projection = _context_projection()
    projection["_revision"] = "sha256:" + "0" * 64

    response = _client(projection).post("/workflows/validate", json={"schema_version": "1.0.0"})

    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is False
    assert body["issues"] == [
        {
            "key": "validation_context_stale",
            "message": "Workflow validation context projection is stale",
        }
    ]
    assert body["yaml_preview"] is None


@pytest.mark.parametrize("body", ["not-json", ["not", "object"]])
def test_operator_validate_rejects_malformed_bodies(body: object) -> None:
    client = _client(_context_projection())

    if isinstance(body, str):
        response = client.post("/workflows/validate", content=body)
    else:
        response = client.post("/workflows/validate", json=body)

    assert 400 <= response.status_code < 500
