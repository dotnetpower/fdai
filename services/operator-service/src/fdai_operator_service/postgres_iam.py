"""PostgreSQL projections and proposal-only outboxes for the Operator IAM family."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from typing import Any, cast

from fdai_service_contracts import ModelBindingPolicy
from pydantic import ValidationError

from fdai_operator_service.families.iam.contracts import (
    AccessGrantDecisionCommand,
    AccessGrantDecisionResult,
    AccessGrantRecord,
    AccessGrantSnapshot,
    AccessGrantSnapshotQuery,
    AccessRequestCommand,
    AccessRequestQuery,
    AccessReviewCommand,
    AssignmentCaseQuery,
    AssignmentCreateCommand,
    AssignmentTransitionCommand,
    ConfigurationReviewCommand,
    DirectoryIdentity,
    DirectoryStatus,
    HandoverGoalCommand,
    HilApprovalDecision,
    HilDecisionCommand,
    HilDecisionOutboxRequest,
    HilDecisionReceipt,
    HilPendingItem,
    IamPrincipal,
    JsonMapping,
    KillSwitchCommand,
    ModelBindingDraftCommand,
    ModelBindingRequestCommand,
    ModelPreferenceCommand,
    RuntimeSettingsCommand,
    WebSearchSettingsCommand,
)
from fdai_operator_service.families.iam.errors import (
    IamConflictError,
    IamFamilyError,
    IamNotFoundError,
    IamPermissionError,
    IamUnavailableError,
)
from fdai_operator_service.families.iam.hil_callback_audit import HilCallbackAuditRecord
from fdai_operator_service.families.iam.hil_callback_context import HilCallbackContext
from fdai_operator_service.families.iam.hil_decision_outbox import (
    hil_decision_delivery_key,
)
from fdai_operator_service.families.iam.hil_decision_outbox import (
    outbox_payload as _outbox_payload,
)
from fdai_operator_service.postgres_family_store import (
    PostgresFamilyStore,
    PostgresFamilyStoreUnavailable,
    PostgresProposalConflict,
    StoredProposal,
    StoredStatePage,
    StoredStateRecord,
)

_HIL_PARK_PREFIX = "hil_park:"
_HIL_DECISION_PREFIX = "operator-hil-decision:"
_HIL_CALLBACK_AUDIT_PREFIX = "operator-hil-callback-audit:"
_ACCESS_GRANT_PREFIX = "execution-authorization:grant-request:"
_ACCESS_GRANT_SCAN_LIMIT = 1_000
_IAM_PROPOSAL_PREFIX = "operator-proposal:iam:"
_IAM_PROPOSAL_SCAN_LIMIT = 1_000
_CANONICAL_GRANT_ID = re.compile(r"^[A-Za-z0-9._:-]{1,256}$")
_SCOPE_REF = re.compile(r"^scope://[\x20-\x7E]{1,504}$")
_MODEL_BINDING_POLICY_KEY = "operator-model-binding-policy:current"
_RUNTIME_SETTINGS_POLICY_KEY = "runtime-settings:policy"


@dataclass(frozen=True, slots=True)
class PostgresIamAdapters:
    """Implement IAM read ports and inert request outboxes over PostgreSQL."""

    store: PostgresFamilyStore

    async def snapshot(self, query: AccessGrantSnapshotQuery) -> AccessGrantSnapshot:
        """Read the reviewer-scoped access-grant snapshot for SSE replay."""
        page = await self._pending_grant_page()
        if page.truncated:
            raise IamUnavailableError("access-grant review coverage cannot be proven complete")
        records = page.records
        generated_at = datetime.now(tz=UTC)
        # A decided request leaves the pending view, so the cursor is carried forward
        # rather than allowed to regress with the page it no longer contains.
        sequence = max(_snapshot_sequence(records), query.after_sequence or 0)
        reviewer = query.reviewer_ref.casefold()
        reviewer_roles = {role.casefold() for role in query.reviewer_roles}
        visible = [
            _access_grant(record.value)
            for record in records
            if reviewer_roles and _reviewable(record.value, reviewer, reviewer_roles, generated_at)
        ]
        # Oldest request first, so a busy queue cannot starve the longest-waiting approval.
        visible.sort(key=lambda item: (item.requested_at, item.request_id))
        return AccessGrantSnapshot(
            sequence=sequence,
            generated_at=generated_at,
            requests=tuple(visible[: query.limit]),
        )

    async def decide(self, command: AccessGrantDecisionCommand) -> AccessGrantDecisionResult:
        """Persist a revision-fenced access decision without applying permission."""
        record = await self._state(f"{_ACCESS_GRANT_PREFIX}{command.request_id}")
        if record is None:
            raise IamNotFoundError("access grant request does not exist")
        if str(record.get("status") or "") != "pending":
            raise IamConflictError("access grant request is not pending")
        # Deciding is bound to the same predicate as seeing, so the two cannot drift apart.
        if not _reviewable(
            record,
            command.reviewer_ref.casefold(),
            {role.casefold() for role in command.reviewer_roles},
            command.decided_at,
        ):
            raise IamPermissionError("reviewer is not eligible to decide this access grant")
        quorum = _integer(record, "quorum")
        approved_by = record.get("approved_by", [])
        if quorum < 1 or not isinstance(approved_by, list) or len(approved_by) > quorum:
            raise IamUnavailableError("access-grant approval policy is malformed")
        await self._proposal("access-grants.decide", command, _decision_key(command))
        return AccessGrantDecisionResult(
            request_id=command.request_id,
            status="pending",
            revision=_integer(record, "revision"),
            approved_count=len(approved_by),
            quorum=quorum,
            reviewed_at=command.decided_at,
        )

    async def list_request_page(
        self,
        query: AccessRequestQuery,
    ) -> tuple[Sequence[JsonMapping], int]:
        """Project durable access proposals and independent review decisions."""
        items = await self._access_requests()
        if not _can_manage_group_membership(query.principal):
            requester = query.principal.oid.casefold()
            items = [
                item
                for item in items
                if str(item.get("requester_oid") or "").casefold() == requester
            ]
        total = len(items)
        return items[query.offset : query.offset + query.limit], total

    async def submit(
        self,
        command: AccessRequestCommand | HandoverGoalCommand | KillSwitchCommand,
    ) -> JsonMapping:
        """Persist one IAM, handover, or kill-switch request as an inert proposal."""
        operation = _submit_operation(command)
        stored = await self._proposal(operation, command, _idempotency_key(command))
        if isinstance(command, AccessRequestCommand):
            return _access_request_from_proposal(stored.record)
        return {
            "request_id": stored.proposal_id,
            "proposal_id": stored.proposal_id,
            "status": "pending",
            "dispatch_status": "pending",
            "duplicate": stored.duplicate,
        }

    async def review(
        self,
        command: AccessReviewCommand | AssignmentTransitionCommand,
    ) -> JsonMapping:
        """Persist a review request without changing identity-provider or ownership state."""
        if isinstance(command, AccessReviewCommand):
            request = next(
                (
                    item
                    for item in await self._access_requests()
                    if item.get("request_id") == command.request_id
                ),
                None,
            )
            if request is None:
                raise IamNotFoundError("access request does not exist")
            if (
                str(request.get("requester_oid") or "").casefold()
                == command.principal.oid.casefold()
            ):
                raise IamPermissionError("requester MUST NOT approve their own request")
            if request.get("status") != "pending":
                raise IamConflictError("access request already has a decision")
        else:
            assignment = await self.get_case(command.case_id)
            if assignment.get("state") != "pending_review":
                raise IamConflictError("assignment case is not pending review")
            if assignment.get("revision") != command.expected_revision:
                raise IamConflictError("assignment case revision is stale")
            intent = assignment.get("intent")
            if not isinstance(intent, Mapping):
                raise IamUnavailableError("assignment case intent is malformed")
            reviewer = command.principal.oid.casefold()
            subject = intent.get("subject")
            subject_id = subject.get("subject_id") if isinstance(subject, Mapping) else None
            if reviewer in {
                str(intent.get("requester_ref") or "").casefold(),
                str(subject_id or "").casefold(),
            }:
                raise IamPermissionError(
                    "assignment requester and target MUST NOT review their own case"
                )
            if any(
                str(item.get("reviewer_ref") or "").casefold() == reviewer
                for item in assignment.get("reviews", [])
                if isinstance(item, Mapping)
            ):
                raise IamConflictError("assignment reviewer already recorded a decision")
        operation = (
            "access-requests.review"
            if isinstance(command, AccessReviewCommand)
            else "assignments.review"
        )
        stored = await self._proposal(operation, command, _idempotency_key(command))
        if isinstance(command, AccessReviewCommand):
            if request is None:
                raise IamUnavailableError("access request review lost its request projection")
            return _reviewed_access_request(request, stored.record)
        return await self.get_case(command.case_id)

    async def search(self, query: str, *, limit: int) -> Sequence[DirectoryIdentity]:
        """Search only the materialized human-directory projection."""
        identities = await self._directory()
        needle = query.casefold().strip()
        return tuple(
            item
            for item in identities
            if not needle
            or needle in item.username.casefold()
            or needle in (item.display_name or "").casefold()
        )[:limit]

    async def list_role_roster(
        self,
        role_group_ids: Mapping[str, str],
        *,
        limit: int,
    ) -> Sequence[DirectoryIdentity]:
        """Read the materialized role roster without calling the identity provider."""
        del role_group_ids
        return (await self._directory())[:limit]

    async def get_by_subject_id(self, subject_id: str) -> DirectoryIdentity | None:
        """Resolve one exact materialized human identity."""
        return next(
            (item for item in await self._directory() if item.subject_id == subject_id),
            None,
        )

    async def directory_status(self) -> DirectoryStatus:
        """Return materialized directory availability without inferred freshness."""
        await self._projection("directory")
        return DirectoryStatus(
            source="materialized-projection",
            availability="available",
        )

    async def _access_requests(self) -> list[dict[str, object]]:
        page = await self._iam_proposal_page()
        reviews: dict[str, Mapping[str, object]] = {}
        requests: list[dict[str, object]] = []
        for record in page.records:
            operation = record.value.get("operation")
            if operation == "access-requests.review":
                payload = record.value.get("payload")
                if isinstance(payload, Mapping):
                    request_id = payload.get("request_id")
                    if isinstance(request_id, str):
                        reviews[request_id] = record.value
            elif operation == "access-requests.submit":
                requests.append(_access_request_from_proposal(record.value))
        requests.sort(
            key=lambda item: (str(item.get("requested_at") or ""), str(item["request_id"])),
            reverse=True,
        )
        return [
            _reviewed_access_request(item, reviews[str(item["request_id"])])
            if str(item["request_id"]) in reviews
            else item
            for item in requests
        ]

    async def _iam_proposal_page(self) -> StoredStatePage:
        try:
            page = await self.store.read_state_page(
                prefix=_IAM_PROPOSAL_PREFIX,
                limit=_IAM_PROPOSAL_SCAN_LIMIT,
            )
        except PostgresFamilyStoreUnavailable as exc:
            raise IamUnavailableError(str(exc)) from exc
        if page.truncated:
            raise IamUnavailableError("IAM proposal coverage is incomplete")
        return page

    async def list_case_page(
        self,
        query: AssignmentCaseQuery,
    ) -> tuple[Sequence[JsonMapping], int]:
        """Project bounded assignment cases from durable proposals."""
        items = await self._assignment_cases()
        return items[query.offset : query.offset + query.limit], len(items)

    async def get_case(self, case_id: str) -> JsonMapping:
        """Read one exact assignment case from durable proposals."""
        item = next(
            (entry for entry in await self._assignment_cases() if entry.get("case_id") == case_id),
            None,
        )
        if item is None:
            raise IamNotFoundError(f"assignment case {case_id!r} was not found")
        return item

    async def create_case(self, command: AssignmentCreateCommand) -> JsonMapping:
        """Persist an assignment case intent without applying ownership or IAM effects."""
        stored = await self._proposal("assignments.create", command, command.idempotency_key)
        return _assignment_case_from_proposal(stored.record)

    async def submit_for_review(self, command: AssignmentTransitionCommand) -> JsonMapping:
        """Persist an assignment submission request for independent review."""
        current = await self.get_case(command.case_id)
        if current.get("state") != "draft":
            return current
        if current.get("revision") != command.expected_revision:
            raise IamConflictError("assignment case revision is stale")
        await self._proposal("assignments.submit", command, _idempotency_key(command))
        return await self.get_case(command.case_id)

    async def assignment_projection(self, query: AssignmentCaseQuery) -> JsonMapping:
        """Join durable cases into an explicit observation-only projection."""
        cases = await self._assignment_cases()
        page = cases[query.offset : query.offset + query.limit]
        return {
            "items": [_assignment_projection_item(item) for item in page],
            "total": len(cases),
            "next_cursor": (
                query.offset + len(page) if query.offset + len(page) < len(cases) else None
            ),
            "directory_availability": "available",
            "case_projection_truncated": False,
        }

    async def _assignment_cases(self) -> list[dict[str, object]]:
        page = await self._iam_proposal_page()
        submissions: dict[str, Mapping[str, object]] = {}
        reviews: dict[str, list[Mapping[str, object]]] = {}
        cases: list[dict[str, object]] = []
        for record in page.records:
            operation = record.value.get("operation")
            payload = record.value.get("payload")
            if not isinstance(payload, Mapping):
                continue
            case_id = payload.get("case_id")
            if operation == "assignments.create":
                cases.append(_assignment_case_from_proposal(record.value))
            elif operation == "assignments.submit" and isinstance(case_id, str):
                submissions[case_id] = record.value
            elif operation == "assignments.review" and isinstance(case_id, str):
                reviews.setdefault(case_id, []).append(record.value)
        projected = [
            _project_assignment_case(
                item,
                submitted=submissions.get(str(item["case_id"])),
                reviews=reviews.get(str(item["case_id"]), []),
            )
            for item in cases
        ]
        projected.sort(key=lambda item: str(item["case_id"]), reverse=True)
        return projected

    async def invitation_for_session(
        self,
        *,
        subject_ref: str,
        session_id: str,
    ) -> JsonMapping | None:
        """Read one matching handover invitation from the materialized projection."""
        payload = await self._projection("handover.invitations")
        return next(
            (
                item
                for item in _mapping_items(payload)
                if item.get("subject_ref") == subject_ref and item.get("session_id") == session_id
            ),
            None,
        )

    async def get_goal(self, goal_id: str) -> JsonMapping:
        """Read one exact handover goal from the materialized projection."""
        payload = await self._projection("handover.goals")
        item = next(
            (entry for entry in _mapping_items(payload) if entry.get("goal_id") == goal_id),
            None,
        )
        if item is None:
            raise IamNotFoundError(f"handover goal {goal_id!r} was not found")
        return item

    async def projection(
        self,
        principal_id: str | None = None,
        *,
        can_manage_web_search: bool = False,
        can_manage_model_bindings: bool = False,
        refresh_model_catalog: bool = False,
        can_manage: bool = False,
    ) -> JsonMapping:
        """Read model or runtime settings without mutating their policy source."""
        del refresh_model_catalog
        operation = "model-settings" if principal_id is not None else "runtime-settings"
        payload = await self._projection(operation)
        if principal_id is not None:
            web_search = payload.get("web_search")
            if not isinstance(web_search, Mapping):
                raise IamUnavailableError("model settings projection has no web_search object")
            binding_policy = await self._state(_MODEL_BINDING_POLICY_KEY)
            environment = str(payload.get("environment") or "unspecified")
            if binding_policy is not None and binding_policy.get("environment") != environment:
                raise IamUnavailableError(
                    "model binding policy environment does not match the Settings projection"
                )
            return {
                **payload,
                "web_search": {**web_search, "can_manage": can_manage_web_search},
                "binding_policy": (
                    _binding_policy_projection(
                        binding_policy,
                        can_manage=can_manage_model_bindings,
                    )
                    if binding_policy is not None
                    else {
                        "environment": environment,
                        "revision": 0,
                        "state": "not-configured",
                        "policy": None,
                        "policy_digest": None,
                        "can_manage": can_manage_model_bindings,
                        "execution_authority": False,
                    }
                ),
            }
        runtime_policy = await self._state(_RUNTIME_SETTINGS_POLICY_KEY)
        return {
            **_runtime_settings_projection(payload, runtime_policy),
            "can_manage": can_manage,
        }

    async def set_preference(self, command: ModelPreferenceCommand) -> None:
        """Queue a revisioned narrator preference proposal."""
        await self._proposal("model-settings.preference", command, _idempotency_key(command))

    async def set_web_search_settings(self, command: WebSearchSettingsCommand) -> None:
        """Queue a revisioned web-search policy proposal."""
        await self._proposal("model-settings.web-search", command, _idempotency_key(command))

    async def save_binding_policy(self, command: ModelBindingDraftCommand) -> JsonMapping:
        """Atomically store one revisioned draft and its authority-free proposal receipt."""
        try:
            policy = ModelBindingPolicy.model_validate(command.policy)
        except ValidationError as exc:
            raise IamConflictError("model binding policy is invalid") from exc
        if policy.digest() != command.policy_digest:
            raise IamConflictError("model binding policy digest does not match its content")
        if policy.revision != command.expected_revision + 1:
            raise IamConflictError("model binding policy revision conflict")
        projection = await self._projection("model-settings")
        deployment_environment = projection.get("environment")
        if not isinstance(deployment_environment, str) or not deployment_environment:
            raise IamUnavailableError("model Settings projection has no deployment environment")
        if policy.environment != deployment_environment:
            raise IamConflictError(
                "model binding policy environment does not match this deployment"
            )
        state: dict[str, object] = {
            "environment": policy.environment,
            "revision": policy.revision,
            "state": "draft",
            "policy": policy.model_dump(mode="json", exclude_none=True),
            "policy_digest": policy.digest(),
            "execution_authority": False,
            "activation_boundary": "protected-plan-only",
        }
        try:
            stored = await self.store.append_revisioned_proposal(
                family="iam",
                operation="model-settings.binding-policy.draft",
                principal_id=command.actor_id,
                idempotency_key=command.idempotency_key,
                payload=_command_payload(command),
                state_key=_MODEL_BINDING_POLICY_KEY,
                state_value=state,
                expected_revision=command.expected_revision,
            )
        except PostgresProposalConflict as exc:
            raise IamConflictError(str(exc)) from exc
        except PostgresFamilyStoreUnavailable as exc:
            raise IamUnavailableError(str(exc)) from exc
        return _binding_receipt(stored, state="draft", command=command)

    async def request_binding_assessment(self, command: ModelBindingRequestCommand) -> JsonMapping:
        """Queue a protected provider assessment for one exact stored policy."""
        return await self._request_binding_operation(command, operation="assessment")

    async def request_binding_plan(self, command: ModelBindingRequestCommand) -> JsonMapping:
        """Queue a protected plan only when the draft binds the active artifact digest."""
        return await self._request_binding_operation(command, operation="plan")

    async def _request_binding_operation(
        self,
        command: ModelBindingRequestCommand,
        *,
        operation: str,
    ) -> JsonMapping:
        state = await self._state(_MODEL_BINDING_POLICY_KEY)
        if state is None:
            raise IamNotFoundError("model binding policy draft does not exist")
        if (
            state.get("environment") != command.environment
            or state.get("revision") != command.policy_revision
            or state.get("policy_digest") != command.policy_digest
        ):
            raise IamConflictError("model binding policy request does not match the current draft")
        policy = _stored_binding_policy(state)
        if operation == "plan" and policy.expected_active_digest is None:
            raise IamConflictError(
                "model binding plan requires an expected active resolved-models digest"
            )
        if operation == "plan":
            projection = await self._projection("model-settings")
            resolved_metadata = projection.get("resolved_metadata")
            active_digest = (
                resolved_metadata.get("digest") if isinstance(resolved_metadata, Mapping) else None
            )
            if not isinstance(active_digest, str):
                raise IamUnavailableError(
                    "model Settings projection has no active resolved-models digest"
                )
            if policy.expected_active_digest != active_digest:
                raise IamConflictError(
                    "model binding plan does not match the active resolved-models digest"
                )
        stored = await self._proposal(
            f"model-settings.binding-policy.{operation}",
            command,
            command.idempotency_key,
        )
        return _binding_receipt(
            stored,
            state=f"{operation}-requested",
            command=command,
        )

    async def update(self, command: RuntimeSettingsCommand) -> None:
        """Atomically record a proposal and the revision-fenced runtime override."""

        projection = await self._projection("runtime-settings")
        current = await self._state(_RUNTIME_SETTINGS_POLICY_KEY)
        try:
            state = _runtime_settings_state(projection, current, command)
            await self.store.append_revisioned_proposal(
                family="iam",
                operation="runtime-settings.update",
                principal_id=command.actor_id,
                idempotency_key=_idempotency_key(command),
                payload=_command_payload(command),
                state_key=_RUNTIME_SETTINGS_POLICY_KEY,
                state_value=state,
                expected_revision=command.expected_revision,
            )
        except PostgresProposalConflict as exc:
            raise IamConflictError(str(exc)) from exc
        except PostgresFamilyStoreUnavailable as exc:
            raise IamUnavailableError(str(exc)) from exc
        except ValueError as exc:
            raise IamFamilyError(str(exc)) from exc

    async def run(self, command: ConfigurationReviewCommand) -> JsonMapping:
        """Queue a configuration-review evidence campaign request."""
        stored = await self._proposal("configuration-review.run", command, command.run_id)
        return {"campaign_id": stored.proposal_id, "state": "pending"}

    async def resume(self, *, principal_id: str) -> JsonMapping:
        """Queue a resume request without running the evidence campaign in-process."""
        stored = await self._proposal(
            "configuration-review.resume",
            {"principal_id": principal_id},
            f"resume:{principal_id}",
        )
        return {"campaign_id": stored.proposal_id, "state": "pending"}

    async def get_pending_by_approval_id(self, approval_id: str) -> HilPendingItem | None:
        """Read one existing risk-gate HIL park record."""
        state = await self._state(f"{_HIL_PARK_PREFIX}{approval_id}")
        if state is None or state.get("status") != "pending":
            return None
        idempotency_key = state.get("idempotency_key")
        if not isinstance(idempotency_key, str) or not idempotency_key:
            raise IamUnavailableError("pending HIL record has no idempotency key")
        raw_metadata = state.get("metadata", {})
        metadata = (
            {str(key): str(value) for key, value in raw_metadata.items()}
            if isinstance(raw_metadata, Mapping)
            else {}
        )
        correlation_id = state.get("correlation_id")
        request_fingerprint = state.get("request_fingerprint")
        approval_context = state.get("approval_context")
        if isinstance(correlation_id, str) and correlation_id:
            metadata.setdefault("correlation_id", correlation_id)
        if isinstance(request_fingerprint, str) and request_fingerprint:
            metadata.setdefault("action_hash", request_fingerprint)
        if isinstance(approval_context, Mapping):
            expires_at = approval_context.get("expires_at")
            if isinstance(expires_at, str) and expires_at:
                metadata.setdefault("expires_at", expires_at)
        return HilPendingItem(
            approval_id=approval_id,
            idempotency_key=idempotency_key,
            submitter_oid=str(state.get("submitter_oid") or ""),
            metadata=metadata,
        )

    async def get_decision_by_approval_id(
        self,
        approval_id: str,
    ) -> HilDecisionReceipt | None:
        """Read a previously recorded idempotent HIL decision."""
        state = await self._state(f"{_HIL_DECISION_PREFIX}{approval_id}")
        return None if state is None else _hil_receipt(state)

    async def record_decision(self, command: HilDecisionCommand) -> HilDecisionReceipt:
        """Record a signed decision and queue no managed-resource effect.

        The durable proposal identity deliberately excludes the observation
        timestamp. A callback that must be re-signed after the replay window
        closed carries a new ``decided_at`` for the same human decision, so
        including it would turn a legitimate proposal-first recovery into an
        idempotency conflict. Identity is instead the stable approval, the
        decision, the normalized actor, and a justification digest, so a
        conflicting decision, actor, or justification is still refused.
        """
        pending = await self._find_state(
            prefix=_HIL_PARK_PREFIX,
            field="idempotency_key",
            value=command.idempotency_key,
        )
        if pending is None:
            raise IamNotFoundError("pending HIL item was not found")
        approval_id = pending.get("approval_id")
        if not isinstance(approval_id, str) or not approval_id:
            raise IamUnavailableError("pending HIL record has no approval id")
        stored = await self._proposal(
            "hil.decision.record",
            _decision_identity(approval_id, command),
            command.idempotency_key,
        )
        receipt = HilDecisionReceipt(
            approval_id=approval_id,
            idempotency_key=command.idempotency_key,
            decision=command.decision,
            approver_oid=command.approver_oid,
            decided_at=command.decided_at,
            receipt_ref=stored.proposal_id,
            justification=command.justification,
        )
        state = _json_mapping(asdict(receipt))
        try:
            created = await self.store.create_state(
                f"{_HIL_DECISION_PREFIX}{approval_id}",
                state,
            )
        except PostgresFamilyStoreUnavailable as exc:
            raise IamUnavailableError("HIL decision receipt store is unavailable") from exc
        if not created:
            existing = await self.get_decision_by_approval_id(approval_id)
            if existing is None:
                raise IamUnavailableError("recorded HIL decision disappeared")
            if (
                existing.idempotency_key != command.idempotency_key
                or existing.decision is not command.decision
                or existing.approver_oid.strip().casefold()
                != command.approver_oid.strip().casefold()
            ):
                raise IamConflictError(
                    "recorded HIL decision conflicts with the concurrent durable receipt"
                )
            return replace(existing, already_recorded=True)
        return receipt

    async def enqueue(self, request: HilDecisionOutboxRequest) -> None:
        """Queue a recorded HIL decision for typed downstream transport.

        The proposal is the durable outbox record. Broker publication happens
        only after this write returns, so a crash between the two leaves a
        replayable ``pending`` record for the lease-fenced drainer.
        """
        await self._proposal(
            "hil.decision.enqueue",
            _outbox_payload(request.receipt),
            hil_decision_delivery_key(request.receipt.idempotency_key),
        )

    async def mark_delivered(self, receipt: HilDecisionReceipt) -> HilDecisionReceipt:
        """Mark only the durable outbox handoff, never the managed-resource effect.

        Delivery is monotonic: a stale caller can never move a delivered
        receipt back to undelivered.
        """
        key = f"{_HIL_DECISION_PREFIX}{receipt.approval_id}"
        current = await self._state(key)
        stored = _hil_receipt(current) if current is not None else receipt
        if stored.delivered:
            return replace(stored, already_recorded=True, delivered=True)
        delivered = replace(stored, delivered=True)
        try:
            await self.store.write_state(key, _json_mapping(asdict(delivered)))
        except PostgresFamilyStoreUnavailable as exc:
            raise IamUnavailableError("HIL delivery receipt store is unavailable") from exc
        return replace(delivered, already_recorded=receipt.already_recorded)

    async def mark_decision_published(self, idempotency_key: str) -> bool:
        """Close the durable outbox record once the broker accepted the decision."""
        try:
            return cast(
                bool,
                await self.store.mark_hil_decision_published(
                    idempotency_key=hil_decision_delivery_key(idempotency_key),
                ),
            )
        except PostgresFamilyStoreUnavailable as exc:
            raise IamUnavailableError("HIL decision outbox store is unavailable") from exc

    async def append_callback_audit(self, record: HilCallbackAuditRecord) -> None:
        """Append one sanitized callback phase as an immutable Operator record."""
        key = f"{_HIL_CALLBACK_AUDIT_PREFIX}{record.callback_id}:{record.phase.value}"
        value = _json_mapping(asdict(record))
        try:
            created = await self.store.create_state(key, value)
            if created:
                return
            existing = await self.store.read_state(key)
        except PostgresFamilyStoreUnavailable as exc:
            raise IamUnavailableError("HIL callback audit store is unavailable") from exc
        if existing is None:
            raise IamUnavailableError("HIL callback audit phase disappeared")
        immutable_fields = set(value) - {"recorded_at"}
        if any(existing.get(field) != value[field] for field in immutable_fields):
            raise IamConflictError("HIL callback audit phase conflicts with its durable record")

    async def get_callback_context(self, approval_id: str) -> HilCallbackContext | None:
        """Read immutable callback identity from a pending or terminal park."""
        state = await self._state(f"{_HIL_PARK_PREFIX}{approval_id}")
        if state is None:
            return None
        approval_context = state.get("approval_context")
        if not isinstance(approval_context, Mapping):
            raise IamUnavailableError("HIL callback context is malformed")
        correlation_id = state.get("correlation_id")
        idempotency_key = state.get("idempotency_key")
        action_hash = state.get("request_fingerprint")
        if not all(
            isinstance(value, str) and value
            for value in (correlation_id, idempotency_key, action_hash)
        ):
            raise IamUnavailableError("HIL callback identity is incomplete")
        expires_at = _datetime(approval_context.get("expires_at"), "expires_at")
        raw_metadata = state.get("metadata")
        metadata = (
            {str(key): str(value) for key, value in raw_metadata.items()}
            if isinstance(raw_metadata, Mapping)
            else {}
        )
        return HilCallbackContext(
            approval_id=approval_id,
            correlation_id=cast(str, correlation_id),
            idempotency_key=cast(str, idempotency_key),
            action_hash=cast(str, action_hash),
            expires_at=expires_at,
            submitter_oid=str(state.get("submitter_oid") or ""),
            metadata=metadata,
        )

    async def _directory(self) -> tuple[DirectoryIdentity, ...]:
        payload = await self._projection("directory")
        return tuple(_directory_identity(item) for item in _mapping_items(payload))

    async def _projection(self, operation: str) -> dict[str, object]:
        try:
            return cast(
                dict[str, object],
                await self.store.read_projection(family="iam", operation=operation),
            )
        except PostgresFamilyStoreUnavailable as exc:
            raise IamUnavailableError(str(exc)) from exc

    async def _proposal(
        self,
        operation: str,
        command: object,
        idempotency_key: str,
    ) -> StoredProposal:
        payload = _command_payload(command)
        try:
            return await self.store.append_proposal(
                family="iam",
                operation=operation,
                principal_id=_principal_id(payload),
                idempotency_key=idempotency_key,
                payload=payload,
            )
        except PostgresProposalConflict as exc:
            raise IamConflictError(str(exc)) from exc
        except PostgresFamilyStoreUnavailable as exc:
            raise IamUnavailableError(str(exc)) from exc

    async def _state(self, key: str) -> dict[str, object] | None:
        try:
            return cast(dict[str, object] | None, await self.store.read_state(key))
        except PostgresFamilyStoreUnavailable as exc:
            raise IamUnavailableError("authoritative IAM state is unavailable") from exc

    async def _find_state(self, *, prefix: str, field: str, value: str) -> dict[str, object] | None:
        try:
            return cast(
                dict[str, object] | None,
                await self.store.find_state(prefix=prefix, field=field, value=value),
            )
        except PostgresFamilyStoreUnavailable as exc:
            raise IamUnavailableError("authoritative IAM state is unavailable") from exc

    async def _pending_grant_page(self) -> StoredStatePage:
        try:
            return await self.store.read_state_page(
                prefix=_ACCESS_GRANT_PREFIX,
                limit=_ACCESS_GRANT_SCAN_LIMIT,
                match_field="status",
                match_value="pending",
            )
        except PostgresFamilyStoreUnavailable as exc:
            raise IamUnavailableError("authoritative IAM state is unavailable") from exc


def _submit_operation(command: object) -> str:
    if isinstance(command, AccessRequestCommand):
        return "access-requests.submit"
    if isinstance(command, HandoverGoalCommand):
        return "handover.submit"
    return "kill-switch.submit"


def _access_request_from_proposal(value: Mapping[str, object]) -> dict[str, object]:
    payload = value.get("payload")
    if not isinstance(payload, Mapping):
        raise IamUnavailableError("stored access-request proposal payload is malformed")
    principal = payload.get("principal")
    if not isinstance(principal, Mapping):
        raise IamUnavailableError("stored access-request principal is malformed")
    proposal_id = value.get("proposal_id")
    accepted_at = value.get("accepted_at")
    required = {
        "idempotency_key": payload.get("idempotency_key"),
        "identity_provider": payload.get("identity_provider"),
        "target_subject_id": payload.get("target_subject_id"),
        "target_username": payload.get("target_username"),
        "operation": payload.get("operation"),
        "role": payload.get("role"),
        "justification": payload.get("justification"),
    }
    if (
        not isinstance(proposal_id, str)
        or not isinstance(accepted_at, str)
        or not isinstance(principal.get("oid"), str)
        or any(not isinstance(item, str) or not item for item in required.values())
    ):
        raise IamUnavailableError("stored access-request proposal is malformed")
    return {
        "request_id": proposal_id,
        **required,
        "requester_oid": principal["oid"],
        "requested_at": accepted_at,
        "status": "pending",
        "reviewed_by": None,
        "reviewed_at": None,
        "review_justification": None,
        "proposal_id": proposal_id,
        "dispatch_status": value.get("dispatch_status", "pending"),
    }


def _assignment_case_from_proposal(value: Mapping[str, object]) -> dict[str, object]:
    payload = value.get("payload")
    proposal_id = value.get("proposal_id")
    if not isinstance(payload, Mapping) or not isinstance(proposal_id, str):
        raise IamUnavailableError("stored assignment proposal is malformed")
    principal = payload.get("principal")
    subject_provider = payload.get("subject_provider")
    subject_id = payload.get("subject_id")
    if not isinstance(principal, Mapping):
        raise IamUnavailableError("stored assignment identity is malformed")
    requester = principal.get("oid")
    requested_role = payload.get("requested_role")
    idempotency_key = payload.get("idempotency_key")
    justification = payload.get("justification")
    duty_bindings = payload.get("duty_bindings")
    goal_refs = payload.get("goal_refs")
    if (
        not all(
            isinstance(item, str) and item
            for item in (
                requester,
                subject_provider,
                subject_id,
                requested_role,
                idempotency_key,
                justification,
            )
        )
        or not isinstance(duty_bindings, list)
        or not isinstance(goal_refs, list)
    ):
        raise IamUnavailableError("stored assignment proposal fields are malformed")
    return {
        "case_id": proposal_id,
        "intent": {
            "idempotency_key": idempotency_key,
            "subject": {
                "provider": subject_provider,
                "subject_id": subject_id,
            },
            "requested_role": requested_role,
            "duty_bindings": duty_bindings,
            "goal_refs": goal_refs,
            "requester_ref": requester,
            "justification": justification,
        },
        "state": "draft",
        "revision": 1,
        "reviews": [],
        "effect_receipts": [],
        "degraded_reason": None,
        "superseded_by": None,
    }


def _project_assignment_case(
    assignment: Mapping[str, object],
    *,
    submitted: Mapping[str, object] | None,
    reviews: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    projected = dict(assignment)
    if submitted is None:
        return projected
    projected["state"] = "pending_review"
    projected["revision"] = 2
    projected_reviews: list[dict[str, object]] = []
    rejected = False
    for review in sorted(reviews, key=lambda item: str(item.get("accepted_at") or "")):
        payload = review.get("payload")
        principal = payload.get("principal") if isinstance(payload, Mapping) else None
        reviewer = principal.get("oid") if isinstance(principal, Mapping) else None
        decision = payload.get("decision") if isinstance(payload, Mapping) else None
        accepted_at = review.get("accepted_at")
        if (
            not isinstance(reviewer, str)
            or decision not in {"approve", "reject"}
            or not isinstance(accepted_at, str)
        ):
            raise IamUnavailableError("stored assignment review is malformed")
        projected_reviews.append(
            {
                "reviewer_ref": reviewer,
                "decision": decision,
                "reviewed_at": accepted_at,
            }
        )
        rejected = rejected or decision == "reject"
    projected["reviews"] = projected_reviews
    projected["revision"] = 2 + len(projected_reviews)
    intent = projected.get("intent")
    requested_role = intent.get("requested_role") if isinstance(intent, Mapping) else None
    quorum = 2 if requested_role in {"Approver", "Owner"} else 1
    approvals = sum(item["decision"] == "approve" for item in projected_reviews)
    if rejected:
        projected["state"] = "rejected"
    elif approvals >= quorum:
        projected["state"] = "approved"
    return projected


def _assignment_projection_item(assignment: Mapping[str, object]) -> dict[str, object]:
    intent = assignment.get("intent")
    if not isinstance(intent, Mapping):
        raise IamUnavailableError("assignment projection intent is malformed")
    subject = intent.get("subject")
    duties = intent.get("duty_bindings")
    if not isinstance(subject, Mapping) or not isinstance(duties, list):
        raise IamUnavailableError("assignment projection fields are malformed")
    return {
        "subject": {
            "provider": subject.get("provider"),
            "subject_id": subject.get("subject_id"),
            "display_name": None,
            "username": None,
            "active": None,
        },
        "roles": None,
        "duties": [
            {
                **dict(item),
                "responsibility": "accountable",
                "source": "stewardship",
            }
            for item in duties
            if isinstance(item, Mapping)
        ],
        "coverage": None,
        "assignment_case": dict(assignment),
        "handover": {
            "goal_refs": intent.get("goal_refs", []),
            "state": None,
            "evidence_refs": None,
            "availability": "not_connected",
        },
    }


def _reviewed_access_request(
    request: Mapping[str, object],
    review: Mapping[str, object],
) -> dict[str, object]:
    payload = review.get("payload")
    if not isinstance(payload, Mapping):
        raise IamUnavailableError("stored access-review proposal payload is malformed")
    principal = payload.get("principal")
    decision = payload.get("decision")
    accepted_at = review.get("accepted_at")
    justification = payload.get("justification")
    if (
        not isinstance(principal, Mapping)
        or not isinstance(principal.get("oid"), str)
        or decision not in {"approve", "reject"}
        or not isinstance(accepted_at, str)
        or not isinstance(justification, str)
    ):
        raise IamUnavailableError("stored access-review proposal is malformed")
    return {
        **request,
        "status": "approved" if decision == "approve" else "rejected",
        "reviewed_by": principal["oid"],
        "reviewed_at": accepted_at,
        "review_justification": justification,
    }


def _can_manage_group_membership(principal: IamPrincipal) -> bool:
    return any(role.value == "Owner" for role in principal.roles)


def _idempotency_key(command: object) -> str:
    for name in ("idempotency_key", "request_id", "run_id"):
        value = getattr(command, name, None)
        if isinstance(value, str) and value:
            return value
    payload = _command_payload(command)
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        ).hexdigest()
    )


def _runtime_settings_state(
    base_projection: Mapping[str, object],
    current: Mapping[str, object] | None,
    command: RuntimeSettingsCommand,
) -> dict[str, object]:
    projected = _runtime_settings_projection(base_projection, current)
    if projected.get("revision") != command.expected_revision:
        raise IamConflictError("runtime settings revision mismatch")
    raw_settings = projected.get("settings")
    if not isinstance(raw_settings, list):
        raise IamUnavailableError("runtime settings projection has no settings")
    settings = {
        str(setting.get("key")): setting
        for setting in raw_settings
        if isinstance(setting, Mapping) and isinstance(setting.get("key"), str)
    }
    raw_overrides = current.get("overrides") if current is not None else None
    if raw_overrides is not None and not isinstance(raw_overrides, Mapping):
        raise IamUnavailableError("stored runtime settings overrides are malformed")
    overrides = dict(raw_overrides) if isinstance(raw_overrides, Mapping) else {}
    if not command.changes:
        raise ValueError("runtime settings changes MUST NOT be empty")
    for key, value in command.changes.items():
        setting = settings.get(key)
        if setting is None:
            raise ValueError(f"unknown runtime setting: {key}")
        if value is None:
            overrides.pop(key, None)
        else:
            overrides[key] = _validate_runtime_setting_value(setting, value)
    updated_at = datetime.now(UTC).isoformat()
    return {
        "revision": command.expected_revision + 1,
        "overrides": overrides,
        "updated_at": updated_at,
        "updated_by": command.actor_id,
    }


def _runtime_settings_projection(
    base_projection: Mapping[str, object],
    state: Mapping[str, object] | None,
) -> dict[str, object]:
    projection = dict(base_projection)
    raw_settings = projection.get("settings")
    if not isinstance(raw_settings, list):
        raise IamUnavailableError("runtime settings projection has no settings")
    if state is None:
        return projection
    revision = state.get("revision")
    overrides = state.get("overrides")
    updated_at = state.get("updated_at")
    updated_by = state.get("updated_by")
    if (
        not isinstance(revision, int)
        or isinstance(revision, bool)
        or revision < 1
        or not isinstance(overrides, Mapping)
        or not isinstance(updated_at, str)
        or not updated_at
        or not isinstance(updated_by, str)
        or not updated_by
    ):
        raise IamUnavailableError("stored runtime settings are malformed")
    settings: list[dict[str, object]] = []
    known_keys: set[str] = set()
    for raw_setting in raw_settings:
        if not isinstance(raw_setting, Mapping):
            raise IamUnavailableError("runtime settings projection contains a malformed setting")
        setting = dict(raw_setting)
        key = setting.get("key")
        if not isinstance(key, str) or not key or key in known_keys:
            raise IamUnavailableError("runtime settings projection contains an invalid key")
        known_keys.add(key)
        environment_value = setting.get("environment_value")
        if key in overrides:
            override = _validate_runtime_setting_value(setting, overrides[key])
            setting["override_value"] = override
            setting["effective_value"] = override
        else:
            setting["override_value"] = None
            setting["effective_value"] = environment_value
        settings.append(setting)
    unknown = set(overrides) - known_keys
    if unknown:
        raise IamUnavailableError("stored runtime settings contain an unknown key")
    projection.update(
        {
            "revision": revision,
            "updated_at": updated_at,
            "updated_by": updated_by,
            "settings": settings,
        }
    )
    return projection


def _validate_runtime_setting_value(
    setting: Mapping[str, object],
    value: object,
) -> object:
    key = setting.get("key")
    value_type = setting.get("value_type")
    if not isinstance(key, str):
        raise IamUnavailableError("runtime setting key is malformed")
    if value_type == "boolean":
        if not isinstance(value, bool):
            raise ValueError(f"{key} MUST be a boolean")
        return value
    if value_type == "enum":
        options = setting.get("options")
        if not isinstance(value, str) or not isinstance(options, list) or value not in options:
            raise ValueError(f"{key} MUST be one of the projected options")
        return value
    if value_type == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"{key} MUST be an integer")
        number = float(value)
    elif value_type == "number":
        if not isinstance(value, int | float) or isinstance(value, bool):
            raise ValueError(f"{key} MUST be a number")
        number = float(value)
    else:
        raise IamUnavailableError("runtime setting type is malformed")
    if not math.isfinite(number):
        raise ValueError(f"{key} MUST be finite")
    minimum = setting.get("minimum")
    maximum = setting.get("maximum")
    if isinstance(minimum, int | float) and number < float(minimum):
        raise ValueError(f"{key} is below the projected minimum")
    if isinstance(maximum, int | float) and number > float(maximum):
        raise ValueError(f"{key} is above the projected maximum")
    return value


def _principal_id(payload: Mapping[str, object]) -> str | None:
    for key in ("principal_id", "actor_id", "actor_oid", "reviewer_ref"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    principal = payload.get("principal")
    return str(principal.get("oid")) if isinstance(principal, Mapping) else None


def _command_payload(command: object) -> dict[str, object]:
    if isinstance(command, Mapping):
        return _json_mapping(command)
    return _json_mapping(asdict(cast(Any, command)))


def _json_mapping(value: object) -> dict[str, object]:
    normalized = json.loads(json.dumps(value, default=_json_default))
    if not isinstance(normalized, dict):
        raise ValueError("IAM adapter payload MUST serialize to a JSON object")
    return cast(dict[str, object], normalized)


def _json_default(value: object) -> object:
    """Encode command values deterministically so a durable digest is process-stable."""
    if isinstance(value, set | frozenset):
        return sorted(str(item) for item in value)
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    return str(value)


def _binding_receipt(
    stored: StoredProposal,
    *,
    state: str,
    command: ModelBindingDraftCommand | ModelBindingRequestCommand,
) -> JsonMapping:
    policy_digest = command.policy_digest
    policy_revision = (
        command.expected_revision + 1
        if isinstance(command, ModelBindingDraftCommand)
        else command.policy_revision
    )
    return {
        "proposal_id": stored.proposal_id,
        "accepted_at": stored.accepted_at,
        "duplicate": stored.duplicate,
        "state": state,
        "policy_digest": policy_digest,
        "policy_revision": policy_revision,
        "execution_authority": False,
        "activation_boundary": "protected-plan-only",
    }


def _stored_binding_policy(state: Mapping[str, object]) -> ModelBindingPolicy:
    policy_raw = state.get("policy")
    if not isinstance(policy_raw, Mapping):
        raise IamUnavailableError("stored model binding policy is malformed")
    try:
        policy = ModelBindingPolicy.model_validate(policy_raw)
    except ValidationError as exc:
        raise IamUnavailableError("stored model binding policy is malformed") from exc
    if (
        state.get("environment") != policy.environment
        or state.get("revision") != policy.revision
        or state.get("policy_digest") != policy.digest()
        or state.get("state") != "draft"
        or state.get("execution_authority") is not False
        or state.get("activation_boundary") != "protected-plan-only"
    ):
        raise IamUnavailableError("stored model binding policy metadata is inconsistent")
    return policy


def _binding_policy_projection(
    state: Mapping[str, object],
    *,
    can_manage: bool,
) -> JsonMapping:
    policy = _stored_binding_policy(state)
    return {
        "environment": policy.environment,
        "revision": policy.revision,
        "state": "draft",
        "policy": policy.model_dump(mode="json", exclude_none=True),
        "policy_digest": policy.digest(),
        "can_manage": can_manage,
        "execution_authority": False,
        "activation_boundary": "protected-plan-only",
    }


def _mapping_items(payload: Mapping[str, object]) -> tuple[JsonMapping, ...]:
    raw = payload.get("items", [])
    if not isinstance(raw, list) or not all(isinstance(item, dict) for item in raw):
        raise IamUnavailableError("authoritative IAM projection items are malformed")
    return tuple(cast(JsonMapping, item) for item in raw)


def _total(payload: Mapping[str, object], items: Sequence[object]) -> int:
    raw = payload.get("total", len(items))
    if not isinstance(raw, int) or isinstance(raw, bool) or raw < 0:
        raise IamUnavailableError("authoritative IAM projection total is malformed")
    return raw


def _integer(payload: Mapping[str, object], key: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise IamUnavailableError(f"authoritative IAM projection {key} is malformed")
    return value


def _datetime(value: object, name: str) -> datetime:
    if not isinstance(value, str):
        raise IamUnavailableError(f"authoritative IAM projection {name} is malformed")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise IamUnavailableError(f"authoritative IAM projection {name} is malformed") from exc
    if parsed.tzinfo is None:
        raise IamUnavailableError(f"authoritative IAM projection {name} has no timezone")
    return parsed.astimezone(UTC)


def _access_grant(value: object) -> AccessGrantRecord:
    if not isinstance(value, Mapping):
        raise IamUnavailableError("access-grant projection item is malformed")
    quorum = _integer(value, "quorum")
    if quorum < 1:
        raise IamUnavailableError("access-grant projection quorum is malformed")
    return AccessGrantRecord(
        request_id=_grant_identifier(value.get("request_id"), "request_id"),
        correlation_id=_grant_identifier(value.get("original_action_id"), "original_action_id"),
        capability_id=_grant_identifier(value.get("capability_id"), "capability_id"),
        scope_ref=_grant_scope(value.get("scope_ref")),
        grant_mode=_grant_identifier(value.get("grant_mode"), "grant_mode"),
        requested_at=_datetime(value.get("requested_at"), "requested_at"),
        expires_at=_datetime(value.get("expires_at"), "expires_at"),
        quorum=quorum,
        status=str(value.get("status") or ""),
        revision=_integer(value, "revision"),
    )


def _grant_identifier(value: object, name: str) -> str:
    """Bound one projected identifier to the exact range the browser contract accepts."""
    if not isinstance(value, str) or not _CANONICAL_GRANT_ID.match(value):
        raise IamUnavailableError(f"authoritative IAM projection {name} is malformed")
    return value


def _grant_scope(value: object) -> str:
    if not isinstance(value, str) or not _SCOPE_REF.match(value):
        raise IamUnavailableError("authoritative IAM projection scope_ref is malformed")
    return value


def _decision_key(command: AccessGrantDecisionCommand) -> str:
    """Fence one reviewer's decision on one revision so a quorum can still accumulate."""
    reviewer = hashlib.sha256(command.reviewer_ref.encode()).hexdigest()[:32]
    return f"{command.request_id}:{command.expected_revision}:{reviewer}"


