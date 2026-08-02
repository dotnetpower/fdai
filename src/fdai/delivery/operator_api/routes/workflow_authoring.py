"""Read-only workflow authoring routes (custom business-process builder).

Two endpoints back the console's ``workflow-builder`` view, the surface
an operator uses to map a custom business process onto the ontology:

- ``GET  /workflows/action-types`` - the ActionType palette. A read-only
  projection of the loaded ActionType catalog so the builder can offer a
  typed dropdown of every mutation primitive (with its safety posture)
  instead of a free-text field. Picking from the palette is what makes a
  step's ``action_type_ref`` resolvable at load time.
- ``POST /workflows/validate`` - validate a draft Workflow mapping and
  return a canonical YAML preview. This is a *pure function*: it runs the
  same :func:`load_workflow_from_mapping` the catalog loader uses (JSON
  Schema + pydantic structural invariants + ActionType / rule
  cross-reference) and returns the aggregated issues. It writes no state,
  registers no side effect, and never creates a PR - the console copies
  the previewed YAML into a remediation PR through the git-native path,
  never a console button (app-shape.instructions.md § Operator console).
- ``GET  /workflows/catalog`` - the shipped (built-in) Workflow catalog.
  A read-only projection of the loaded Workflow catalog so the builder
  can list every built-in process and show its full content (trigger,
  steps, promotion gate, YAML) before an operator drafts a new one.

Both routes require the Reader role and are opt-in through
:class:`~fdai.delivery.operator_api.main.OperatorApiConfig.workflow_authoring`
(unset by default so upstream stays minimal). The catalog data is
injected, not read from disk in the handler, so the routes stay pure and
testable exactly like the pantheon projections.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import yaml
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from fdai.rule_catalog.schema.workflow import (
    WorkflowCatalogError,
    load_workflow_from_mapping,
)
from fdai.shared.contracts.models import OntologyActionType, Workflow
from fdai.shared.contracts.registry import SchemaRegistry

_LOGGER = logging.getLogger(__name__)

# Cap the validate request body. A workflow draft is a few KB at most; 256 KB
# is a generous ceiling that still fails closed against an oversized or
# malicious payload before it is buffered into memory + parsed.
_MAX_VALIDATE_BODY_BYTES = 256 * 1024

ACTION_TYPES_ROUTE_PATH = "/workflows/action-types"
VALIDATE_ROUTE_PATH = "/workflows/validate"
CATALOG_ROUTE_PATH = "/workflows/catalog"


@dataclass(frozen=True, slots=True)
class WorkflowAuthoringConfig:
    """Injected catalog inputs for the authoring routes.

    ``action_types`` is the loaded ActionType palette. ``rule_ids`` is the
    set of Rule ids a step may reference through ``guard_rule_ref``; when
    empty the validator skips the guard cross-check (a caller that has not
    loaded the rule catalog passes an empty set rather than fail a draft
    that names a real guard), matching the ``rule_ids=None`` contract of
    :func:`load_workflow_from_mapping`. ``workflows`` is the loaded
    built-in Workflow catalog, served read-only by the catalog route so
    the builder can list and inspect shipped processes.
    """

    schema_registry: SchemaRegistry
    action_types: tuple[OntologyActionType, ...]
    rule_ids: frozenset[str] = field(default_factory=frozenset)
    workflows: tuple[Workflow, ...] = ()


def _serialize_action_type(at: OntologyActionType) -> dict[str, object]:
    """Project one ActionType to the fields the builder palette needs.

    Only the decision-relevant surface: identity, the category bucket, the
    rollback / irreversibility posture, the default mode, and a compact
    summary of which tiers escalate to HIL. This is what an operator needs
    to choose a step and understand its safety weight, not the full model.
    """
    hil_tiers: list[str] = []
    ceiling = at.ceiling_by_tier
    if ceiling is not None:
        for tier_name in ("t0", "t1", "t2"):
            tier = getattr(ceiling, tier_name)
            autonomy = getattr(tier, "autonomy", None)
            if autonomy is not None and autonomy.value == "enforce_hil":
                hil_tiers.append(tier_name.upper())
    return {
        "name": at.name,
        "operation": at.operation.value,
        "category": at.category.value if at.category is not None else None,
        "rollback_contract": at.rollback_contract.value,
        "irreversible": at.irreversible,
        "default_mode": at.default_mode.value,
        "execution_path": at.execution_path.value if at.execution_path is not None else None,
        "env_scope": at.env_scope.value,
        "hil_tiers": hil_tiers,
        "description": at.description,
    }


def _workflow_ordered_mapping(workflow: Workflow) -> dict[str, Any]:
    """Build the canonical catalog-as-code mapping for a Workflow.

    Field order matches the shipped workflow files under
    ``rule-catalog/workflows/``. ``None`` values are dropped; a step's
    optional fields are emitted only when set. Shared by the YAML preview
    and the read-only catalog projection so both stay in lockstep.
    """
    ordered: dict[str, Any] = {
        "schema_version": str(workflow.schema_version),
        "name": workflow.name,
        "version": str(workflow.version),
    }
    if workflow.description is not None:
        ordered["description"] = workflow.description
    trigger: dict[str, Any] = {"kind": workflow.trigger.kind.value}
    if workflow.trigger.signal_type is not None:
        trigger["signal_type"] = workflow.trigger.signal_type
    if workflow.trigger.schedule is not None:
        trigger["schedule"] = workflow.trigger.schedule
    ordered["trigger"] = trigger
    ordered["default_mode"] = workflow.default_mode.value
    gate = workflow.promotion_gate
    ordered["promotion_gate"] = {
        "min_shadow_days": gate.min_shadow_days,
        "min_samples": gate.min_samples,
        "min_accuracy": gate.min_accuracy,
        "max_policy_escapes": gate.max_policy_escapes,
    }
    steps: list[dict[str, Any]] = []
    for step in workflow.steps:
        step_out: dict[str, Any] = {"id": step.id, "action_type_ref": step.action_type_ref}
        if step.guard_rule_ref is not None:
            step_out["guard_rule_ref"] = step.guard_rule_ref
        if step.compensated_by is not None:
            step_out["compensated_by"] = step.compensated_by
        if step.on_failure is not None:
            step_out["on_failure"] = step.on_failure
        if step.params:
            step_out["params"] = dict(step.params)
        steps.append(step_out)
    ordered["steps"] = steps
    if workflow.anti_scope is not None:
        ordered["anti_scope"] = workflow.anti_scope
    return ordered


def _workflow_to_yaml(workflow: Workflow) -> str:
    """Render a validated Workflow to canonical catalog-as-code YAML.

    The preview is copy-paste ready for a remediation PR.
    """
    return yaml.safe_dump(
        _workflow_ordered_mapping(workflow), sort_keys=False, allow_unicode=False, width=80
    )


def _serialize_workflow(workflow: Workflow) -> dict[str, Any]:
    """Project one built-in Workflow to a read-only catalog entry.

    Carries the full structured content (so the console can render a
    property table) plus the canonical YAML (so it can show the raw
    catalog-as-code form), never a mutable handle.
    """
    mapping = _workflow_ordered_mapping(workflow)
    mapping["step_count"] = len(workflow.steps)
    mapping["yaml"] = _workflow_to_yaml(workflow)
    return mapping


def make_action_types_route(
    *,
    config: WorkflowAuthoringConfig,
    authorize: Callable[[Request], Awaitable[str]],
    path: str = ACTION_TYPES_ROUTE_PATH,
) -> Route:
    """Return the ``GET /workflows/action-types`` palette route."""

    palette = sorted(
        (_serialize_action_type(at) for at in config.action_types),
        key=lambda entry: str(entry["name"]),
    )

    async def handler(request: Request) -> Response:
        await authorize(request)
        return JSONResponse({"action_types": palette, "count": len(palette)})

    return Route(path, handler, methods=["GET"])


def make_workflow_validate_route(
    *,
    config: WorkflowAuthoringConfig,
    authorize: Callable[[Request], Awaitable[str]],
    path: str = VALIDATE_ROUTE_PATH,
) -> Route:
    """Return the ``POST /workflows/validate`` route.

    The request body is the draft Workflow mapping. The response is always
    HTTP 200 with ``{valid, issues, yaml_preview}`` - a validation *result*
    is not an HTTP error. A malformed request body (not JSON, not an
    object) is a 400 client error, distinct from a well-formed draft that
    fails workflow validation.
    """
    action_type_names = {at.name for at in config.action_types}
    rule_ids: set[str] | None = set(config.rule_ids) if config.rule_ids else None

    async def handler(request: Request) -> Response:
        await authorize(request)
        # Fail closed on an oversized body before buffering / parsing it.
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                declared = int(content_length)
            except ValueError:
                return JSONResponse({"error": "invalid content-length"}, status_code=400)
            if declared > _MAX_VALIDATE_BODY_BYTES:
                return JSONResponse({"error": "request body too large"}, status_code=413)
        raw = await request.body()
        if len(raw) > _MAX_VALIDATE_BODY_BYTES:
            return JSONResponse({"error": "request body too large"}, status_code=413)
        try:
            body = json.loads(raw)
        except json.JSONDecodeError as exc:
            return JSONResponse(
                {"error": f"request body is not valid JSON: {exc}"}, status_code=400
            )
        if not isinstance(body, dict):
            return JSONResponse(
                {"error": "request body must be a JSON object (a Workflow draft)"},
                status_code=400,
            )
        try:
            model = load_workflow_from_mapping(
                body,
                schema_registry=config.schema_registry,
                action_type_names=action_type_names,
                rule_ids=rule_ids,
                origin="draft",
            )
        except WorkflowCatalogError as exc:
            return JSONResponse(
                {
                    "valid": False,
                    "issues": [{"key": i.key, "message": i.message} for i in exc.issues],
                    "yaml_preview": None,
                }
            )
        except Exception:  # noqa: BLE001 - boundary hardening: never 500 on untrusted input
            # The loader is designed to aggregate every issue into a
            # WorkflowCatalogError; anything else is unexpected. Fail closed
            # with a safe message and no stack leak, and log for triage.
            _LOGGER.warning("workflow_validate_unexpected_error", exc_info=True)
            return JSONResponse({"error": "could not validate the draft"}, status_code=422)
        return JSONResponse({"valid": True, "issues": [], "yaml_preview": _workflow_to_yaml(model)})

    return Route(path, handler, methods=["POST"])


def make_workflow_catalog_route(
    *,
    config: WorkflowAuthoringConfig,
    authorize: Callable[[Request], Awaitable[str]],
    path: str = CATALOG_ROUTE_PATH,
) -> Route:
    """Return the ``GET /workflows/catalog`` built-in-workflow route.

    A read-only projection of the loaded Workflow catalog, name-ordered so
    the console can list every shipped process and inspect its full
    content before an operator drafts a new one.
    """
    catalog = sorted(
        (_serialize_workflow(w) for w in config.workflows),
        key=lambda entry: str(entry["name"]),
    )

    async def handler(request: Request) -> Response:
        await authorize(request)
        return JSONResponse({"workflows": catalog, "count": len(catalog)})

    return Route(path, handler, methods=["GET"])


__all__ = [
    "ACTION_TYPES_ROUTE_PATH",
    "CATALOG_ROUTE_PATH",
    "VALIDATE_ROUTE_PATH",
    "WorkflowAuthoringConfig",
    "make_action_types_route",
    "make_workflow_catalog_route",
    "make_workflow_validate_route",
]
