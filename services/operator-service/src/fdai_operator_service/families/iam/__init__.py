"""Service-local Starlette factory for IAM and human governance routes."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import cast

from fdai_operator_service.families.iam.access_grants import make_access_grant_routes
from fdai_operator_service.families.iam.assignments import make_assignment_routes
from fdai_operator_service.families.iam.contracts import (
    AccessGrantOutbox,
    AssignmentRequestOutbox,
    AuthorizePrincipal,
    ConfigurationReviewOutbox,
    HandoverGoalOutbox,
    HilDecisionOutbox,
    HilDecisionRegistry,
    HumanAccessRequestOutbox,
    HumanIdentityDirectory,
    KillSwitchOutbox,
    ModelSettingsOutbox,
    RuntimeSettingsOutbox,
)
from fdai_operator_service.families.iam.governance import (
    make_configuration_review_routes,
    make_kill_switch_route,
)
from fdai_operator_service.families.iam.handover import make_handover_routes
from fdai_operator_service.families.iam.hil_callback import (
    HilCallbackConfig,
    make_hil_callback_route,
)
from fdai_operator_service.families.iam.iam_routes import make_iam_routes
from fdai_operator_service.families.iam.manifest import IAM_FAMILY_MANIFEST
from fdai_operator_service.families.iam.settings import (
    make_model_settings_routes,
    make_runtime_settings_routes,
)
from fdai_operator_service.redaction import redact_projection
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route


@dataclass(frozen=True, slots=True)
class IamFamilyBindings:
    """Injected non-privileged ports for the complete IAM route family."""

    authorize: AuthorizePrincipal
    authenticate: AuthorizePrincipal
    access_grants: AccessGrantOutbox | None = None
    human_access: HumanAccessRequestOutbox | None = None
    directory: HumanIdentityDirectory | None = None
    assignments: AssignmentRequestOutbox | None = None
    handover_goals: HandoverGoalOutbox | None = None
    model_settings: ModelSettingsOutbox | None = None
    runtime_settings: RuntimeSettingsOutbox | None = None
    kill_switch: KillSwitchOutbox | None = None
    configuration_review: ConfigurationReviewOutbox | None = None
    hil_registry: HilDecisionRegistry | None = None
    hil_outbox: HilDecisionOutbox | None = None
    hil_config: HilCallbackConfig | None = None
    identity_provider: str = "entra"
    role_group_ids: dict[str, str] | None = None


def make_iam_family_routes(bindings: IamFamilyBindings) -> tuple[Route, ...]:
    """Build the exact frozen IAM surface; missing dependencies fail closed per route."""
    routes = (
        *make_access_grant_routes(
            outbox=bindings.access_grants,
            authorize=bindings.authorize,
        ),
        *make_iam_routes(
            outbox=bindings.human_access,
            authorize=bindings.authorize,
            authenticate=bindings.authenticate,
            directory=bindings.directory,
            identity_provider=bindings.identity_provider,
            role_group_ids=bindings.role_group_ids,
        ),
        *make_assignment_routes(
            outbox=bindings.assignments,
            authorize=bindings.authorize,
            directory=bindings.directory,
            identity_provider=bindings.identity_provider,
        ),
        *make_handover_routes(
            outbox=bindings.handover_goals,
            authorize=bindings.authorize,
        ),
        *make_model_settings_routes(
            outbox=bindings.model_settings,
            authorize=bindings.authorize,
        ),
        *make_runtime_settings_routes(
            outbox=bindings.runtime_settings,
            authorize=bindings.authorize,
        ),
        make_kill_switch_route(
            outbox=bindings.kill_switch,
            authorize=bindings.authorize,
        ),
        *make_configuration_review_routes(
            outbox=bindings.configuration_review,
            authorize=bindings.authorize,
        ),
        make_hil_callback_route(
            registry=bindings.hil_registry,
            outbox=bindings.hil_outbox,
            config=bindings.hil_config,
        ),
    )
    snapshot = tuple(
        (next(iter((route.methods or set()) - {"HEAD"})), route.path, route.name)
        for route in routes
    )
    expected = tuple((item.method, item.path, item.name) for item in IAM_FAMILY_MANIFEST)
    if snapshot != expected:
        raise RuntimeError("IAM family route factory does not match its frozen manifest")
    return tuple(_redacting_route(route) for route in routes)


def _redacting_route(route: Route) -> Route:
    endpoint = cast(Callable[[Request], Awaitable[Response]], route.endpoint)

    async def redacted_endpoint(request: Request) -> Response:
        response = await endpoint(request)
        if not isinstance(response, JSONResponse):
            return response
        payload = json.loads(bytes(response.body))
        headers = {
            key: value
            for key, value in response.headers.items()
            if key.casefold() not in {"content-length", "content-type"}
        }
        return JSONResponse(
            redact_projection(payload),
            status_code=response.status_code,
            headers=headers,
            background=response.background,
        )

    redacted_endpoint.__name__ = route.name
    methods = sorted((route.methods or set()) - {"HEAD", "OPTIONS"})
    return Route(route.path, redacted_endpoint, methods=methods, name=route.name)


__all__ = [
    "IAM_FAMILY_MANIFEST",
    "HilCallbackConfig",
    "IamFamilyBindings",
    "make_iam_family_routes",
]