def _snapshot_sequence(records: Sequence[StoredStateRecord]) -> int:
    """Derive a non-decreasing replay cursor from the newest authoritative write time."""
    return max((int(record.updated_at.timestamp() * 1_000_000) for record in records), default=0)


def _reviewable(
    value: Mapping[str, object],
    reviewer: str,
    reviewer_roles: set[str],
    now: datetime,
) -> bool:
    """Report whether one authoritative grant request is reviewable by this principal."""
    if str(value.get("status") or "") != "pending":
        return False
    if _datetime(value.get("expires_at"), "expires_at") <= now:
        return False
    if str(value.get("requester_ref") or "").casefold() == reviewer:
        return False
    approver_roles = value.get("approver_roles")
    if not isinstance(approver_roles, list):
        raise IamUnavailableError("access-grant approver roles are malformed")
    return bool(reviewer_roles.intersection(str(role).casefold() for role in approver_roles))


def _directory_identity(value: Mapping[str, Any]) -> DirectoryIdentity:
    roles = value.get("roles", [])
    if not isinstance(roles, list):
        raise IamUnavailableError("directory identity roles are malformed")
    return DirectoryIdentity(
        provider=str(value.get("provider") or ""),
        subject_id=str(value.get("subject_id") or ""),
        username=str(value.get("username") or ""),
        display_name=str(value["display_name"]) if value.get("display_name") is not None else None,
        active=value.get("active") is True,
        principal_type=str(value.get("principal_type") or "person"),
        roles=tuple(str(role) for role in roles),
    )


