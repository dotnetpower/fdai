"""Rule revision reference retention, approved retirement, and rollback eligibility."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from fdai_service_contracts.compatibility import canonical_digest
from fdai_service_contracts.rule_activation_cohort import (
    RuleCohortCandidateActiveV2,
    RuleCohortPrepareV2,
    RuleReplicaAppliedV2,
)
from fdai_service_contracts.rule_activation_manifest import RuleRevisionIdentityRef
from fdai_service_contracts.rule_activation_retention import (
    RuleRevisionReferenceKind,
    RuleRevisionReferenceV2,
    RuleRevisionRetentionSnapshotV2,
    RuleRevisionRetirementCommandV2,
    RuleRevisionRetirementReceiptV2,
    rule_revision_retention_snapshot_digest,
    rule_revision_retirement_receipt_digest,
)
from fdai_service_contracts.rule_activation_revision_change import (
    RuleBindingAuthorityPointerV2,
    RuleRevisionChangeProposalV2,
    RuleRevisionTransitionKind,
    RuleRollbackEligibilityV2,
)
from fdai_service_contracts.rule_activation_slots import (
    RuleBindingMoveCandidateV2,
    RuleDualRevisionSlotV2,
)
from fdai_service_contracts.rule_activation_upgrade import RuleActivationAuthorityPointerV2

from fdai.shared.providers.rule_revision_retirement import (
    RuleRevisionRegistryReader,
    RuleRevisionRetirementAuthorizer,
)
from fdai.shared.providers.state_store import StateStore

_CURRENT_KEY = "rule-activation-v2:current"
_RETENTION_EPOCH_KEY = "rule-activation-v2:retention-epoch"
_RETIRED_PREFIX = "rule-activation-v2:retired:"
_ROLLBACK_PREFIX = "rule-activation-v2:rollback-eligible:"
_STATE_SCAN_LIMIT = 50_001


class RuleRevisionRetentionConflictError(RuntimeError):
    """Raised when references, approval, or the retention epoch blocks retirement."""


class RuleRevisionRetentionCorruptionError(RuntimeError):
    """Raised when retained reference state fails exact validation."""


class StateStoreRuleRevisionRetention:
    """Derive complete references and serialize retirement against new activation."""

    def __init__(
        self,
        *,
        store: StateStore,
        authorizer: RuleRevisionRetirementAuthorizer,
        registry: RuleRevisionRegistryReader,
    ) -> None:
        self._store = store
        self._authorizer = authorizer
        self._registry = registry

    async def snapshot(
        self,
        revision: RuleRevisionIdentityRef,
        *,
        captured_at: datetime,
    ) -> RuleRevisionRetentionSnapshotV2:
        if not self._registry.has_retained_closure(revision):
            raise RuleRevisionRetentionConflictError(
                "Rule revision retained closure is unavailable"
            )
        epoch = await self._retention_epoch()
        references = await self._references(revision, at=captured_at)
        return RuleRevisionRetentionSnapshotV2(
            revision=revision,
            retention_epoch_revision=epoch,
            references=references,
            captured_at=captured_at,
            snapshot_digest=rule_revision_retention_snapshot_digest(
                revision=revision,
                retention_epoch_revision=epoch,
                references=references,
                captured_at=captured_at,
            ),
        )

    async def retire(
        self,
        command: RuleRevisionRetirementCommandV2,
    ) -> RuleRevisionRetirementReceiptV2:
        validated = RuleRevisionRetirementCommandV2.model_validate_json(command.model_dump_json())
        proposal = validated.proposal
        revision = proposal.snapshot.revision
        key = _RETIRED_PREFIX + revision.revision_digest.removeprefix("sha256:")
        existing = await self._store.read_state(key)
        if existing is not None:
            receipt = RuleRevisionRetirementReceiptV2.model_validate(existing)
            if receipt.retirement_command_digest == validated.command_digest:
                return receipt
            raise RuleRevisionRetentionConflictError(
                "Rule revision is already retired by another command"
            )
        current = await self.snapshot(revision, captured_at=validated.commanded_at)
        if (
            current.retention_epoch_revision != proposal.snapshot.retention_epoch_revision
            or current.references
        ):
            raise RuleRevisionRetentionConflictError(
                "Rule revision retirement references changed after approval"
            )
        if not await self._authorizer.authorize_retirement(
            validated.approval,
            proposal=proposal,
        ):
            raise RuleRevisionRetentionConflictError(
                "Rule revision retirement approval is not authoritative"
            )
        receipt = RuleRevisionRetirementReceiptV2(
            revision=revision,
            reference_snapshot_digest=proposal.snapshot.snapshot_digest,
            retirement_command_digest=validated.command_digest,
            retired_at=validated.commanded_at,
            receipt_digest=rule_revision_retirement_receipt_digest(
                revision=revision,
                reference_snapshot_digest=proposal.snapshot.snapshot_digest,
                retirement_command_digest=validated.command_digest,
                retired_at=validated.commanded_at,
            ),
        )
        epoch = current.retention_epoch_revision
        changed = await self._store.compare_and_set_state_with_audit_and_insert_before(
            _RETENTION_EPOCH_KEY,
            {
                "revision": epoch + 1,
                "last_retirement_command_digest": validated.command_digest,
            },
            expected_revision=epoch,
            insert_key=key,
            insert_value=receipt.model_dump(mode="json"),
            not_before=validated.commanded_at,
            expires_at=validated.approval.approved_at + timedelta(hours=24),
            audit_entry={
                "actor": validated.approval.approver_ids[-1],
                "producer_principal": "Saga",
                "action_kind": "rule_activation.revision-retired",
                "rule_id": revision.rule_id,
                "rule_version": revision.rule_version,
                "revision_digest": revision.revision_digest,
                "reference_snapshot_digest": proposal.snapshot.snapshot_digest,
                "approval_digest": validated.approval.approval_digest,
                "command_digest": validated.command_digest,
                "recorded_at": validated.commanded_at.isoformat(),
                "activation_authority": False,
                "execution_authority": False,
            },
        )
        if not changed:
            winner = await self._store.read_state(key)
            if winner is not None:
                receipt = RuleRevisionRetirementReceiptV2.model_validate(winner)
                if receipt.retirement_command_digest == validated.command_digest:
                    return receipt
            raise RuleRevisionRetentionConflictError("Rule revision retirement CAS conflict")
        return receipt

    async def rollback_eligibility_expires_at(
        self,
        proposal: RuleRevisionChangeProposalV2,
    ) -> datetime | None:
        if (
            proposal.transition_kind is not RuleRevisionTransitionKind.ROLLBACK
            or proposal.rollback_eligibility_digest is None
        ):
            return None
        raw = await self._store.read_state(
            _ROLLBACK_PREFIX + proposal.rollback_eligibility_digest.removeprefix("sha256:")
        )
        if raw is None:
            return None
        try:
            eligibility = RuleRollbackEligibilityV2.model_validate(raw)
        except ValueError as exc:
            raise RuleRevisionRetentionCorruptionError(
                "Rule rollback eligibility failed validation"
            ) from exc
        current_raw = await self._store.read_state(_CURRENT_KEY)
        if current_raw is None:
            return None
        try:
            current = RuleActivationAuthorityPointerV2.model_validate(current_raw)
        except ValueError as exc:
            raise RuleRevisionRetentionCorruptionError(
                "Rule rollback current authority failed validation"
            ) from exc
        target = proposal.identity_transition.target
        source = proposal.identity_transition.source
        if (
            eligibility.eligibility_digest != proposal.rollback_eligibility_digest
            or current.pointer_digest != proposal.source_authority_pointer_digest
            or current.transition_command_digest != eligibility.revision_change_command_digest
            or eligibility.superseding_generation_digest != source.generation.generation_digest
            or eligibility.source_identity.profile_snapshot.members
            != target.profile_snapshot.members
            or eligibility.source_identity.profile_snapshot.profile_id
            != target.profile_snapshot.profile_id
            or eligibility.source_binding.binding_id != proposal.binding_id
            or eligibility.source_binding.revision != proposal.to_revision
        ):
            return None
        return eligibility.expires_at

    async def _references(
        self,
        revision: RuleRevisionIdentityRef,
        *,
        at: datetime,
    ) -> tuple[RuleRevisionReferenceV2, ...]:
        references: set[tuple[RuleRevisionReferenceKind, str]] = set()
        current_raw = await self._store.read_state(_CURRENT_KEY)
        if current_raw is None:
            raise RuleRevisionRetentionConflictError(
                "Rule revision retirement requires authoritative v2 state"
            )
        current = RuleActivationAuthorityPointerV2.model_validate(current_raw)
        if revision in current.active_identity.profile_snapshot.members:
            references.add((RuleRevisionReferenceKind.ACTIVE, current.pointer_digest))

        prepares = await self._all_states("rule-activation-v2:prepare:")
        cohorts: dict[str, RuleCohortPrepareV2] = {}
        for raw in prepares:
            cohort = RuleCohortPrepareV2.model_validate(raw)
            cohorts[cohort.prepare_digest] = cohort
        latest_prepare = await self._store.read_state("rule-activation-v2:latest-prepare")
        latest_prepare_digest = (
            latest_prepare.get("prepare_digest") if latest_prepare is not None else None
        )
        if latest_prepare_digest is not None and not isinstance(latest_prepare_digest, str):
            raise RuleRevisionRetentionCorruptionError("Rule latest prepare reference is malformed")
        if latest_prepare_digest is not None:
            latest_cohort = cohorts.get(latest_prepare_digest)
            if latest_cohort is None:
                raise RuleRevisionRetentionCorruptionError(
                    "Rule latest prepare lacks its retained cohort"
                )
            if revision in latest_cohort.generation.members:
                references.add((RuleRevisionReferenceKind.PREPARED, latest_cohort.prepare_digest))

        candidate_raw = await self._store.read_state("rule-activation-v2:candidate-active")
        candidate_prepare_digest: str | None = None
        if candidate_raw is not None:
            candidate = candidate_raw.get("candidate")
            if not isinstance(candidate, dict):
                raise RuleRevisionRetentionCorruptionError(
                    "Rule candidate-active reference is malformed"
                )
            try:
                candidate_record = RuleCohortCandidateActiveV2.model_validate(candidate)
            except ValueError as exc:
                raise RuleRevisionRetentionCorruptionError(
                    "Rule candidate-active reference failed validation"
                ) from exc
            candidate_prepare_digest = candidate_record.prepare_digest
            candidate_cohort = cohorts.get(candidate_prepare_digest)
            if candidate_cohort is None:
                raise RuleRevisionRetentionCorruptionError(
                    "Rule candidate-active reference lacks its retained preparation"
                )
            if revision in candidate_cohort.generation.members:
                references.add(
                    (
                        RuleRevisionReferenceKind.ACTIVE,
                        canonical_digest(candidate_record.model_dump(mode="json")),
                    )
                )
        applied_rows = await self._all_states("rule-activation-v2:applied:")
        for raw in applied_rows:
            applied = RuleReplicaAppliedV2.model_validate(raw)
            if applied.prepare_digest != candidate_prepare_digest:
                continue
            applied_cohort = cohorts.get(applied.prepare_digest)
            if applied_cohort is None:
                raise RuleRevisionRetentionCorruptionError(
                    "Rule applied reference lacks its retained preparation"
                )
            if revision in applied_cohort.generation.members:
                references.add((RuleRevisionReferenceKind.APPLIED, canonical_digest(raw)))

        rollback_rows = await self._all_states(_ROLLBACK_PREFIX)
        completed_commands: set[str] = set()
        for raw in rollback_rows:
            eligibility = RuleRollbackEligibilityV2.model_validate(raw)
            completed_commands.add(eligibility.revision_change_command_digest)
            if eligibility.expires_at > at and (
                revision in eligibility.source_identity.profile_snapshot.members
                or eligibility.source_binding.revision == revision
            ):
                references.add(
                    (
                        RuleRevisionReferenceKind.ROLLBACK_ELIGIBLE,
                        eligibility.eligibility_digest,
                    )
                )

        desired_rows = await self._all_states("rule-activation-v2:desired:")
        for raw in desired_rows:
            command_digest = _required_digest(raw, "command_digest")
            if command_digest not in completed_commands and _contains_revision(
                raw.get("members"),
                revision,
            ):
                references.add(
                    (
                        RuleRevisionReferenceKind.DESIRED,
                        _required_digest(raw, "desired_digest"),
                    )
                )

        bindings = await self._all_states("rule-activation-v2:binding:")
        for raw in bindings:
            binding = RuleBindingAuthorityPointerV2.model_validate(raw)
            if binding.enforcing.revision == revision:
                references.add(
                    (
                        RuleRevisionReferenceKind.ENFORCEMENT_PIN,
                        binding.pointer_digest,
                    )
                )

        moves = await self._all_states("rule-activation-v2:binding-move:")
        for raw in moves:
            move = RuleBindingMoveCandidateV2.model_validate(raw)
            if move.target_enforcing.revision == revision:
                references.add((RuleRevisionReferenceKind.PROMOTION_RECORD, move.command_digest))

        slots = await self._all_states("rule-activation-v2:slot:")
        for raw in slots:
            slot = RuleDualRevisionSlotV2.model_validate(raw)
            if revision in {
                slot.enforcing.revision,
                slot.prepared_shadow.revision,
            }:
                references.add((RuleRevisionReferenceKind.ENFORCEMENT_PIN, slot.slot_digest))
        return tuple(
            RuleRevisionReferenceV2(
                revision=revision,
                kind=kind,
                owner_digest=owner_digest,
            )
            for kind, owner_digest in sorted(references, key=lambda item: (item[0].value, item[1]))
        )

    async def _all_states(self, prefix: str) -> tuple[dict[str, Any], ...]:
        rows = await self._store.read_states(prefix, limit=_STATE_SCAN_LIMIT)
        if len(rows) == _STATE_SCAN_LIMIT:
            raise RuleRevisionRetentionConflictError(
                "Rule revision reference scan exceeded its bounded limit"
            )
        return tuple(dict(row) for row in rows)

    async def _retention_epoch(self) -> int:
        raw = await self._store.read_state(_RETENTION_EPOCH_KEY)
        if raw is None:
            await self._store.write_state_if_absent(
                _RETENTION_EPOCH_KEY,
                {"revision": 1, "last_transition_command_digest": None},
            )
            raw = await self._store.read_state(_RETENTION_EPOCH_KEY)
        revision = raw.get("revision") if raw is not None else None
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
            raise RuleRevisionRetentionCorruptionError(
                "Rule revision retention epoch failed validation"
            )
        return revision


def _contains_revision(value: object, revision: RuleRevisionIdentityRef) -> bool:
    if not isinstance(value, list):
        raise RuleRevisionRetentionCorruptionError("Rule retained member reference is malformed")
    try:
        members = tuple(RuleRevisionIdentityRef.model_validate(item) for item in value)
    except ValueError as exc:
        raise RuleRevisionRetentionCorruptionError(
            "Rule retained member reference failed validation"
        ) from exc
    return revision in members


def _required_digest(raw: dict[str, Any], field: str) -> str:
    value = raw.get(field)
    if not isinstance(value, str):
        raise RuleRevisionRetentionCorruptionError(f"Rule retained reference lacks {field}")
    return value


__all__ = [
    "RuleRevisionRetentionConflictError",
    "RuleRevisionRetentionCorruptionError",
    "StateStoreRuleRevisionRetention",
]
