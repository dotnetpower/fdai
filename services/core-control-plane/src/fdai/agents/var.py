from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable, Mapping
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from fdai.agents._framework.action_run_identity import validate_action_run_identity
from fdai.agents._framework.action_semantics import ActionSemanticsCatalog, quorum_for
from fdai.agents._framework.adapters import (
    AdminCard,
    AdminNotificationAdapter,
    InMemoryAdminChannel,
)
from fdai.agents._framework.assignment_workflow import AssignmentReviewMixin
from fdai.agents._framework.base import Agent
from fdai.agents._framework.bounded import BoundedLruDict, BoundedLruSet
from fdai.agents._framework.bus import PantheonBus
from fdai.agents._framework.introspection import IntrospectionResult
from fdai.agents._framework.pantheon import _VAR
from fdai.agents._framework.producer_auth import require_topic_owner
from fdai.agents._framework.thor_dispatch_validation import bounded_params
from fdai.agents._framework.var_admin import deliver_admin_card as _deliver_admin_card
from fdai.agents._framework.var_decisions import (
    ApprovalDecisionState,
    TestContextReviewMixin,
    VarDecisionJournal,
    approval_for_ticket,
    final_approval_record,
)
from fdai.agents._framework.var_development_authority import (
    DevelopmentOwnerAuthorizer,
    VarDevelopmentAuthorityMixin,
)
from fdai.agents._framework.var_document_hil import ingest_document_hil
from fdai.agents._framework.var_final_approval import (
    claim_approval_publication as _claim_approval_publication,
)
from fdai.agents._framework.var_final_approval import (
    release_approval_publication_claim as _release_approval_publication_claim,
)
from fdai.agents._framework.var_final_approval import (
    validate_final_record,
)
from fdai.agents._framework.var_health import health as _var_health
from fdai.agents._framework.var_introspection import evidence_available as _var_evidence_available
from fdai.agents._framework.var_introspection import introspect_var as _introspect_var
from fdai.agents._framework.var_pending_durability import (
    PENDING_TICKET_PREFIX,
    SHADOW_REVIEW_PREFIX,
    checkpoint_pending_ticket,
    checkpoint_shadow_review,
    load_pending_ticket,
    mark_pending_ticket_closed_by_identity,
    shadow_review_from_state,
)
from fdai.agents._framework.var_shadow_review import RefCountedAsyncLock, decide_shadow_review_once
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
from fdai.shared.contracts.models import FullAuthorityDevelopmentProfile
from fdai.shared.providers.development_authority import DevelopmentAuthorityBindingSource
from fdai.shared.providers.state_store import StateStore

ApproverAuthorizer = Callable[[str, str], bool | Awaitable[bool]]


