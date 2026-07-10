"""Console action submission - the write-direction conversational entry.

The read-only console deck answers questions (see :mod:`chat`). This module
adds the ONE write-direction path an operator conversation needs: submitting an
action the operator asked for (``restart vm-1``) into the typed pantheon
pipeline, where Forseti judges it, Var approves a high-risk one, and Thor
executes - the operator's chat NEVER executes anything itself.

Boundary contract (why this is not a "console button that executes"):

- **Propose, never execute.** The submitter publishes an ``ActionProposal``
  record onto the raw event topic (the same topic the pantheon's Huginn
  ingests). It holds no executor identity and calls no mutation surface. The
  proposal is a *signal*, exactly like a rule-fired event - the same precedent
  as the HIL approval callback (operator-console.md 13.3).
- **Server-derived RBAC.** The operator's role comes from the validated bearer
  token (:class:`~fdai.core.rbac.resolver.Principal`), never from client JSON.
  An operator without ``author-draft-pr`` capability (Reader) is refused before
  anything is published. Forseti re-checks the initiator principal downstream
  (deny + SecurityEvent) - defense in depth.
- **initiator_principal is the operator.** Bragi's ``translate_action_intent``
  is the single source of truth for verb -> ActionType, shared with the
  pantheon-internal path so the two never drift.

Registered only when a :class:`ConsoleActionSubmitter` is wired at the
composition root (``ReadApiConfig.console_action``); absent, the route does not
exist and the console has no action-submit surface.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Final

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from fdai.agents.bragi import translate_action_intent
from fdai.core.rbac.resolver import Principal
from fdai.core.rbac.roles import Capability, has_capability
from fdai.shared.providers.event_bus import EventBus

_LOG = logging.getLogger(__name__)

DEFAULT_ACTION_PATH: Final[str] = "/chat/action"
DEFAULT_MAX_BODY_BYTES: Final[int] = 8_000

#: The capability an operator MUST hold to submit an action proposal. Contributor
#: and above carry it; a Reader does not (see rbac/roles.py capability matrix).
_SUBMIT_CAPABILITY: Final[Capability] = Capability.AUTHOR_DRAFT_PR


@dataclass(frozen=True, slots=True)
class ConsoleActionSubmitter:
    """Publishes an operator ActionProposal onto the raw event topic.

    ``raw_event_topic`` MUST be the ingress topic the pantheon's Huginn
    consumes (the same ``kafka.topic_events`` the P1 loop reads), so a
    submitted proposal is normalized into ``object.event`` and judged by
    Forseti with ``initiator_principal`` set - the RBAC hook and the whole
    judge/approve/execute pipeline then apply unchanged.
    """

    event_bus: EventBus
    raw_event_topic: str

    async def submit(
        self,
        *,
        question: str,
        principal: Principal,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """Submit an operator command, or refuse it. Returns a status envelope.

        - No ``author-draft-pr`` capability -> ``{"submitted": False,
          "reason": "rbac_capability"}`` (Reader is refused; nothing publishes).
        - Command verb maps to no ActionType -> ``{"submitted": False,
          "reason": "unmapped_action_intent"}``.
        - Otherwise publishes the proposal and returns ``{"submitted": True,
          "correlation_id": ..., "action_type": ...}``.
        """
        correlation_id = f"conv-{uuid.uuid4()}"
        if not has_capability(principal.roles, _SUBMIT_CAPABILITY):
            _LOG.info("console action refused: principal lacks %s", _SUBMIT_CAPABILITY.value)
            return {
                "submitted": False,
                "reason": "rbac_capability",
                "required_capability": _SUBMIT_CAPABILITY.value,
                "correlation_id": correlation_id,
            }
        action_type, resource_id = translate_action_intent(question)
        if action_type is None:
            return {
                "submitted": False,
                "reason": "unmapped_action_intent",
                "correlation_id": correlation_id,
            }
        proposal: dict[str, Any] = {
            "idempotency_key": correlation_id,
            "correlation_id": correlation_id,
            "initiator_principal": principal.oid,
            "operator_initiated": True,
            "action_type": action_type,
            "resource_id": resource_id,
            "event_type": "operator_request",
            "params": {"question": question, "session_id": session_id},
        }
        # Key by resource (per-resource ordering) so concurrent proposals on
        # the same resource serialize; fall back to the correlation id.
        key = resource_id or correlation_id
        await self.event_bus.publish(self.raw_event_topic, key, proposal)
        _LOG.info(
            "console action submitted: action_type=%s correlation_id=%s",
            action_type,
            correlation_id,
        )
        return {
            "submitted": True,
            "correlation_id": correlation_id,
            "action_type": action_type,
            "resource_id": resource_id,
        }


AuthorizePrincipalFn = Callable[[Request], Awaitable[Principal]]
"""Resolve the request's authenticated :class:`Principal` (roles) or raise 401.

Distinct from the read routes' ``authorize`` (which returns only the ``oid``):
the action route needs the role bag to gate on capability server-side.
"""


def make_console_action_route(
    *,
    submitter: ConsoleActionSubmitter,
    authorize_principal: AuthorizePrincipalFn,
    path: str = DEFAULT_ACTION_PATH,
    max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
) -> Route:
    """Build the ``POST /chat/action`` route.

    Body: ``{"prompt": str, "session_id": str?}``. The route authenticates the
    caller, resolves their role from the token, and submits (or refuses) the
    action. A capability refusal is ``403``; an unmapped command is ``200`` with
    ``submitted: false`` so the deck can render "I can't do that yet".
    """

    async def handler(request: Request) -> JSONResponse:
        principal = await authorize_principal(request)

        declared_len = request.headers.get("content-length")
        if declared_len is not None:
            try:
                if int(declared_len) > max_body_bytes:
                    raise HTTPException(status_code=413, detail="action body too large")
            except ValueError:
                pass
        body_bytes = await request.body()
        if len(body_bytes) > max_body_bytes:
            raise HTTPException(status_code=413, detail="action body too large")
        try:
            body = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=400, detail="action body MUST be JSON") from exc
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="action body MUST be a JSON object")
        prompt = body.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise HTTPException(status_code=400, detail="prompt MUST be a non-empty string")
        session_id = body.get("session_id")
        if session_id is not None and not isinstance(session_id, str):
            raise HTTPException(status_code=400, detail="session_id MUST be a string")

        result = await submitter.submit(
            question=prompt.strip(),
            principal=principal,
            session_id=session_id,
        )
        status_code = 403 if result.get("reason") == "rbac_capability" else 200
        return JSONResponse(result, status_code=status_code)

    return Route(path, handler, methods=["POST"])
