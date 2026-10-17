"""Reviewed-replay authority for production and profile-scoped development."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from fdai.core.case_history import CaseHistoryMaterializer
from fdai.core.measurement import OperationalPromotionReceipt
from fdai.core.measurement.operational_promotion import (
    OperationalPromotionEvaluator,
    action_type_digest,
    operational_promotion_receipt_digest,
)
from fdai.core.measurement.operational_promotion_runner import OperationalPromotionEvidenceSource
from fdai.core.measurement.promotion_binding import ReviewedReplayBinding
from fdai.shared.contracts.development_authority import (
    canonical_authority_digest,
    development_promotion_target_digest,
    revalidate_development_authority,
)
from fdai.shared.contracts.models import (
    DevelopmentActionConfirmation,
    DevelopmentAuthorityGrant,
    DevelopmentBindingVerification,
    DevelopmentPromotionApproval,
    FullAuthorityDevelopmentProfile,
    OntologyActionType,
)
from fdai.shared.providers.case_history import CaseHistoryMetadataStore
from fdai.shared.providers.decision_evidence_verifier import DecisionEvidenceAdmissionProvider
from fdai.shared.providers.development_authority import (
    DevelopmentAuthorityBindingRequest,
    DevelopmentAuthorityBindingSource,
    resolve_development_binding,
)

from .promotion_revalidation import PreparedReplayReview, prepare_replay_review

_LOG = logging.getLogger(__name__)
_GIT_REVISION = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_IDENTIFIER = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_LEARNING_AGENTS = frozenset({"norns", "mimir"})


def _normalized_principal(value: str) -> str:
    """Canonical form of a reviewer identifier for identity comparison.

    Principal spellings differ in case and surrounding space, so the learner
    agent could otherwise be recorded as its own independent reviewer.
    """

    return value.strip().casefold()


@dataclass(frozen=True, slots=True)
class ReviewedReplayPromotionEvidence:
    """Inert review attribution over an exact package and replay.

    The reviewer identity is compared case-insensitively against the learning
    agents, so ``Norns`` cannot re-enter as ``norns`` and review its own
    promotion evidence. Production authority still requires independent
    admissions and current scoped source revalidation; these fields alone
    never prove an approval.
    """

    action_type: str
    action_type_version: str
    action_type_digest: str
    fdai_revision: str
    scenario_set_version: str
    candidate_digest: str
    package_digest: str
    replay_first_digest: str
    replay_second_digest: str
    promotion_evidence_digest: str
    promotion_policy_digest: str
    review_ref: str
    reviewer_principal: str
    approved: bool
    reviewer_role: Literal["independent_reviewer", "owner"] = "independent_reviewer"
    development_confirmation: DevelopmentActionConfirmation | None = None
    development_binding_verification: DevelopmentBindingVerification | None = None
    development_grant: DevelopmentAuthorityGrant | None = None
    development_binding_request: DevelopmentAuthorityBindingRequest | None = None
    reviewed_replay_binding: ReviewedReplayBinding | None = None

    def __post_init__(self) -> None:
        if _IDENTIFIER.fullmatch(self.action_type) is None:
            raise ValueError("reviewed replay action type MUST be canonical")
        if not self.action_type_version or _SHA256.fullmatch(self.action_type_digest) is None:
            raise ValueError("reviewed replay ActionType identity MUST be complete")
        if _GIT_REVISION.fullmatch(self.fdai_revision) is None:
            raise ValueError("reviewed replay FDAI revision MUST be immutable")
        if _IDENTIFIER.fullmatch(self.scenario_set_version) is None:
            raise ValueError("reviewed replay scenario set MUST be canonical")
        for value in (
            self.candidate_digest,
            self.package_digest,
            self.replay_first_digest,
            self.replay_second_digest,
            self.promotion_evidence_digest,
            self.promotion_policy_digest,
        ):
            if _SHA256.fullmatch(value) is None:
                raise ValueError("reviewed replay digests MUST be lowercase SHA-256")
        if self.replay_first_digest != self.replay_second_digest:
            raise ValueError("reviewed replay results MUST be deterministic")
        if (
            not self.review_ref
            or len(self.review_ref) > 512
            or not self.reviewer_principal.strip()
            or len(self.reviewer_principal) > 512
            or _normalized_principal(self.reviewer_principal) in _LEARNING_AGENTS
        ):
            raise ValueError("reviewed replay requires an independent reviewer")
        if not isinstance(self.approved, bool):
            raise ValueError("reviewed replay approval MUST be boolean")
        if self.reviewer_role not in {"independent_reviewer", "owner"}:
            raise ValueError("reviewed replay reviewer role is invalid")
        binding = self.reviewed_replay_binding
        if binding is not None and (
            not isinstance(binding, ReviewedReplayBinding)
            or (
                binding.candidate_digest,
                binding.package_digest,
                binding.replay_first_digest,
                binding.replay_second_digest,
            )
            != (
                self.candidate_digest,
                self.package_digest,
                self.replay_first_digest,
                self.replay_second_digest,
            )
        ):
            raise ValueError("reviewed replay binding does not match reviewed artifacts")
        development_parts = (
            self.development_confirmation,
            self.development_binding_verification,
            self.development_grant,
            self.development_binding_request,
        )
        if self.reviewer_role == "owner" and any(part is None for part in development_parts):
            raise ValueError("Owner promotion review requires complete development authority")
        if self.reviewer_role == "independent_reviewer" and any(
            part is not None for part in development_parts
        ):
            raise ValueError("independent promotion review cannot carry development authority")

    @property
    def development_only(self) -> bool:
        return self.reviewer_role == "owner"

    @property
    def promotion_target_digest(self) -> str:
        """Bind development confirmation parameters to the exact promoted tuple."""

        return development_promotion_target_digest(
            action_type=self.action_type,
            action_type_version=self.action_type_version,
            action_type_digest="sha256:" + self.action_type_digest,
            reviewed_replay_digest=self.reviewed_replay_digest,
            source_revision=self.fdai_revision,
            scenario_set_version=self.scenario_set_version,
            promotion_evidence_digest="sha256:" + self.promotion_evidence_digest,
        )

    @property
    def reviewed_replay_digest(self) -> str:
        material = {
            "candidate_digest": self.candidate_digest,
            "package_digest": self.package_digest,
            "replay_first_digest": self.replay_first_digest,
            "replay_second_digest": self.replay_second_digest,
            "promotion_evidence_digest": self.promotion_evidence_digest,
            "promotion_policy_digest": self.promotion_policy_digest,
            "review_ref": self.review_ref,
            "reviewer_principal": self.reviewer_principal,
            "approved": self.approved,
        }
        if self.reviewed_replay_binding is not None:
            material.update(
                {
                    "action_type": self.action_type,
                    "action_type_version": self.action_type_version,
                    "action_type_digest": self.action_type_digest,
                    "fdai_revision": self.fdai_revision,
                    "scenario_set_version": self.scenario_set_version,
                    "reviewer_role": self.reviewer_role,
                    "reviewed_replay_binding": self.reviewed_replay_binding.to_mapping(),
                }
            )
        return canonical_authority_digest(material)


class ReviewedReplayAuthority:
    """Match exact replay subjects, with production unavailable until prepared.

    Production checks consume a short-lived asynchronous preparation, never
    perform synchronous I/O, and never restore a serialized preparation.
    Profile-scoped development authority remains a separate namespace.
    """

    def __init__(
        self,
        evidence: tuple[ReviewedReplayPromotionEvidence, ...],
        *,
        development_profile: FullAuthorityDevelopmentProfile | None = None,
        development_binding_source: DevelopmentAuthorityBindingSource | None = None,
        development_action_types: dict[str, OntologyActionType] | None = None,
        clock: Callable[[], datetime] | None = None,
        production_evidence_source: OperationalPromotionEvidenceSource | None = None,
        production_admission_provider: DecisionEvidenceAdmissionProvider | None = None,
        case_materializer: CaseHistoryMaterializer | None = None,
        case_metadata: CaseHistoryMetadataStore | None = None,
        production_action_types: dict[str, OntologyActionType] | None = None,
        production_evaluator: OperationalPromotionEvaluator | None = None,
    ) -> None:
        if (
            case_materializer is not None
            and case_metadata is not None
            and case_materializer._metadata is not case_metadata
        ):
            raise ValueError("reviewed replay MUST use the materializer's authoritative metadata")
        self._clock = clock or (lambda: datetime.now(tz=UTC))
        self._production_source = production_evidence_source
        self._production_admissions = production_admission_provider
        self._case_materializer = case_materializer
        self._case_metadata = case_metadata
        self._production_action_types = dict(production_action_types or {})
        self._production_evaluator = production_evaluator
        self._prepared: dict[tuple[str, ...], PreparedReplayReview] = {}
        self._preparing: dict[tuple[str, ...], object] = {}
        self._evidence = {
            (
                item.action_type,
                item.action_type_version,
                item.action_type_digest,
                item.fdai_revision,
                item.scenario_set_version,
                item.promotion_evidence_digest,
                item.promotion_policy_digest,
            ): item
            for item in evidence
            if not item.development_only
        }
        development_items = tuple(item for item in evidence if item.development_only)
        self._development_evidence: dict[
            tuple[str, str, str, str, str, str, str, str],
            ReviewedReplayPromotionEvidence,
        ] = {}
        now = self._clock()
        for item in development_items:
            confirmation = item.development_confirmation
            persisted_verification = item.development_binding_verification
            grant = item.development_grant
            request = item.development_binding_request
            if (
                development_profile is None
                or confirmation is None
                or persisted_verification is None
                or grant is None
                or request is None
            ):
                raise ValueError("Owner promotion review requires an injected development profile")
            verification = resolve_development_binding(
                development_binding_source,
                request,
                now=now,
            )
            if verification != persisted_verification:
                raise ValueError("Owner promotion review binding changed")
            promotion_action = (development_action_types or {}).get(
                verification.binding.action_type
            )
            if (
                promotion_action is None
                or verification.binding.action_type_version != promotion_action.version
                or verification.binding.action_type_digest
                != "sha256:" + action_type_digest(promotion_action)
            ):
                raise ValueError("Owner promotion action does not match current ActionType")
            decision = revalidate_development_authority(
                development_profile,
                confirmation,
                verification,
                grant,
                now=now,
                original_quorum=grant.original_quorum,
            )
            if (
                not decision.eligible
                or _normalized_principal(item.reviewer_principal)
                != _normalized_principal(development_profile.owner_principal)
                or verification.binding.params_digest != item.promotion_target_digest
            ):
                raise ValueError(
                    "Owner promotion review does not match exact development authority"
                )
            key = (
                grant.profile_digest,
                item.action_type,
                item.action_type_version,
                item.action_type_digest,
                item.fdai_revision,
                item.scenario_set_version,
                item.promotion_evidence_digest,
                item.promotion_policy_digest,
            )
            if key in self._development_evidence:
                raise ValueError("reviewed replay authority identities MUST be unique")
            self._development_evidence[key] = item
        if len(self._evidence) + len(self._development_evidence) != len(evidence):
            raise ValueError("reviewed replay authority identities MUST be unique")

    def accepts(
        self,
        *,
        action_type: str,
        action_type_version: str,
        action_type_digest: str,
        fdai_revision: str,
        scenario_set_version: str,
        evidence_digest: str,
        policy_digest: str,
    ) -> bool:
        """Consume a current single-use preparation for one exact authority tuple."""

        key = (
            action_type,
            action_type_version,
            action_type_digest,
            fdai_revision,
            scenario_set_version,
            evidence_digest,
            policy_digest,
        )
        proof = self._prepared.pop(key, None)
        return proof is not None and proof.current(self._clock())

    async def prepare(
        self,
        *,
        action_type: str,
        action_type_version: str,
        action_type_digest: str,
        fdai_revision: str,
        scenario_set_version: str,
        evidence_digest: str,
        policy_digest: str,
    ) -> bool:
        """Prepare one single-use production check; missing bindings stay unavailable.

        Call immediately before synchronous promotion. Restart validation calls this
        again, never trusting a serialized proof or a timeless source-state cache.
        A concurrent newer preparation supersedes this attempt, including on failure.
        """
        key = (
            action_type,
            action_type_version,
            action_type_digest,
            fdai_revision,
            scenario_set_version,
            evidence_digest,
            policy_digest,
        )
        self._prepared.pop(key, None)
        generation = object()
        self._preparing[key] = generation
        evidence = self._evidence.get(key)
        current_action = self._production_action_types.get(action_type)
        try:
            if (
                evidence is None
                or self._production_source is None
                or self._production_admissions is None
                or self._case_materializer is None
                or self._case_metadata is None
                or self._production_evaluator is None
                or current_action is None
            ):
                return False
            proof = await prepare_replay_review(
                evidence,
                source=self._production_source,
                admission_provider=self._production_admissions,
                materializer=self._case_materializer,
                case_metadata=self._case_metadata,
                action_type=current_action,
                evaluator=self._production_evaluator,
                clock=self._clock,
            )
            if (
                proof is None
                or self._preparing.get(key) is not generation
                or not proof.current(self._clock())
            ):
                return False
            self._prepared[key] = proof
            return True
        except Exception as exc:  # noqa: BLE001 - async provider boundary, deny without retry
            _LOG.warning("reviewed replay preparation failed: %s", type(exc).__name__)
            return False
        finally:
            if self._preparing.get(key) is generation:
                self._preparing.pop(key)

    def authorize_development(
        self,
        *,
        profile_digest: str,
        action_type: OntologyActionType,
        fdai_revision: str,
        scenario_set_version: str,
        evidence_digest: str,
        policy_digest: str,
        approved_at: datetime,
    ) -> DevelopmentPromotionApproval | None:
        """Return exact development-only promotion authority for current target."""

        key = (
            profile_digest,
            action_type.name,
            action_type.version,
            action_type_digest(action_type),
            fdai_revision,
            scenario_set_version,
            evidence_digest,
            policy_digest,
        )
        evidence = self._development_evidence.get(key)
        if evidence is None or not evidence.approved:
            return None
        verification = evidence.development_binding_verification
        grant = evidence.development_grant
        if verification is None or grant is None:
            return None
        return DevelopmentPromotionApproval(
            profile_digest=profile_digest,
            confirmation_digest=grant.confirmation_digest,
            binding_verification_digest=verification.digest,
            promotion_action_type=verification.binding.action_type,
            target_action_type=action_type.name,
            target_action_type_version=action_type.version,
            target_action_type_digest="sha256:" + action_type_digest(action_type),
            promotion_target_digest=evidence.promotion_target_digest,
            reviewed_replay_digest=evidence.reviewed_replay_digest,
            fdai_revision=fdai_revision,
            scenario_set_version=scenario_set_version,
            promotion_evidence_digest="sha256:" + evidence_digest,
            review_ref=evidence.review_ref,
            reviewer_principal=evidence.reviewer_principal,
            approved_at=approved_at,
            valid_until=grant.valid_until,
        )

    def accepts_development(
        self,
        *,
        profile_digest: str,
        action_type: str,
        action_type_version: str,
        action_type_digest: str,
        fdai_revision: str,
        scenario_set_version: str,
        evidence_digest: str,
        policy_digest: str,
    ) -> bool:
        """Accept sole-Owner review only in the exact profile namespace."""

        evidence = self._development_evidence.get(
            (
                profile_digest,
                action_type,
                action_type_version,
                action_type_digest,
                fdai_revision,
                scenario_set_version,
                evidence_digest,
                policy_digest,
            )
        )
        return evidence is not None and evidence.approved

    def review_attribution(
        self,
        *,
        profile_digest: str,
        action_type: str,
        action_type_version: str,
        action_type_digest: str,
        fdai_revision: str,
        scenario_set_version: str,
        evidence_digest: str,
        policy_digest: str,
    ) -> dict[str, object] | None:
        """Return explicit development-only attribution for audit."""

        item = self._development_evidence.get(
            (
                profile_digest,
                action_type,
                action_type_version,
                action_type_digest,
                fdai_revision,
                scenario_set_version,
                evidence_digest,
                policy_digest,
            )
        )
        if item is None:
            return None
        return {
            "reviewer_principal": item.reviewer_principal,
            "reviewer_role": item.reviewer_role,
            "development_profile_digest": profile_digest,
            "development_only": True,
            "production_ready": False,
        }


class ReviewedReplayReceiptVerifier:
    """Adapt reviewed replay evidence to the in-process promotion registry."""

    def __init__(self, authority: ReviewedReplayAuthority) -> None:
        self._authority = authority

    def verify(
        self,
        *,
        action_type: OntologyActionType,
        receipt: OperationalPromotionReceipt,
    ) -> bool:
        key = (
            action_type.name,
            receipt.action_type_version,
            receipt.action_type_digest,
            receipt.fdai_revision,
            receipt.scenario_set_version,
            receipt.evidence_digest,
            receipt.policy_digest or "",
        )
        evidence = self._authority._evidence.get(key)
        proof = self._authority._prepared.get(key)
        if (
            evidence is None
            or proof is None
            or receipt.reviewed_replay_binding != evidence.reviewed_replay_binding
            or receipt.action_type_name != action_type.name
            or receipt.action_type_version != action_type.version
            or receipt.action_type_digest != action_type_digest(action_type)
            or receipt.decision_evidence_receipt_digest is None
            or receipt.decision_evidence_verification_bundle_digest is None
            or operational_promotion_receipt_digest(receipt) != proof.evaluated_receipt_digest
        ):
            self._authority._prepared.pop(key, None)
            return False
        return self._authority.accepts(
            action_type=action_type.name,
            action_type_version=receipt.action_type_version,
            action_type_digest=receipt.action_type_digest,
            fdai_revision=receipt.fdai_revision,
            scenario_set_version=receipt.scenario_set_version,
            evidence_digest=receipt.evidence_digest,
            policy_digest=receipt.policy_digest or "",
        )

    def verify_development(
        self,
        *,
        profile_digest: str,
        action_type: OntologyActionType,
        receipt: OperationalPromotionReceipt,
    ) -> bool:
        """Verify one receipt only for a profile-scoped development registry."""

        return self._authority.accepts_development(
            profile_digest=profile_digest,
            action_type=action_type.name,
            action_type_version=receipt.action_type_version,
            action_type_digest=receipt.action_type_digest,
            fdai_revision=receipt.fdai_revision,
            scenario_set_version=receipt.scenario_set_version,
            evidence_digest=receipt.evidence_digest,
            policy_digest=receipt.policy_digest or "",
        )


class ReviewedReplayPersistedAuthorityVerifier:
    """Revalidate durable ENFORCE attribution after restart."""

    def __init__(self, authority: ReviewedReplayAuthority) -> None:
        self._authority = authority

    async def verify(
        self,
        *,
        action_type: str,
        action_type_version: str,
        action_type_digest: str,
        evidence_digest: str,
        fdai_revision: str,
        scenario_set_version: str,
        policy_digest: str,
    ) -> bool:
        if not await self._authority.prepare(
            action_type=action_type,
            action_type_version=action_type_version,
            action_type_digest=action_type_digest,
            fdai_revision=fdai_revision,
            scenario_set_version=scenario_set_version,
            evidence_digest=evidence_digest,
            policy_digest=policy_digest,
        ):
            return False
        return self._authority.accepts(
            action_type=action_type,
            action_type_version=action_type_version,
            action_type_digest=action_type_digest,
            fdai_revision=fdai_revision,
            scenario_set_version=scenario_set_version,
            evidence_digest=evidence_digest,
            policy_digest=policy_digest,
        )


__all__ = [
    "ReviewedReplayAuthority",
    "ReviewedReplayPersistedAuthorityVerifier",
    "ReviewedReplayPromotionEvidence",
    "ReviewedReplayReceiptVerifier",
]
