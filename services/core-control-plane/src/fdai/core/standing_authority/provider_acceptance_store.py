"""Atomic store seam and acquisition classification for provider acceptance."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Literal, Protocol, Self, runtime_checkable

from fdai.core.standing_authority.lifecycle_codec import (
    AuthorizationLifecycleError,
    content_digest,
    require_digest,
)
from fdai.core.standing_authority.provider_acceptance import (
    ProviderAcceptanceIdentity,
    ProviderAcceptanceRecord,
    ProviderAcceptanceState,
)

PROCESS_LOCAL_LINEARIZATION = "process_local"


class ProviderAcceptanceAcquireDecision(StrEnum):
    """Disposition of one target-fence-keyed preparation attempt."""

    PERMITTED = "permitted"
    DUPLICATE_SAME = "duplicate_same"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class ProviderSubmissionPermit:
    """One-shot process-local permit bound to an exact prepared record."""

    schema_version: Literal["1.0.0"]
    target_fence_digest: str
    identity_digest: str
    prepared_record_digest: str
    expected_revision: Literal[1]
    permit_digest: str
    execution_authority: Literal[False] = False
    effect_verification_authority: Literal[False] = False
    promotion_authority: Literal[False] = False
    production_eligible: Literal[False] = False

    def __post_init__(self) -> None:
        if self.schema_version != "1.0.0" or self.expected_revision != 1:
            raise AuthorizationLifecycleError("unsupported provider submission permit")
        for name, value in (
            ("target_fence_digest", self.target_fence_digest),
            ("identity_digest", self.identity_digest),
            ("prepared_record_digest", self.prepared_record_digest),
            ("permit_digest", self.permit_digest),
        ):
            require_digest(name, value)
        if any(
            (
                self.execution_authority,
                self.effect_verification_authority,
                self.promotion_authority,
                self.production_eligible,
            )
        ):
            raise AuthorizationLifecycleError(
                "provider submission permit MUST remain no-authority and ineligible"
            )
        expected = _permit_digest(self)
        if self.permit_digest != expected:
            raise AuthorizationLifecycleError("provider submission permit digest mismatch")

    @classmethod
    def create(cls, record: ProviderAcceptanceRecord) -> Self:
        """Create the sole permit associated with an inserted prepared record."""

        if record.state is not ProviderAcceptanceState.PREPARED or record.revision != 1:
            raise AuthorizationLifecycleError(
                "provider submission permit requires the initial prepared record"
            )
        values: dict[str, object] = {
            "schema_version": "1.0.0",
            "target_fence_digest": record.identity.target_fence_digest,
            "identity_digest": record.identity.identity_digest,
            "prepared_record_digest": record.record_digest,
            "expected_revision": 1,
            "execution_authority": False,
            "effect_verification_authority": False,
            "promotion_authority": False,
            "production_eligible": False,
        }
        values["permit_digest"] = content_digest(
            {
                "domain": "provider-submission-permit",
                **values,
            }
        )
        return cls(**values)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class ProviderAcceptanceAcquireResult:
    """Atomic preparation result with a permit only for a new insertion."""

    candidate_identity: ProviderAcceptanceIdentity
    decision: ProviderAcceptanceAcquireDecision
    observed_record: ProviderAcceptanceRecord
    permit: ProviderSubmissionPermit | None

    def __post_init__(self) -> None:
        if self.decision is ProviderAcceptanceAcquireDecision.PERMITTED:
            if (
                self.permit is None
                or self.observed_record.identity != self.candidate_identity
                or self.observed_record.state is not ProviderAcceptanceState.PREPARED
                or self.observed_record.revision != 1
                or self.permit.identity_digest != self.candidate_identity.identity_digest
                or self.permit.prepared_record_digest != self.observed_record.record_digest
            ):
                raise AuthorizationLifecycleError(
                    "permitted provider acceptance requires the exact prepared record"
                )
        else:
            if self.permit is not None:
                raise AuthorizationLifecycleError(
                    "observed provider acceptance MUST NOT issue a permit"
                )
            if self.decision is not classify_provider_acceptance(
                self.observed_record,
                self.candidate_identity,
            ):
                raise AuthorizationLifecycleError(
                    "provider acceptance decision mismatched candidate"
                )


@dataclass(frozen=True, slots=True)
class ProviderAcceptanceTransitionReceipt:
    """Exact readback proof for one accepted state transition."""

    prior_record_digest: str
    record: ProviderAcceptanceRecord
    receipt_digest: str
    execution_authority: Literal[False] = False
    effect_verification_authority: Literal[False] = False

    def __post_init__(self) -> None:
        require_digest("prior_record_digest", self.prior_record_digest)
        require_digest("receipt_digest", self.receipt_digest)
        if (
            self.record.prior_record_digest != self.prior_record_digest
            or self.execution_authority is not False
            or self.effect_verification_authority is not False
        ):
            raise AuthorizationLifecycleError(
                "provider acceptance transition receipt is inconsistent"
            )
        expected = content_digest(
            {
                "domain": "provider-acceptance-transition-receipt",
                "prior_record_digest": self.prior_record_digest,
                "record_digest": self.record.record_digest,
                "execution_authority": False,
                "effect_verification_authority": False,
            }
        )
        if self.receipt_digest != expected:
            raise AuthorizationLifecycleError(
                "provider acceptance transition receipt digest mismatch"
            )

    @classmethod
    def create(
        cls,
        *,
        prior_record_digest: str,
        record: ProviderAcceptanceRecord,
    ) -> Self:
        """Build exact readback evidence for one compare-and-set transition."""

        receipt_digest = content_digest(
            {
                "domain": "provider-acceptance-transition-receipt",
                "prior_record_digest": prior_record_digest,
                "record_digest": record.record_digest,
                "execution_authority": False,
                "effect_verification_authority": False,
            }
        )
        return cls(
            prior_record_digest=prior_record_digest,
            record=record,
            receipt_digest=receipt_digest,
        )


@runtime_checkable
class ProviderAcceptanceStore(Protocol):
    """Target-keyed atomic preparation, CAS transition, and readback seam."""

    linearization_scope: str

    async def acquire_prepared(
        self,
        record: ProviderAcceptanceRecord,
    ) -> ProviderAcceptanceAcquireResult: ...

    async def compare_and_transition(
        self,
        *,
        prior_record_digest: str,
        expected_revision: int,
        record: ProviderAcceptanceRecord,
    ) -> ProviderAcceptanceTransitionReceipt: ...

    async def read(
        self,
        target_fence_digest: str,
    ) -> ProviderAcceptanceRecord | None: ...


def classify_provider_acceptance(
    existing: ProviderAcceptanceRecord,
    candidate: ProviderAcceptanceIdentity,
) -> ProviderAcceptanceAcquireDecision:
    """Classify a candidate without granting submission authority."""

    if existing.identity.target_fence_digest != candidate.target_fence_digest:
        raise AuthorizationLifecycleError("provider acceptance classifier target fence mismatch")
    if existing.identity.identity_digest == candidate.identity_digest:
        return ProviderAcceptanceAcquireDecision.DUPLICATE_SAME
    return ProviderAcceptanceAcquireDecision.BLOCKED


def provider_submission_blocked(
    record: ProviderAcceptanceRecord | None,
) -> bool:
    """Block resubmission for every existing state, including non-acceptance."""

    return record is not None


def _permit_digest(permit: ProviderSubmissionPermit) -> str:
    values = asdict(permit)
    values.pop("permit_digest", None)
    return content_digest(
        {
            "domain": "provider-submission-permit",
            **values,
        }
    )


__all__ = [
    "PROCESS_LOCAL_LINEARIZATION",
    "ProviderAcceptanceAcquireDecision",
    "ProviderAcceptanceAcquireResult",
    "ProviderAcceptanceStore",
    "ProviderAcceptanceTransitionReceipt",
    "ProviderSubmissionPermit",
    "classify_provider_acceptance",
    "provider_submission_blocked",
]