def _decision_identity(approval_id: str, command: HilDecisionCommand) -> dict[str, object]:
    """Return the timestamp-free durable identity of one human decision.

    A justification digest keeps the exact text out of the durable proposal
    request while still refusing a retry that changes the recorded reasoning.
    """
    return {
        "approval_id": approval_id,
        "idempotency_key": command.idempotency_key,
        "decision": command.decision.value,
        "approver_oid": command.approver_oid.strip().casefold(),
        "justification_digest": "sha256:"
        + hashlib.sha256(command.justification.strip().encode("utf-8")).hexdigest(),
    }


def _hil_receipt(value: Mapping[str, object]) -> HilDecisionReceipt:
    try:
        return HilDecisionReceipt(
            approval_id=str(value["approval_id"]),
            idempotency_key=str(value["idempotency_key"]),
            decision=HilApprovalDecision(str(value["decision"])),
            approver_oid=str(value["approver_oid"]),
            decided_at=_datetime(value.get("decided_at"), "decided_at"),
            receipt_ref=str(value["receipt_ref"]),
            justification=str(value.get("justification") or ""),
            already_recorded=value.get("already_recorded") is True,
            delivered=value.get("delivered") is True,
        )
    except KeyError as exc:
        raise IamUnavailableError("stored HIL decision receipt is malformed") from exc


__all__ = ["PostgresIamAdapters"]
