"""Microsoft Teams Bot activity receiver for human approval decisions.

A Teams Adaptive Card cannot compute the internal callback HMAC, so a card
click can never satisfy
:func:`~fdai_operator_service.families.iam.hil_callback.make_hil_callback_route`.
This module is the repository-owned Teams boundary instead.

Authority chain
---------------

1. The ``Authorization`` header carries the **Bot Framework service token**.
   It is verified with the same
   :class:`~fdai_operator_service.families.conversation.channel_edge.teams_auth.TeamsServiceTokenVerifier`
   the Operator channel edge already uses (fixed RS256, bounded JWKS, exact
   Bot application audience, Bot Framework issuer, ``serviceurl`` claim).
2. The activity envelope must come from the separately configured
   group-connected approval team and channel in the configured tenant, over an
   allowed service URL that matches the service token.
3. The human actor is ``from.aadObjectId`` taken from that verified envelope -
   never from card data.
4. ``value.authentication.token`` carries the **delegated (OBO) user token**.
   It is verified by the Operator authenticator, which enforces the configured
   Operator API audience, and the callback authority then enforces the
   authorized Teams bot client (``azp``) and current Entra App Roles.
5. Card data contributes only bindings the server re-verifies against the
   durable park: ``approval_id``, ``correlation_id``, ``idempotency_key``,
   ``action_hash``, ``audience``, plus the ``decision`` and ``justification``.
   Any other key - notably ``provider_actor_id`` or ``roles`` - is refused.

The normalized decision then resolves through the same
:class:`~fdai_operator_service.families.iam.hil_callback_decision.HilCallbackDecisionService`
as the signed internal callback, so Teams gains no separate decision path.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

from fdai_operator_service.families.conversation.channel_edge.teams_auth import (
    TeamsAuthenticationError,
    TeamsServiceTokenVerifier,
    VerifiedTeamsServiceToken,
)
from fdai_operator_service.families.conversation.channel_edge.teams_ingress import (
    normalize_teams_service_url,
)
from fdai_operator_service.families.iam.contracts import (
    HilApprovalDecision,
    HilDecisionOutbox,
    HilDecisionRegistry,
)
from fdai_operator_service.families.iam.hil_callback_audit import (
    HilCallbackAuditWriter,
    HilCallbackOutcome,
)
from fdai_operator_service.families.iam.hil_callback_authority import (
    HilCallbackAuthority,
    HilCallbackChannel,
)
from fdai_operator_service.families.iam.hil_callback_context import (
    HilCallbackContextReader,
)
from fdai_operator_service.families.iam.hil_callback_decision import (
    HilCallbackAttempt,
    HilCallbackDecisionService,
    NormalizedHilDecision,
)
from fdai_operator_service.families.iam.http import error_response
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route

TEAMS_TENANT_ID_ENV: Final = "FDAI_TEAMS_TENANT_ID"
TEAMS_SERVICE_URLS_ENV: Final = "FDAI_TEAMS_ALLOWED_SERVICE_URLS_JSON"
HIL_DECISION_ACTION: Final = "fdai.hil.decision"
"""Fixed value of the Adaptive Card ``Action.Execute`` ``verb`` field."""
DEFAULT_TEAMS_MAX_BODY_BYTES: Final = 32 * 1024
_MAX_SERVICE_URLS: Final = 32
_MAX_TOKEN_LENGTH: Final = 8_192
TEAMS_ACTION_DATA_FIELDS: Final = frozenset(
    {
        "decision",
        "justification",
        "approval_id",
        "correlation_id",
        "idempotency_key",
        "action_hash",
        "audience",
    }
)


@dataclass(frozen=True, slots=True)
class TeamsHilCallbackConfig:
    """Closed Teams approval surface supplied by the composition root."""

    application_id: str
    tenant_id: str
    team_id: str
    channel_id: str
    allowed_service_urls: frozenset[str]
    max_body_bytes: int = DEFAULT_TEAMS_MAX_BODY_BYTES

    def __post_init__(self) -> None:
        for name, value in (
            ("application_id", self.application_id),
            ("tenant_id", self.tenant_id),
            ("team_id", self.team_id),
            ("channel_id", self.channel_id),
        ):
            if not value.strip() or len(value) > 200:
                raise ValueError(f"Teams HIL callback {name} MUST be bounded and non-empty")
        if not self.allowed_service_urls or len(self.allowed_service_urls) > _MAX_SERVICE_URLS:
            raise ValueError("Teams HIL callback service URLs MUST be a bounded non-empty set")
        if any(normalize_teams_service_url(url) != url for url in self.allowed_service_urls):
            raise ValueError("Teams HIL callback service URLs MUST be normalized HTTPS origins")
        if self.max_body_bytes < 1:
            raise ValueError("Teams HIL callback max_body_bytes MUST be positive")

    @property
    def approval_audience(self) -> str:
        """Return the server-derived group-connected approval audience."""
        return f"teams:{self.team_id}:{self.channel_id}"

    @classmethod
    def from_environment(
        cls,
        values: Mapping[str, str],
        *,
        application_id: str,
        team_id: str,
        channel_id: str,
    ) -> TeamsHilCallbackConfig | None:
        """Build the receiver config, or return ``None`` when Teams A1 is off."""
        tenant_id = values.get(TEAMS_TENANT_ID_ENV, "").strip()
        raw_urls = values.get(TEAMS_SERVICE_URLS_ENV, "").strip()
        if not (application_id and team_id and channel_id):
            return None
        if not tenant_id or not raw_urls:
            raise ValueError("Teams A1 callback requires a tenant and allowed Bot service URLs")
        return cls(
            application_id=application_id,
            tenant_id=tenant_id,
            team_id=team_id,
            channel_id=channel_id,
            allowed_service_urls=frozenset(_service_urls(raw_urls)),
        )


class TeamsCallbackError(RuntimeError):
    """A Teams activity failed closed before any decision was considered."""

    def __init__(self, message: str, *, status_code: int, kind: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.kind = kind


@dataclass(frozen=True, slots=True)
class NormalizedTeamsActivity:
    """Server-derived Teams identity plus re-verifiable card bindings."""

    activity_id: str
    aad_object_id: str
    audience: str
    delegated_token: str
    decision: HilApprovalDecision
    justification: str
    correlation_id: str
    idempotency_key: str
    action_hash: str
    service_url: str
    verification_ref: str


class TeamsHilCallbackNormalizer:
    """Authenticate one Teams activity and normalize its approval bindings."""

    def __init__(
        self,
        *,
        config: TeamsHilCallbackConfig,
        tokens: TeamsServiceTokenVerifier,
    ) -> None:
        self._config = config
        self._tokens = tokens

    @property
    def max_body_bytes(self) -> int:
        """Return the ingress byte ceiling before the request body is buffered."""
        return self._config.max_body_bytes

    async def authenticate_transport(
        self,
        authorization: str | None,
    ) -> VerifiedTeamsServiceToken:
        """Verify the Bot service token before any durable callback audit write."""
        if not authorization:
            raise TeamsCallbackError(
                "Teams activity is missing its Bot service token",
                status_code=401,
                kind="unauthorized",
            )
        try:
            return await self._tokens.verify(authorization)
        except TeamsAuthenticationError as exc:
            raise TeamsCallbackError(
                "Teams service authentication failed",
                status_code=401,
                kind="unauthorized",
            ) from exc

    async def normalize(
        self,
        *,
        body: bytes,
        authorization: str | None,
        approval_id: str,
        service_identity: VerifiedTeamsServiceToken | None = None,
    ) -> NormalizedTeamsActivity:
        """Verify the Bot service identity, envelope, and exact card bindings."""
        if len(body) > self._config.max_body_bytes:
            raise TeamsCallbackError(
                "Teams activity exceeds the configured limit",
                status_code=413,
                kind="body_too_large",
            )
        service_identity = service_identity or await self.authenticate_transport(authorization)
        payload = _json_object(body)
        if payload.get("type") != "invoke" or payload.get("name") != "adaptiveCard/action":
            raise TeamsCallbackError(
                "Teams approval activities MUST be adaptiveCard/action invokes",
                status_code=400,
                kind="unsupported_activity",
            )
        if payload.get("channelId") != "msteams":
            raise TeamsCallbackError(
                "Teams approval activities MUST originate on msteams",
                status_code=400,
                kind="unsupported_activity",
            )
        service_url = _service_url(payload, service_identity.service_url)
        if service_url not in self._config.allowed_service_urls:
            raise TeamsCallbackError(
                "Teams service URL is not authorized",
                status_code=403,
                kind="invalid_service_url",
            )
        channel_data = _object(payload, "channelData")
        if _text(_object(channel_data, "tenant"), "id", 200) != self._config.tenant_id:
            raise TeamsCallbackError(
                "Teams tenant is not authorized", status_code=403, kind="unknown_tenant"
            )
        if (
            _text(_object(channel_data, "team"), "id", 200) != self._config.team_id
            or _text(_object(channel_data, "channel"), "id", 200) != self._config.channel_id
        ):
            raise TeamsCallbackError(
                "Teams approval channel is not the configured approval destination",
                status_code=403,
                kind="wrong_channel",
            )
        aad_object_id = _text(_object(payload, "from"), "aadObjectId", 200)
        value = _object(payload, "value")
        action = _object(value, "action")
        if action.get("verb") != HIL_DECISION_ACTION:
            raise TeamsCallbackError(
                "Teams approval action verb is not the approval verb",
                status_code=400,
                kind="unsupported_action",
            )
        delegated_token = _text(_object(value, "authentication"), "token", _MAX_TOKEN_LENGTH)
        data = _object(action, "data")
        if set(data) != TEAMS_ACTION_DATA_FIELDS:
            raise TeamsCallbackError(
                "Teams action data fields do not match the receiver contract",
                status_code=400,
                kind="bad_request",
            )
        if _text(data, "approval_id", 128) != approval_id:
            raise TeamsCallbackError(
                "Teams action data does not match the callback approval identity",
                status_code=409,
                kind="context_mismatch",
            )
        if _text(data, "audience", 512) != self._config.approval_audience:
            raise TeamsCallbackError(
                "Teams action data does not match the configured approval audience",
                status_code=403,
                kind="wrong_audience",
            )
        try:
            decision = HilApprovalDecision(_text(data, "decision", 16).casefold())
        except ValueError as exc:
            raise TeamsCallbackError(
                "Teams decision MUST be approve or reject",
                status_code=400,
                kind="bad_request",
            ) from exc
        return NormalizedTeamsActivity(
            activity_id=_text(payload, "id", 200),
            aad_object_id=aad_object_id,
            audience=self._config.approval_audience,
            delegated_token=delegated_token,
            decision=decision,
            justification=_text(data, "justification", 1_000),
            correlation_id=_text(data, "correlation_id", 256),
            idempotency_key=_text(data, "idempotency_key", 256),
            action_hash=_text(data, "action_hash", 256),
            service_url=service_url,
            verification_ref=f"teams-service-key:{service_identity.key_id}",
        )


def make_hil_teams_callback_route(
    *,
    registry: HilDecisionRegistry | None,
    outbox: HilDecisionOutbox | None,
    authority: HilCallbackAuthority | None,
    audit: HilCallbackAuditWriter | None,
    context_reader: HilCallbackContextReader | None,
    normalizer: TeamsHilCallbackNormalizer | None,
    clock: Callable[[], datetime] | None = None,
) -> Route:
    """Build the Teams Bot activity receiver bound to the shared decision service."""
    now = clock or (lambda: datetime.now(UTC))

    async def handler(request: Request) -> Response:
        if (
            registry is None
            or outbox is None
            or authority is None
            or audit is None
            or context_reader is None
            or normalizer is None
        ):
            return error_response(503, "Teams HIL callback is not configured")
        service = HilCallbackDecisionService(
            registry=registry,
            outbox=outbox,
            authority=authority,
            audit=audit,
            context_reader=context_reader,
            clock=now,
        )
        try:
            raw = await _read_bounded_activity_body(request, normalizer.max_body_bytes)
        except TeamsCallbackError as exc:
            return error_response(exc.status_code, str(exc), kind=exc.kind)
        try:
            service_identity = await normalizer.authenticate_transport(
                request.headers.get("authorization")
            )
        except TeamsCallbackError as exc:
            return error_response(exc.status_code, str(exc), kind=exc.kind)
        try:
            approval_id = _approval_id_from_activity(raw)
        except TeamsCallbackError as exc:
            approval_id = "unresolved:" + hashlib.sha256(raw).hexdigest()
            session = await service.begin(
                HilCallbackAttempt(
                    callback_id=_activity_callback_id(approval_id, raw),
                    approval_id=approval_id,
                    channel_hint=HilCallbackChannel.TEAMS.value,
                )
            )
            if isinstance(session, Response):
                return session
            return await session.finish(
                error_response(exc.status_code, str(exc), kind=exc.kind),
                outcome=HilCallbackOutcome.INVALID,
                authority_basis=f"teams:{exc.kind}",
            )
        session = await service.begin(
            HilCallbackAttempt(
                callback_id=_activity_callback_id(approval_id, raw),
                approval_id=approval_id,
                channel_hint=HilCallbackChannel.TEAMS.value,
            )
        )
        if isinstance(session, Response):
            return session
        try:
            activity = await normalizer.normalize(
                body=raw,
                authorization=request.headers.get("authorization"),
                approval_id=approval_id,
                service_identity=service_identity,
            )
        except TeamsCallbackError as exc:
            return await session.finish(
                error_response(exc.status_code, str(exc), kind=exc.kind),
                outcome=HilCallbackOutcome.INVALID,
                authority_basis=f"teams:{exc.kind}",
            )
        return await service.decide(
            session,
            approval_id=approval_id,
            payload=NormalizedHilDecision(
                decision=activity.decision,
                justification=activity.justification,
                channel=HilCallbackChannel.TEAMS,
                provider_actor_id=activity.aad_object_id,
                audience=activity.audience,
                correlation_id=activity.correlation_id,
                idempotency_key=activity.idempotency_key,
                action_hash=activity.action_hash,
                decided_at=now(),
                authorization=f"Bearer {activity.delegated_token}",
            ),
        )

    return Route("/hil/teams-activity", handler, methods=["POST"])


async def _read_bounded_activity_body(request: Request, maximum: int) -> bytes:
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            declared_bytes = int(declared)
            if declared_bytes < 0 or declared_bytes > maximum:
                raise TeamsCallbackError(
                    "Teams activity exceeds the configured limit",
                    status_code=413,
                    kind="body_too_large",
                )
        except ValueError as exc:
            raise TeamsCallbackError(
                "Teams activity content-length is invalid",
                status_code=400,
                kind="bad_request",
            ) from exc
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > maximum:
            raise TeamsCallbackError(
                "Teams activity exceeds the configured limit",
                status_code=413,
                kind="body_too_large",
            )
    return bytes(body)


def _approval_id_from_activity(raw: bytes) -> str:
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TeamsCallbackError(
            "Teams activity is invalid JSON",
            status_code=400,
            kind="bad_request",
        ) from exc
    if not isinstance(payload, Mapping):
        raise TeamsCallbackError(
            "Teams activity MUST be an object",
            status_code=400,
            kind="bad_request",
        )
    data = _object(_object(_object(payload, "value"), "action"), "data")
    return _text(data, "approval_id", 128)


def _activity_callback_id(approval_id: str, raw: bytes) -> str:
    digest = hashlib.sha256()
    digest.update(approval_id.encode())
    digest.update(b"\0")
    digest.update(raw)
    return f"hil-teams-activity:{digest.hexdigest()}"


def _service_url(payload: Mapping[str, Any], token_service_url: str) -> str:
    try:
        activity_url = normalize_teams_service_url(_text(payload, "serviceUrl", 512))
        token_url = normalize_teams_service_url(token_service_url)
    except ValueError as exc:
        raise TeamsCallbackError(
            "Teams service URL is invalid", status_code=403, kind="invalid_service_url"
        ) from exc
    if activity_url != token_url:
        raise TeamsCallbackError(
            "Teams service URL does not match the service token",
            status_code=403,
            kind="invalid_service_url",
        )
    return activity_url


def _service_urls(raw: str) -> tuple[str, ...]:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("Teams allowed service URLs MUST be valid JSON") from exc
    if not isinstance(parsed, list) or not 1 <= len(parsed) <= _MAX_SERVICE_URLS:
        raise ValueError("Teams allowed service URLs MUST be a bounded JSON array")
    return tuple(normalize_teams_service_url(str(item)) for item in parsed)


def _json_object(body: bytes) -> Mapping[str, Any]:
    try:
        payload = json.loads(body or b"{}", object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise TeamsCallbackError(
            "Teams activity body is invalid JSON", status_code=400, kind="bad_request"
        ) from exc
    if not isinstance(payload, Mapping):
        raise TeamsCallbackError(
            "Teams activity body MUST be an object", status_code=400, kind="bad_request"
        )
    return payload


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate Teams activity key")
        value[key] = item
    return value


def _object(value: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    item = value.get(key)
    if not isinstance(item, Mapping):
        raise TeamsCallbackError(
            f"Teams activity '{key}' is invalid", status_code=400, kind="bad_request"
        )
    return item


def _text(value: Mapping[str, Any], key: str, maximum: int) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip() or len(item.strip()) > maximum:
        raise TeamsCallbackError(
            f"Teams activity '{key}' MUST be bounded non-empty text",
            status_code=400,
            kind="bad_request",
        )
    return item.strip()


__all__ = [
    "DEFAULT_TEAMS_MAX_BODY_BYTES",
    "HIL_DECISION_ACTION",
    "NormalizedTeamsActivity",
    "TEAMS_ACTION_DATA_FIELDS",
    "TEAMS_SERVICE_URLS_ENV",
    "TEAMS_TENANT_ID_ENV",
    "TeamsCallbackError",
    "TeamsHilCallbackConfig",
    "TeamsHilCallbackNormalizer",
    "make_hil_teams_callback_route",
]
