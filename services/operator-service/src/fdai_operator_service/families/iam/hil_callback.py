"""Signed internal HIL callback bound to the shared decision service.

This route authenticates an internal Slack or relay callback with an HMAC
signature over the exact bytes. Microsoft Teams service callbacks do not use
it: a Teams Adaptive Card cannot compute the shared secret, so Teams enters
through :mod:`fdai_operator_service.families.iam.hil_teams_callback` and
resolves in the same ``HilCallbackDecisionService`` as this route, which is
why a ``channel=teams`` body is refused here.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

from fdai_operator_service.families.iam.contracts import (
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
from fdai_operator_service.families.iam.hil_callback_validation import (
    CallbackError,
    UnauthorizedCallbackError,
    authenticate_and_parse,
    body_hint,
    callback_id,
    compute_hmac,
    read_bounded_body,
)
from fdai_operator_service.families.iam.http import error_response
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route

DEFAULT_MAX_SKEW_SECONDS: Final = 300
DEFAULT_MAX_BODY_BYTES: Final = 8 * 1024


@dataclass(frozen=True, slots=True)
class HilCallbackConfig:
    """HMAC and request ceilings supplied by the composition root."""

    secret: str
    max_skew_seconds: int = DEFAULT_MAX_SKEW_SECONDS
    max_body_bytes: int = DEFAULT_MAX_BODY_BYTES

    def __post_init__(self) -> None:
        if not self.secret:
            raise ValueError("HilCallbackConfig.secret MUST be non-empty")
        if self.max_skew_seconds <= 0:
            raise ValueError("max_skew_seconds MUST be positive")
        if self.max_body_bytes <= 0:
            raise ValueError("max_body_bytes MUST be positive")


def make_hil_callback_route(
    *,
    registry: HilDecisionRegistry | None,
    outbox: HilDecisionOutbox | None,
    config: HilCallbackConfig | None,
    authority: HilCallbackAuthority | None = None,
    audit: HilCallbackAuditWriter | None = None,
    context_reader: HilCallbackContextReader | None = None,
    clock: Callable[[], datetime] | None = None,
) -> Route:
    """Build the URL-bound callback with current authority and durable audit."""
    now = clock or (lambda: datetime.now(UTC))

    async def handler(request: Request) -> Response:
        if (
            registry is None
            or outbox is None
            or config is None
            or authority is None
            or audit is None
            or context_reader is None
        ):
            return error_response(503, "HIL callback dependencies are not configured")
        approval_id = str(request.path_params["approval_id"])
        if not approval_id or len(approval_id) > 128:
            return error_response(400, "approval_id is invalid", kind="bad_request")
        service = HilCallbackDecisionService(
            registry=registry,
            outbox=outbox,
            authority=authority,
            audit=audit,
            context_reader=context_reader,
            clock=now,
        )
        try:
            raw = await read_bounded_body(request, config.max_body_bytes)
        except CallbackError as exc:
            return error_response(exc.status_code, str(exc), kind=exc.kind)
        hint = body_hint(raw)
        try:
            payload = authenticate_and_parse(
                request=request,
                raw=raw,
                secret=config.secret,
                max_skew_seconds=config.max_skew_seconds,
                clock=now,
                approval_id=approval_id,
            )
        except UnauthorizedCallbackError as exc:
            return error_response(exc.status_code, str(exc), kind=exc.kind)
        except CallbackError as exc:
            session = await service.begin(
                HilCallbackAttempt(
                    callback_id=callback_id(
                        approval_id,
                        request.headers.get("x-fdai-timestamp", ""),
                        raw,
                    ),
                    approval_id=approval_id,
                    channel_hint=hint.get("channel", "unknown"),
                    actor_hint=hint.get("provider_actor_id"),
                )
            )
            if isinstance(session, Response):
                return session
            return await session.finish(
                error_response(exc.status_code, str(exc), kind=exc.kind),
                outcome=HilCallbackOutcome.INVALID,
            )
        session = await service.begin(
            HilCallbackAttempt(
                callback_id=callback_id(
                    approval_id,
                    request.headers.get("x-fdai-timestamp", ""),
                    raw,
                ),
                approval_id=approval_id,
                channel_hint=hint.get("channel", "unknown"),
                actor_hint=hint.get("provider_actor_id"),
            )
        )
        if isinstance(session, Response):
            return session
        if payload.channel is HilCallbackChannel.TEAMS:
            return await session.finish(
                error_response(
                    400,
                    "Teams decisions MUST enter through the Teams activity receiver",
                    kind="wrong_transport",
                ),
                outcome=HilCallbackOutcome.INVALID,
            )
        return await service.decide(
            session,
            approval_id=approval_id,
            payload=NormalizedHilDecision(
                decision=payload.decision,
                justification=payload.justification,
                channel=payload.channel,
                provider_actor_id=payload.provider_actor_id,
                audience=payload.audience,
                correlation_id=payload.correlation_id,
                idempotency_key=payload.idempotency_key,
                action_hash=payload.action_hash,
                decided_at=payload.signed_at,
                authorization=request.headers.get("authorization"),
            ),
        )

    return Route("/hil/{approval_id}/decision", handler, methods=["POST"])


__all__ = [
    "DEFAULT_MAX_BODY_BYTES",
    "DEFAULT_MAX_SKEW_SECONDS",
    "HilCallbackConfig",
    "compute_hmac",
    "make_hil_callback_route",
]
