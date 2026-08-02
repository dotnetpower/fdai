"""Principal-scoped WorkflowDefinition and WorkflowBinding routes."""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from fdai.core.user_context_projection import UserContextOntologyProjector
from fdai.core.workflow.definition import build_workflow_definition
from fdai.rule_catalog.schema.workflow import (
    WorkflowCatalogError,
    load_workflow_from_mapping,
)
from fdai.shared.contracts.models import OntologyActionType
from fdai.shared.contracts.registry import SchemaRegistry
from fdai.shared.providers.workflow_definition import (
    WorkflowBindingRecord,
    WorkflowBindingStore,
    WorkflowBindingTrigger,
    WorkflowDefinitionConflictError,
    WorkflowDefinitionStore,
    WorkflowLifecycle,
    WorkflowOrigin,
    WorkflowVisibility,
)

AuthorizeFn = Callable[[Request], Awaitable[str]]
_LOGGER = logging.getLogger(__name__)


async def _project_after_commit(
    operation: Awaitable[object],
    *,
    record_ref: str,
) -> None:
    try:
        await operation
    except Exception:  # noqa: BLE001 - source commit succeeded; durable recovery owns retry
        _LOGGER.exception("workflow ontology projection deferred for %s", record_ref)


@dataclass(frozen=True, slots=True)
class WorkflowDefinitionRoutesConfig:
    definitions: WorkflowDefinitionStore
    bindings: WorkflowBindingStore
    schema_registry: SchemaRegistry
    action_types: tuple[OntologyActionType, ...]
    rule_ids: frozenset[str] = frozenset()
    ontology_projector: UserContextOntologyProjector | None = None


def make_workflow_definition_routes(
    *, config: WorkflowDefinitionRoutesConfig, authorize: AuthorizeFn
) -> tuple[Route, ...]:
    action_types = {item.name: item for item in config.action_types}

    async def catalog(request: Request) -> Response:
        principal_id = await authorize(request)
        definitions = await config.definitions.list_visible(principal_id=principal_id)
        bindings = await config.bindings.list_for_principal(principal_id=principal_id)
        groups: dict[str, list[dict[str, Any]]] = {
            "built_in": [],
            "shared": [],
            "mine": [],
        }
        for definition in definitions:
            if definition.origin is WorkflowOrigin.UPSTREAM:
                group = "built_in"
            elif definition.owner_ref == principal_id:
                group = "mine"
            else:
                group = "shared"
            groups[group].append(_json(definition))
        return JSONResponse(
            {
                "groups": groups,
                "bindings": [_json(binding) for binding in bindings],
                "counts": {key: len(value) for key, value in groups.items()},
            }
        )

    async def create_definition(request: Request) -> Response:
        principal_id = await authorize(request)
        body = await _confirmed_body(request)
        document = body.get("workflow")
        if not isinstance(document, Mapping):
            raise HTTPException(status_code=400, detail="workflow MUST be an object")
        try:
            workflow = load_workflow_from_mapping(
                document,
                schema_registry=config.schema_registry,
                action_type_names=set(action_types),
                rule_ids=set(config.rule_ids) if config.rule_ids else None,
                origin="user-draft",
            )
            definition = build_workflow_definition(
                workflow,
                action_types=action_types,
                origin=WorkflowOrigin.USER,
                visibility=WorkflowVisibility.PRIVATE,
                lifecycle=WorkflowLifecycle.DRAFT,
                owner_ref=principal_id,
                derived_from=_optional_text(body, "derived_from"),
                source_ref=f"user:{principal_id}",
                created_at=datetime.now(tz=UTC),
            )
            stored = await config.definitions.put(definition)
            if config.ontology_projector is not None:
                await _project_after_commit(
                    config.ontology_projector.project_workflow_definition(stored),
                    record_ref=f"workflow-definition:{stored.definition_id}",
                )
        except WorkflowCatalogError as exc:
            return JSONResponse(
                {
                    "valid": False,
                    "issues": [
                        {"key": issue.key, "message": issue.message} for issue in exc.issues
                    ],
                },
                status_code=422,
            )
        except WorkflowDefinitionConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse({"valid": True, "definition": _json(stored)}, status_code=201)

    async def create_binding(request: Request) -> Response:
        principal_id = await authorize(request)
        body = await _confirmed_body(request)
        definition_id = _required_text(body, "definition_id")
        visible = await config.definitions.list_visible(principal_id=principal_id)
        definition = next(
            (item for item in visible if item.definition_id == definition_id),
            None,
        )
        if definition is None:
            raise HTTPException(status_code=404, detail="workflow definition not found")
        if definition.lifecycle not in {
            WorkflowLifecycle.SHADOW,
            WorkflowLifecycle.PUBLISHED,
        }:
            raise HTTPException(
                status_code=409,
                detail="workflow definition is not runnable",
            )
        try:
            trigger = WorkflowBindingTrigger(_required_text(body, "trigger"))
            scope_ref = _optional_text(body, "scope_ref")
            cron_expression = _optional_text(body, "cron_expression")
            timezone = _optional_text(body, "timezone")
            signal_type = _optional_text(body, "signal_type")
            _validate_binding_trigger(
                trigger,
                cron_expression=cron_expression,
                timezone=timezone,
                signal_type=signal_type,
            )
            existing_bindings = await config.bindings.list_for_principal(principal_id=principal_id)
            if any(
                item.definition_id == definition_id
                and item.trigger is trigger
                and item.scope_ref == scope_ref
                and item.cron_expression == cron_expression
                and item.timezone == timezone
                and item.signal_type == signal_type
                for item in existing_bindings
            ):
                raise HTTPException(
                    status_code=409,
                    detail="an equivalent workflow binding already exists",
                )
            record = WorkflowBindingRecord(
                binding_id=f"binding-{uuid4().hex}",
                principal_id=principal_id,
                definition_id=definition_id,
                trigger=trigger,
                # Runtime dispatch is not wired yet. Store the confirmed
                # binding as inert configuration rather than implying that it
                # will execute.
                enabled=False,
                scope_ref=scope_ref,
                cron_expression=cron_expression,
                timezone=timezone,
                signal_type=signal_type,
                parameters=_scalar_mapping(body.get("parameters", {})),
                created_at=datetime.now(tz=UTC),
                updated_at=datetime.now(tz=UTC),
            )
            stored = await config.bindings.create(record)
            if config.ontology_projector is not None:
                await _project_after_commit(
                    config.ontology_projector.project_workflow_binding(stored),
                    record_ref=f"workflow-binding:{principal_id}:{stored.binding_id}",
                )
        except WorkflowDefinitionConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse(_json(stored), status_code=201)

    async def update_binding(request: Request) -> Response:
        principal_id = await authorize(request)
        body = await _confirmed_body(request)
        binding_id = request.path_params["binding_id"]
        existing = next(
            (
                item
                for item in await config.bindings.list_for_principal(principal_id=principal_id)
                if item.binding_id == binding_id
            ),
            None,
        )
        if existing is None:
            raise HTTPException(status_code=404, detail="workflow binding not found")
        expected = body.get("expected_revision")
        if not isinstance(expected, int) or isinstance(expected, bool):
            raise HTTPException(status_code=400, detail="expected_revision MUST be an integer")
        try:
            updated = replace(
                existing,
                enabled=bool(body.get("enabled", existing.enabled)),
                scope_ref=_optional_text(body, "scope_ref", existing.scope_ref),
                parameters=_scalar_mapping(body.get("parameters", existing.parameters)),
                updated_at=datetime.now(tz=UTC),
            )
            stored = await config.bindings.put(updated, expected_revision=expected)
            if config.ontology_projector is not None:
                await _project_after_commit(
                    config.ontology_projector.project_workflow_binding(stored),
                    record_ref=f"workflow-binding:{principal_id}:{stored.binding_id}",
                )
        except WorkflowDefinitionConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse(_json(stored))

    async def delete_binding(request: Request) -> Response:
        principal_id = await authorize(request)
        deleted = await config.bindings.delete(
            principal_id=principal_id,
            binding_id=request.path_params["binding_id"],
        )
        if deleted and config.ontology_projector is not None:
            object_id = f"workflow-binding:{principal_id}:{request.path_params['binding_id']}"
            await _project_after_commit(
                config.ontology_projector.delete(object_id),
                record_ref=object_id,
            )
        return Response(status_code=204 if deleted else 404)

    return (
        Route("/workflows/definitions", catalog, methods=["GET"]),
        Route("/workflows/definitions", create_definition, methods=["POST"]),
        Route("/workflows/bindings", create_binding, methods=["POST"]),
        Route("/workflows/bindings/{binding_id:str}", update_binding, methods=["PUT"]),
        Route("/workflows/bindings/{binding_id:str}", delete_binding, methods=["DELETE"]),
    )


