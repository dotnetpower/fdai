"""Durable write-direction entry for FDAI Console conversations.

The route proposes typed events and confirms incident records; it never holds
an executor identity or mutates a managed resource. Server-derived RBAC and
the owning agents remain authoritative. The route exists only when a
``ConsoleActionSubmitter`` is supplied at the composition root.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Final

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import BaseRoute, Route

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
from fdai.shared.contracts.models import IncidentSeverity
from fdai.shared.providers.event_bus import EventBus
from fdai.shared.providers.state_store import StateStore
from fdai.shared.providers.testing.state_store import InMemoryStateStore

from ..console_action_dispatch import (
    ConsoleActionDispatch,
    ConsoleActionDispatchConflictError,
    ConsoleActionDispatcher,
    ConsoleActionDispatcherConfig,
    ConsoleActionDispatchState,
    ConsoleActionDispatchStore,
    console_action_intent_digest,
)
from ..console_incident_ticket import ConsoleIncidentTicketCoordinator
from .incident_chat import open_investigation_incident, submit_incident_chat

_LOG = logging.getLogger(__name__)

DEFAULT_ACTION_PATH: Final[str] = "/chat/action"
DEFAULT_ACTION_CONFIRM_PATH: Final[str] = "/chat/action/confirm"
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
    investigation_incident_severity: IncidentSeverity = IncidentSeverity.SEV3
    incident_proposals: IncidentProposalStore = field(
        default_factory=InMemoryIncidentProposalStore,
        repr=False,
    )
    dispatch_state_store: StateStore = field(default_factory=InMemoryStateStore, repr=False)
    dispatch_config: ConsoleActionDispatcherConfig = field(
        default_factory=ConsoleActionDispatcherConfig,
        repr=False,
    )
    incident_ticket_retention_seconds: int = 86_400
    _dispatcher: ConsoleActionDispatcher = field(init=False, repr=False, compare=False)
    _incident_ticket: ConsoleIncidentTicketCoordinator = field(
        init=False,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        # Fail fast at composition: an empty topic would publish proposals into
        # a nameless stream the pantheon never consumes.
        if not self.raw_event_topic or not self.raw_event_topic.strip():
            raise ValueError("raw_event_topic MUST be a non-empty topic name")
        dispatcher = ConsoleActionDispatcher(
            store=ConsoleActionDispatchStore(self.dispatch_state_store),
            event_bus=self.event_bus,
            config=self.dispatch_config,
        )
        object.__setattr__(self, "_dispatcher", dispatcher)
        object.__setattr__(
            self,
            "_incident_ticket",
            ConsoleIncidentTicketCoordinator(
                dispatcher=dispatcher,
                state_store=self.dispatch_state_store,
                event_topic=self.raw_event_topic,
                batch_size=self.dispatch_config.batch_size,
                blocked_retention_seconds=self.incident_ticket_retention_seconds,
            ),
        )

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
                prepare_incident_ticket=self._prepare_incident_ticket,
            )
            if incident_result is not None:
                if (
                    incident_result.get("submitted") is True
                    and incident_result.get("action_type") == "incident.create"
                ):
                    try:
                        dispatch = await self._publish_incident_ticket_proposal(
                            incident_result=incident_result,
                            principal=principal,
                            session_id=session_id,
                        )
                    except Exception:  # noqa: BLE001 - incident exists; surface ticket failure
                        _LOG.exception("incident ticket proposal publish failed")
                        incident_result["ticket_proposal_submitted"] = False
                    else:
                        incident_result["ticket_proposal_submitted"] = (
                            dispatch.state is ConsoleActionDispatchState.PUBLISHED
                        )
                        incident_result["ticket_proposal_status"] = dispatch.state.value
                        incident_result["ticket_proposal_request_id"] = dispatch.dispatch_id
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
        action_params: dict[str, object] = {
            "question": bounded_question,
            "session_id": bounded_session,
        }
        investigation: tuple[str, str] | None = None
        if action_type == "tool.run-chaos-experiment":
            chaos_request = _parse_chaos_request(bounded_question)
            if chaos_request is None:
                return {
                    "submitted": False,
                    "reason": "invalid_action_arguments",
                    "correlation_id": correlation_id,
                    "action_type": action_type,
                }
            scenario_id, targets = chaos_request
            bounded_resource = targets[0][:MAX_RESOURCE_ID_CHARS]
            action_params = {"scenario_id": scenario_id, "targets": list(targets)}
        elif action_type == "tool.run-investigation":
            investigation_request = _parse_investigation_request(bounded_question)
            if investigation_request is None:
                return {
                    "submitted": False,
                    "reason": "invalid_action_arguments",
                    "correlation_id": correlation_id,
                    "action_type": action_type,
                }
            resource_kind, resource_ref = investigation_request
            investigation = investigation_request
            bounded_resource = resource_ref[:MAX_RESOURCE_ID_CHARS]
            action_params = {
                "resource_ref": bounded_resource,
                "resource_kind": resource_kind,
            }
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
        incident_id: str | None = None
        if investigation is not None and self.incident_workflow is not None:
            if not bounded_session:
                return {
                    "submitted": False,
                    "reason": "incident_session_required",
                    "correlation_id": correlation_id,
                    "action_type": action_type,
                    "message": (
                        "Investigation requires a conversation session so its Incident and "
                        "progress trace can be resumed."
                    ),
                }
            resource_kind, resource_ref = investigation
            opened = await open_investigation_incident(
                workflow=self.incident_workflow,
                principal=principal,
                session_id=bounded_session,
                resource_kind=resource_kind,
                resource_ref=resource_ref,
                severity=self.investigation_incident_severity,
            )
            incident_id = str(opened.incident.incident_id)
            correlation_id = incident_id
            action_params = {**action_params, "incident_id": incident_id}

        client_key = (idempotency_key or "").strip()[:MAX_IDEMPOTENCY_CHARS]
        # Namespace the dedup key by the initiator so one operator cannot reuse
        # (or guess) another operator's idempotency key to suppress their action
        # at Huginn. Absent a client key, fall back to the unique correlation.
        if incident_id is not None:
            dedup_key = f"{principal.oid}::investigation::{incident_id}"[:MAX_IDEMPOTENCY_CHARS]
        else:
            dedup_key = (
                _operator_idempotency_key(principal.oid, client_key)
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
            "params": action_params,
        }
        if incident_id is not None:
            proposal["incident_id"] = incident_id
        # Key by resource (per-resource ordering) so concurrent proposals on
        # the same resource serialize; fall back to the dedup key.
        key = bounded_resource or dedup_key
        try:
            dispatch = await self._dispatch_proposal(
                key=key,
                proposal=proposal,
            )
        except ConsoleActionDispatchConflictError as exc:
            return await self._refuse(
                reason="idempotency_collision",
                actor=principal.oid,
                correlation_id=correlation_id,
                action_type=action_type,
                resource_id=bounded_resource,
                extra={
                    "action_type": action_type,
                    "winning_request_id": exc.dispatch_id,
                    "winning_correlation_id": exc.correlation_id,
                    "winning_accepted_at": exc.accepted_at.isoformat(),
                },
            )
        correlation_id = dispatch.correlation_id
        _LOG.info(
            "console action submitted: action_type=%s correlation_id=%s",
            action_type,
            correlation_id,
        )
        response: dict[str, Any] = {
            "submitted": True,
            "correlation_id": correlation_id,
            "action_type": action_type,
            "resource_id": bounded_resource,
            "durably_queued": True,
            "request_id": dispatch.dispatch_id,
            "dispatch_status": dispatch.state.value,
            "accepted_at": dispatch.accepted_at.isoformat(),
        }
        if incident_id is not None:
            response.update(
                {
                    "incident_id": incident_id,
                    "incident_state": "open",
                    "links": {
                        "incident": f"/incidents/{incident_id}",
                        "trace": f"/audit?correlation_id={correlation_id}",
                        "live": f"/live?correlation_id={correlation_id}",
                    },
                }
            )
        return response

    async def submit_planned(
        self,
        *,
        action_type: str,
        arguments: Mapping[str, object],
        principal: Principal,
        session_id: str | None,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Confirm one typed model draft after server allowlist validation."""

        if action_type == "incident.create":
            _reject_planned_arguments(arguments, {"severity", "target"})
            severity = arguments.get("severity")
            target = arguments.get("target")
            if (
                not isinstance(severity, str)
                or severity.lower() not in {item.value for item in IncidentSeverity}
                or not isinstance(target, str)
                or not target.strip()
                or len(target) > MAX_RESOURCE_ID_CHARS
            ):
                return {"submitted": False, "reason": "invalid_action_arguments"}
            prepared = await self.submit(
                question=f"create {severity.lower()} incident target {target.strip()}",
                principal=principal,
                session_id=session_id,
                idempotency_key=idempotency_key,
            )
            if prepared.get("reason") != "incident_confirmation_required":
                return prepared
            return await self.submit(
                question="confirm",
                principal=principal,
                session_id=session_id,
                idempotency_key=idempotency_key,
            )

        if action_type not in self.action_type_names:
            return {"submitted": False, "reason": "unmapped_action_intent"}
        _reject_planned_arguments(arguments, {"resource_id"})
        resource_id = arguments.get("resource_id")
        if resource_id is not None and (
            not isinstance(resource_id, str)
            or not resource_id.strip()
            or len(resource_id) > MAX_RESOURCE_ID_CHARS
        ):
            return {"submitted": False, "reason": "invalid_action_arguments"}
        command = action_type
        if isinstance(resource_id, str):
            command = f"{command} {resource_id.strip()}"
        return await self.submit(
            question=command,
            principal=principal,
            session_id=session_id,
            idempotency_key=idempotency_key,
        )

    async def _publish_incident_ticket_proposal(
        self,
        *,
        incident_result: dict[str, Any],
        principal: Principal,
        session_id: str | None,
    ) -> ConsoleActionDispatch:
        return await self._incident_ticket.publish(
            incident_id=str(incident_result["incident_id"]),
            actor_oid=principal.oid,
            session_id=session_id,
        )

    async def _prepare_incident_ticket(
        self,
        proposal: Any,
        principal: Principal,
        session_id: str,
    ) -> None:
        await self._incident_ticket.prepare(proposal, principal.oid, session_id)

    async def reconcile_incident_ticket_dispatches(self) -> int:
        return await self._incident_ticket.reconcile()

    async def _dispatch_proposal(
        self,
        *,
        key: str,
        proposal: Mapping[str, object],
    ) -> ConsoleActionDispatch:
        return await self._dispatcher.submit(
            idempotency_key=str(proposal["idempotency_key"]),
            intent_digest=console_action_intent_digest(
                topic=self.raw_event_topic,
                partition_key=key,
                payload=proposal,
            ),
            topic=self.raw_event_topic,
            partition_key=key,
            payload=proposal,
            correlation_id=str(proposal["correlation_id"]),
            actor_oid=str(proposal["initiator_principal"]),
        )

    async def redrive_pending(self) -> int:
        """Publish one bounded batch of durable pending proposals."""
        return await self._dispatcher.drain_due()

    @property
    def dispatcher(self) -> ConsoleActionDispatcher:
        """Return the dispatcher for the composition-owned recovery worker."""
        return self._dispatcher