class Var(VarDevelopmentAuthorityMixin, TestContextReviewMixin, AssignmentReviewMixin, Agent):
    _MAX_PENDING = 5_000
    _MAX_CARDS = 5_000

    def __init__(
        self,
        *,
        bus: PantheonBus | None = None,
        admin_channel: AdminNotificationAdapter | None = None,
        approver_authorizer: ApproverAuthorizer | None = None,
        state_store: StateStore | None = None,
        development_profile: FullAuthorityDevelopmentProfile | None = None,
        development_executor_principal: str | None = None,
        development_owner_authorizer: DevelopmentOwnerAuthorizer | None = None,
        development_binding_source: DevelopmentAuthorityBindingSource | None = None,
        action_semantics: ActionSemanticsCatalog | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        super().__init__(spec=_VAR)
        self.bus = bus
        self._clock = clock or (lambda: datetime.now(tz=UTC))
        self.admin_channel = admin_channel or InMemoryAdminChannel()
        self._approver_authorizer = approver_authorizer
        self._initialize_development_authority(
            profile=development_profile,
            executor_principal=development_executor_principal,
            owner_authorizer=development_owner_authorizer,
            binding_source=development_binding_source,
            clock=clock,
        )
        self._state_store = state_store
        self._decision_journal = (
            VarDecisionJournal(
                state_store,
                state_prefix=APPROVAL_STATE_PREFIX,
                clock=self._clock,
            )
            if state_store is not None
            else None
        )
        self._decision_locks: dict[str, RefCountedAsyncLock] = {}
        self._shadow_review_locks: dict[str, RefCountedAsyncLock] = {}
        self._pending: dict[str, PendingHilTicket] = {}
        self.initialize_assignment_review()
        self._pending_shadow_reviews: dict[str, PendingShadowReview] = {}
        self._last_cards: dict[tuple[str, str], AdminCard] = {}
        self._blocked_attempts: BoundedLruSet[str] = BoundedLruSet(self._MAX_PENDING)
        self._final_approvals: BoundedLruDict[tuple[str, str], dict[str, Any]] = BoundedLruDict(
            self._MAX_PENDING
        )
        self._published_approvals: BoundedLruSet[tuple[str, str]] = BoundedLruSet(self._MAX_PENDING)
        self._action_correlation_identities: BoundedLruDict[str, str] = BoundedLruDict(
            self._MAX_PENDING
        )
        self._action_semantics = action_semantics

    def bind_bus(self, bus: PantheonBus) -> None:
        self.bus = bus

    def bind_action_semantics(self, action_semantics: ActionSemanticsCatalog | None) -> None:
        self._action_semantics = action_semantics

    async def on_typed_message(self, topic: str, payload: dict[str, Any]) -> None:
        if topic in {"object.action-run", "object.audit-entry", "object.event"}:
            if require_topic_owner(self, topic, payload, behavior="typed_message:rejected_owner"):
                return
        if await self._test_context_review_message(topic, payload, self.record_behavior):
            return
        if await self._assignment_review_message(topic, payload):
            return
        if topic == "object.audit-entry":
            await ingest_document_hil(self, payload)
            await self._ingest_shadow_review(payload)
            return
        if topic != "object.action-run":
            self.record_behavior("typed_message:ignored")
            return
        state = str(payload.get("state") or "")
        if state != "hil_pending":
            self.record_behavior("action_run:ignored_non_hil")
            return
        correlation = str(payload.get("correlation_id", ""))
        if not correlation:
            self.record_behavior("ticket_invalid_correlation")
            return
        try:
            action_run_identity = validate_action_run_identity(payload)
        except ValueError:
            self.record_behavior("ticket_invalid_action_identity")
            return
        action_type = str(payload.get("action_type") or "")
        if not action_type:
            self.record_behavior("ticket_invalid_action_type")
            return
        if not await claim_action_correlation_identity(
            self._state_store,
            self._action_correlation_identities,
            correlation,
            action_run_identity,
        ):
            self.record_behavior("ticket_identity_conflict")
            return
        raw_quorum = payload.get("quorum_required", 1)
        if isinstance(raw_quorum, bool):
            self.record_behavior("ticket_invalid_quorum")
            return
        try:
            payload_quorum = max(1, int(raw_quorum))
        except (TypeError, ValueError):
            self.record_behavior("ticket_invalid_quorum")
            return
        try:
            original_quorum, effective_quorum, development_authority = (
                self._admit_development_ticket(payload, quorum=payload_quorum)
            )
        except ValueError:
            self.record_behavior("ticket_invalid_development_authority")
            return
        required_quorum = quorum_for(action_type, self._action_semantics)
        if development_authority is None:
            if payload_quorum < required_quorum:
                self.record_behavior("ticket_quorum_restored")
            quorum = max(payload_quorum, required_quorum)
            original_quorum = quorum
            effective_quorum = quorum
        elif original_quorum < required_quorum:
            self.record_behavior("ticket_invalid_development_authority")
            return
        else:
            quorum = effective_quorum
        params = bounded_params(payload.get("params"))
        if params is None:
            self.record_behavior("ticket_invalid_params")
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
                self.record_behavior("ticket_duplicate")
                return
            self.record_behavior("ticket_identity_conflict")
            return
        ticket = PendingHilTicket(
            correlation_id=correlation,
            action_id=raw_action_id,
            action_type=action_type,
            resource_id=raw_resource_id,
            quorum_required=quorum,
            original_quorum_required=original_quorum,
            effective_quorum_required=effective_quorum,
            development_authority=development_authority,
            action_run_identity=action_run_identity,
            initiator_principal=raw_initiator.strip() if raw_initiator else None,
            idempotency_key=raw_idempotency_key or "",
            rollback_contract=raw_rollback_contract,
            params=params,
            decision_case=(
                dict(payload["decision_case"])
                if isinstance(payload.get("decision_case"), dict)
                else None
            ),
        )
        await checkpoint_pending_ticket(self._state_store, ticket)
        self._pending[correlation] = ticket
        self.record_behavior("ticket_pending")
        if self._state_store is None:
            _evict_oldest_ticket(self._pending, self._MAX_PENDING, keep=correlation)

    async def _ingest_shadow_review(self, payload: dict[str, Any]) -> None:
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
        review = PendingShadowReview(
            correlation_id=correlation,
            action_type=action_type,
            observed_at=observed_at,
            policy_escape=policy_escape,
            initiator_principal=initiator.strip() if initiator else None,
        )
        await checkpoint_shadow_review(self._state_store, review)
        self._pending_shadow_reviews[correlation] = review
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
        lock_entry = self._decision_locks.get(correlation_id)
        if lock_entry is None:
            lock_entry = RefCountedAsyncLock(asyncio.Lock())
            self._decision_locks[correlation_id] = lock_entry
        lock_entry.ref_count += 1
        try:
            async with lock_entry.lock:
                return await self._record_decision_locked(
                    correlation_id,
                    approver=approver,
                    decision=decision,
                )
        finally:
            lock_entry.ref_count -= 1
            if lock_entry.ref_count == 0 and self._decision_locks.get(correlation_id) is lock_entry:
                del self._decision_locks[correlation_id]

    async def _record_decision_locked(
        self,
        correlation_id: str,
        *,
        approver: str,
        decision: str,
    ) -> dict[str, Any] | None:
        ticket = self._pending.get(correlation_id)
        if ticket is None:
            ticket = await load_pending_ticket(self._state_store, correlation_id)
            if ticket is not None:
                self._pending[correlation_id] = ticket
        if ticket is None:
            self.record_behavior("decision:missing_ticket")
            return {"state": "rejected", "reason": "missing_ticket"}
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
        development_owner_eligible = await self._development_owner_eligible(
            ticket,
            approver=approver_norm,
            correlation_id=correlation_id,
        )
        if initiator_norm and approver_norm == initiator_norm and not development_owner_eligible:
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
        await self.rehydrate_pending_work()
        finalized = 0
        journal = self._decision_journal
        if journal is not None:
            decisions = await journal.pending_finalizations(limit=self._MAX_PENDING)
            for decision in decisions:
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
        for pending_approval in await self._pending_final_approvals_page(limit=self._MAX_PENDING):
            await self._publish_final_approval(pending_approval)
            published += 1
        return finalized, published

    async def rehydrate_pending_work(self) -> tuple[int, int]:
        if self._state_store is None:
            return 0, 0
        tickets = await self._state_store.read_state_page(
            PENDING_TICKET_PREFIX,
            limit=self._MAX_PENDING,
            field="status",
            value="pending",
        )
        restored_tickets = 0
        for stored in tickets[0]:
            identity = stored.get("ticket_identity")
            if not isinstance(identity, Mapping):
                raise RuntimeError("durable pending HIL ticket is malformed")
            ticket = _ticket_from_identity(identity)
            if (
                await self._load_final_approval(ticket.correlation_id, ticket.action_run_identity)
                is not None
            ):
                await mark_pending_ticket_closed_by_identity(
                    self._state_store,
                    ticket.correlation_id,
                    ticket.action_run_identity,
                )
                continue
            self._pending[ticket.correlation_id] = ticket
            if ticket.action_run_identity is not None:
                self._action_correlation_identities.set(
                    ticket.correlation_id,
                    ticket.action_run_identity,
                )
            restored_tickets += 1
        reviews = await self._state_store.read_state_page(
            SHADOW_REVIEW_PREFIX,
            limit=self._MAX_PENDING,
            field="status",
            value="pending",
        )
        restored_reviews = 0
        for stored in reviews[0]:
            review = shadow_review_from_state(stored)
            self._pending_shadow_reviews[review.correlation_id] = review
            restored_reviews += 1
        return restored_tickets, restored_reviews

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
        approval, _published = validate_final_record(stored, correlation_id)
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
                stored_approval, _published = validate_final_record(stored, correlation_id)
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
            await mark_pending_ticket_closed_by_identity(
                self._state_store,
                correlation_id,
                action_run_identity,
            )
            return None
        if self.bus is None:
            self.record_behavior("publication:unavailable")
            if self._state_store is not None:
                _remove_pending_ticket(
                    self._pending,
                    correlation_id,
                    action_run_identity,
                )
                await mark_pending_ticket_closed_by_identity(
                    self._state_store,
                    correlation_id,
                    action_run_identity,
                )
            return deepcopy(approval)
        if not await _claim_approval_publication(
            store=self._state_store,
            approval=approval,
            published_cache=self._published_approvals,
        ):
            return None
        publish_task = asyncio.create_task(
            self.bus.publish("Var", "object.approval", deepcopy(approval))
        )
        try:
            await asyncio.shield(publish_task)
            await asyncio.shield(self._mark_approval_published(approval))
        except asyncio.CancelledError:
            await asyncio.shield(publish_task)
            await asyncio.shield(self._mark_approval_published(approval))
            raise
        except Exception:
            await _release_approval_publication_claim(
                store=self._state_store,
                approval=approval,
            )
            raise
        _remove_pending_ticket(
            self._pending,
            correlation_id,
            action_run_identity,
        )
        await mark_pending_ticket_closed_by_identity(
            self._state_store,
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
        _approval, published = validate_final_record(stored, correlation_id)
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
                stored_approval, published = validate_final_record(stored, correlation_id)
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
        approvals = await self._pending_final_approvals_page(limit=1)
        return approvals[0] if approvals else None

    async def _pending_final_approvals_page(self, *, limit: int) -> list[dict[str, Any]]:
        if self._state_store is None:
            return []
        rows, _total = await self._state_store.read_state_page(
            f"{APPROVAL_STATE_PREFIX}/",
            limit=limit,
            field="publication_status",
            value="pending",
        )
        approvals: list[dict[str, Any]] = []
        for stored in reversed(rows):
            correlation_id = str(stored.get("correlation_id") or "")
            approval, _published = validate_final_record(stored, correlation_id)
            approvals.append(approval)
        return approvals

    async def decide_shadow_review(
        self,
        correlation_id: str,
        *,
        reviewer: str,
        agreed: bool,
    ) -> dict[str, Any] | None:
        """Publish one real human review without manufacturing another sample."""

        return await decide_shadow_review_once(
            pending=self._pending_shadow_reviews,
            locks=self._shadow_review_locks,
            state_store=self._state_store,
            bus=self.bus,
            record_behavior=self.record_behavior,
            record_blocked_attempt=self._record_blocked_attempt,
            correlation_id=correlation_id,
            reviewer=reviewer,
            agreed=agreed,
        )

    def pending_tickets(self) -> tuple[PendingHilTicket, ...]:
        return tuple(self._pending.values())

    def pending_shadow_reviews(self) -> tuple[PendingShadowReview, ...]:
        return tuple(self._pending_shadow_reviews.values())

    def _record_blocked_attempt(self, key: str, correlation_id: str, approver: str) -> None:
        _record_blocked_attempt_once(self, key, correlation_id, approver)

    deliver_admin_card = _deliver_admin_card
    health = _var_health

    def conversation_evidence_available(self, context: dict[str, Any]) -> bool:
        return _var_evidence_available(self)

    async def introspect(self, question: str, context: dict[str, Any]) -> IntrospectionResult:
        return await _introspect_var(self, question, context)


__all__ = ["PendingHilTicket", "PendingShadowReview", "Var"]
