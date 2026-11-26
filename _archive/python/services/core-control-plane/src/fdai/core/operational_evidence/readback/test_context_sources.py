"""Test-context source contracts and shared verification rules.

The verifier reads Operator command rows only through a view whose rows a database trigger lets
the Operator identity alone insert, and reads Mimir's revisioned history and its atomic audit
entries under its own read-only role. Rebuilding claims and digests reuses the consumers' pure
functions, so the verifier and each boundary owner can never canonicalize differently.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from fdai_service_contracts.ontology_query import content_digest
from fdai_service_contracts.operational_evidence import OperationalEvidenceRejectionClass
from fdai_service_contracts.operator_authentication import (
    OperatorAuthenticationEvidenceClass,
    OperatorAuthenticationReceipt,
)
from fdai_service_contracts.test_context import (
    TestContextCommand,
    context_command_from_record,
)
from pydantic import ValidationError

from fdai.core.operational_context.test_context import TestContextClaim
from fdai.core.operational_context.test_context_commands import transition_claim
from fdai.shared.providers.audit_hash import next_hash

from ..grant_registry import CaseScope, CaseScopeGrantRegistry, GrantDecision
from ..rejections import ReadbackRejection, reject
from ..trust_registry import Venue

_R = OperationalEvidenceRejectionClass
OPERATOR_OUTBOX_SOURCE = "operator-service.test-context-outbox"
TEST_CONTEXT_STORE_SOURCE = "core-control-plane.test-context-store"
MAX_TARGET_COMMANDS = 64
_OPERATIONS = {"propose": "proposed", "review": "reviewed", "revoke": "revoked"}


@dataclass(frozen=True, slots=True)
class OperatorCommandRow:
    """One Operator-inserted test-context command row, as the view exposes it."""

    key: str
    record: Mapping[str, Any]
    dispatch_status: str
    authentication_receipt: Mapping[str, Any] | None


@dataclass(frozen=True, slots=True)
class AuditRow:
    """One hash-chained audit row for a test-context transition."""

    seq: int
    entry: Mapping[str, Any]
    previous_hash: str
    entry_hash: str


class OperatorCommandSource(Protocol):
    """Read Operator test-context command rows; never another row family."""

    async def commands_for_key(self, idempotency_key: str) -> tuple[OperatorCommandRow, ...]: ...

    async def commands_for_target(
        self, *, access_scope_digest: str, target_ref: str
    ) -> tuple[OperatorCommandRow, ...]: ...


class ContextHistorySource(Protocol):
    """Read Mimir's revisioned history for one scope and target."""

    async def history(
        self, *, access_scope_digest: str, target_ref: str
    ) -> Mapping[str, Any] | None: ...


class ContextAuditSource(Protocol):
    """Read the atomic audit rows written with test-context revisions."""

    async def transition_entries(
        self, *, context_digests: tuple[str, ...]
    ) -> tuple[AuditRow, ...]: ...


@dataclass(frozen=True, slots=True)
class AuthenticatedCommand:
    """A command whose human principal and grant the verifier re-established from sources."""

    row: OperatorCommandRow
    command: TestContextCommand
    receipt: OperatorAuthenticationReceipt
    decision: GrantDecision

    @property
    def digest(self) -> str:
        return content_digest(self.command.model_dump(mode="json"))


def authenticate_command(
    row: OperatorCommandRow,
    *,
    grants: CaseScopeGrantRegistry,
    venue: Venue,
    purpose_id: str,
    at: datetime,
) -> AuthenticatedCommand | ReadbackRejection:
    """Rebuild one command and re-establish its principal from the retained receipt only."""

    try:
        command = context_command_from_record(row.record)
    except (KeyError, TypeError, ValueError, ValidationError):
        return reject(_R.PARTIAL, "source_record_malformed")
    if row.record.get("request_digest") != operator_request_digest(row.record):
        return reject(_R.REPLAY_SUBSTITUTED, "request_digest_mismatch")
    if row.dispatch_status == "rejected":
        return reject(_R.PARTIAL, "delivery_rejected")
    if row.authentication_receipt is None:
        return reject(_R.PARTIAL, "authentication_receipt_missing")
    try:
        receipt = OperatorAuthenticationReceipt.model_validate(row.authentication_receipt)
    except (ValidationError, ValueError):
        return reject(_R.PARTIAL, "authentication_receipt_invalid")
    if receipt.principal_kind != "human" or receipt.subject_id != command.actor_id:
        return reject(_R.CROSS_SCOPE, "principal_mismatch")
    scope = row.record["payload"]["scope"]
    if tuple(sorted(scope.get("groups") or ())) != receipt.groups:
        return reject(_R.CROSS_SCOPE, "principal_groups_mismatch")
    if tuple(sorted(scope.get("roles") or ())) != receipt.roles:
        return reject(_R.CROSS_SCOPE, "principal_roles_mismatch")
    if not receipt.valid_at(command.requested_at):
        return reject(_R.STALE, "authentication_receipt_not_current")
    if (
        venue is Venue.DEPLOYED
        and receipt.evidence_class is OperatorAuthenticationEvidenceClass.LOCAL_LOOPBACK
    ):
        return reject(_R.SYNTHETIC_LIVE, "local_loopback_receipt")
    request = command.request
    decision = grants.authorize(
        receipt,
        access_scope_digest=request.access_scope_digest,
        operation="test-context." + request.operation,
        purpose_id=purpose_id,
        at=at,
        target_ref=request.target_ref,
        policy_revision=request.policy_revision,
    )
    if not decision.allowed or decision.rejection_class is not None:
        return reject(
            decision.rejection_class or _R.CROSS_SCOPE,
            *decision.reasons,
            conflicts=decision.conflicts,
        )
    return AuthenticatedCommand(row=row, command=command, receipt=receipt, decision=decision)


