"""Var - Approver (Wave 3 + Wave 6 behavior).

Var carries the HIL approval principal (Wave 3) and delivers admin
security notifications through the ChatOps admin channel (Wave 6).
Every card is deduped by (initiator, action_type) within a rolling
window and the last-seen counter is incremented on repeat.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable, Mapping
from copy import deepcopy
from typing import Any

from fdai.agents._framework.action_run_identity import validate_action_run_identity
from fdai.agents._framework.adapters import (
    AdminCard,
    AdminNotificationAdapter,
    InMemoryAdminChannel,
)
from fdai.agents._framework.assignment_workflow import AssignmentReviewMixin
from fdai.agents._framework.base import Agent
from fdai.agents._framework.bounded import BoundedLruDict, BoundedLruSet
from fdai.agents._framework.bus import PantheonBus
from fdai.agents._framework.introspection import (
    IntrospectionResult,
    agent_state_evidence_ref,
    capability_facts,
    capped_list,
    mentioned,
)
from fdai.agents._framework.pantheon import _VAR
from fdai.agents._framework.var_decisions import (
    ApprovalDecisionState,
    TestContextReviewMixin,
    VarDecisionJournal,
    approval_for_ticket,
    final_approval_record,
)
from fdai.agents._framework.var_ticket_identity import (
    APPROVAL_STATE_PREFIX,
    PendingHilTicket,
    PendingShadowReview,
    claim_action_correlation_identity,
)
from fdai.agents._framework.var_ticket_identity import (
    approval_action_identity as _approval_action_identity,
)
from fdai.agents._framework.var_ticket_identity import (
    approval_cache_key as _approval_cache_key,
)
from fdai.agents._framework.var_ticket_identity import (
    approval_state_key as _approval_state_key,
)
from fdai.agents._framework.var_ticket_identity import (
    evict_oldest_ticket as _evict_oldest_ticket,
)
from fdai.agents._framework.var_ticket_identity import (
    record_blocked_attempt as _record_blocked_attempt_once,
)
from fdai.agents._framework.var_ticket_identity import (
    remove_pending_ticket as _remove_pending_ticket,
)
from fdai.agents._framework.var_ticket_identity import (
    ticket_from_identity as _ticket_from_identity,
)
from fdai.agents._framework.var_ticket_identity import (
    ticket_identity as _ticket_identity,
)
from fdai.shared.providers.state_store import StateStore

ApproverAuthorizer = Callable[[str, str], bool | Awaitable[bool]]


class Var(TestContextReviewMixin, AssignmentReviewMixin, Agent):
    """Wave-3 HIL approval + Wave-6 admin channel delivery."""

    #: Bound the in-memory maps so a long-lived approver cannot leak one entry
    #: per never-decided HIL item / admin card forever (oldest-first eviction).
    _MAX_PENDING = 5_000
    _MAX_CARDS = 5_000

    def __init__(
        self,
        *,
        bus: PantheonBus | None = None,
        admin_channel: AdminNotificationAdapter | None = None,
        approver_authorizer: ApproverAuthorizer | None = None,
        state_store: StateStore | None = None,
    ) -> None:
        super().__init__(spec=_VAR)
        self.bus = bus
        self.admin_channel = admin_channel or InMemoryAdminChannel()
        self._approver_authorizer = approver_authorizer
        self._state_store = state_store
        self._decision_journal = (
            VarDecisionJournal(state_store, state_prefix=APPROVAL_STATE_PREFIX)
            if state_store is not None
            else None
        )
        self._decision_lock = asyncio.Lock()
        self._pending: dict[str, PendingHilTicket] = {}
        self.initialize_assignment_review()
        self._pending_shadow_reviews: dict[str, PendingShadowReview] = {}
        # (initiator, action_type) -> AdminCard for dedup counter update
        self._last_cards: dict[tuple[str, str], AdminCard] = {}
        # (correlation, approver) pairs already counted as a blocked attempt,
        # so a caller that retries the same rejected approval does not inflate
        # the security metric. Bounded (a distinct blocked attempt still
        # counts; only an exact retry is deduped).
        self._blocked_attempts: BoundedLruSet[str] = BoundedLruSet(self._MAX_PENDING)
        self._final_approvals: BoundedLruDict[tuple[str, str], dict[str, Any]] = BoundedLruDict(
            self._MAX_PENDING
        )
        self._published_approvals: BoundedLruSet[tuple[str, str]] = BoundedLruSet(self._MAX_PENDING)
        self._action_correlation_identities: BoundedLruDict[str, str] = BoundedLruDict(
            self._MAX_PENDING
        )

    def bind_bus(self, bus: PantheonBus) -> None:
        self.bus = bus

    async def on_typed_message(self, topic: str, payload: dict[str, Any]) -> None:
        if await self._test_context_review_message(topic, payload, self.record_behavior):
            return
        if await self._assignment_review_message(topic, payload):
            return
        if topic == "object.audit-entry":
            self._ingest_document_hil(payload)
            self._ingest_shadow_review(payload)
            return
        if topic != "object.action-run":
            return
        if payload.get("state") != "hil_pending":
            return
        correlation = str(payload.get("correlation_id", ""))
        if not correlation:
            return
        try:
            action_run_identity = validate_action_run_identity(payload)
        except ValueError:
            self.record_behavior("ticket_invalid_action_identity")
            return
        if not await claim_action_correlation_identity(
            self._state_store,
            self._action_correlation_identities,
            correlation,
            action_run_identity,
        ):
            self.record_behavior("ticket_identity_conflict")
            return
        # Clamp quorum to a floor of 1: a forged / malformed action-run must
        # never yield a zero-or-negative quorum that would approve with no
        # approver (the two-approver requirement for irreversible actions is
        # set by Forseti; this only prevents a downgrade below one).
        raw_quorum = payload.get("quorum_required", 1)
        if isinstance(raw_quorum, bool):
            self.record_behavior("ticket_invalid_quorum")
            return
        try:
            quorum = max(1, int(raw_quorum))
        except (TypeError, ValueError):
            self.record_behavior("ticket_invalid_quorum")
            return
        raw_initiator = payload.get("initiator_principal")
        if raw_initiator is not None and not isinstance(raw_initiator, str):
            self.record_behavior("ticket_invalid_initiator")
            return
        raw_idempotency_key = payload.get(
            "action_idempotency_key",
            payload.get("idempotency_key"),
        )
        if raw_idempotency_key is not None and (
            not isinstance(raw_idempotency_key, str)
            or not raw_idempotency_key
            or raw_idempotency_key != raw_idempotency_key.strip()
        ):
            self.record_behavior("ticket_invalid_idempotency_key")
            return
        raw_action_id = payload.get("action_id")
        if raw_action_id is not None and not isinstance(raw_action_id, str):
            self.record_behavior("ticket_invalid_action_id")
            return
        raw_resource_id = payload.get("resource_id")
        if raw_resource_id is not None and not isinstance(raw_resource_id, str):
            self.record_behavior("ticket_invalid_resource_id")
            return
        raw_rollback_contract = payload.get("rollback_contract", "state_forward_only")
        if not isinstance(raw_rollback_contract, str) or not raw_rollback_contract:
            self.record_behavior("ticket_invalid_rollback_contract")
            return
        if await self._load_final_approval(correlation, action_run_identity) is not None:
            self.record_behavior("ticket_finalized_replay")
            return
        existing = self._pending.get(correlation)
        if existing is not None:
            if existing.action_run_identity == action_run_identity:
                return
            self.record_behavior("ticket_identity_conflict")
            return
        self._pending[correlation] = PendingHilTicket(
            correlation_id=correlation,
            action_id=raw_action_id,
            action_type=str(payload.get("action_type", "")),
            resource_id=raw_resource_id,
            quorum_required=quorum,
            action_run_identity=action_run_identity,
            initiator_principal=raw_initiator.strip() if raw_initiator else None,
            idempotency_key=raw_idempotency_key or "",
            rollback_contract=raw_rollback_contract,
            params=(dict(payload["params"]) if isinstance(payload.get("params"), Mapping) else {}),
            decision_case=(
                dict(payload["decision_case"])
                if isinstance(payload.get("decision_case"), dict)
                else None
            ),
        )
        self.record_behavior("ticket_pending")
        _evict_oldest_ticket(self._pending, self._MAX_PENDING, keep=correlation)

    def _ingest_document_hil(self, payload: dict[str, Any]) -> None:
        if (
            payload.get("producer_principal") != "Saga"
            or payload.get("kind") != "document_ingestion"
            or payload.get("audited_topic") != "object.verdict"
            or payload.get("stage") != "protection_check"
            or payload.get("decision") != "hil"
        ):
            return
        correlation = str(payload.get("correlation_id") or "")
        document_id = str(payload.get("document_id") or "")
        upload_id = str(payload.get("upload_id") or "")
        if not correlation or not document_id or not upload_id or correlation in self._pending:
            return
        self._pending[correlation] = PendingHilTicket(
            correlation_id=correlation,
            action_type="document.promote-authoritative",
            resource_id=document_id,
            quorum_required=1,
            initiator_principal=str(payload.get("initiator_principal") or "") or None,
            kind="document_ingestion",
            document_id=document_id,
            upload_id=upload_id,
            stage="protection_check",
            idempotency_key=str(payload.get("idempotency_key") or ""),
        )
        self.record_behavior("document_ticket_pending")
        _evict_oldest_ticket(self._pending, self._MAX_PENDING, keep=correlation)

    def _ingest_shadow_review(self, payload: dict[str, Any]) -> None:
        if (
            payload.get("producer_principal") != "Saga"
            or payload.get("audited_topic") != "object.action-run"
            or payload.get("shadow_mode") is not True
            or payload.get("operator_reviewed") is not False
        ):
            return
        correlation = str(payload.get("shadow_observation_id") or "")
        action_type = str(payload.get("action_type") or "")
        observed_at = str(payload.get("observed_at") or "")
        policy_escape = payload.get("policy_escape")
        if (
            not correlation
            or not action_type
            or not observed_at
            or not isinstance(policy_escape, bool)
            or correlation in self._pending_shadow_reviews
        ):
            self.record_behavior("shadow_review_invalid")
            return
        initiator = payload.get("initiator_principal")
        if initiator is not None and not isinstance(initiator, str):
            self.record_behavior("shadow_review_invalid")
            return
        self._pending_shadow_reviews[correlation] = PendingShadowReview(
            correlation_id=correlation,
            action_type=action_type,
            observed_at=observed_at,
            policy_escape=policy_escape,
            initiator_principal=initiator.strip() if initiator else None,
        )
        _evict_oldest_ticket(
            self._pending_shadow_reviews,
            self._MAX_PENDING,
            keep=correlation,
        )
        self.record_behavior("shadow_review_pending")

    async def decide(
        self,
        correlation_id: str,
        *,
        approver: str,
        decision: str,
    ) -> dict[str, Any] | None:
        async with self._decision_lock:
            return await self._record_decision_locked(
                correlation_id,
                approver=approver,
                decision=decision,
            )

    async def _record_decision_locked(
        self,
        correlation_id: str,
        *,
        approver: str,
        decision: str,
    ) -> dict[str, Any] | None:
        ticket = self._pending.get(correlation_id)
        if ticket is None:
            return None
        final_approval = await self._load_final_approval(
            correlation_id,
            ticket.action_run_identity,
        )
        if final_approval is not None:
            if final_approval.get("action_run_identity") != ticket.action_run_identity:
                raise RuntimeError("stored final approval conflicts with the pending ticket")
            return await self._publish_final_approval(final_approval)

        approver_norm = approver.strip().casefold()
        if not approver_norm:
            raise ValueError(f"approver MUST be a non-empty principal on {correlation_id!r}")
        initiator_norm = (ticket.initiator_principal or "").strip().casefold()
        if initiator_norm and approver_norm == initiator_norm:
            self._record_blocked_attempt("self_approval_blocked", correlation_id, approver_norm)
            raise ValueError(
                f"principal {approver_norm!r} cannot decide an action it initiated "
                f"({correlation_id!r}): no self-approval"
            )
        if self._approver_authorizer is not None:
            authorized = self._approver_authorizer(approver_norm, ticket.action_type)
            if inspect.isawaitable(authorized):
                authorized = await authorized
            if not authorized:
                self._record_blocked_attempt(
                    "approver_unauthorized",
                    correlation_id,
                    approver_norm,
                )
                raise PermissionError(
                    f"principal {approver_norm!r} is not authorized to decide "
                    f"{ticket.action_type!r}"
                )
        if decision not in {"approve", "reject"}:
            raise ValueError(f"unknown decision {decision!r}")
        if decision == "approve":
            # No self-approval: the operator who initiated the action can never
            # approve it (approval and initiation are distinct principals - a
            # pantheon safety invariant, agent-pantheon.md). Enforced here even
            # if the entry RBAC gate was bypassed upstream. Compare case-folded
            # (Azure UPNs / object ids are case-insensitive) so neither the
            # self-approval nor the distinct-approver quorum can be bypassed by
            # varying case, and reject a blank approver outright. This matches
            # the case-insensitive rule the operator-memory approval path
            # already enforces.
            if approver_norm in ticket.approvers:
                self._record_blocked_attempt(
                    "double_approval_blocked", correlation_id, approver_norm
                )
                raise ValueError(
                    f"principal {approver_norm!r} cannot self-approve twice on {correlation_id!r}"
                )

        durable_decision: ApprovalDecisionState | None = None
        if self._decision_journal is not None:
            durable_decision = await self._decision_journal.record(
                state_key=_approval_state_key(
                    correlation_id,
                    "decisions",
                    ticket.action_run_identity,
                ),
                correlation_id=correlation_id,
                action_type=ticket.action_type,
                quorum_required=ticket.quorum_required,
                ticket_identity=_ticket_identity(ticket),
                principal=approver_norm,
                decision="approved" if decision == "approve" else "rejected",
            )
            ticket.approvers = list(durable_decision.approved_principals)
            ticket.rejected = durable_decision.rejected
        else:
            if decision == "reject":
                ticket.rejected = True
            else:
                ticket.approvers.append(approver_norm)

        if ticket.rejected or len(ticket.approvers) >= ticket.quorum_required:
            final = "rejected" if ticket.rejected else "approved"
            self.record_behavior(final)
            approval = approval_for_ticket(ticket, state=final)
            final_approval = await self._checkpoint_final_approval(approval)
            if durable_decision is not None and self._decision_journal is not None:
                await self._decision_journal.mark_finalized(
                    state_key=_approval_state_key(
                        correlation_id,
                        "decisions",
                        ticket.action_run_identity,
                    ),
                    ticket_identity=durable_decision.ticket_identity,
                )
            return await self._publish_final_approval(final_approval)
        return None

    async def recover_approvals(self) -> tuple[int, int]:
        """Finalize terminal decisions and publish pending finals at startup."""
        finalized = 0
        journal = self._decision_journal
        if journal is not None:
            for index in range(self._MAX_PENDING + 1):
                decision = await journal.next_pending_finalization()
                if decision is None:
                    break
                if index == self._MAX_PENDING:
                    raise RuntimeError("approval finalization recovery capacity exceeded")
                ticket = _ticket_from_identity(decision.ticket_identity)
                approval = approval_for_ticket(
                    ticket,
                    state=decision.disposition,
                    approvers=decision.approved_principals,
                )
                await self._checkpoint_final_approval(approval)
                await journal.mark_finalized(
                    state_key=_approval_state_key(
                        ticket.correlation_id,
                        "decisions",
                        ticket.action_run_identity,
                    ),
                    ticket_identity=decision.ticket_identity,
                )
                finalized += 1
        if self.bus is None or self._state_store is None:
            return finalized, 0
        published = 0
        for index in range(self._MAX_PENDING + 1):
            pending_approval = await self._next_pending_final_approval()
            if pending_approval is None:
                break
            if index == self._MAX_PENDING:
                raise RuntimeError("approval publication recovery capacity exceeded")
            await self._publish_final_approval(pending_approval)
            published += 1
        return finalized, published

    async def _load_final_approval(
        self,
        correlation_id: str,
        action_run_identity: str | None,
    ) -> dict[str, Any] | None:
        cache_key = _approval_cache_key(correlation_id, action_run_identity)
        cached = self._final_approvals.get(cache_key)
        if cached is not None:
            return deepcopy(cached)
        if self._state_store is None:
            return None
        stored = await self._state_store.read_state(
            _approval_state_key(correlation_id, "final", action_run_identity)
        )
        if stored is None:
            return None
        approval, _published = self._validate_final_record(stored, correlation_id)
        if approval.get("action_run_identity") != action_run_identity:
            raise RuntimeError("stored final approval identity does not match its key")
        self._final_approvals.set(cache_key, deepcopy(approval))
        return approval

    async def _checkpoint_final_approval(
        self,
        approval: dict[str, Any],
    ) -> dict[str, Any]:
        correlation_id = str(approval["correlation_id"])
        action_run_identity = _approval_action_identity(approval)
        cache_key = _approval_cache_key(correlation_id, action_run_identity)
        cached = self._final_approvals.get(cache_key)
        if cached is not None:
            if cached != approval:
                raise RuntimeError("approval finalization collided with a different payload")
            return deepcopy(cached)
        if self._state_store is not None:
            key = _approval_state_key(correlation_id, "final", action_run_identity)
            record = final_approval_record(
                approval,
                publication_status="pending",
                revision=1,
            )
            created = await self._state_store.write_state_if_absent(key, record)
            if not created:
                stored = await self._state_store.read_state(key)
                if stored is None:
                    raise RuntimeError("approval final record disappeared after collision")
                stored_approval, _published = self._validate_final_record(stored, correlation_id)
                if stored_approval != approval:
                    raise RuntimeError("approval finalization collided with a different payload")
                approval = stored_approval
        self._final_approvals.set(cache_key, deepcopy(approval))
        return deepcopy(approval)

    async def _publish_final_approval(
        self,
        approval: dict[str, Any],
    ) -> dict[str, Any] | None:
        correlation_id = str(approval["correlation_id"])
        action_run_identity = _approval_action_identity(approval)
        if await self._approval_was_published(correlation_id, action_run_identity):
            _remove_pending_ticket(
                self._pending,
                correlation_id,
                action_run_identity,
            )
            return None
        if self.bus is None:
            _remove_pending_ticket(
                self._pending,
                correlation_id,
                action_run_identity,
            )
            return deepcopy(approval)
        await self.bus.publish("Var", "object.approval", deepcopy(approval))
        await self._mark_approval_published(approval)
        _remove_pending_ticket(
            self._pending,
            correlation_id,
            action_run_identity,
        )
        return deepcopy(approval)

    async def _approval_was_published(
        self,
        correlation_id: str,
        action_run_identity: str | None,
    ) -> bool:
        cache_key = _approval_cache_key(correlation_id, action_run_identity)
        if cache_key in self._published_approvals:
            return True
        if self._state_store is None:
            return False
        stored = await self._state_store.read_state(
            _approval_state_key(correlation_id, "final", action_run_identity)
        )
        if stored is None:
            return False
        _approval, published = self._validate_final_record(stored, correlation_id)
        if not published:
            return False
        if _approval_action_identity(_approval) != action_run_identity:
            raise RuntimeError("stored final approval identity does not match its key")
        self._published_approvals.add(cache_key)
        return True

    async def _mark_approval_published(self, approval: Mapping[str, Any]) -> None:
        correlation_id = str(approval["correlation_id"])
        action_run_identity = _approval_action_identity(approval)
        cache_key = _approval_cache_key(correlation_id, action_run_identity)
        if self._state_store is not None:
            key = _approval_state_key(correlation_id, "final", action_run_identity)
            for _attempt in range(16):
                stored = await self._state_store.read_state(key)
                if stored is None:
                    raise RuntimeError("approval final record disappeared before publication")
                stored_approval, published = self._validate_final_record(stored, correlation_id)
                if stored_approval != dict(approval):
                    raise RuntimeError("approval publication receipt collision")
                if published:
                    break
                revision = int(stored["revision"])
                advanced = await self._state_store.compare_and_set_state_with_audit(
                    key,
                    final_approval_record(
                        stored_approval,
                        publication_status="published",
                        revision=revision + 1,
                    ),
                    expected_revision=revision,
                    audit_entry={
                        "actor": "Var",
                        "action_kind": "approval.published",
                        "correlation_id": correlation_id,
                        "idempotency_key": str(approval["idempotency_key"]),
                        "state": str(approval["state"]),
                    },
                )
                if advanced:
                    break
            else:
                raise RuntimeError("approval publication CAS retry limit exceeded")
        self._published_approvals.add(cache_key)

    async def _next_pending_final_approval(self) -> dict[str, Any] | None:
        if self._state_store is None:
            return None
        stored = await self._state_store.find_state(
            f"{APPROVAL_STATE_PREFIX}/",
            field="publication_status",
            value="pending",
        )
        if stored is None:
            return None
        correlation_id = str(stored.get("correlation_id") or "")
        approval, _published = self._validate_final_record(stored, correlation_id)
        return approval

    @staticmethod
    def _validate_final_approval(
        stored: Mapping[str, Any],
        correlation_id: str,
    ) -> dict[str, Any]:
        approval = dict(stored)
        if (
            approval.get("producer_principal") != "Var"
            or approval.get("correlation_id") != correlation_id
            or approval.get("state") not in {"approved", "rejected"}
            or not isinstance(approval.get("idempotency_key"), str)
            or not approval["idempotency_key"]
        ):
            raise RuntimeError("stored final approval is malformed")
        _approval_action_identity(approval)
        return deepcopy(approval)

    @classmethod
    def _validate_final_record(
        cls,
        stored: Mapping[str, Any],
        correlation_id: str,
    ) -> tuple[dict[str, Any], bool]:
        revision = stored.get("revision")
        status = stored.get("publication_status")
        approval_raw = stored.get("approval")
        if (
            stored.get("schema_version") != "1.0.0"
            or stored.get("record_kind") != "final_approval"
            or not isinstance(revision, int)
            or isinstance(revision, bool)
            or revision < 1
            or status not in {"pending", "published"}
            or not isinstance(approval_raw, Mapping)
            or stored.get("correlation_id") != correlation_id
        ):
            raise RuntimeError("stored final approval record is malformed")
        approval = cls._validate_final_approval(approval_raw, correlation_id)
        canonical = final_approval_record(
            approval,
            publication_status=str(status),
            revision=revision,
        )
        if dict(stored) != canonical:
            raise RuntimeError("stored final approval record is malformed")
        return approval, status == "published"

    async def decide_shadow_review(
        self,
        correlation_id: str,
        *,
        reviewer: str,
        agreed: bool,
    ) -> dict[str, Any] | None:
        """Publish one real human review without manufacturing another sample."""

        ticket = self._pending_shadow_reviews.get(correlation_id)
        if ticket is None:
            return None
        reviewer_norm = reviewer.strip().casefold()
        if not reviewer_norm:
            raise ValueError("shadow outcome reviewer MUST be a non-empty principal")
        if not isinstance(agreed, bool):
            raise ValueError("shadow outcome agreement MUST be boolean")
        initiator_norm = (ticket.initiator_principal or "").strip().casefold()
        if initiator_norm and reviewer_norm == initiator_norm:
            self._record_blocked_attempt(
                "shadow_review_self_approval_blocked",
                correlation_id,
                reviewer_norm,
            )
            raise ValueError("a shadow outcome initiator cannot review their own action")
        approval: dict[str, Any] = {
            "producer_principal": "Var",
            "kind": "shadow_outcome_review",
            "correlation_id": ticket.correlation_id,
            "idempotency_key": f"shadow-review:{ticket.correlation_id}",
            "action_type": ticket.action_type,
            "state": "reviewed",
            "approvers": [reviewer_norm],
            "shadow_mode": True,
            "shadow_observation_id": ticket.correlation_id,
            "observed_at": ticket.observed_at,
            "operator_reviewed": True,
            "operator_agreed": agreed,
            "policy_escape": ticket.policy_escape,
        }
        if self.bus is not None:
            await self.bus.publish("Var", "object.approval", approval)
        del self._pending_shadow_reviews[correlation_id]
        self.record_behavior("shadow_review_completed")
        return approval

    def pending_tickets(self) -> tuple[PendingHilTicket, ...]:
        return tuple(self._pending.values())

    def pending_shadow_reviews(self) -> tuple[PendingShadowReview, ...]:
        """Return bounded shadow outcomes awaiting a distinct human review."""

        return tuple(self._pending_shadow_reviews.values())

    def _record_blocked_attempt(self, key: str, correlation_id: str, approver: str) -> None:
        _record_blocked_attempt_once(self, key, correlation_id, approver)

    # ---- admin notification (Wave 6) ----------------------------------

    async def deliver_admin_card(self, payload: dict[str, Any]) -> AdminCard:
        """Deliver an admin ChatOps card. Dedups by (initiator, action)."""
        initiator = str(payload.get("initiator_principal", ""))
        action = str(payload.get("attempted_action", ""))
        severity = str(payload.get("severity", "high"))
        counter = int(payload.get("counter", 1))
        key = (initiator, action)
        card = AdminCard(
            severity=severity,
            initiator_principal=initiator,
            attempted_action=action,
            counter=counter,
        )
        delivery = self.admin_channel.upsert(key, card)
        delivered = await delivery if inspect.isawaitable(delivery) else delivery
        self._last_cards[key] = delivered
        _evict_oldest_ticket(self._last_cards, self._MAX_CARDS, keep=key)
        return delivered

    # ---- conversational port -------------------------------------------

    def conversation_evidence_available(self, context: dict[str, Any]) -> bool:
        """Approval answers rest on pending tickets; the policy alone is config."""
        return bool(self._pending)

    async def introspect(self, question: str, context: dict[str, Any]) -> IntrospectionResult:
        pending = self._pending
        facts = {
            **capability_facts(self.spec),
            "pending_hil": len(pending),
            "correlations": capped_list(sorted(pending)),
        }
        corr = mentioned(question, pending)
        if corr:
            ticket = pending[corr[0]]
            facts.update(
                {
                    "correlation_id": ticket.correlation_id,
                    "action_type": ticket.action_type,
                    "quorum_required": ticket.quorum_required,
                    "approvals": len(ticket.approvers),
                    "rejected": ticket.rejected,
                }
            )
            evidence_ref = agent_state_evidence_ref(self.spec.name, facts)
            facts["evidence_refs"] = [evidence_ref]
            answer = (
                f"HIL {ticket.correlation_id!r} ({ticket.action_type}): "
                f"{len(ticket.approvers)}/{ticket.quorum_required} approval(s)"
                + (", rejected" if ticket.rejected else "")
                + f". Evidence: {evidence_ref}."
            )
            return IntrospectionResult(answer=answer, facts=facts)
        evidence_ref = agent_state_evidence_ref(self.spec.name, facts)
        facts["evidence_refs"] = [evidence_ref]
        if context.get("locale") == "ko":
            answer = (
                "저는 사람의 HIL 결정을 Approval로 기록하는 파이프라인 승인 principal인 Var입니다. "
                "Thor에게 보고하지만 Thor와는 별도 principal입니다. 현재 사람의 승인, 만료, quorum "
                "및 no-self-approval을 확인하며 작업을 판단하거나 실행하지 않습니다. 침묵이나 이전 "
                "승인을 현재 권한으로 간주하지 않습니다. 이 대화 포트는 읽기 전용이며 승인 요청은 "
                "운영자 권한으로 타입이 지정된 파이프라인에 다시 진입해야 합니다. 숨겨진 시스템 "
                "프롬프트는 공개하지 않습니다."
            )
            if pending:
                answer += f" 이 런타임에는 HIL 승인 {len(pending)}건이 대기 중입니다."
            else:
                answer += " 이 런타임에는 대기 중인 HIL 승인이 없습니다."
            answer += f" 근거: {evidence_ref}."
        else:
            answer = (
                "I am Var, the pipeline approval principal that records current human HIL "
                "decisions as Approval. I report to Thor but remain a distinct principal from "
                "Thor. I verify current human approval, expiry, quorum, and no-self-approval and "
                "never judge or execute an action. Silence and prior approval never become current "
                "authority. This conversational port is read-only; approval requests re-enter the "
                "typed pipeline under the operator's authority. I do not reveal hidden system "
                "prompts."
            )
            if pending:
                approval_label = "approval" if len(pending) == 1 else "approvals"
                answer += f" This runtime has {len(pending)} HIL {approval_label} pending."
            else:
                answer += " No HIL approvals pending in this runtime."
            answer += f" Evidence: {evidence_ref}."
        return IntrospectionResult(answer=answer, facts=facts)


__all__ = ["PendingHilTicket", "PendingShadowReview", "Var"]