_CHAOS_REQUEST = re.compile(
    r"(?:tool\.)?run[- ]chaos[- ]experiment\s+"
    r"(?P<scenario>[a-z0-9._-]+)\s+(?:on|targets?)\s+"
    r"(?P<targets>[a-z0-9._:/,-]+)",
    re.IGNORECASE,
)
_INVESTIGATION_REQUEST = re.compile(
    r"(?:tool\.)?run[- ]investigation\s+"
    r"(?P<kind>aks_cluster|mysql_flexible_server|azure_openai|"
    r"application_gateway|api_management)\s+"
    r"(?P<resource>[a-z0-9._:/-]+)",
    re.IGNORECASE,
)


def _parse_chaos_request(question: str) -> tuple[str, tuple[str, ...]] | None:
    match = _CHAOS_REQUEST.search(question)
    if match is None:
        return None
    targets = tuple(item.strip() for item in match.group("targets").split(",") if item.strip())
    if not targets:
        return None
    return match.group("scenario"), targets


def _parse_investigation_request(question: str) -> tuple[str, str] | None:
    match = _INVESTIGATION_REQUEST.search(question)
    if match is None:
        return None
    return match.group("kind").lower(), match.group("resource")


def _reject_planned_arguments(arguments: Mapping[str, object], allowed: set[str]) -> None:
    if any(not isinstance(key, str) or key not in allowed for key in arguments):
        raise ValueError("planned action arguments contain unsupported fields")


