"""Console action submission - the write-direction conversational entry.

The read-only console deck answers questions (see :mod:`chat`). This module
adds the ONE write-direction path an operator conversation needs. Ordinary
mutation requests (``restart vm-1``) enter the typed pantheon pipeline, where
Forseti judges them, Var approves high-risk requests, and Thor executes.
Incident requests prepare and confirm an audited control-plane record through
``IncidentLifecycleWorkflow``; they never invoke a resource executor.

Boundary contract (why this is not a "console button that executes"):

- **Propose, never execute.** The submitter publishes an ``ActionProposal``
  record onto the raw event topic (the same topic the pantheon's Huginn
  ingests). It holds no executor identity and calls no mutation surface. The
  proposal is a *signal*, exactly like a rule-fired event - the same precedent
  as the HIL approval callback (operator-console.md 13.3).
- **Confirm incident records.** Incident creation requires severity, target,
  Contributor RBAC, and a same-principal/session confirmation. The registry is
  the sole writer and the chat route holds no cloud mutation identity.
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
from dataclasses import dataclass, field
from typing import Any, Final

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from fdai.agents.bragi import translate_action_intent
from fdai.core.console_request import (
    PriorRequestOutcome,
    evaluate_operator_rerequest,
)
from fdai.core.incident.proposal_store import (
    IncidentProposalStore,
    InMemoryIncidentProposalStore,
)
from fdai.core.incident.workflow import IncidentLifecycleWorkflow
from fdai.core.rbac.resolver import Principal
from fdai.core.rbac.roles import Capability, has_capability
from fdai.shared.providers.event_bus import EventBus

from .incident_chat import submit_incident_chat

_LOG = logging.getLogger(__name__)

DEFAULT_ACTION_PATH: Final[str] = "/chat/action"
DEFAULT_MAX_BODY_BYTES: Final[int] = 8_000

#: Hard caps on operator-supplied values that ride into the proposal (and thus
#: into every downstream store and the audit log). The body-byte cap already
#: bounds the request; these bound the individual fields so one large value
#: cannot bloat the pipeline / audit or become a pathological bus partition key.
MAX_PROMPT_CHARS: Final[int] = 4_000
MAX_QUESTION_CHARS: Final[int] = 2_000
MAX_RESOURCE_ID_CHARS: Final[int] = 200
MAX_IDEMPOTENCY_CHARS: Final[int] = 200
MAX_SESSION_ID_CHARS: Final[int] = 200

#: The capability an operator MUST hold to submit an action proposal. Contributor
#: and above carry it; a Reader does not (see rbac/roles.py capability matrix).
_SUBMIT_CAPABILITY: Final[Capability] = Capability.AUTHOR_DRAFT_PR


PriorOutcomeLookup = Callable[[str, str | None, str], Awaitable[PriorRequestOutcome]]
"""Resolve the pipeline's last terminal conclusion for one operator request.

Called with ``(initiator_oid, resource_id, action_type)`` and returns a
:class:`~fdai.core.console_request.PriorRequestOutcome`. Injected at the
composition root; absent (``None``) the submitter treats every request as
having no prior verdict (``NONE``), preserving the pre-Scenario-B behavior.
A fork backs it with the audit / verdict store. It MUST NOT raise - a lookup
failure is the fork's responsibility to map to ``NONE`` (fail-open to a fresh
judgement, never to a silent deny-override).
"""


@dataclass(frozen=True, slots=True)
class RefusalRecord:
    """One operator action submission refused BEFORE the typed pipeline.

    The RBAC-capability, blank-principal, and deny-override refusals all fire
    *before* a proposal is published, so Forseti never sees them and cannot
    raise its own ``SecurityEvent``. A single ``_LOG.info`` line cannot surface
    a pattern; a wired :data:`RefusalObserver` turns each refusal into an
    audit / metric / security signal so repeated refusals for one ``actor``
    (privilege probing) become detectable. Inert data: the observer decides
    whether a count crosses a threshold - the submitter never blocks on it.
    """

    actor: str
    reason: str
    action_type: str | None
    resource_id: str | None
    correlation_id: str


RefusalObserver = Callable[[RefusalRecord], Awaitable[None]]
"""Optional sink notified when a submission is refused pre-pipeline.

