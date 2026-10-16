"""Approved, atomic Rule activation identity cutover from v1 to v2."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from fdai_service_contracts.rule_activation_cohort import (
    RuleReplicaAcknowledgementV2,
    rule_acknowledgement_set_digest,
)
from fdai_service_contracts.rule_activation_upgrade import (
    RuleActivationAuthorityPointerV2,
    RuleIdentityUpgradeCommandV2,
    RuleReviewedPolicyBaselineV2,
    rule_activation_authority_pointer_v2_digest,
)
from fdai_service_contracts.rule_activation_versioning import (
    RuleActivationRecordKind,
    decode_rule_activation_record,
)

from fdai.core.rule_activation.cohort import StateStoreRuleActivationCohort
from fdai.core.rule_activation.ledger import StateStoreRuleActivationLedger
from fdai.shared.providers.rule_identity_upgrade import RuleIdentityUpgradeAuthorizer
from fdai.shared.providers.state_store import StateStore

_V1_CURRENT_KEY = "rule-activation:current"
_V2_CURRENT_KEY = "rule-activation-v2:current"
_MANIFEST_PREFIX = "rule-activation:manifest-nonce:"


class RuleIdentityUpgradeConflictError(RuntimeError):
    """Raised when exact upgrade preconditions or the authority CAS fail."""


class RuleIdentityUpgradeCorruptionError(RuntimeError):
    """Raised when the v1/v2 authority fence is incomplete or inconsistent."""


class StateStoreRuleIdentityUpgrade:
    """Cut over authority only after approval, cohort, manifest, and baseline proof."""

    def __init__(
        self,
        *,
        store: StateStore,
        legacy_ledger: StateStoreRuleActivationLedger,
        cohort_ledger: StateStoreRuleActivationCohort,
        authorizer: RuleIdentityUpgradeAuthorizer,
    ) -> None:
        self._store = store
        self._legacy_ledger = legacy_ledger
        self._cohort_ledger = cohort_ledger
        self._authorizer = authorizer

    async def apply(
        self,
        command: RuleIdentityUpgradeCommandV2,
        *,
        baseline: RuleReviewedPolicyBaselineV2,
    ) -> RuleActivationAuthorityPointerV2:
        """Atomically fence v1 and install the sole authoritative v2 pointer."""

        validated = RuleIdentityUpgradeCommandV2.model_validate_json(command.model_dump_json())
        reviewed = RuleReviewedPolicyBaselineV2.model_validate_json(baseline.model_dump_json())
        proposal = validated.proposal
        if reviewed.baseline_digest != proposal.policy_baseline_digest:
            raise RuleIdentityUpgradeConflictError(
                "Rule identity upgrade baseline does not match the proposal"
            )
        if reviewed.reviewed_at > proposal.proposed_at:
            raise RuleIdentityUpgradeConflictError(
                "Rule identity upgrade baseline was reviewed after the proposal"
            )
        legacy = await self._legacy_ledger.current_generation()
        if legacy is None:
            raise RuleIdentityUpgradeConflictError(
                "Rule identity upgrade source generation is unavailable"
            )
        if (
            legacy.generation_id != proposal.source_generation_id
            or legacy.generation_digest != proposal.source_generation_digest
            or legacy.profile_id != proposal.target_identity.profile_snapshot.profile_id
            or legacy.profile_version != proposal.target_identity.profile_snapshot.profile_version
        ):
            raise RuleIdentityUpgradeConflictError(
                "Rule identity upgrade source generation identity mismatch"
            )
        self._validate_reviewed_mapping(legacy.members, reviewed, validated)
        await self._validate_verified_manifest(reviewed, validated)
        acknowledgement_set_digest, lease_expires_at = await self._validate_cohort(
            validated,
            reviewed,
        )
        if not await self._authorizer.authorize_identity_upgrade(
            validated.approval,
            proposal=proposal,
            baseline=reviewed,
        ):
            raise RuleIdentityUpgradeConflictError(
                "Rule identity upgrade approval is not authoritative"
            )

        existing = await self._read_v2_pointer()
        if existing is not None:
            if existing.upgrade_command_digest == validated.command_digest:
                await self._verify_fence(existing)
                return existing
            raise RuleIdentityUpgradeConflictError(
                "Another Rule activation v2 authority pointer already exists"
            )

        raw_v1, v1_body = await self._read_v1_pointer()
        if (
            v1_body.get("generation_id") != legacy.generation_id
            or v1_body.get("generation_digest") != legacy.generation_digest
        ):
            raise RuleIdentityUpgradeConflictError(
                "Rule identity upgrade source pointer changed before cutover"
            )
        if v1_body.get("v2_authoritative") is True:
            raise RuleIdentityUpgradeCorruptionError(
                "Rule activation v1 is fenced without a readable v2 pointer"
            )
        pointer = self._build_pointer(
            validated,
            acknowledgement_set_digest=acknowledgement_set_digest,
        )
        frozen_v1 = {
            **raw_v1,
            "revision": _revision(v1_body) + 1,
            "v2_authoritative": True,
            "v2_pointer_digest": pointer.pointer_digest,
            "v2_upgrade_command_digest": validated.command_digest,
        }
        changed = await self._store.compare_and_set_state_with_audit_and_insert_before(
            _V1_CURRENT_KEY,
            frozen_v1,
            expected_revision=_revision(v1_body),
            insert_key=_V2_CURRENT_KEY,
            insert_value=pointer.model_dump(mode="json"),
            not_before=validated.commanded_at,
            expires_at=lease_expires_at,
            audit_entry={
                "actor": validated.approval.approver_ids[-1],
                "producer_principal": "Saga",
                "action_kind": "rule_activation.identity-upgraded",
                "source_generation_digest": proposal.source_generation_digest,
                "target_generation_digest": pointer.active_generation.generation_digest,
                "signed_manifest_digest": proposal.signed_manifest_digest,
                "policy_baseline_digest": proposal.policy_baseline_digest,
                "cohort_prepare_digest": proposal.cohort_prepare_digest,
                "acknowledgement_set_digest": acknowledgement_set_digest,
                "approval_digest": validated.approval.approval_digest,
                "command_digest": validated.command_digest,
                "recorded_at": validated.commanded_at.isoformat(),
                "activation_authority": True,
                "execution_authority": False,
            },
        )
        if not changed:
            winner = await self._read_v2_pointer()
            if winner is not None and winner.upgrade_command_digest == validated.command_digest:
                await self._verify_fence(winner)
                return winner
            raise RuleIdentityUpgradeConflictError("Rule identity upgrade authority CAS conflict")
        readback = await self.current_authority_pointer()
        if readback is None or readback.pointer_digest != pointer.pointer_digest:
            raise RuleIdentityUpgradeCorruptionError(
                "Rule identity upgrade authoritative readback failed"
            )
        return readback

    async def current_authority_pointer(self) -> RuleActivationAuthorityPointerV2 | None:
        """Read back an approved v2 pointer; startup never originates one."""

        pointer = await self._read_v2_pointer()
        _, v1_body = await self._read_v1_pointer()
        fenced = v1_body.get("v2_authoritative") is True
        if pointer is None:
            if fenced:
                raise RuleIdentityUpgradeCorruptionError(
                    "Rule activation v1 is fenced without a v2 authority pointer"
                )
            return None
        if not fenced:
            raise RuleIdentityUpgradeCorruptionError(
                "Rule activation v2 pointer exists without the v1 authority fence"
            )
        await self._verify_fence(pointer, v1_body=v1_body)
        return pointer

    @staticmethod
    def _validate_reviewed_mapping(
        legacy_members: tuple[Any, ...],
        baseline: RuleReviewedPolicyBaselineV2,
        command: RuleIdentityUpgradeCommandV2,
    ) -> None:
        proposal = command.proposal
        if baseline.release_id != proposal.release_id:
            raise RuleIdentityUpgradeConflictError(
                "Rule identity upgrade baseline release mismatch"
            )
        if tuple(entry.legacy_member for entry in baseline.entries) != legacy_members:
            raise RuleIdentityUpgradeConflictError(
                "Rule identity upgrade baseline does not cover the exact v1 members"
            )
        target_members = proposal.target_identity.profile_snapshot.members
        if tuple(entry.revision for entry in baseline.entries) != target_members:
            raise RuleIdentityUpgradeConflictError(
                "Rule identity upgrade target members differ from the reviewed baseline"
            )

    async def _validate_verified_manifest(
        self,
        baseline: RuleReviewedPolicyBaselineV2,
        command: RuleIdentityUpgradeCommandV2,
    ) -> None:
        proposal = command.proposal
        raw = await self._store.find_state(
            _MANIFEST_PREFIX,
            field="manifest_digest",
            value=proposal.signed_manifest_digest,
        )
        target = proposal.target_identity
        expected = {
            "release_id": proposal.release_id,
            "target_generation_id": target.generation.generation_id,
            "target_generation_digest": target.generation.generation_digest,
            "profile_id": target.profile_snapshot.profile_id,
            "profile_version": target.profile_snapshot.profile_version,
            "catalog_manifest_digest": target.catalog_manifest.manifest_digest,
            "revision_registry_root": baseline.revision_registry_root,
            "members": [member.model_dump(mode="json") for member in target.generation.members],
        }
        if raw is None or any(raw.get(key) != value for key, value in expected.items()):
            raise RuleIdentityUpgradeConflictError(
                "Rule identity upgrade signed manifest verification is unavailable"
            )

    async def _validate_cohort(
        self,
        command: RuleIdentityUpgradeCommandV2,
        baseline: RuleReviewedPolicyBaselineV2,
    ) -> tuple[str, datetime]:
        proposal = command.proposal
        cohort = await self._cohort_ledger.cohort(proposal.cohort_prepare_digest)
        target = proposal.target_identity
        if (
            cohort.generation != target.generation
            or cohort.catalog_manifest_digest != target.catalog_manifest.manifest_digest
            or cohort.revision_registry_root != baseline.revision_registry_root
            or any(replica.release_id != proposal.release_id for replica in cohort.replicas)
        ):
            raise RuleIdentityUpgradeConflictError(
                "Rule identity upgrade cohort does not match the target release"
            )
        candidate = await self._cohort_ledger.candidate_active()
        if (
            candidate.prepare_digest != cohort.prepare_digest
            or candidate.generation_digest != cohort.generation.generation_digest
        ):
            raise RuleIdentityUpgradeConflictError(
                "Rule identity upgrade cohort is not candidate-active"
            )
        evidence_by_replica = {
            item.replica.replica_id: item for item in command.compatibility_evidence
        }
        if tuple(evidence_by_replica) != tuple(replica.replica_id for replica in cohort.replicas):
            raise RuleIdentityUpgradeConflictError(
                "Rule identity upgrade lacks exact serving-replica compatibility evidence"
            )
        acknowledgements: list[RuleReplicaAcknowledgementV2] = []
        for replica in cohort.replicas:
            compatibility = evidence_by_replica[replica.replica_id]
            applied = await self._cohort_ledger.applied(cohort.prepare_digest, replica.replica_id)
            acknowledgement = await self._cohort_ledger.acknowledgement(
                cohort.prepare_digest,
                replica.replica_id,
            )
            if (
                compatibility.replica != replica
                or compatibility.signed_manifest_digest != proposal.signed_manifest_digest
                or acknowledgement is None
                or compatibility.supported_read_schema_versions
                != acknowledgement.supported_read_schema_versions
                or compatibility.write_schema_version != acknowledgement.write_schema_version
                or compatibility.authentication_receipt_digest
                != acknowledgement.authentication_receipt_digest
                or compatibility.verifier_principal_id != acknowledgement.principal_id
                or compatibility.verified_at != acknowledgement.observed_at
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
                raise RuleIdentityUpgradeConflictError(
                    "Rule identity upgrade replica evidence is incomplete"
                )
            acknowledgements.append(acknowledgement)
        if (
            rule_acknowledgement_set_digest(tuple(acknowledgements))
            != candidate.acknowledgement_set_digest
        ):
            raise RuleIdentityUpgradeConflictError(
                "Rule identity upgrade acknowledgement set is inconsistent"
            )
        return (
            candidate.acknowledgement_set_digest,
            min(replica.serving_lease_expires_at for replica in cohort.replicas),
        )

    @staticmethod
    def _build_pointer(
        command: RuleIdentityUpgradeCommandV2,
        *,
        acknowledgement_set_digest: str,
    ) -> RuleActivationAuthorityPointerV2:
        proposal = command.proposal
        return RuleActivationAuthorityPointerV2(
            revision=1,
            source_generation_digest=proposal.source_generation_digest,
            active_generation=proposal.target_identity.generation,
            signed_manifest_digest=proposal.signed_manifest_digest,
            release_id=proposal.release_id,
            policy_baseline_digest=proposal.policy_baseline_digest,
            cohort_prepare_digest=proposal.cohort_prepare_digest,
            acknowledgement_set_digest=acknowledgement_set_digest,
            upgrade_command_digest=command.command_digest,
            activated_at=command.commanded_at,
            pointer_digest=rule_activation_authority_pointer_v2_digest(
                revision=1,
                source_generation_digest=proposal.source_generation_digest,
                active_generation=proposal.target_identity.generation,
                signed_manifest_digest=proposal.signed_manifest_digest,
                release_id=proposal.release_id,
                policy_baseline_digest=proposal.policy_baseline_digest,
                cohort_prepare_digest=proposal.cohort_prepare_digest,
                acknowledgement_set_digest=acknowledgement_set_digest,
                upgrade_command_digest=command.command_digest,
                activated_at=command.commanded_at,
            ),
        )

    async def _read_v1_pointer(self) -> tuple[dict[str, Any], Mapping[str, object]]:
        raw = await self._store.read_state(_V1_CURRENT_KEY)
        if raw is None:
            raise RuleIdentityUpgradeConflictError(
                "Rule identity upgrade source pointer is unavailable"
            )
        try:
            decoded = decode_rule_activation_record(
                raw,
                expected_kind=RuleActivationRecordKind.POINTER,
            )
            if decoded.schema_version != "1.0.0":
                raise ValueError
            body = decoded.body
            _revision(body)
        except (TypeError, ValueError) as exc:
            raise RuleIdentityUpgradeCorruptionError(
                "Rule activation v1 pointer failed validation"
            ) from exc
        return dict(raw), body

    async def _read_v2_pointer(self) -> RuleActivationAuthorityPointerV2 | None:
        raw = await self._store.read_state(_V2_CURRENT_KEY)
        if raw is None:
            return None
        try:
            return RuleActivationAuthorityPointerV2.model_validate(raw)
        except ValueError as exc:
            raise RuleIdentityUpgradeCorruptionError(
                "Rule activation v2 authority pointer failed validation"
            ) from exc

    async def _verify_fence(
        self,
        pointer: RuleActivationAuthorityPointerV2,
        *,
        v1_body: Mapping[str, object] | None = None,
    ) -> None:
        if v1_body is None:
            _, v1_body = await self._read_v1_pointer()
        if (
            v1_body.get("v2_authoritative") is not True
            or v1_body.get("v2_pointer_digest") != pointer.pointer_digest
            or v1_body.get("v2_upgrade_command_digest") != pointer.upgrade_command_digest
            or v1_body.get("generation_digest") != pointer.source_generation_digest
        ):
            raise RuleIdentityUpgradeCorruptionError(
                "Rule activation v1/v2 authority fence mismatch"
            )


def _revision(pointer: Mapping[str, object]) -> int:
    revision = pointer.get("revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise ValueError("Rule activation pointer revision is invalid")
    return revision


__all__ = [
    "RuleIdentityUpgradeConflictError",
    "RuleIdentityUpgradeCorruptionError",
    "StateStoreRuleIdentityUpgrade",
]