def _operator_idempotency_key(principal_oid: str, client_key: str) -> str:
    namespaced = f"{principal_oid}::{client_key}"
    if len(namespaced) <= MAX_IDEMPOTENCY_CHARS:
        return namespaced
    digest = hashlib.sha256(namespaced.encode("utf-8")).hexdigest()
    return f"operator::{digest}"


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
        if result.get("reason") == "idempotency_collision":
            status_code = 409
        elif result.get("reason") in ("rbac_capability", "deny_override_forbidden"):
            status_code = 403
        else:
            status_code = 202 if result.get("durably_queued") is True else 200
        return JSONResponse(result, status_code=status_code)

    return Route(path, handler, methods=["POST"])


def make_console_action_confirm_route(
    *,
    submitter: ConsoleActionSubmitter,
    authorize_principal: AuthorizePrincipalFn,
    path: str = DEFAULT_ACTION_CONFIRM_PATH,
    max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
) -> Route:
    """Build the typed confirmation route for a semantic action draft."""

    async def handler(request: Request) -> JSONResponse:
        principal = await authorize_principal(request)
        body_bytes = await request.body()
        if len(body_bytes) > max_body_bytes:
            raise HTTPException(status_code=413, detail="action body too large")
        try:
            body = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=400, detail="action body MUST be JSON") from exc
        if not isinstance(body, dict) or set(body) != {
            "action_type",
            "arguments",
            "session_id",
            "idempotency_key",
        }:
            raise HTTPException(status_code=400, detail="typed action confirmation is invalid")
        action_type = body["action_type"]
        arguments = body["arguments"]
        session_id = body["session_id"]
        idempotency_key = body["idempotency_key"]
        if not isinstance(action_type, str) or not action_type:
            raise HTTPException(status_code=400, detail="action_type MUST be a string")
        if not isinstance(arguments, dict):
            raise HTTPException(status_code=400, detail="arguments MUST be an object")
        if session_id is not None and not isinstance(session_id, str):
            raise HTTPException(status_code=400, detail="session_id MUST be a string")
        if (
            not isinstance(idempotency_key, str)
            or not idempotency_key
            or len(idempotency_key) > MAX_IDEMPOTENCY_CHARS
        ):
            raise HTTPException(status_code=400, detail="idempotency_key is invalid")
        try:
            result = await submitter.submit_planned(
                action_type=action_type,
                arguments=arguments,
                principal=principal,
                session_id=session_id,
                idempotency_key=idempotency_key,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if result.get("reason") == "idempotency_collision":
            status_code = 409
        elif result.get("reason") in ("rbac_capability", "deny_override_forbidden"):
            status_code = 403
        else:
            status_code = 202 if result.get("durably_queued") is True else 200
        return JSONResponse(result, status_code=status_code)

    return Route(path, handler, methods=["POST"])


def append_console_action_route(
    routes: list[BaseRoute],
    *,
    submitter: ConsoleActionSubmitter | None,
    authorize_principal: AuthorizePrincipalFn,
    core_paths: frozenset[str],
    logger: logging.Logger,
) -> None:
    """Append the optional propose-only console action route."""
    if submitter is None:
        return
    if DEFAULT_ACTION_PATH in core_paths:
        raise ValueError(f"action path {DEFAULT_ACTION_PATH!r} collides with a core route")
    routes.append(
        make_console_action_route(
            submitter=submitter,
            authorize_principal=authorize_principal,
        )
    )
    routes.append(
        make_console_action_confirm_route(
            submitter=submitter,
            authorize_principal=authorize_principal,
        )
    )
    logger.info(
        "console_action_route_wired",
        extra={
            "path": DEFAULT_ACTION_PATH,
            "mode": "propose-only",
            "required_capability": "contributor",
        },
    )
