"""Emergency stop and configuration-review request routes."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final, Protocol
from uuid import NAMESPACE_URL, uuid5

from fdai_operator_service.auth import AuthenticationError, OperatorAuthenticator
from fdai_operator_service.families.iam.capabilities import IamCapability, has_capability
from fdai_operator_service.families.iam.contracts import (
    AuthorizePrincipal,
    ConfigurationReviewCommand,
    ConfigurationReviewOutbox,
    IamPrincipal,
)
from fdai_operator_service.families.iam.errors import IamFamilyError
from fdai_operator_service.families.iam.http import (
    error_response,
    family_error,
    read_json_object,
)
from fdai_operator_service.operator_request_receipt import OperatorRequestReceiptIssuer
from fdai_service_contracts import OperatorPrincipalKind
from fdai_service_contracts.kill_switch import (
    KILL_SWITCH_REQUEST_TOPIC,
    KillSwitchRequestBody,
    KillSwitchRequestEvent,
)
from fdai_service_contracts.operator_authentication import OperatorAuthenticationReceipt
from pydantic import ValidationError
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

DEFAULT_KILL_SWITCH_PATH: Final = "/system/kill-switch"
_MAX_BODY_BYTES: Final = 16_000
_MAX_IDEMPOTENCY_CHARS: Final = 200
_FRESH_AUTH_BOUND: Final = timedelta(minutes=10)
_KILL_SWITCH_NAMESPACE = uuid5(NAMESPACE_URL, "https://fdai.dev/operator/kill-switch")
_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


@dataclass(frozen=True, slots=True)
class FreshKillSwitchPrincipal:
    """Freshly authenticated emergency operator and token-free evidence."""

    principal: IamPrincipal
    authentication_receipt: OperatorAuthenticationReceipt
    authenticated_at: datetime


class FreshKillSwitchPrincipalAuthenticator(Protocol):
    """Authenticate an Owner or Break-Glass kill-switch request."""

    async def authenticate_kill_switch(self, request: Request) -> FreshKillSwitchPrincipal: ...


class KillSwitchEventPublisher(Protocol):
    """Publish one typed kill-switch request event."""

    async def publish_kill_switch_request(
        self,
        *,
        topic: str,
        key: str,
        payload: Mapping[str, object],
    ) -> object: ...


class _BusPublisher(Protocol):
    async def publish(self, topic: str, key: str, payload: Mapping[str, object]) -> object: ...


@dataclass(frozen=True, slots=True)
class BusKillSwitchEventPublisher:
    """Publish kill-switch requests through the Operator event-bus seam."""

    bus: _BusPublisher

    async def publish_kill_switch_request(
        self,
        *,
        topic: str,
        key: str,
        payload: Mapping[str, object],
    ) -> object:
        return await self.bus.publish(topic, key, payload)


@dataclass(frozen=True, slots=True)
class OperatorFreshKillSwitchPrincipalAuthenticator:
    """Adapt the common Operator authenticator to the kill-switch boundary."""

    authenticator: OperatorAuthenticator

    async def authenticate_kill_switch(self, request: Request) -> FreshKillSwitchPrincipal:
        try:
            identity = self.authenticator.authenticate_identity(
                request.headers.get("authorization")
            )
        except AuthenticationError as exc:
            raise IamFamilyError("kill-switch authentication failed") from exc
        if identity.authentication_receipt is None or identity.authenticated_at is None:
            raise IamFamilyError("kill-switch requires a token with auth_time")
        return FreshKillSwitchPrincipal(
            principal=IamPrincipal(
                oid=identity.principal.subject_id,
                roles=identity.principal.roles,
                username=identity.username,
                principal_kind=identity.principal.principal_kind,
            ),
            authentication_receipt=identity.authentication_receipt,
            authenticated_at=identity.authenticated_at,
        )


def make_kill_switch_route(
    *,
    authenticator: FreshKillSwitchPrincipalAuthenticator | None,
    publisher: KillSwitchEventPublisher | None,
    receipt_issuer: OperatorRequestReceiptIssuer | None,
    clock: Callable[[], datetime] | None = None,
    path: str = DEFAULT_KILL_SWITCH_PATH,
) -> Route:
    """Build the emergency-stop request route without any provider execution port."""
    if not path.startswith("/"):
        raise ValueError("kill-switch path MUST start with '/'")
    now = clock or (lambda: datetime.now(UTC))

    async def handler(request: Request) -> Response:
        if authenticator is None or publisher is None or receipt_issuer is None:
            return error_response(503, "kill-switch publishing is not configured")
        try:
            fresh = await authenticator.authenticate_kill_switch(request)
        except IamFamilyError as exc:
            return family_error(exc)
        principal = fresh.principal
        if principal.principal_kind is not OperatorPrincipalKind.HUMAN:
            return error_response(403, "kill-switch requires a human principal")
        if not has_capability(principal.roles, IamCapability.TRIGGER_KILL_SWITCH):
            return error_response(
                403,
                "kill-switch command requires capability 'trigger-kill-switch'",
            )
        evaluated_at = now().astimezone(UTC)
        authenticated_at = fresh.authenticated_at.astimezone(UTC)
        if not authenticated_at <= evaluated_at <= authenticated_at + _FRESH_AUTH_BOUND:
            return error_response(403, "fresh authentication is required", kind="stale_auth")
        try:
            body = KillSwitchRequestBody.model_validate(
                await read_json_object(request, maximum=_MAX_BODY_BYTES)
            )
            idempotency_key = _required_header(
                request,
                "Idempotency-Key",
                maximum=_MAX_IDEMPOTENCY_CHARS,
            )
        except HTTPException as exc:
            return error_response(exc.status_code, str(exc.detail))
        except ValidationError:
            return error_response(400, "kill-switch request is invalid", kind="invalid_body")
        request_id = str(uuid5(_KILL_SWITCH_NAMESPACE, f"{principal.oid}\0{idempotency_key}"))
        correlation_id = f"kill-switch:{request_id}"
        principal_roles = frozenset(role.value for role in principal.roles)
        event = KillSwitchRequestEvent.create(
            body=body,
            request_id=request_id,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            initiator_principal=principal.oid,
            requested_at=evaluated_at,
            authentication_receipt=fresh.authentication_receipt,
            operator_request_receipt=receipt_issuer.issue(
                KillSwitchRequestEvent.operator_receipt_event(
                    body=body,
                    correlation_id=correlation_id,
                    idempotency_key=idempotency_key,
                    initiator_principal=principal.oid,
                    requested_at=evaluated_at,
                    authenticated_at=fresh.authenticated_at,
                    principal_roles=principal_roles,
                )
            ),
        )
        await publisher.publish_kill_switch_request(
            topic=KILL_SWITCH_REQUEST_TOPIC,
            key=event.idempotency_key,
            payload=event.model_dump(mode="json"),
        )
        return JSONResponse(
            {
                "request_id": event.request_id,
                "request_digest": event.request_digest,
                "published": True,
            },
            status_code=202,
        )

    return Route(path, handler, methods=["POST"])


def _required_header(request: Request, name: str, *, maximum: int) -> str:
    value = request.headers.get(name, "").strip()
    if not value:
        raise HTTPException(status_code=400, detail=f"{name} header is required")
    if len(value) > maximum:
        raise HTTPException(status_code=400, detail=f"{name} header is too long")
    return value


def make_configuration_review_routes(
    *,
    outbox: ConfigurationReviewOutbox | None,
    authorize: AuthorizePrincipal,
    clock: Callable[[], datetime] | None = None,
) -> tuple[Route, ...]:
    """Build evidence-campaign request routes without executing configuration changes."""
    now = clock or (lambda: datetime.now(UTC))

    async def run_review(request: Request) -> Response:
        principal = await authorize(request)
        if not _at_least_contributor(principal.roles):
            return error_response(403, "configuration review requires Contributor")
        if outbox is None:
            return error_response(503, "configuration review outbox is not configured")
        run_id = request.headers.get("idempotency-key", "").strip()
        if _RUN_ID.fullmatch(run_id) is None:
            return error_response(400, "valid Idempotency-Key header is required")
        try:
            result = await outbox.run(
                ConfigurationReviewCommand(
                    principal_id=principal.oid,
                    run_id=run_id,
                    requested_at=now(),
                )
            )
        except IamFamilyError as exc:
            return family_error(exc)
        return JSONResponse(dict(result))

    async def resume_review(request: Request) -> Response:
        principal = await authorize(request)
        if not _at_least_approver(principal.roles):
            return error_response(403, "configuration review resume requires Approver")
        if outbox is None:
            return error_response(503, "configuration review outbox is not configured")
        try:
            result = await outbox.resume(principal_id=principal.oid)
        except IamFamilyError as exc:
            return family_error(exc)
        return JSONResponse(dict(result))

    return (
        Route("/configuration-baselines/review/run", run_review, methods=["POST"]),
        Route("/configuration-baselines/review/resume", resume_review, methods=["POST"]),
    )


def _at_least_contributor(roles: frozenset[object]) -> bool:
    return any(
        getattr(role, "value", None) in {"Contributor", "Approver", "Owner"} for role in roles
    )


def _at_least_approver(roles: frozenset[object]) -> bool:
    return any(getattr(role, "value", None) in {"Approver", "Owner"} for role in roles)


__all__ = [
    "BusKillSwitchEventPublisher",
    "DEFAULT_KILL_SWITCH_PATH",
    "FreshKillSwitchPrincipal",
    "FreshKillSwitchPrincipalAuthenticator",
    "KillSwitchEventPublisher",
    "OperatorFreshKillSwitchPrincipalAuthenticator",
    "make_configuration_review_routes",
    "make_kill_switch_route",
]
