"""Signed Slack click to one-use, Entra-authenticated browser handoff."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, quote, urlsplit

from fdai_operator_service.auth import AuthenticationError, OperatorAuthenticator, _extract_bearer
from fdai_operator_service.families.iam.capabilities import IamCapability, has_capability
from fdai_operator_service.families.iam.contracts import (
    HilApprovalDecision,
    HilDecisionOutbox,
    HilDecisionRegistry,
)
from fdai_operator_service.families.iam.hil_callback_audit import (
    HilCallbackAuditWriter,
    HilCallbackOutcome,
    actor_identity_reference,
)
from fdai_operator_service.families.iam.hil_callback_authority import (
    HilCallbackActor,
    HilCallbackAuthorityConfig,
)
from fdai_operator_service.families.iam.hil_callback_context import HilCallbackContextReader
from fdai_operator_service.families.iam.hil_callback_decision import (
    HilCallbackAttempt,
    HilCallbackDecisionService,
)
from fdai_operator_service.families.iam.hil_callback_validation import (
    CallbackError,
    read_bounded_body,
)
from fdai_operator_service.families.iam.http import error_response, read_json_object
from fdai_operator_service.postgres_family_store import (
    PostgresFamilyStore,
    PostgresFamilyStoreConfig,
    PostgresFamilyStoreUnavailable,
)
from fdai_service_contracts import OperatorPrincipalKind, OperatorRole
from psycopg import AsyncConnection
from psycopg import Error as PostgresError
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

_TOKEN = re.compile(r"^[A-Za-z0-9_-]{43}$")
_MAX_BODY = 16_384
_WINDOW = timedelta(minutes=5)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate Slack interaction field")
        result[key] = value
    return result


def _field(value: object, name: str, maximum: int = 200) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise ValueError(f"Slack interaction {name} is invalid")
    return value


@dataclass(frozen=True, slots=True)
class VerifiedSlackClick:
    """Identity and intent extracted only after authenticating the raw body."""

    workspace: str
    sender: str
    approval_id: str
    decision: HilApprovalDecision
    click_digest: str


def verify_slack_click(
    raw: bytes,
    headers: Mapping[str, str],
    *,
    secret: str,
    workspace: str,
    now: datetime,
) -> VerifiedSlackClick:
    """Require Slack v0 HMAC, bounded time, and one exact block action."""
    if len(raw) > _MAX_BODY or not secret or now.tzinfo is None:
        raise ValueError("Slack interaction verifier is unavailable")
    timestamp = headers.get("x-slack-request-timestamp", "")
    signature = headers.get("x-slack-signature", "")
    if not re.fullmatch(r"[0-9]{10,11}", timestamp):
        raise ValueError("Slack interaction timestamp is invalid")
    if abs(now - datetime.fromtimestamp(int(timestamp), UTC)) > _WINDOW:
        raise ValueError("Slack interaction is outside the replay window")
    expected = (
        "v0="
        + hmac.new(
            secret.encode(), b"v0:" + timestamp.encode() + b":" + raw, hashlib.sha256
        ).hexdigest()
    )
    if not hmac.compare_digest(signature, expected):
        raise ValueError("Slack interaction signature is invalid")
    if (
        headers.get("content-type", "").split(";", 1)[0].strip()
        != "application/x-www-form-urlencoded"
    ):
        raise ValueError("Slack interaction content type is invalid")
    fields = parse_qs(raw.decode("utf-8"), strict_parsing=True, max_num_fields=2)
    if set(fields) != {"payload"} or len(fields["payload"]) != 1:
        raise ValueError("Slack interaction payload is invalid")
    payload = json.loads(fields["payload"][0], object_pairs_hook=_unique_object)
    if not isinstance(payload, dict) or payload.get("type") != "block_actions":
        raise ValueError("Slack interaction type is invalid")
    team, user, actions = payload.get("team"), payload.get("user"), payload.get("actions")
    if (
        not isinstance(team, dict)
        or not isinstance(user, dict)
        or not isinstance(actions, list)
        or len(actions) != 1
        or not isinstance(actions[0], dict)
    ):
        raise ValueError("Slack interaction actor or action is invalid")
    team_id = _field(team.get("id"), "workspace")
    if team_id != workspace:
        raise ValueError("Slack interaction workspace is not configured")
    sender = _field(user.get("id"), "sender")
    action = actions[0]
    action_id = action.get("action_id")
    if not isinstance(action_id, str):
        raise ValueError("Slack interaction action is invalid")
    decision = {
        "fdai_hil_approve": HilApprovalDecision.APPROVE,
        "fdai_hil_reject": HilApprovalDecision.REJECT,
    }.get(action_id)
    if decision is None:
        raise ValueError("Slack interaction action is not supported")
    approval_id = _field(action.get("value"), "approval", 128)
    trigger = _field(payload.get("trigger_id"), "trigger")
    return VerifiedSlackClick(
        workspace=team_id,
        sender=sender,
        approval_id=approval_id,
        decision=decision,
        click_digest=hashlib.sha256(f"{team_id}\0{sender}\0{trigger}".encode()).hexdigest(),
    )


def _mapping_revision(config: HilCallbackAuthorityConfig) -> str:
    return hashlib.sha256(
        json.dumps(
            dict(config.slack_principal_by_sender_id), sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


def _trusted_console_origin(origin: str | None) -> bool:
    if origin is None:
        return False
    try:
        parsed = urlsplit(origin)
        port = parsed.port
    except ValueError:
        return False
    return (
        (
            parsed.scheme == "https"
            or (parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"})
        )
        and bool(parsed.netloc)
        and (port is None or 1 <= port <= 65535)
        and parsed.username is None
        and parsed.password is None
        and not any((parsed.path, parsed.query, parsed.fragment))
    )


class PostgresSlackHandoffStore:
    """Use Operator-owned state rows and a single SQL CAS for nonce consumption."""

    def __init__(self, config: PostgresFamilyStoreConfig) -> None:
        self._config = config
        self._store = PostgresFamilyStore(config)

    async def create_click(self, digest: str) -> bool:
        return await self._store.create_state("operator-slack-click:" + digest, {"received": True})

    async def put(self, digest: str, record: Mapping[str, object]) -> None:
        if not await self._store.create_state("operator-slack-handoff:" + digest, record):
            raise PostgresFamilyStoreUnavailable("Slack handoff nonce collision")

    async def read(self, digest: str) -> dict[str, object] | None:
        return await self._store.read_state("operator-slack-handoff:" + digest)

    async def consume(self, digest: str) -> bool:
        """Exactly one concurrent caller can transition a nonce to consumed."""
        try:
            async with await AsyncConnection.connect(
                self._config.dsn.replace("postgresql+psycopg://", "postgresql://", 1),
                connect_timeout=self._config.connect_timeout_s,
            ) as connection:
                async with connection.transaction():
                    await connection.execute(
                        "SELECT set_config('statement_timeout', %s, true)",
                        (str(self._config.statement_timeout_ms),),
                    )
                    cursor = await connection.execute(
                        """UPDATE state_kv
                           SET value = jsonb_set(value, '{consumed}', 'true'::jsonb),
                           updated_at = NOW()
                           WHERE key = %s AND value->>'consumed' = 'false'
                             AND (value->>'expires_at')::timestamptz > NOW()
                           RETURNING key""",
                        (f"operator-slack-handoff:{digest}",),
                    )
                    return await cursor.fetchone() is not None
        except PostgresError as exc:
            raise PostgresFamilyStoreUnavailable("Slack handoff store is unavailable") from exc


def make_slack_handoff_routes(
    *,
    store: PostgresSlackHandoffStore | None,
    signing_secret: str | None,
    config: HilCallbackAuthorityConfig | None,
    authenticator: OperatorAuthenticator | None,
    registry: HilDecisionRegistry | None,
    outbox: HilDecisionOutbox | None,
    audit: HilCallbackAuditWriter | None,
    context_reader: HilCallbackContextReader | None,
    console_origin: str | None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> tuple[Route, ...]:
    """Bind a click to immutable park facts; the browser can supply only justification."""

    def available() -> bool:
        return bool(
            store
            and signing_secret
            and config
            and config.slack_a1_enabled
            and authenticator
            and registry
            and outbox
            and audit
            and context_reader
            and _trusted_console_origin(console_origin)
        )

    async def interaction(request: Request) -> Response:
        if (
            not available()
            or store is None
            or signing_secret is None
            or config is None
            or config.slack_approval_audience is None
            or context_reader is None
            or console_origin is None
        ):
            return error_response(503, "Slack approval handoff is not configured")
        try:
            raw = await read_bounded_body(request, _MAX_BODY)
        except CallbackError:
            return error_response(413, "Slack interaction body is too large")
        try:
            click = verify_slack_click(
                raw,
                request.headers,
                secret=signing_secret,
                workspace=config.slack_approval_audience.removeprefix("slack:"),
                now=clock(),
            )
        except (ValueError, UnicodeError, json.JSONDecodeError):
            return error_response(401, "Slack interaction verification failed")
        mapped = config.slack_principal_by_sender_id.get(click.sender)
        if mapped is None:
            return error_response(403, "Slack actor mapping is unavailable")
        try:
            context = await context_reader.get_callback_context(click.approval_id)
        except Exception:  # noqa: BLE001 - a failed park read cannot mint a handoff.
            return error_response(503, "Slack approval context is unavailable")
        if context is None or not context.action_hash or context.expires_at <= clock():
            return error_response(410, "Slack approval context is unavailable or expired")
        expiry = min(context.expires_at, clock() + _WINDOW)
        token = secrets.token_urlsafe(32)
        digest = hashlib.sha256(token.encode()).hexdigest()
        record: dict[str, object] = {
            "approval_id": click.approval_id,
            "action_hash": context.action_hash,
            "correlation_id": context.correlation_id,
            "idempotency_key": context.idempotency_key,
            "workspace": click.workspace,
            "sender": click.sender,
            "mapped_oid": mapped,
            "mapping_revision": _mapping_revision(config),
            "decision": click.decision.value,
            "issued_at": clock().isoformat(),
            "expires_at": expiry.isoformat(),
            "consumed": False,
        }
        try:
            if not await store.create_click(click.click_digest):
                return error_response(409, "Slack interaction was already received")
            await store.put(digest, record)
        except PostgresFamilyStoreUnavailable:
            return error_response(503, "Slack approval handoff store is unavailable")
        url = f"{console_origin.rstrip('/')}/approvals?handoff={quote(token)}"
        return JSONResponse(
            {
                "response_type": "ephemeral",
                "text": f"Continue this approval in FDAI Console: {url}",
            },
            headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
        )

    async def load(request: Request) -> tuple[dict[str, object] | None, Response | None]:
        if (
            not available()
            or store is None
            or config is None
            or config.slack_approval_audience is None
            or authenticator is None
            or context_reader is None
        ):
            return None, error_response(503, "Slack approval handoff is not configured")
        token = request.path_params["nonce"]
        if not _TOKEN.fullmatch(token):
            return None, error_response(404, "Slack handoff was not found")
        try:
            record = await store.read(hashlib.sha256(token.encode()).hexdigest())
        except PostgresFamilyStoreUnavailable:
            return None, error_response(503, "Slack handoff store is unavailable")
        if record is None or record.get("consumed") is not False:
            return None, error_response(410, "Slack handoff is no longer available")
        expiry = record.get("expires_at")
        try:
            valid_expiry = isinstance(expiry, str) and datetime.fromisoformat(expiry) > clock()
        except (ValueError, TypeError):
            valid_expiry = False
        if not valid_expiry:
            return None, error_response(410, "Slack handoff has expired")
        if record.get("mapping_revision") != _mapping_revision(config) or record.get(
            "workspace"
        ) != config.slack_approval_audience.removeprefix("slack:"):
            return None, error_response(409, "Slack actor mapping has changed")
        sender = record.get("sender")
        if not isinstance(sender, str) or config.slack_principal_by_sender_id.get(
            sender
        ) != record.get("mapped_oid"):
            return None, error_response(409, "Slack actor mapping has changed")
        try:
            principal = authenticator.authenticate(request.headers.get("authorization"))
        except AuthenticationError:
            return None, error_response(401, "Entra authentication is required")
        if (
            principal.principal_kind is not OperatorPrincipalKind.HUMAN
            or principal.subject_id.strip().casefold() != record.get("mapped_oid")
        ):
            return None, error_response(403, "Entra principal does not match Slack actor")
        if not has_capability(principal.roles, IamCapability.APPROVE_RUNTIME_HIL):
            return None, error_response(403, "principal lacks runtime approval authority")
        approval_id = record.get("approval_id")
        if not isinstance(approval_id, str):
            return None, error_response(503, "Slack handoff context is malformed")
        try:
            context = await context_reader.get_callback_context(approval_id)
        except Exception:  # noqa: BLE001 - no decision without current park state.
            return None, error_response(503, "parked approval context is unavailable")
        if (
            context is None
            or context.expires_at <= clock()
            or any(
                getattr(context, field) != record.get(field)
                for field in ("action_hash", "correlation_id", "idempotency_key")
            )
        ):
            return None, error_response(409, "parked approval context has changed")
        return record, None

    async def preview(request: Request) -> Response:
        record, failure = await load(request)
        if failure is not None:
            return failure
        if record is None:
            return error_response(503, "Slack handoff context is unavailable")
        return JSONResponse(
            {"approval_id": record["approval_id"], "decision": record["decision"]},
            headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
        )

    async def decide(request: Request) -> Response:
        record, failure = await load(request)
        if failure is not None:
            return failure
        if (
            record is None
            or store is None
            or authenticator is None
            or registry is None
            or outbox is None
            or audit is None
            or context_reader is None
        ):
            return error_response(503, "Slack handoff dependencies are unavailable")
        # Authentication time must be a signed Entra access-token claim. A token
        # acquired silently after the click is not evidence of reauthentication.
        try:
            claims = authenticator.verifier(_extract_bearer(request.headers.get("authorization")))
        except Exception:  # noqa: BLE001 - verifier failures cannot establish reauthentication.
            return error_response(401, "fresh Entra reauthentication is unavailable")
        auth_time = claims.get("auth_time")
        try:
            signed_auth_time = (
                datetime.fromtimestamp(auth_time, UTC) if type(auth_time) is int else None
            )
            issued_at = datetime.fromisoformat(str(record["issued_at"]))
        except (TypeError, ValueError, OverflowError):
            return error_response(403, "fresh Entra reauthentication is required")
        if (
            signed_auth_time is None
            # Entra records whole seconds. Same-second sign-ins can precede
            # the click, so only a later second proves a new authentication.
            or signed_auth_time.timestamp() <= int(issued_at.timestamp())
            or signed_auth_time > clock() + timedelta(seconds=60)
        ):
            return error_response(403, "fresh Entra reauthentication is required")
        if str(claims.get("oid", "")).strip().casefold() != record["mapped_oid"]:
            return error_response(403, "Entra principal does not match Slack actor")
        body = await read_json_object(request, maximum=8_192)
        if (
            set(body) != {"justification"}
            or not isinstance(body["justification"], str)
            or not 1 <= len(body["justification"].strip()) <= 2_000
        ):
            return error_response(400, "only a non-empty justification is accepted")
        try:
            existing = await registry.get_decision_by_approval_id(str(record["approval_id"]))
        except Exception:  # noqa: BLE001 - no decision without terminal state read.
            return error_response(503, "approval decision state is unavailable")
        if existing is not None:
            return error_response(409, "approval has already been decided")
        digest = hashlib.sha256(request.path_params["nonce"].encode()).hexdigest()
        approval_id = str(record["approval_id"])
        principal = authenticator.authenticate(request.headers.get("authorization"))
        actor = HilCallbackActor(
            oid=principal.subject_id.strip().casefold(),
            identity_ref=actor_identity_reference(principal.subject_id),
            roles=principal.roles - {OperatorRole.BREAK_GLASS},
            authority_basis="slack_signed_click+entra_fresh_browser",
        )
        service = HilCallbackDecisionService(
            registry=registry,
            outbox=outbox,
            authority=None,
            audit=audit,
            context_reader=context_reader,
            clock=clock,
        )
        session = await service.begin(
            HilCallbackAttempt(
                callback_id=f"hil-slack-handoff:{digest}:{secrets.token_hex(8)}",
                approval_id=approval_id,
                intent_digest="sha256:" + digest,
                channel_hint="slack",
                actor_hint=None,
            )
        )
        if isinstance(session, Response):
            return session
        try:
            claimed = await store.consume(digest)
        except PostgresFamilyStoreUnavailable:
            return await session.finish(
                error_response(503, "Slack handoff store is unavailable"),
                outcome=HilCallbackOutcome.INVALID,
                actor=actor,
            )
        if not claimed:
            return await session.finish(
                error_response(409, "Slack handoff has already been used"),
                outcome=HilCallbackOutcome.INVALID,
                actor=actor,
            )
        return await service.decide_authenticated(
            session,
            approval_id=approval_id,
            decision=HilApprovalDecision(str(record["decision"])),
            justification=body["justification"].strip(),
            actor=actor,
        )

    return (
        Route("/hil/slack/interaction", interaction, methods=["POST"], name="slack_interaction"),
        Route("/hil/slack/handoff/{nonce}", preview, methods=["GET"], name="slack_handoff_preview"),
        Route("/hil/slack/handoff/{nonce}", decide, methods=["POST"], name="slack_handoff_decide"),
    )


__all__ = ["PostgresSlackHandoffStore", "make_slack_handoff_routes", "verify_slack_click"]
