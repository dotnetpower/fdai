"""Approved Rule revision changes under the authoritative v2 generation."""

from __future__ import annotations

from datetime import datetime

from fdai_service_contracts.rule_activation_cohort import (
    RuleReplicaAcknowledgementV2,
    rule_acknowledgement_set_digest,
)
from fdai_service_contracts.rule_activation_revision_change import (
    RuleBindingAuthorityPointerV2,
    RuleRevisionChangeCommandV2,
    rule_binding_authority_pointer_v2_digest,
)
from fdai_service_contracts.rule_activation_slots import RuleRevisionBindingV2
from fdai_service_contracts.rule_activation_upgrade import (
    RuleActivationAuthorityPointerV2,
    RuleActivationAuthorityTransitionKind,
    rule_activation_authority_pointer_v2_digest,
)

from fdai.core.rule_activation.cohort import StateStoreRuleActivationCohort
from fdai.core.rule_activation.identity_upgrade import StateStoreRuleIdentityUpgrade
from fdai.core.rule_activation.slots import StateStoreRuleActivationSlots
from fdai.shared.providers.rule_revision_change import RuleRevisionChangeAuthorizer
from fdai.shared.providers.state_store import StateStore

_V2_CURRENT_KEY = "rule-activation-v2:current"
_BINDING_PREFIX = "rule-activation-v2:binding:"
_MANIFEST_PREFIX = "rule-activation:manifest-nonce:"


class RuleRevisionChangeConflictError(RuntimeError):
    """Raised when an exact revision-change precondition or CAS fails."""


class RuleRevisionChangeCorruptionError(RuntimeError):
    """Raised when retained authority state fails exact validation."""