async def _body(request: Request) -> dict[str, Any]:
    raw = await request.body()
    if len(raw) > 256 * 1024:
        raise HTTPException(status_code=413, detail="request body too large")
    try:
        value = json.loads(raw) if raw else {}
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="request body MUST be JSON") from exc
    if not isinstance(value, dict):
        raise HTTPException(status_code=400, detail="request body MUST be an object")
    value.pop("principal_id", None)
    value.pop("owner_ref", None)
    return value


async def _confirmed_body(request: Request) -> dict[str, Any]:
    body = await _body(request)
    if body.get("confirmed") is not True:
        raise HTTPException(status_code=409, detail="explicit confirmation is required")
    return body


def _scalar_mapping(raw: object) -> dict[str, str | int | float | bool]:
    if not isinstance(raw, Mapping):
        raise ValueError("parameters MUST be an object")
    result: dict[str, str | int | float | bool] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not isinstance(value, (str, int, float, bool)):
            raise ValueError("parameters MUST contain scalar values")
        result[key] = value
    return result


def _validate_binding_trigger(
    trigger: WorkflowBindingTrigger,
    *,
    cron_expression: str | None,
    timezone: str | None,
    signal_type: str | None,
) -> None:
    if trigger is WorkflowBindingTrigger.SCHEDULE:
        if cron_expression is None or timezone is None:
            raise ValueError("schedule binding requires cron_expression and timezone")
        if signal_type is not None:
            raise ValueError("schedule binding MUST NOT declare signal_type")
        return
    if trigger is WorkflowBindingTrigger.SIGNAL:
        if signal_type is None:
            raise ValueError("signal binding requires signal_type")
        if cron_expression is not None or timezone is not None:
            raise ValueError("signal binding MUST NOT declare schedule fields")
        return
    if cron_expression is not None or timezone is not None or signal_type is not None:
        raise ValueError("deck_open binding MUST NOT declare schedule or signal fields")


def _required_text(body: Mapping[str, Any], key: str) -> str:
    value = body.get(key)
    if not isinstance(value, str) or not value.strip():
        raise HTTPException(status_code=400, detail=f"{key} MUST be a non-empty string")
    return value.strip()


def _optional_text(body: Mapping[str, Any], key: str, default: str | None = None) -> str | None:
    value = body.get(key, default)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise HTTPException(status_code=400, detail=f"{key} MUST be a non-empty string")
    return value.strip()


def _json(value: Any) -> Any:
    return json.loads(
        json.dumps(asdict(value), default=lambda item: getattr(item, "value", str(item)))
    )


__all__ = ["WorkflowDefinitionRoutesConfig", "make_workflow_definition_routes"]
