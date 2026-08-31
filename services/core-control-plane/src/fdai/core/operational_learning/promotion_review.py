"""Independent reviewed-replay authority for operational-learning promotion."""

from __future__ import annotations

import re
from dataclasses import dataclass

from fdai.core.measurement import OperationalPromotionReceipt
from fdai.shared.contracts.models import OntologyActionType

_GIT_REVISION = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_IDENTIFIER = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_LEARNING_AGENTS = frozenset({"Norns", "Mimir"})


@dataclass(frozen=True, slots=True)
class ReviewedReplayPromotionEvidence:
    """One approved review over an exact inert package and replay."""

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
    review_ref: str
    reviewer_principal: str
    approved: bool

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
        ):
            if _SHA256.fullmatch(value) is None:
                raise ValueError("reviewed replay digests MUST be lowercase SHA-256")
        if self.replay_first_digest != self.replay_second_digest:
            raise ValueError("reviewed replay results MUST be deterministic")
        if (
            not self.review_ref
            or len(self.review_ref) > 512
            or not self.reviewer_principal
            or self.reviewer_principal in _LEARNING_AGENTS
        ):
            raise ValueError("reviewed replay requires an independent reviewer")
        if not isinstance(self.approved, bool):
            raise ValueError("reviewed replay approval MUST be boolean")


class ReviewedReplayAuthority:
    """Match O7 receipts and persisted records to independently reviewed replay."""

    def __init__(self, evidence: tuple[ReviewedReplayPromotionEvidence, ...]) -> None:
        self._evidence = {
            (
                item.action_type,
                item.action_type_version,
                item.action_type_digest,
                item.fdai_revision,
                item.scenario_set_version,
                item.promotion_evidence_digest,
            ): item
            for item in evidence
        }
        if len(self._evidence) != len(evidence):
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
    ) -> bool:
        """Return whether one exact persisted or incoming authority tuple is approved."""

        evidence = self._evidence.get(
            (
                action_type,
                action_type_version,
                action_type_digest,
                fdai_revision,
                scenario_set_version,
                evidence_digest,
            )
        )
        return evidence is not None and evidence.approved


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
        return self._authority.accepts(
            action_type=action_type.name,
            action_type_version=receipt.action_type_version,
            action_type_digest=receipt.action_type_digest,
            fdai_revision=receipt.fdai_revision,
            scenario_set_version=receipt.scenario_set_version,
            evidence_digest=receipt.evidence_digest,
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
    ) -> bool:
        return self._authority.accepts(
            action_type=action_type,
            action_type_version=action_type_version,
            action_type_digest=action_type_digest,
            fdai_revision=fdai_revision,
            scenario_set_version=scenario_set_version,
            evidence_digest=evidence_digest,
        )


__all__ = [
    "ReviewedReplayAuthority",
    "ReviewedReplayPersistedAuthorityVerifier",
    "ReviewedReplayPromotionEvidence",
    "ReviewedReplayReceiptVerifier",
]
