"""Entra-authenticated FDAI Console decisions for exact pending HIL approvals."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Final

from fdai_operator_service.families.iam.capabilities import (
    IamCapability,
    has_capability,
)
from fdai_operator_service.families.iam.contracts import (
    AuthorizePrincipal,
    HilApprovalDecision,
    HilDecisionOutbox,
    HilDecisionRegistry,
)
from fdai_operator_service.families.iam.hil_callback_audit import (
    HilCallbackAuditWriter,
    actor_identity_reference,
)
from fdai_operator_service.families.iam.hil_callback_authority import HilCallbackActor
from fdai_operator_service.families.iam.hil_callback_context import (
    HilCallbackContextReader,
)
from fdai_operator_service.families.iam.hil_callback_decision import (
    HilCallbackAttempt,
    HilCallbackDecisionService,
)
from fdai_operator_service.families.iam.http import (
    error_response,
    read_json_object,
    require_string,
)
from fdai_service_contracts import OperatorPrincipalKind, OperatorRole
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route

_MAX_BODY_BYTES: Final = 8_192
_MAX_JUSTIFICATION_CHARS: Final = 2_000
_IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9._:-]{1,256}$")
_FIELDS = frozenset({"decision", "justification"})


def make_hil_operator_decision_route(
    *,
    authorize: AuthorizePrincipal,
    registry: HilDecisionRegistry | None,
    outbox: HilDecisionOutbox | None,
    audit: HilCallbackAuditWriter | None,
    context_reader: HilCallbackContextReader | None,
    clock: Callable[[], datetime] | None = None,
) -> Route:
    """Build the browser decision route without accepting client-supplied authority."""
    now = clock or (lambda: datetime.now(UTC))

    async def post_hil_operator_decision(request: Request) -> Response:
        if registry is None or outbox is None or audit is None or context_reader is None:
            return error_response(503, "Console HIL decision dependencies are not configured")
        principal = await authorize(request)
        if principal.principal_kind is not OperatorPrincipalKind.HUMAN:
            return error_response(403, "HIL decisions require a human principal")
        if not has_capability(principal.roles, IamCapability.APPROVE_RUNTIME_HIL):
            return error_response(403, "principal lacks runtime approval authority")

        approval_id = str(request.path_params["approval_id"])
        if not approval_id or len(approval_id) > 128:
            return error_response(400, "approval_id is invalid")
        request_key = request.headers.get("idempotency-key", "").strip()
        if _IDEMPOTENCY_KEY.fullmatch(request_key) is None:
            return error_response(400, "valid Idempotency-Key header is required")
        body = await read_json_object(request, maximum=_MAX_BODY_BYTES)
        if set(body) != _FIELDS:
            return error_response(
                400,
                "Console HIL decision body MUST contain only decision and justification",
            )
        raw_decision = require_string(body, "decision")
        try:
            decision = HilApprovalDecision(raw_decision)
        except ValueError:
            return error_response(400, "decision MUST be approve or reject")
        justification = require_string(body, "justification").strip()
        if not justification or len(justification) > _MAX_JUSTIFICATION_CHARS:
            return error_response(
                400,
                "justification MUST be between 1 and 2000 characters",
            )

        canonical_intent = json.dumps(
            {
                "approval_id": approval_id,
                "decision": decision.value,
                "justification": justification,
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        callback_id = (
            "hil-console:"
            + hashlib.sha256(
                f"{principal.oid.strip().casefold()}\0{request_key}".encode()
            ).hexdigest()
        )
        service = HilCallbackDecisionService(
            registry=registry,
            outbox=outbox,
            authority=None,
            audit=audit,
            context_reader=context_reader,
            clock=now,
        )
        actor = HilCallbackActor(
            oid=principal.oid.strip().casefold(),
            identity_ref=actor_identity_reference(principal.oid),
            roles=principal.roles - {OperatorRole.BREAK_GLASS},
            authority_basis="operator_console+entra_app_role",
        )
        session = await service.begin(
            HilCallbackAttempt(
                callback_id=callback_id,
                approval_id=approval_id,
                intent_digest="sha256:" + hashlib.sha256(canonical_intent).hexdigest(),
                channel_hint="operator-console",
                actor_hint=principal.oid,
            )
        )
        if isinstance(session, Response):
            return session
        return await service.decide_authenticated(
            session,
            approval_id=approval_id,
            decision=decision,
            justification=justification,
            actor=actor,
        )

    return Route(
        "/hil/{approval_id}/operator-decision",
        post_hil_operator_decision,
        methods=["POST"],
        name="post_hil_operator_decision",
    )


__all__ = ["make_hil_operator_decision_route"]