Injected at the composition root; absent, only a structured log line is
emitted. It MUST NOT raise into the refusal path - the submitter guards the
call and still returns the refusal even if the observer fails (best-effort
observability never breaks the security-relevant refusal, mirroring the
handoff-escalation best-effort contract).
"""


@dataclass(frozen=True, slots=True)
class ConsoleActionSubmitter:
    """Publishes an operator ActionProposal onto the raw event topic.

    ``raw_event_topic`` MUST be the ingress topic the pantheon's Huginn
    consumes (the same ``kafka.topic_events`` the P1 loop reads), so a
    submitted proposal is normalized into ``object.event`` and judged by
    Forseti with ``initiator_principal`` set - the RBAC hook and the whole
    judge/approve/execute pipeline then apply unchanged.

    ``prior_outcome_lookup`` (optional) enforces Scenario B's deny-override
    block: when the pipeline previously denied this exact request, a repeat
    is refused before anything is published; a prior no-op (or no prior
    verdict) proceeds normally. Absent, no deny-override check runs.
    """

    event_bus: EventBus
    raw_event_topic: str
    action_type_names: frozenset[str] = frozenset()
    prior_outcome_lookup: PriorOutcomeLookup | None = None
    refusal_observer: RefusalObserver | None = None
    incident_workflow: IncidentLifecycleWorkflow | None = None
    incident_proposals: IncidentProposalStore = field(
        default_factory=InMemoryIncidentProposalStore,
        repr=False,
    )

    def __post_init__(self) -> None:
        # Fail fast at composition: an empty topic would publish proposals into
        # a nameless stream the pantheon never consumes.
        if not self.raw_event_topic or not self.raw_event_topic.strip():
            raise ValueError("raw_event_topic MUST be a non-empty topic name")

    async def _refuse(
        self,
        *,
        reason: str,
        actor: str,
        correlation_id: str,
        action_type: str | None = None,
        resource_id: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Log + observe a pre-pipeline refusal, then return its envelope.

        Central refusal path so every security-relevant block (blank principal,
        missing capability, deny-override) is logged with the same structured
        fields and offered to the injected :data:`RefusalObserver`. The observer
        is best-effort: a failure is logged but never converts a refusal into a
        server error (which a client could retry).
        """
        _LOG.info(
            "console action refused: reason=%s actor=%s action_type=%s",
            reason,
            actor or "<blank>",
            action_type,
        )
        if self.refusal_observer is not None:
            record = RefusalRecord(
                actor=actor,
                reason=reason,
                action_type=action_type,
                resource_id=resource_id,
                correlation_id=correlation_id,
            )
            try:
                await self.refusal_observer(record)
            except Exception:  # noqa: BLE001 - observability MUST NOT break the refusal
                _LOG.exception("refusal observer raised; refusal still returned")
        envelope: dict[str, Any] = {
            "submitted": False,
            "reason": reason,
            "correlation_id": correlation_id,
        }
        if extra:
            envelope.update(extra)
        return envelope

    async def submit(
        self,
        *,
        question: str,
        principal: Principal,
        session_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Submit an operator command, or refuse it. Returns a status envelope.

        - Blank principal id -> ``{"submitted": False,
          "reason": "invalid_principal"}`` (fail closed; nothing publishes).
        - No ``author-draft-pr`` capability -> ``{"submitted": False,
          "reason": "rbac_capability"}`` (Reader is refused; nothing publishes).
        - Command verb maps to no ActionType -> ``{"submitted": False,
          "reason": "unmapped_action_intent"}``.
        - The pipeline previously denied this exact request -> ``{"submitted":
          False, "reason": "deny_override_forbidden"}`` (Scenario B: a repeat
          cannot override a deny; nothing publishes).
        - Otherwise publishes the proposal and returns ``{"submitted": True,
          "correlation_id": ..., "action_type": ...}``.

        ``idempotency_key`` (client-supplied, optional) becomes the proposal's
        dedup key so a retried submit collapses at Huginn instead of enqueuing a
        second action. Absent, a fresh key is used (each call is distinct).
        """
        correlation_id = f"conv-{uuid.uuid4()}"
        # Fail closed on a malformed principal - never publish an action with an
        # empty initiator (which would only be denied downstream anyway).
        if not principal.oid or not principal.oid.strip():
            return await self._refuse(
                reason="invalid_principal", actor="", correlation_id=correlation_id
            )
        if not has_capability(principal.roles, _SUBMIT_CAPABILITY):
            return await self._refuse(
                reason="rbac_capability",
                actor=principal.oid,
                correlation_id=correlation_id,
                extra={"required_capability": _SUBMIT_CAPABILITY.value},
            )
        if session_id is not None and len(session_id) > MAX_SESSION_ID_CHARS:
            return {
                "submitted": False,
                "reason": "session_id_too_long",
                "correlation_id": correlation_id,
            }
        if idempotency_key is not None and len(idempotency_key) > MAX_IDEMPOTENCY_CHARS:
            return {
                "submitted": False,
                "reason": "idempotency_key_too_long",
                "correlation_id": correlation_id,
            }
        if self.incident_workflow is not None:
            incident_result = await submit_incident_chat(
                workflow=self.incident_workflow,
                proposals=self.incident_proposals,
                question=question,
                principal=principal,
                session_id=session_id,
                correlation_id=correlation_id,
                max_question_chars=MAX_QUESTION_CHARS,
            )
            if incident_result is not None:
                return incident_result
        action_type, resource_id = translate_action_intent(question, self.action_type_names)
        if action_type is None:
            return {
                "submitted": False,
                "reason": "unmapped_action_intent",
                "correlation_id": correlation_id,
            }
        # Bound operator-supplied values before they ride into the pipeline.
        bounded_resource = resource_id[:MAX_RESOURCE_ID_CHARS] if resource_id else None
        bounded_question = question[:MAX_QUESTION_CHARS]
        bounded_session = session_id[:MAX_SESSION_ID_CHARS] if session_id else None
        # Scenario B deny-override block: a prior deny for this exact request is
        # authoritative - a repeat console ask cannot lift it. A prior no-op (or
        # no prior verdict) proceeds to a fresh judgement. Only applied when a
        # lookup seam is wired; absent, every request is treated as fresh.
        if self.prior_outcome_lookup is not None:
            prior_outcome = await self.prior_outcome_lookup(
                principal.oid, bounded_resource, action_type
            )
            if not evaluate_operator_rerequest(prior_outcome=prior_outcome).allowed:
                return await self._refuse(
                    reason="deny_override_forbidden",
                    actor=principal.oid,
                    correlation_id=correlation_id,
                    action_type=action_type,
                    resource_id=bounded_resource,
                    extra={"action_type": action_type},
                )
        client_key = (idempotency_key or "").strip()[:MAX_IDEMPOTENCY_CHARS]
        # Namespace the dedup key by the initiator so one operator cannot reuse
        # (or guess) another operator's idempotency key to suppress their action
        # at Huginn. Absent a client key, fall back to the unique correlation.
        # The whole key is bounded so a long oid + key cannot become a huge bus
        # partition value.
        dedup_key = (
            f"{principal.oid}::{client_key}"[:MAX_IDEMPOTENCY_CHARS]
            if client_key
            else correlation_id
        )
        proposal: dict[str, Any] = {
            "idempotency_key": dedup_key,
            "correlation_id": correlation_id,
            "initiator_principal": principal.oid,
            "operator_initiated": True,
            "action_type": action_type,
            "resource_id": bounded_resource,
            "event_type": "operator_request",
            "params": {"question": bounded_question, "session_id": bounded_session},
        }
        # Key by resource (per-resource ordering) so concurrent proposals on
        # the same resource serialize; fall back to the dedup key.
        key = bounded_resource or dedup_key
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
            "resource_id": bounded_resource,
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
        if len(prompt) > MAX_PROMPT_CHARS:
            raise HTTPException(
                status_code=400,
                detail=f"prompt exceeds cap ({len(prompt)} > {MAX_PROMPT_CHARS})",
            )
        session_id = body.get("session_id")
        if session_id is not None and not isinstance(session_id, str):
            raise HTTPException(status_code=400, detail="session_id MUST be a string")
        if isinstance(session_id, str) and len(session_id) > MAX_SESSION_ID_CHARS:
            raise HTTPException(
                status_code=400,
                detail=f"session_id exceeds cap ({len(session_id)} > {MAX_SESSION_ID_CHARS})",
            )
        idempotency_key = body.get("idempotency_key")
        if idempotency_key is not None and not isinstance(idempotency_key, str):
            raise HTTPException(status_code=400, detail="idempotency_key MUST be a string")
        if isinstance(idempotency_key, str) and len(idempotency_key) > MAX_IDEMPOTENCY_CHARS:
            raise HTTPException(
                status_code=400,
                detail=(
                    "idempotency_key exceeds cap "
                    f"({len(idempotency_key)} > {MAX_IDEMPOTENCY_CHARS})"
                ),
            )

        result = await submitter.submit(
            question=prompt.strip(),
            principal=principal,
            session_id=session_id,
            idempotency_key=idempotency_key,
        )
        status_code = (
            403 if result.get("reason") in ("rbac_capability", "deny_override_forbidden") else 200
        )
        return JSONResponse(result, status_code=status_code)

    return Route(path, handler, methods=["POST"])