class StateStoreRuleRevisionChanges:
    """Move one revision and enforcing binding through one atomic authority CAS."""

    def __init__(
        self,
        *,
        store: StateStore,
        identity_ledger: StateStoreRuleIdentityUpgrade,
        cohort_ledger: StateStoreRuleActivationCohort,
        slot_ledger: StateStoreRuleActivationSlots,
        authorizer: RuleRevisionChangeAuthorizer,
    ) -> None:
        self._store = store
        self._identity_ledger = identity_ledger
        self._cohort_ledger = cohort_ledger
        self._slot_ledger = slot_ledger
        self._authorizer = authorizer

    async def apply(
        self,
        command: RuleRevisionChangeCommandV2,
    ) -> tuple[RuleActivationAuthorityPointerV2, RuleBindingAuthorityPointerV2]:
        """Atomically select the target generation and its approved enforcing binding."""

        validated = RuleRevisionChangeCommandV2.model_validate_json(command.model_dump_json())
        proposal = validated.proposal
        current = await self._identity_ledger.current_authority_pointer()
        if current is None:
            raise RuleRevisionChangeConflictError(
                "Rule revision change requires an authoritative v2 pointer"
            )
        binding_key = _BINDING_PREFIX + proposal.binding_id
        if current.transition_command_digest == validated.command_digest:
            binding = await self._read_binding(binding_key)
            if (
                binding is not None
                and binding.revision_change_command_digest == validated.command_digest
            ):
                return current, binding
            raise RuleRevisionChangeCorruptionError(
                "Rule revision change pointer lacks its binding authority"
            )
        if (
            proposal.source_authority_pointer_digest != current.pointer_digest
            or proposal.identity_transition.source != current.active_identity
        ):
            raise RuleRevisionChangeConflictError(
                "Rule revision change source authority identity mismatch"
            )

        slot = await self._slot_ledger.slot(proposal.slot_digest)
        move = await self._slot_ledger.move_candidate(proposal.binding_move_command_digest)
        if (
            move.slot_digest != slot.slot_digest
            or move.from_binding_digest != slot.enforcing.binding_digest
            or move.shadow_binding_digest != slot.prepared_shadow.binding_digest
            or slot.enforcing.revision != proposal.from_revision
            or slot.prepared_shadow.revision != proposal.to_revision
            or move.target_enforcing.revision != proposal.to_revision
            or slot.enforcing.profile_snapshot_digest
            != proposal.identity_transition.source.profile_snapshot.snapshot_digest
            or slot.prepared_shadow.profile_snapshot_digest
            != proposal.identity_transition.target.profile_snapshot.snapshot_digest
            or move.target_enforcing.profile_snapshot_digest
            != proposal.identity_transition.target.profile_snapshot.snapshot_digest
            or slot.enforcing.binding_id != proposal.binding_id
            or slot.prepared_shadow.binding_id != proposal.binding_id
            or move.target_enforcing.binding_id != proposal.binding_id
            or slot.cohort_prepare_digest != proposal.cohort_prepare_digest
            or slot.acknowledgement_set_digest != move.acknowledgement_set_digest
        ):
            raise RuleRevisionChangeConflictError(
                "Rule revision change binding move does not match the proposal"
            )
        existing_binding = await self._read_binding(binding_key)
        expected_binding_revision = 0
        if existing_binding is not None:
            if (
                existing_binding.enforcing.binding_digest != move.from_binding_digest
                or existing_binding.generation_digest
                != proposal.identity_transition.source.generation.generation_digest
                or existing_binding.enforcing.profile_snapshot_digest
                != proposal.identity_transition.source.profile_snapshot.snapshot_digest
            ):
                raise RuleRevisionChangeConflictError(
                    "Rule revision change source binding authority mismatch"
                )
            expected_binding_revision = existing_binding.revision
        elif slot.enforcing.revision != proposal.from_revision:
            raise RuleRevisionChangeConflictError(
                "Rule revision change initial source binding mismatch"
            )

        acknowledgement_set_digest, lease_expires_at = await self._validate_cohort(
            validated,
            move.required_replica_ids,
        )
        if acknowledgement_set_digest != move.acknowledgement_set_digest:
            raise RuleRevisionChangeConflictError(
                "Rule revision change move and cohort acknowledgement sets differ"
            )
        await self._validate_verified_manifest(validated)
        if not await self._authorizer.authorize_revision_change(
            validated.approval,
            proposal=proposal,
        ):
            raise RuleRevisionChangeConflictError(
                "Rule revision change approval is not authoritative"
            )

        replacement = self._build_authority_pointer(
            current,
            validated,
            acknowledgement_set_digest=acknowledgement_set_digest,
        )
        binding = self._build_binding_pointer(
            existing_binding,
            validated,
            move.target_enforcing,
            previous_binding_digest=move.from_binding_digest,
        )
        changed = await self._store.compare_and_set_state_pair_with_audit_before(
            _V2_CURRENT_KEY,
            replacement.model_dump(mode="json"),
            expected_revision=current.revision,
            second_key=binding_key,
            second_value=binding.model_dump(mode="json"),
            expected_second_revision=expected_binding_revision,
            not_before=validated.commanded_at,
            expires_at=lease_expires_at,
            audit_entry={
                "actor": validated.approval.approver_ids[-1],
                "producer_principal": "Saga",
                "action_kind": "rule_activation.revision-changed",
                "rule_id": proposal.rule_id,
                "from_revision_digest": proposal.from_revision.revision_digest,
                "to_revision_digest": proposal.to_revision.revision_digest,
                "source_generation_digest": (
                    proposal.identity_transition.source.generation.generation_digest
                ),
                "target_generation_digest": (
                    proposal.identity_transition.target.generation.generation_digest
                ),
                "source_authority_pointer_digest": current.pointer_digest,
                "target_authority_pointer_digest": replacement.pointer_digest,
                "binding_pointer_digest": binding.pointer_digest,
                "approval_digest": validated.approval.approval_digest,
                "command_digest": validated.command_digest,
                "recorded_at": validated.commanded_at.isoformat(),
                "activation_authority": True,
                "execution_authority": False,
            },
        )
        if not changed:
            winner = await self._identity_ledger.current_authority_pointer()
            winner_binding = await self._read_binding(binding_key)
            if (
                winner is not None
                and winner.transition_command_digest == validated.command_digest
                and winner_binding is not None
                and winner_binding.revision_change_command_digest == validated.command_digest
            ):
                return winner, winner_binding
            raise RuleRevisionChangeConflictError("Rule revision change authority CAS conflict")
        readback = await self._identity_ledger.current_authority_pointer()
        binding_readback = await self._read_binding(binding_key)
        if (
            readback is None
            or readback.pointer_digest != replacement.pointer_digest
            or binding_readback is None
            or binding_readback.pointer_digest != binding.pointer_digest
        ):
            raise RuleRevisionChangeCorruptionError(
                "Rule revision change authoritative readback failed"
            )
        return readback, binding_readback

    async def _validate_cohort(
        self,
        command: RuleRevisionChangeCommandV2,
        required_replica_ids: tuple[str, ...],
    ) -> tuple[str, datetime]:
        proposal = command.proposal
        target = proposal.identity_transition.target
        cohort = await self._cohort_ledger.cohort(proposal.cohort_prepare_digest)
        if (
            cohort.generation != target.generation
            or cohort.catalog_manifest_digest != target.catalog_manifest.manifest_digest
            or cohort.revision_registry_root != proposal.revision_registry_root
            or tuple(replica.replica_id for replica in cohort.replicas) != required_replica_ids
            or any(replica.release_id != proposal.release_id for replica in cohort.replicas)
        ):
            raise RuleRevisionChangeConflictError(
                "Rule revision change cohort does not match the target identity"
            )
        candidate = await self._cohort_ledger.candidate_active()
        if (
            candidate.prepare_digest != cohort.prepare_digest
            or candidate.generation_digest != cohort.generation.generation_digest
        ):
            raise RuleRevisionChangeConflictError(
                "Rule revision change cohort is not candidate-active"
            )
        acknowledgements: list[RuleReplicaAcknowledgementV2] = []
        for replica in cohort.replicas:
            acknowledgement = await self._cohort_ledger.acknowledgement(
                cohort.prepare_digest,
                replica.replica_id,
            )
            applied = await self._cohort_ledger.applied(cohort.prepare_digest, replica.replica_id)
            if (
                acknowledgement is None
                or acknowledgement.disposition.value != "acknowledged"
                or not {"1.0.0", "2.0.0"}.issubset(acknowledgement.supported_read_schema_versions)
                or acknowledgement.write_schema_version != "2.0.0"
                or (
                    acknowledgement.replica_id,
                    acknowledgement.principal_id,
                    acknowledgement.release_id,
                    acknowledgement.startup_epoch,
                    acknowledgement.serving_lease_id,
                )
                != (
                    replica.replica_id,
                    replica.principal_id,
                    replica.release_id,
                    replica.startup_epoch,
                    replica.serving_lease_id,
                )
                or applied is None
                or (
                    applied.replica_id,
                    applied.principal_id,
                    applied.release_id,
                    applied.startup_epoch,
                    applied.serving_lease_id,
                )
                != (
                    replica.replica_id,
                    replica.principal_id,
                    replica.release_id,
                    replica.startup_epoch,
                    replica.serving_lease_id,
                )
                or applied.acknowledgement_set_digest != candidate.acknowledgement_set_digest
                or applied.generation_digest != candidate.generation_digest
            ):
                raise RuleRevisionChangeConflictError(
                    "Rule revision change replica evidence is incomplete"
                )
            acknowledgements.append(acknowledgement)
        if (
            rule_acknowledgement_set_digest(tuple(acknowledgements))
            != candidate.acknowledgement_set_digest
        ):
            raise RuleRevisionChangeConflictError(
                "Rule revision change acknowledgement set is inconsistent"
            )
        return (
            candidate.acknowledgement_set_digest,
            min(replica.serving_lease_expires_at for replica in cohort.replicas),
        )

    async def _validate_verified_manifest(self, command: RuleRevisionChangeCommandV2) -> None:
        proposal = command.proposal
        target = proposal.identity_transition.target
        raw = await self._store.find_state(
            _MANIFEST_PREFIX,
            field="manifest_digest",
            value=proposal.signed_manifest_digest,
        )
        expected = {
            "release_id": proposal.release_id,
            "target_generation_id": target.generation.generation_id,
            "target_generation_digest": target.generation.generation_digest,
            "profile_id": target.profile_snapshot.profile_id,
            "profile_version": target.profile_snapshot.profile_version,
            "catalog_manifest_digest": target.catalog_manifest.manifest_digest,
            "revision_registry_root": proposal.revision_registry_root,
            "members": [member.model_dump(mode="json") for member in target.generation.members],
        }
        if raw is None or any(raw.get(key) != value for key, value in expected.items()):
            raise RuleRevisionChangeConflictError(
                "Rule revision change signed manifest verification is unavailable"
            )

    @staticmethod
    def _build_authority_pointer(
        current: RuleActivationAuthorityPointerV2,
        command: RuleRevisionChangeCommandV2,
        *,
        acknowledgement_set_digest: str,
    ) -> RuleActivationAuthorityPointerV2:
        proposal = command.proposal
        return RuleActivationAuthorityPointerV2(
            revision=current.revision + 1,
            transition_kind=RuleActivationAuthorityTransitionKind.REVISION_CHANGE,
            previous_generation_digest=current.active_identity.generation.generation_digest,
            active_identity=proposal.identity_transition.target,
            signed_manifest_digest=proposal.signed_manifest_digest,
            release_id=proposal.release_id,
            transition_evidence_digest=proposal.proposal_digest,
            cohort_prepare_digest=proposal.cohort_prepare_digest,
            acknowledgement_set_digest=acknowledgement_set_digest,
            authority_upgrade_command_digest=current.authority_upgrade_command_digest,
            transition_command_digest=command.command_digest,
            activated_at=command.commanded_at,
            pointer_digest=rule_activation_authority_pointer_v2_digest(
                revision=current.revision + 1,
                transition_kind=RuleActivationAuthorityTransitionKind.REVISION_CHANGE,
                previous_generation_digest=current.active_identity.generation.generation_digest,
                active_identity=proposal.identity_transition.target,
                signed_manifest_digest=proposal.signed_manifest_digest,
                release_id=proposal.release_id,
                transition_evidence_digest=proposal.proposal_digest,
                cohort_prepare_digest=proposal.cohort_prepare_digest,
                acknowledgement_set_digest=acknowledgement_set_digest,
                authority_upgrade_command_digest=current.authority_upgrade_command_digest,
                transition_command_digest=command.command_digest,
                activated_at=command.commanded_at,
            ),
        )

    @staticmethod
    def _build_binding_pointer(
        current: RuleBindingAuthorityPointerV2 | None,
        command: RuleRevisionChangeCommandV2,
        enforcing: RuleRevisionBindingV2,
        *,
        previous_binding_digest: str,
    ) -> RuleBindingAuthorityPointerV2:
        revision = 1 if current is None else current.revision + 1
        return RuleBindingAuthorityPointerV2(
            revision=revision,
            binding_id=enforcing.binding_id,
            enforcing=enforcing,
            generation_digest=(
                command.proposal.identity_transition.target.generation.generation_digest
            ),
            previous_binding_digest=previous_binding_digest,
            binding_move_command_digest=command.proposal.binding_move_command_digest,
            revision_change_command_digest=command.command_digest,
            changed_at=command.commanded_at,
            pointer_digest=rule_binding_authority_pointer_v2_digest(
                revision=revision,
                binding_id=enforcing.binding_id,
                enforcing=enforcing,
                generation_digest=(
                    command.proposal.identity_transition.target.generation.generation_digest
                ),
                previous_binding_digest=previous_binding_digest,
                binding_move_command_digest=command.proposal.binding_move_command_digest,
                revision_change_command_digest=command.command_digest,
                changed_at=command.commanded_at,
            ),
        )

    async def _read_binding(self, key: str) -> RuleBindingAuthorityPointerV2 | None:
        raw = await self._store.read_state(key)
        if raw is None:
            return None
        try:
            return RuleBindingAuthorityPointerV2.model_validate(raw)
        except ValueError as exc:
            raise RuleRevisionChangeCorruptionError(
                "Rule binding authority pointer failed validation"
            ) from exc


__all__ = [
    "RuleRevisionChangeConflictError",
    "RuleRevisionChangeCorruptionError",
    "StateStoreRuleRevisionChanges",
]
