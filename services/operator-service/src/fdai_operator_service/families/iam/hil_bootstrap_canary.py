"""Deterministic no-network canary for the composed human approval path.

Scope and honesty
-----------------

This is a **local dry run**, not a live Microsoft Teams, Slack, Entra, or
broker proof. It runs the *real* composed modules - the signed internal
callback route, the Teams Bot activity receiver and normalizer, the shared
decision service, the two-phase audit, the durable outbox publisher, and the
lease-fenced replay drainer - against in-process fakes:

* the Bot Framework service token and the delegated (OBO) user token are real
  RS256 JWTs signed by an ephemeral in-process key, verified by the production
  verifiers against an in-process JWKS;
* the broker is an in-process publisher that can be told to fail;
* the durable store is an in-process record set with the same
  claim / release / publish semantics the PostgreSQL store implements.

Nothing here proves a deployed Teams tenant, a real Entra token, or a real
Kafka acceptance. :attr:`HilBootstrapCanaryResult.mode` reports that plainly.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any, Final

import httpx
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fdai_operator_service.auth import OperatorAuthenticator
from fdai_operator_service.families.conversation.channel_edge.teams_auth import (
    TeamsServiceTokenVerifier,
    TeamsTokenConfig,
)
from fdai_operator_service.families.iam.contracts import (
    HilDecisionCommand,
    HilDecisionOutboxRequest,
    HilDecisionReceipt,
    HilPendingItem,
)
from fdai_operator_service.families.iam.hil_callback import (
    HilCallbackConfig,
    compute_hmac,
    make_hil_callback_route,
)
from fdai_operator_service.families.iam.hil_callback_audit import (
    HilCallbackAuditRecord,
    HilCallbackOutcome,
)
from fdai_operator_service.families.iam.hil_callback_authority import (
    EntraHilCallbackAuthority,
    HilCallbackAuthorityConfig,
    HilCallbackChannel,
)
from fdai_operator_service.families.iam.hil_callback_context import HilCallbackContext
from fdai_operator_service.families.iam.hil_decision_outbox import (
    DurableHilDecisionOutboxPublisher,
    HilDecisionOutboxDrainer,
    hil_decision_delivery_key,
    hil_decision_payload,
    outbox_payload,
)
from fdai_operator_service.families.iam.hil_teams_callback import (
    HIL_DECISION_ACTION,
    TeamsHilCallbackConfig,
    TeamsHilCallbackNormalizer,
    make_hil_teams_callback_route,
)
from fdai_service_contracts import OperatorRole
from starlette.applications import Starlette

_NOW: Final = datetime(2026, 1, 1, tzinfo=UTC)
_SECRET: Final = "ephemeral-local-canary-key"  # noqa: S105 - non-deployment synthetic value.
_TEAM_ID: Final = "synthetic-team"
_CHANNEL_ID: Final = "synthetic-channel"
_TENANT_ID: Final = "synthetic-tenant"
_BOT_APPLICATION_ID: Final = "synthetic-approval-bot"
_OPERATOR_AUDIENCE: Final = "api://synthetic-operator"
_ISSUER: Final = "https://login.microsoftonline.com/synthetic-tenant/v2.0"
_SERVICE_URL: Final = "https://smba.trafficmanager.invalid/amer"
_SLACK_TEAM_ID: Final = "synthetic-workspace"
_TEAMS_ACTOR: Final = "synthetic-teams-aad-object-id"
_SLACK_ACTOR: Final = "slack-synthetic-approver"
_AUDIENCES: Final = {
    HilCallbackChannel.TEAMS: f"teams:{_TEAM_ID}:{_CHANNEL_ID}",
    HilCallbackChannel.SLACK: f"slack:{_SLACK_TEAM_ID}",
}
_GROUP_IDS: Final = {
    OperatorRole.READER: "synthetic-readers",
    OperatorRole.CONTRIBUTOR: "synthetic-contributors",
    OperatorRole.APPROVER: "synthetic-approvers",
    OperatorRole.OWNER: "synthetic-owners",
    OperatorRole.BREAK_GLASS: "synthetic-break-glass",
}


class _SyntheticIdentity:
    """Own one ephemeral RSA key that signs both synthetic token families."""

    def __init__(self) -> None:
        self._key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.key_id = "canary-key-1"
        self._private_pem = self._key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )

    def jwks(self) -> Sequence[Mapping[str, Any]]:
        """Return the bounded in-process JSON Web Key Set."""
        public = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(self._key.public_key()))
        public.update({"kid": self.key_id, "use": "sig", "alg": "RS256"})
        return (public,)

    def service_token(self, *, service_url: str = _SERVICE_URL) -> str:
        """Sign one synthetic Bot Framework service token."""
        now = datetime.now(tz=UTC)
        return jwt.encode(
            {
                "iss": "https://api.botframework.com",
                "aud": _BOT_APPLICATION_ID,
                "serviceurl": service_url,
                "nbf": int((now - timedelta(seconds=10)).timestamp()),
                "exp": int((now + timedelta(minutes=5)).timestamp()),
            },
            self._private_pem,
            algorithm="RS256",
            headers={"kid": self.key_id},
        )

    def delegated_token(self, *, oid: str, roles: Sequence[str] = ("Approver",)) -> str:
        """Sign one synthetic delegated (OBO) Operator API user token."""
        now = datetime.now(tz=UTC)
        return jwt.encode(
            {
                "iss": _ISSUER,
                "aud": _OPERATOR_AUDIENCE,
                "oid": oid,
                "idtyp": "user",
                "roles": list(roles),
                "azp": _BOT_APPLICATION_ID,
                "exp": int((now + timedelta(minutes=5)).timestamp()),
            },
            self._private_pem,
            algorithm="RS256",
            headers={"kid": self.key_id},
        )

    def verify_operator_token(self, token: str) -> Mapping[str, object]:
        """Verify one delegated token exactly as the Operator verifier would."""
        public = self._key.public_key()
        claims: Mapping[str, object] = jwt.decode(
            token,
            public,
            algorithms=["RS256"],
            audience=_OPERATOR_AUDIENCE,
            issuer=_ISSUER,
            options={"require": ["exp", "iss", "aud"]},
        )
        return claims


class _CanaryJwks:
    def __init__(self, identity: _SyntheticIdentity) -> None:
        self._identity = identity
        self.calls = 0

    async def get_keys(self) -> Sequence[Mapping[str, Any]]:
        self.calls += 1
        return self._identity.jwks()


class _CanaryRegistry:
    """In-process stand-in for the durable Operator IAM decision records."""

    def __init__(self) -> None:
        self.pending = {
            "teams-rejection": _pending(
                "teams-rejection",
                expires_at=_NOW + timedelta(minutes=5),
            ),
            "slack-approval": _pending(
                "slack-approval",
                expires_at=_NOW + timedelta(minutes=5),
            ),
            "expired-approval": _pending(
                "expired-approval",
                expires_at=_NOW - timedelta(seconds=1),
            ),
        }
        self.receipts: dict[str, HilDecisionReceipt] = {}

    async def get_pending_by_approval_id(self, approval_id: str) -> HilPendingItem | None:
        return self.pending.get(approval_id)

    async def get_decision_by_approval_id(
        self,
        approval_id: str,
    ) -> HilDecisionReceipt | None:
        return self.receipts.get(approval_id)

    async def record_decision(self, command: HilDecisionCommand) -> HilDecisionReceipt:
        pending = next(
            item
            for item in self.pending.values()
            if item.idempotency_key == command.idempotency_key
        )
        receipt = HilDecisionReceipt(
            approval_id=pending.approval_id,
            idempotency_key=command.idempotency_key,
            decision=command.decision,
            approver_oid=command.approver_oid,
            decided_at=command.decided_at,
            receipt_ref=f"canary-receipt:{pending.approval_id}",
            justification=command.justification,
        )
        self.receipts[pending.approval_id] = receipt
        return receipt

    async def mark_delivered(self, receipt: HilDecisionReceipt) -> HilDecisionReceipt:
        stored = self.receipts.get(receipt.approval_id, receipt)
        if stored.delivered:
            return stored
        delivered = replace(stored, delivered=True)
        self.receipts[receipt.approval_id] = delivered
        return delivered

    async def get_callback_context(self, approval_id: str) -> HilCallbackContext | None:
        pending = self.pending.get(approval_id)
        if pending is None:
            return None
        return HilCallbackContext(
            approval_id=approval_id,
            correlation_id=pending.metadata["correlation_id"],
            idempotency_key=pending.idempotency_key,
            action_hash=pending.metadata["action_hash"],
            expires_at=datetime.fromisoformat(pending.metadata["expires_at"]),
            submitter_oid=pending.submitter_oid,
            metadata=pending.metadata,
        )


class _CanaryOutboxStore:
    """In-process durable outbox with the PostgreSQL claim/release semantics."""

    def __init__(self) -> None:
        self.records: dict[str, dict[str, Any]] = {}

    async def enqueue(self, request: HilDecisionOutboxRequest) -> None:
        key = hil_decision_delivery_key(request.receipt.idempotency_key)
        self.records.setdefault(
            key,
            {
                "key": key,
                "dispatch_status": "pending",
                "claim_id": None,
                "attempt": 0,
                "payload": outbox_payload(request.receipt),
            },
        )

    async def claim_hil_decision_proposal(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
    ) -> _CanaryClaim | None:
        del worker_id, lease_seconds
        for record in self.records.values():
            if record["dispatch_status"] != "pending":
                continue
            record["dispatch_status"] = "claimed"
            record["claim_id"] = str(uuid.uuid4())
            record["attempt"] += 1
            return _CanaryClaim(
                key=str(record["key"]),
                claim_id=str(record["claim_id"]),
                payload=dict(record["payload"]),
            )
        return None

    async def mark_proposal_published(self, *, key: str, claim_id: str) -> bool:
        record = self.records.get(key)
        if record is None or record["claim_id"] != claim_id:
            return False
        record["dispatch_status"] = "published"
        return True

    async def mark_proposal_rejected(
        self,
        *,
        key: str,
        claim_id: str,
        reason_code: str,
    ) -> bool:
        record = self.records.get(key)
        if record is None or record["claim_id"] != claim_id:
            return False
        record["dispatch_status"] = "rejected"
        record["rejection_reason"] = reason_code
        return True

    async def release_proposal_claim(self, *, key: str, claim_id: str) -> bool:
        record = self.records.get(key)
        if record is None or record["claim_id"] != claim_id:
            return False
        record["dispatch_status"] = "pending"
        record["claim_id"] = None
        return True

    async def mark_decision_published(self, idempotency_key: str) -> bool:
        record = self.records.get(hil_decision_delivery_key(idempotency_key))
        if record is None or record["dispatch_status"] != "pending":
            return False
        record["dispatch_status"] = "published"
        return True


@dataclass(frozen=True, slots=True)
class _CanaryClaim:
    key: str
    claim_id: str
    payload: Mapping[str, object]


class _CanaryPublisher:
    """Broker stand-in whose first attempt can fail like a real outage."""

    def __init__(self, *, fail_first: bool = False) -> None:
        self.published: list[tuple[str, str, dict[str, object]]] = []
        self._fail_first = fail_first

    async def publish(self, topic: str, key: str, payload: dict[str, object]) -> object:
        if self._fail_first:
            self._fail_first = False
            raise RuntimeError("synthetic broker rejection")
        self.published.append((topic, key, payload))
        return object()


class _CanaryAudit:
    def __init__(self) -> None:
        self.records: list[HilCallbackAuditRecord] = []

    async def append_callback_audit(self, record: HilCallbackAuditRecord) -> None:
        self.records.append(record)

    def teardown(self) -> None:
        self.records.clear()


@dataclass(frozen=True, slots=True)
class HilBootstrapCanaryResult:
    """Secret-free bounded canary summary."""

    mode: str
    slack_approval: str
    teams_rejection: str
    timeout: str
    teams_tampered_card: str
    audit_records_before_teardown: int
    retained_records_after_teardown: int
    client_closed: bool
    broker_publications: int
    replayed_after_broker_failure: bool
    live_network_calls: int = 0
    live_teams_proof: bool = False

    def to_dict(self) -> dict[str, object]:
        """Return the exact bounded canary projection."""
        return {
            "mode": self.mode,
            "slack_approval": self.slack_approval,
            "teams_rejection": self.teams_rejection,
            "timeout": self.timeout,
            "teams_tampered_card": self.teams_tampered_card,
            "audit_records_before_teardown": self.audit_records_before_teardown,
            "retained_records_after_teardown": self.retained_records_after_teardown,
            "client_closed": self.client_closed,
            "broker_publications": self.broker_publications,
            "replayed_after_broker_failure": self.replayed_after_broker_failure,
            "live_network_calls": self.live_network_calls,
            "live_teams_proof": self.live_teams_proof,
        }


async def run_local_hil_bootstrap_canary() -> HilBootstrapCanaryResult:
    """Run the composed callback, normalizer, publish, and replay paths locally."""
    identity = _SyntheticIdentity()
    registry = _CanaryRegistry()
    durable = _CanaryOutboxStore()
    publisher = _CanaryPublisher(fail_first=True)
    audit = _CanaryAudit()
    config = HilCallbackConfig(secret=_SECRET)
    outbox = DurableHilDecisionOutboxPublisher(
        durable=durable,
        publisher=publisher,
        topic="fdai.hil.decisions",
        ledger=durable,
        registry=registry,
    )
    authority = EntraHilCallbackAuthority(
        authenticator=OperatorAuthenticator(
            verifier=identity.verify_operator_token,
            group_ids=_GROUP_IDS,
        ),
        config=HilCallbackAuthorityConfig.from_environment(
            {
                "FDAI_TEAMS_APPLICATION_ID": _BOT_APPLICATION_ID,
                "FDAI_TEAMS_APPROVAL_TEAM_ID": _TEAM_ID,
                "FDAI_TEAMS_APPROVAL_CHANNEL_ID": _CHANNEL_ID,
                "FDAI_TEAMS_PRINCIPAL_MAP_JSON": json.dumps(
                    {_TEAMS_ACTOR: "synthetic-approver-oid"}
                ),
                "FDAI_SLACK_TEAM_ID": _SLACK_TEAM_ID,
                "FDAI_SLACK_PRINCIPAL_MAP_JSON": json.dumps(
                    {_SLACK_ACTOR: "synthetic-approver-oid"}
                ),
            },
            group_ids=_GROUP_IDS,
        ),
    )
    normalizer = TeamsHilCallbackNormalizer(
        config=TeamsHilCallbackConfig(
            application_id=_BOT_APPLICATION_ID,
            tenant_id=_TENANT_ID,
            team_id=_TEAM_ID,
            channel_id=_CHANNEL_ID,
            allowed_service_urls=frozenset({_SERVICE_URL}),
        ),
        tokens=TeamsServiceTokenVerifier(
            config=TeamsTokenConfig(application_id=_BOT_APPLICATION_ID),
            jwks=_CanaryJwks(identity),
        ),
    )
    app = Starlette(
        routes=[
            make_hil_callback_route(
                registry=registry,
                outbox=outbox,
                config=config,
                authority=authority,
                audit=audit,
                context_reader=registry,
                clock=lambda: _NOW,
            ),
            make_hil_teams_callback_route(
                registry=registry,
                outbox=outbox,
                authority=authority,
                audit=audit,
                context_reader=registry,
                normalizer=normalizer,
                clock=lambda: _NOW,
            ),
        ]
    )
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://canary.invalid",
    )
    try:
        slack = await _post_signed(
            client,
            config,
            identity,
            approval_id="slack-approval",
            decision="approve",
        )
        teams = await _post_activity(
            client,
            identity,
            approval_id="teams-rejection",
            decision="reject",
        )
        expired = await _post_activity(
            client,
            identity,
            approval_id="expired-approval",
            decision="approve",
        )
        tampered = await _post_activity(
            client,
            identity,
            approval_id="teams-rejection",
            decision="reject",
            extra_data={"provider_actor_id": "attacker-supplied-actor"},
        )
        statuses = (
            slack.status_code,
            teams.status_code,
            expired.status_code,
            tampered.status_code,
        )
        if statuses != (503, 200, 410, 400):
            raise RuntimeError(
                f"local HIL canary did not reach its expected terminal statuses: {statuses}"
            )
        if slack.json()["error"]["kind"] != "decision_publish_failed":
            raise RuntimeError("local HIL canary broker failure was not surfaced fail-closed")
        outcomes = Counter(record.outcome for record in audit.records)
        if outcomes != Counter(
            {
                HilCallbackOutcome.PENDING: 4,
                HilCallbackOutcome.ACCEPTED: 1,
                HilCallbackOutcome.REJECTED: 1,
                HilCallbackOutcome.EXPIRED: 1,
                HilCallbackOutcome.INVALID: 1,
            }
        ):
            raise RuntimeError(f"local HIL canary audit phases are incomplete: {dict(outcomes)}")
        replayed = await _replay(durable, registry, publisher)
        audit_count = len(audit.records)
    finally:
        await client.aclose()
    audit.teardown()
    return HilBootstrapCanaryResult(
        mode="local_dry_run_no_network",
        slack_approval="recorded_then_redriven",
        teams_rejection="rejected",
        timeout="expired_fail_closed",
        teams_tampered_card="refused_unknown_card_field",
        audit_records_before_teardown=audit_count,
        retained_records_after_teardown=len(audit.records),
        client_closed=client.is_closed,
        broker_publications=len(publisher.published),
        replayed_after_broker_failure=replayed,
    )


async def _replay(
    durable: _CanaryOutboxStore,
    registry: _CanaryRegistry,
    publisher: _CanaryPublisher,
) -> bool:
    drainer = HilDecisionOutboxDrainer(
        store=durable,
        registry=registry,
        publisher=publisher,
        topic="fdai.hil.decisions",
    )
    redriven = await drainer.run_once()
    if not redriven:
        raise RuntimeError("local HIL canary did not redrive the failed broker publication")
    if await drainer.run_once():
        raise RuntimeError("local HIL canary redrove an already published decision")
    receipt = registry.receipts["slack-approval"]
    if not receipt.delivered:
        raise RuntimeError("local HIL canary marked delivery before broker acceptance")
    expected = hil_decision_payload(replace(receipt, delivered=False))
    if publisher.published[-1][2] != expected:
        raise RuntimeError("local HIL canary replay published a divergent payload")
    return True


async def _post_signed(
    client: httpx.AsyncClient,
    config: HilCallbackConfig,
    identity: _SyntheticIdentity,
    *,
    approval_id: str,
    decision: str,
) -> httpx.Response:
    pending = _pending(approval_id, expires_at=_NOW + timedelta(minutes=5))
    body = json.dumps(
        {
            "decision": decision,
            "justification": "Synthetic canary decision.",
            "channel": HilCallbackChannel.SLACK.value,
            "provider_actor_id": _SLACK_ACTOR,
            "audience": _AUDIENCES[HilCallbackChannel.SLACK],
            "correlation_id": pending.metadata["correlation_id"],
            "idempotency_key": pending.idempotency_key,
            "action_hash": pending.metadata["action_hash"],
        },
        separators=(",", ":"),
    ).encode()
    timestamp = _NOW.isoformat()
    signature = compute_hmac(
        secret=config.secret,
        timestamp=timestamp,
        approval_id=approval_id,
        payload=body,
    )
    return await client.post(
        f"/hil/{approval_id}/decision",
        content=body,
        headers={
            "Authorization": "Bearer " + identity.delegated_token(oid="synthetic-approver-oid"),
            "X-FDAI-Timestamp": timestamp,
            "X-FDAI-Signature": f"sha256={signature}",
        },
    )


async def _post_activity(
    client: httpx.AsyncClient,
    identity: _SyntheticIdentity,
    *,
    approval_id: str,
    decision: str,
    extra_data: Mapping[str, str] | None = None,
) -> httpx.Response:
    pending = _pending(approval_id, expires_at=_NOW + timedelta(minutes=5))
    data: dict[str, str] = {
        "decision": decision,
        "justification": "Synthetic canary decision.",
        "approval_id": approval_id,
        "correlation_id": pending.metadata["correlation_id"],
        "idempotency_key": pending.idempotency_key,
        "action_hash": pending.metadata["action_hash"],
        "audience": _AUDIENCES[HilCallbackChannel.TEAMS],
    }
    data.update(extra_data or {})
    activity = {
        "type": "invoke",
        "name": "adaptiveCard/action",
        "id": f"activity-{approval_id}",
        "channelId": "msteams",
        "serviceUrl": _SERVICE_URL,
        "from": {"aadObjectId": _TEAMS_ACTOR},
        "conversation": {"id": f"19:{_CHANNEL_ID}@thread.tacv2"},
        "channelData": {
            "tenant": {"id": _TENANT_ID},
            "team": {"id": _TEAM_ID},
            "channel": {"id": _CHANNEL_ID},
        },
        "value": {
            "action": {
                "type": "Action.Execute",
                "verb": HIL_DECISION_ACTION,
                "data": data,
            },
            "authentication": {
                "token": identity.delegated_token(oid="synthetic-approver-oid"),
            },
            "trigger": "manual",
        },
    }
    return await client.post(
        "/hil/teams-activity",
        content=json.dumps(activity, separators=(",", ":")).encode(),
        headers={"Authorization": "Bearer " + identity.service_token()},
    )


def _pending(approval_id: str, *, expires_at: datetime) -> HilPendingItem:
    return HilPendingItem(
        approval_id=approval_id,
        idempotency_key=f"canary:{approval_id}",
        submitter_oid="synthetic-submitter",
        metadata={
            "correlation_id": f"canary-correlation:{approval_id}",
            "action_hash": f"canary-action:{approval_id}",
            "expires_at": expires_at.isoformat(),
        },
    )


def run_local_hil_bootstrap_canary_sync() -> HilBootstrapCanaryResult:
    """Run the bounded canary from a synchronous command entry point."""
    return asyncio.run(asyncio.wait_for(run_local_hil_bootstrap_canary(), timeout=30))


__all__ = [
    "HilBootstrapCanaryResult",
    "run_local_hil_bootstrap_canary",
    "run_local_hil_bootstrap_canary_sync",
]
