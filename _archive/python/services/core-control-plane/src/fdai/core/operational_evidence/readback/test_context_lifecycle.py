"""Readbacks for the ``test-context-transition`` and ``operational-test-context`` purposes."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime

from fdai_service_contracts.ontology_query import content_digest
from fdai_service_contracts.operational_evidence import (
    OperationalEvidenceLookup,
    OperationalEvidenceRejectionClass,
)

from fdai.core.operational_context.test_context import TestContextClaim
from fdai.core.operational_context.test_context_commands import transition_claim
from fdai.core.operational_context.test_context_lifecycle import (
    context_transition_digest,
    parse_test_context_history,
)

from ..rejections import ReadbackRejection, reject
from .base import ReadbackContext, ReadbackFacts
from .test_context_sources import (
    MAX_TARGET_COMMANDS,
    TEST_CONTEXT_STORE_SOURCE,
    AuthenticatedCommand,
    ContextAuditSource,
    ContextHistorySource,
    OperatorCommandRow,
    OperatorCommandSource,
    authenticate_command,
    match_revision_commands,
    overlapping_reviewed,
    scope_contains,
    validate_audit_rows,
)

_R = OperationalEvidenceRejectionClass
TRANSITION_PURPOSE = "test-context-transition"
CURRENT_CONTEXT_PURPOSE = "operational-test-context"
_Histories = dict[str, tuple[TestContextClaim, ...]]


class _LifecycleSources:
    def __init__(
        self,
        *,
        commands: OperatorCommandSource,
        history: ContextHistorySource,
        audit: ContextAuditSource,
    ) -> None:
        self._commands = commands
        self._history = history
        self._audit = audit

    async def _read_history(
        self, context: ReadbackContext, target_ref: str
    ) -> tuple[int, _Histories] | ReadbackRejection:
        raw = await self._history.history(
            access_scope_digest=context.access_scope_digest, target_ref=target_ref
        )
        try:
            return parse_test_context_history(raw)
        except (KeyError, TypeError, ValueError):
            return reject(_R.PARTIAL, "history_malformed")

    async def _stable(
        self, context: ReadbackContext, target_ref: str, revision: int
    ) -> ReadbackRejection | None:
        second = await self._read_history(context, target_ref)
        if isinstance(second, ReadbackRejection):
            return second
        if second[0] != revision:
            return reject(
                _R.CONFLICTING,
                "store_revision_changed",
                conflicts=(content_digest({"revision": revision}), content_digest(second[0])),
            )
        return None

    async def _lifecycle(
        self,
        context: ReadbackContext,
        histories: _Histories,
        *,
        target_ref: str,
        purpose_id: str,
    ) -> tuple[dict[str, AuthenticatedCommand], tuple[str, ...]] | ReadbackRejection:
        """Authenticate the command and audit row behind every stored revision."""

        rows = await self._commands.commands_for_target(
            access_scope_digest=context.access_scope_digest, target_ref=target_ref
        )
        if len(rows) > MAX_TARGET_COMMANDS:
            return reject(_R.PARTIAL, "bounded_read_exceeded")
        matched = match_revision_commands(histories, rows)
        if isinstance(matched, ReadbackRejection):
            return matched
        audit = validate_audit_rows(
            histories,
            await self._audit.transition_entries(
                context_digests=tuple(
                    sorted(claim.digest for items in histories.values() for claim in items)
                )
            ),
        )
        if isinstance(audit, ReadbackRejection):
            return audit
        commands: dict[str, AuthenticatedCommand] = {}
        for digest, row in matched.items():
            authenticated = authenticate_command(
                row,
                grants=context.grants,
                venue=context.venue,
                purpose_id=purpose_id,
                at=context.read_at,
            )
            if isinstance(authenticated, ReadbackRejection):
                return authenticated
            commands[digest] = authenticated
        return commands, tuple(sorted(row.entry_hash for row in audit.values()))


class ContextTransitionReadback(_LifecycleSources):
    """Rebuild one pending transition from its Operator command and complete target history."""

    purposes = frozenset({TRANSITION_PURPOSE})

    async def read(self, context: ReadbackContext) -> ReadbackFacts | ReadbackRejection:
        locator = context.request.locator
        target_ref = locator.coordinate("target_ref")
        rows = await self._commands.commands_for_key(locator.coordinate("idempotency_key"))
        trigger = _single_command(rows, context, purpose_id=TRANSITION_PURPOSE)
        if isinstance(trigger, ReadbackRejection):
            return trigger
        request = trigger.command.request
        if (request.context_id, request.target_ref) != (
            locator.coordinate("context_id"),
            target_ref,
        ) or request.access_scope_digest != context.access_scope_digest:
            return reject(_R.CROSS_SCOPE, "locator_mismatch")
        read_at = context.clock()
        first = await self._read_history(context, target_ref)
        if isinstance(first, ReadbackRejection):
            return first
        revision, histories = first
        items = histories.get(request.context_id, ())
        prior = items[-1] if items else None
        if request.operation != "propose" and (
            prior is None or prior.revision != request.expected_revision
        ):
            return reject(_R.STALE, "prior_revision_superseded")
        if request.operation == "propose" and prior is not None:
            return reject(_R.REPLAY_SUBSTITUTED, "proposal_already_recorded")
        try:
            claim = transition_claim(trigger.command, prior)
        except PermissionError:
            return reject(_R.CROSS_SCOPE, "self_review")
        except ValueError:
            return reject(_R.REPLAY_SUBSTITUTED, "command_does_not_match_history")
        lifecycle = await self._lifecycle(
            context, histories, target_ref=target_ref, purpose_id=TRANSITION_PURPOSE
        )
        if isinstance(lifecycle, ReadbackRejection):
            return lifecycle
        commands, audit_hashes = lifecycle
        if prior is not None:
            proposer = commands[items[0].digest]
            if proposer.command.actor_id.casefold() == trigger.command.actor_id.casefold():
                return reject(_R.CROSS_SCOPE, "self_review")
        conflicts = overlapping_reviewed(histories, claim) if claim.state == "reviewed" else ()
        if conflicts:
            return reject(_R.CONFLICTING, "overlapping_reviewed_claim", conflicts=conflicts)
        unstable = await self._stable(context, target_ref, revision)
        if unstable is not None:
            return unstable
        grants = sorted({*trigger.decision.matched_grants, *_grants(commands.values())})
        return ReadbackFacts(
            evidence_digest=context_transition_digest(claim, prior),
            source_identity=TEST_CONTEXT_STORE_SOURCE,
            authentication={
                "commands": sorted(
                    {
                        trigger.receipt.receipt_digest,
                        *(c.receipt.receipt_digest for c in commands.values()),
                    }
                ),
                "trigger_command": trigger.digest,
            },
            completeness=_completeness(histories, revision, audit_hashes),
            conflict={
                "competing_records": 0,
                "overlapping_reviewed": 0,
                "store_revision": revision,
            },
            provenance={
                "prior_digest": prior.digest if prior else None,
                "source_records": sorted(
                    content_digest(c.row.key) for c in (trigger, *commands.values())
                ),
            },
            event_at=min(trigger.command.requested_at, read_at),
            evidence_cutoff=read_at,
            valid_until_cap=claim.effective_to if claim.state == "reviewed" else None,
            matched_grants=tuple(grants),
            authentication_receipts=_receipts((trigger, *commands.values())),
        )


class OperationalTestContextReadback(_LifecycleSources):
    """Re-verify the current reviewed context, its lifecycle, and its admitted lineage."""

    purposes = frozenset({CURRENT_CONTEXT_PURPOSE})

    async def read(self, context: ReadbackContext) -> ReadbackFacts | ReadbackRejection:
        locator = context.request.locator
        lookup = context.request.lookup
        target_ref = locator.coordinate("target_ref")
        read_at = context.clock()
        first = await self._read_history(context, target_ref)
        if isinstance(first, ReadbackRejection):
            return first
        revision, histories = first
        items = histories.get(locator.coordinate("context_id"), ())
        if not items:
            return reject(_R.PARTIAL, "context_missing")
        current = items[-1]
        if current.digest != lookup.evidence_digest:
            if any(item.digest == lookup.evidence_digest for item in items[:-1]):
                return reject(_R.STALE, "context_revision_superseded")
            return reject(_R.REPLAY_SUBSTITUTED, "context_digest_mismatch")
        if (current.target_ref, current.signal_code) != (
            target_ref,
            locator.coordinate("signal_code"),
        ):
            return reject(_R.CROSS_SCOPE, "locator_mismatch")
        if current.policy_revision != lookup.source_revision:
            return reject(_R.REPLAY_SUBSTITUTED, "source_revision_mismatch")
        if current.state == "revoked":
            return reject(_R.REVOKED, "context_revoked")
        if current.state != "reviewed":
            return reject(_R.PARTIAL, "context_not_reviewed")
        if any(claim.recorded_at > read_at for claims in histories.values() for claim in claims):
            return reject(_R.PARTIAL, "future_recorded_revision")
        if not current.effective_from <= read_at < current.effective_to:
            return reject(_R.STALE, "context_not_current")
        scope = scope_contains(
            context.grants,
            access_scope_digest=context.access_scope_digest,
            target_ref=target_ref,
            purpose_id=CURRENT_CONTEXT_PURPOSE,
            at=read_at,
        )
        if isinstance(scope, ReadbackRejection):
            return scope
        conflicts = overlapping_reviewed(histories, current, at=read_at)
        if conflicts:
            return reject(_R.CONFLICTING, "competing_active_context", conflicts=conflicts)
        lifecycle = await self._lifecycle(
            context, histories, target_ref=target_ref, purpose_id=TRANSITION_PURPOSE
        )
        if isinstance(lifecycle, ReadbackRejection):
            return lifecycle
        commands, audit_hashes = lifecycle
        prior = items[-2] if len(items) > 1 else None
        lineage = await self._lineage(context, current, prior, read_at=read_at)
        if isinstance(lineage, ReadbackRejection):
            return lineage
        unstable = await self._stable(context, target_ref, revision)
        if unstable is not None:
            return unstable
        return ReadbackFacts(
            evidence_digest=current.digest,
            source_identity=TEST_CONTEXT_STORE_SOURCE,
            authentication={
                "commands": sorted(c.receipt.receipt_digest for c in commands.values()),
                "lineage": lineage,
            },
            completeness=_completeness(histories, revision, audit_hashes),
            conflict={"active_reviewed": 1, "store_revision": revision},
            provenance={
                "case_scope": scope.case_scope_id,
                "source_records": sorted(content_digest(c.row.key) for c in commands.values()),
            },
            event_at=current.recorded_at,
            evidence_cutoff=read_at,
            valid_until_cap=current.effective_to,
            matched_grants=tuple(sorted(_grants(commands.values()))),
            authentication_receipts=_receipts(commands.values()),
        )

    async def _lineage(
        self,
        context: ReadbackContext,
        current: TestContextClaim,
        prior: TestContextClaim | None,
        *,
        read_at: datetime,
    ) -> str | ReadbackRejection:
        """Accept only the admission of the exact transition that produced ``current``.

        The cited record must carry the lookup the verifier rebuilds for (``current``, its
        prior revision): any other admission, even a valid one for an earlier transition, is a
        substitution. The binding and matched grants must also have survived every revision.
        """

        audit = await self._audit.transition_entries(context_digests=(current.digest,))
        refs = {row.entry.get("admission_ref") for row in audit}
        if len(refs) != 1 or not isinstance(next(iter(refs)), str) or context.lineage is None:
            return reject(_R.PARTIAL, "lineage_missing")
        record = await context.lineage.admission_by_receipt(str(next(iter(refs))))
        if record is None:
            return reject(_R.PARTIAL, "lineage_missing")
        if record.purpose_id != TRANSITION_PURPOSE:
            return reject(_R.REPLAY_SUBSTITUTED, "lineage_purpose_mismatch")
        expected = OperationalEvidenceLookup(
            evidence_digest=context_transition_digest(current, prior),
            scope_digest="sha256:" + current.access_scope_digest,
            purpose_id=TRANSITION_PURPOSE,
            source_revision=current.policy_revision,
        ).lookup_digest
        if record.lookup_digest != expected:
            return reject(_R.REPLAY_SUBSTITUTED, "lineage_lookup_mismatch")
        if not context.history.lineage_intact(record.pins_digest, record.binding, at=read_at):
            return reject(_R.REVOKED, "lineage_revoked")
        return record.receipt_digest


def _single_command(
    rows: Sequence[OperatorCommandRow], context: ReadbackContext, *, purpose_id: str
) -> AuthenticatedCommand | ReadbackRejection:
    if not rows:
        return reject(_R.PARTIAL, "source_record_missing")
    if len(rows) > 1:
        return reject(
            _R.CONFLICTING,
            "competing_command_record",
            conflicts=(content_digest(row.key) for row in rows),
        )
    return authenticate_command(
        rows[0],
        grants=context.grants,
        venue=context.venue,
        purpose_id=purpose_id,
        at=context.read_at,
    )


def _grants(commands: Iterable[AuthenticatedCommand]) -> set[str]:
    values: set[str] = set()
    for command in commands:
        values.update(command.decision.matched_grants)
    return values


def _receipts(commands: Iterable[AuthenticatedCommand]) -> tuple[dict[str, object], ...]:
    unique = {command.receipt.receipt_digest: command.receipt for command in commands}
    return tuple(unique[key].model_dump(mode="json") for key in sorted(unique))


def _completeness(
    histories: Mapping[str, Sequence[TestContextClaim]],
    revision: int,
    audit_hashes: tuple[str, ...],
) -> dict[str, object]:
    return {
        "audit_entries": list(audit_hashes),
        "revisions": sorted(claim.digest for items in histories.values() for claim in items),
        "store_revision": revision,
    }


__all__ = [
    "CURRENT_CONTEXT_PURPOSE",
    "TRANSITION_PURPOSE",
    "OperationalTestContextReadback",
    "ContextTransitionReadback",
]