def operator_request_digest(record: Mapping[str, Any]) -> str:
    """Recompute the Operator outbox request digest over its immutable request fields."""

    request = {
        "family": record.get("family"),
        "operation": record.get("operation"),
        "principal_id": record.get("principal_id"),
        "idempotency_key": record.get("idempotency_key"),
        "payload": record.get("payload"),
    }
    encoded = json.dumps(request, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def scope_contains(
    grants: CaseScopeGrantRegistry,
    *,
    access_scope_digest: str,
    target_ref: str,
    purpose_id: str,
    at: datetime,
) -> CaseScope | ReadbackRejection:
    """Require the target and purpose to belong to one current reviewed case scope."""

    scope = grants.scope_for(access_scope_digest)
    if scope is None:
        return reject(_R.CROSS_SCOPE, "case_scope_unknown")
    if scope.window.revoked:
        return reject(_R.REVOKED, "case_scope_revoked")
    if not scope.window.active_at(at):
        return reject(_R.STALE, "case_scope_not_current")
    if purpose_id not in scope.purposes or not scope.contains(target_ref):
        return reject(_R.CROSS_SCOPE, "target_outside_case_scope")
    return scope


def match_revision_commands(
    histories: Mapping[str, Sequence[TestContextClaim]],
    rows: Iterable[OperatorCommandRow],
) -> dict[str, OperatorCommandRow] | ReadbackRejection:
    """Map every stored revision digest to exactly one Operator command that produced it."""

    candidates: list[tuple[OperatorCommandRow, TestContextCommand]] = []
    for row in rows:
        try:
            candidates.append((row, context_command_from_record(row.record)))
        except (KeyError, TypeError, ValueError, ValidationError):
            return reject(_R.PARTIAL, "source_record_malformed")
    matched: dict[str, OperatorCommandRow] = {}
    for items in histories.values():
        prior: TestContextClaim | None = None
        for revision in items:
            producing = [
                row
                for row, command in candidates
                if _OPERATIONS[command.request.operation] == revision.state
                and command.request.context_id == revision.context_id
                and _rebuilds(command, prior, revision)
            ]
            if not producing:
                return reject(_R.PARTIAL, "revision_without_command")
            if len(producing) > 1:
                return reject(
                    _R.CONFLICTING,
                    "competing_command",
                    conflicts=(content_digest(row.key) for row in producing),
                )
            matched[revision.digest] = producing[0]
            prior = revision
    return matched


def validate_audit_rows(
    histories: Mapping[str, Sequence[TestContextClaim]],
    rows: Iterable[AuditRow],
) -> dict[str, AuditRow] | ReadbackRejection:
    """Require one hash-valid Mimir audit row per revision, bound to its predecessor."""

    by_digest: dict[str, list[AuditRow]] = {}
    for row in rows:
        if next_hash(row.previous_hash, row.entry) != row.entry_hash:
            return reject(_R.REPLAY_SUBSTITUTED, "audit_hash_mismatch")
        digest = row.entry.get("context_digest")
        if isinstance(digest, str):
            by_digest.setdefault(digest, []).append(row)
    matched: dict[str, AuditRow] = {}
    for items in histories.values():
        prior: TestContextClaim | None = None
        for revision in items:
            found = by_digest.get(revision.digest, [])
            if not found:
                return reject(_R.PARTIAL, "audit_entry_missing")
            if len(found) > 1:
                return reject(
                    _R.CONFLICTING,
                    "competing_audit_entry",
                    conflicts=(row.entry_hash for row in found),
                )
            entry = found[0].entry
            if (
                entry.get("action_kind") != "test_context.transition"
                or entry.get("owner_agent") != "Mimir"
                or entry.get("state") != revision.state
                or entry.get("previous_digest") != (prior.digest if prior else None)
                or entry.get("scope_digest") != revision.access_scope_digest
            ):
                return reject(_R.REPLAY_SUBSTITUTED, "audit_entry_mismatch")
            matched[revision.digest] = found[0]
            prior = revision
    return matched


def overlapping_reviewed(
    histories: Mapping[str, Sequence[TestContextClaim]],
    claim: TestContextClaim,
    *,
    at: datetime | None = None,
) -> tuple[str, ...]:
    """Return digests of other current reviewed claims that overlap one claim's signal."""

    conflicts: list[str] = []
    for identity, items in histories.items():
        other = items[-1]
        if identity == claim.context_id or other.state != "reviewed":
            continue
        if other.signal_code != claim.signal_code:
            continue
        if at is not None:
            if other.effective_from <= at < other.effective_to:
                conflicts.append(other.digest)
        elif max(other.effective_from, claim.effective_from) < min(
            other.effective_to, claim.effective_to
        ):
            conflicts.append(other.digest)
    return tuple(sorted(conflicts))


def _rebuilds(
    command: TestContextCommand, prior: TestContextClaim | None, revision: TestContextClaim
) -> bool:
    try:
        return transition_claim(command, prior) == revision
    except (PermissionError, ValueError):
        return False


__all__ = [
    "MAX_TARGET_COMMANDS",
    "OPERATOR_OUTBOX_SOURCE",
    "TEST_CONTEXT_STORE_SOURCE",
    "AuditRow",
    "AuthenticatedCommand",
    "OperatorCommandRow",
    "OperatorCommandSource",
    "ContextAuditSource",
    "ContextHistorySource",
    "authenticate_command",
    "match_revision_commands",
    "operator_request_digest",
    "overlapping_reviewed",
    "scope_contains",
    "validate_audit_rows",
]
