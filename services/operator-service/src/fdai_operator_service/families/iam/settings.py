"""Model and runtime settings routes over revisioned request outboxes."""

from __future__ import annotations

from typing import Final

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from fdai_operator_service.families.iam.capabilities import IamCapability, has_capability
from fdai_operator_service.families.iam.contracts import (
    AuthorizePrincipal,
    ModelPreferenceCommand,
    ModelSettingsOutbox,
    RuntimeSettingsCommand,
    RuntimeSettingsOutbox,
    WebSearchSettingsCommand,
)
from fdai_operator_service.families.iam.errors import IamFamilyError
from fdai_operator_service.families.iam.http import (
    error_response,
    family_error,
    read_json_object,
    require_revision,
)

_MAX_BODY_BYTES: Final = 16_000


def make_model_settings_routes(
    *, outbox: ModelSettingsOutbox | None, authorize: AuthorizePrincipal
) -> tuple[Route, ...]:
    """Build model settings routes that persist policy but never provision a model."""

    async def get_settings(request: Request) -> Response:
        principal = await authorize(request)
        if outbox is None:
            return error_response(503, "model settings outbox is not configured")
        try:
            projection = await outbox.projection(
                principal.oid,
                can_manage_web_search=has_capability(
                    principal.roles, IamCapability.MANAGE_GROUP_MEMBERSHIP
                ),
                refresh_model_catalog=request.query_params.get("refresh_catalog") == "1",
            )
        except IamFamilyError as exc:
            return family_error(exc)
        return JSONResponse(dict(projection))

    async def put_preference(request: Request) -> Response:
        principal = await authorize(request)
        if outbox is None:
            return error_response(503, "model settings outbox is not configured")
        body = await read_json_object(request, maximum=_MAX_BODY_BYTES)
        requested = body.get("preferred_narrator_model")
        if not isinstance(requested, str):
            return error_response(400, "preferred_narrator_model MUST be a string")
        try:
            await outbox.set_preference(
                ModelPreferenceCommand(
                    principal_id=principal.oid,
                    preferred_narrator_model=requested,
                    expected_revision=require_revision(body),
                )
            )
            projection = await outbox.projection(principal.oid)
        except IamFamilyError as exc:
            return family_error(exc)
        return JSONResponse(dict(projection))

    async def put_web_search(request: Request) -> Response:
        principal = await authorize(request)
        if not has_capability(principal.roles, IamCapability.MANAGE_GROUP_MEMBERSHIP):
            return error_response(403, "Owner role is required")
        if outbox is None:
            return error_response(503, "model settings outbox is not configured")
        body = await read_json_object(request, maximum=_MAX_BODY_BYTES)
        enabled = body.get("enabled")
        domains = body.get("allowed_domains")
        if not isinstance(enabled, bool):
            return error_response(400, "enabled MUST be a boolean")
        if not isinstance(domains, list) or not all(isinstance(item, str) for item in domains):
            return error_response(400, "allowed_domains MUST be a string array")
        try:
            normalized = _normalize_domains(tuple(domains))
            if enabled and not normalized:
                return error_response(
                    400, "allowed_domains MUST contain at least one host when enabled"
                )
            await outbox.set_web_search_settings(
                WebSearchSettingsCommand(
                    actor_id=principal.oid,
                    enabled=enabled,
                    allowed_domains=normalized,
                    expected_revision=require_revision(body),
                )
            )
            projection = await outbox.projection(
                principal.oid,
                can_manage_web_search=True,
            )
        except IamFamilyError as exc:
            return family_error(exc)
        except ValueError as exc:
            return error_response(400, str(exc))
        return JSONResponse(dict(projection))

    return (
        Route("/models/settings", get_settings, methods=["GET"]),
        Route("/models/web-search-settings", put_web_search, methods=["PUT"]),
        Route("/me/model-preferences", put_preference, methods=["PUT"]),
    )


def make_runtime_settings_routes(
    *, outbox: RuntimeSettingsOutbox | None, authorize: AuthorizePrincipal
) -> tuple[Route, ...]:
    """Build runtime policy routes that stop at audited durable overrides."""

    async def get_settings(request: Request) -> Response:
        principal = await authorize(request)
        if outbox is None:
            return error_response(503, "runtime settings outbox is not configured")
        try:
            projection = await outbox.projection(
                can_manage=has_capability(principal.roles, IamCapability.MANAGE_RUNTIME_SETTINGS)
            )
        except IamFamilyError as exc:
            return family_error(exc)
        return JSONResponse(dict(projection))

    async def put_settings(request: Request) -> Response:
        principal = await authorize(request)
        if not has_capability(principal.roles, IamCapability.MANAGE_RUNTIME_SETTINGS):
            return error_response(403, "Owner role is required")
        if outbox is None:
            return error_response(503, "runtime settings outbox is not configured")
        body = await read_json_object(request, maximum=_MAX_BODY_BYTES)
        changes = body.get("changes")
        if not isinstance(changes, dict):
            return error_response(400, "changes MUST be an object")
        try:
            await outbox.update(
                RuntimeSettingsCommand(
                    actor_id=principal.oid,
                    changes=changes,
                    expected_revision=require_revision(body),
                )
            )
            projection = await outbox.projection(can_manage=True)
        except IamFamilyError as exc:
            return family_error(exc)
        return JSONResponse(dict(projection))

    return (
        Route("/runtime/settings", get_settings, methods=["GET"]),
        Route("/runtime/settings", put_settings, methods=["PUT"]),
    )


def _normalize_domains(domains: tuple[str, ...]) -> tuple[str, ...]:
    normalized = tuple(
        dict.fromkeys(item.strip().casefold().rstrip(".") for item in domains if item.strip())
    )
    if len(normalized) > 100:
        raise ValueError("allowed_domains MUST contain at most 100 hosts")
    if any(not _valid_domain(domain) for domain in normalized):
        raise ValueError(
            "allowed_domains MUST contain hosts without schemes, paths, ports, or wildcards"
        )
    return normalized


def _valid_domain(domain: str) -> bool:
    if (
        len(domain) > 253
        or "." not in domain
        or any(token in domain for token in ("://", "/", ":", "*"))
    ):
        return False
    return all(
        bool(label)
        and len(label) <= 63
        and label[0].isalnum()
        and label[-1].isalnum()
        and all(character.isalnum() or character == "-" for character in label)
        for label in domain.split(".")
    )


__all__ = ["make_model_settings_routes", "make_runtime_settings_routes"]
