"""Policy-administration request route for the non-privileged Operator API."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import NAMESPACE_URL, uuid5

from fdai_operator_service.auth import AuthenticationError, OperatorAuthenticator
from fdai_operator_service.families.iam.contracts import IamPrincipal
from fdai_operator_service.families.iam.http import error_response, read_json_object
from fdai_operator_service.operator_request_receipt import OperatorRequestReceiptIssuer
from fdai_service_contracts import OperatorPrincipalKind
from fdai_service_contracts.operator_authentication import OperatorAuthenticationReceipt
from fdai_service_contracts.policy_administration import (
    POLICY_REVISION_REQUEST_TOPIC,
    PolicyRevisionRequestBody,
    PolicyRevisionRequestEvent,
)
from pydantic import ValidationError
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

_MAX_BODY_BYTES = 256_000
_MAX_IDEMPOTENCY_CHARS = 200
_FRESH_AUTH_BOUND = timedelta(minutes=10)
_POLICY_NAMESPACE = uuid5(NAMESPACE_URL, "https://fdai.dev/operator/policy-administration")


@dataclass(frozen=True, slots=True)
class FreshPolicyPrincipal:
    """Freshly authenticated policy administrator and token-free evidence."""

    principal: IamPrincipal
    authentication_receipt: OperatorAuthenticationReceipt
    authenticated_at: datetime
    app_roles: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if self.authenticated_at.tzinfo is None or self.authenticated_at.utcoffset() is None:
            raise ValueError("policy-admin authenticated_at MUST include a timezone")


class FreshPolicyPrincipalAuthenticator(Protocol):
    """Authenticate the request and prove a recent human sign-in."""

    async def authenticate_policy_admin(self, request: Request) -> FreshPolicyPrincipal: ...


class PolicyRevisionEventPublisher(Protocol):
    """Publish one typed policy revision request event."""

    async def publish_policy_revision_request(
        self,
        *,
        topic: str,
        key: str,
        payload: Mapping[str, object],
    ) -> object: ...


class _BusPublisher(Protocol):
    async def publish(self, topic: str, key: str, payload: Mapping[str, object]) -> object: ...


@dataclass(frozen=True, slots=True)
class BusPolicyRevisionEventPublisher:
    """Publish policy requests through the existing Operator event-bus seam."""

    bus: _BusPublisher

    async def publish_policy_revision_request(
        self,
        *,
        topic: str,
        key: str,
        payload: Mapping[str, object],
    ) -> object:
        return await self.bus.publish(topic, key, payload)


@dataclass(frozen=True, slots=True)
class OperatorFreshPolicyPrincipalAuthenticator:
    """Adapt the common Operator authenticator to the policy-admin fresh-auth boundary."""

    authenticator: OperatorAuthenticator

    async def authenticate_policy_admin(self, request: Request) -> FreshPolicyPrincipal:
        try:
            identity = self.authenticator.authenticate_identity(
                request.headers.get("authorization")
            )
        except AuthenticationError as exc:
            raise PolicyAdministrationAuthError(
                "policy administration authentication failed",
                status_code=401,
                kind="unauthorized",
            ) from exc
        if identity.authentication_receipt is None or identity.authenticated_at is None:
            raise PolicyAdministrationAuthError(
                "policy administration requires a token with auth_time",
                status_code=403,
                kind="fresh_auth_unavailable",
            )
        return FreshPolicyPrincipal(
            principal=IamPrincipal(
                oid=identity.principal.subject_id,
                roles=identity.principal.roles,
                username=identity.username,
                principal_kind=identity.principal.principal_kind,
            ),
            authentication_receipt=identity.authentication_receipt,
            authenticated_at=identity.authenticated_at,
            app_roles=identity.app_roles,
        )


def make_policy_administration_routes(
    *,
    authenticator: FreshPolicyPrincipalAuthenticator | None,
    publisher: PolicyRevisionEventPublisher | None,
    receipt_issuer: OperatorRequestReceiptIssuer | None = None,
    clock: Callable[[], datetime] | None = None,
) -> tuple[Route, ...]:
    """Build policy-administration routes that only publish typed requests."""

    now = clock or (lambda: datetime.now(UTC))

    async def submit_policy_revision(request: Request) -> Response:
        if authenticator is None or publisher is None or receipt_issuer is None:
            return error_response(503, "policy revision publishing is not configured")
        try:
            principal = await authenticator.authenticate_policy_admin(request)
        except PolicyAdministrationAuthError as exc:
            return error_response(exc.status_code, str(exc), kind=exc.kind)
        if principal.principal.principal_kind is not OperatorPrincipalKind.HUMAN:
            return error_response(403, "policy administration requires a human principal")
        if "policy-admin" not in principal.app_roles:
            return error_response(403, "policy-admin App Role is required")
        evaluated_at = now().astimezone(UTC)
        authenticated_at = principal.authenticated_at.astimezone(UTC)
        if not authenticated_at <= evaluated_at <= authenticated_at + _FRESH_AUTH_BOUND:
            return error_response(403, "fresh authentication is required", kind="stale_auth")
        try:
            body = PolicyRevisionRequestBody.model_validate(
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
            return error_response(400, "policy revision request is invalid", kind="invalid_body")
        request_id = str(
            uuid5(
                _POLICY_NAMESPACE,
                f"{principal.principal.oid}\0{idempotency_key}",
            )
        )
        event = PolicyRevisionRequestEvent.create(
            body=body,
            request_id=request_id,
            correlation_id=f"policy-revision:{request_id}",
            idempotency_key=idempotency_key,
            author_principal=principal.principal.oid,
            requested_at=evaluated_at,
            authentication_receipt=principal.authentication_receipt,
            operator_request_receipt=receipt_issuer.issue(
                PolicyRevisionRequestEvent.operator_receipt_event(
                    body=body,
                    request_id=request_id,
                    correlation_id=f"policy-revision:{request_id}",
                    idempotency_key=idempotency_key,
                    author_principal=principal.principal.oid,
                    authenticated_at=principal.authenticated_at,
                    app_roles=principal.app_roles,
                )
            ),
        )
        await publisher.publish_policy_revision_request(
            topic=POLICY_REVISION_REQUEST_TOPIC,
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

    return (
        Route(
            "/policy/revisions",
            submit_policy_revision,
            methods=["POST"],
            name="policy_revision_request",
        ),
    )


class PolicyAdministrationAuthError(ValueError):
    """Authentication or authorization failed before request validation."""

    def __init__(self, message: str, *, status_code: int, kind: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.kind = kind


def _required_header(request: Request, name: str, *, maximum: int) -> str:
    value = request.headers.get(name, "").strip()
    if not value:
        raise HTTPException(status_code=400, detail=f"{name} header is required")
    if len(value) > maximum:
        raise HTTPException(status_code=400, detail=f"{name} header is too long")
    return value


__all__ = [
    "BusPolicyRevisionEventPublisher",
    "FreshPolicyPrincipal",
    "FreshPolicyPrincipalAuthenticator",
    "OperatorFreshPolicyPrincipalAuthenticator",
    "PolicyAdministrationAuthError",
    "PolicyRevisionEventPublisher",
    "make_policy_administration_routes",
]
