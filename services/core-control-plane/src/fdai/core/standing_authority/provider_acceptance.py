"""Inert process-local ordering model for provider acceptance attempts.

This module is not distributed atomicity, a provider-side idempotency guarantee,
or evidence of effect success. A deterministic client request id supports
correlation only. ``PREPARED`` and ``UNKNOWN`` are commit-equivalent for safety:
both block resubmission, and nothing in this module resolves ``UNKNOWN``.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal, Self, cast
from uuid import NAMESPACE_URL, UUID, uuid5

from fdai.core.standing_authority.lease import EffectStatus
from fdai.core.standing_authority.lifecycle_codec import (
    AuthorizationLifecycleError,
    aware_utc,
    content_digest,
    instant,
    require_aware,
    require_digest,
    require_text,
)

_REVISION = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_METHOD = "POST"


class ProviderAcceptanceState(StrEnum):
    """Monotonic state of one provider request acceptance attempt."""

    PREPARED = "prepared"
    ACCEPTED = "accepted"
    NOT_ACCEPTED = "not_accepted"
    UNKNOWN = "unknown"


class ProviderNonAcceptanceEvidenceKind(StrEnum):
    """Closed positive evidence set proving that no provider submission was accepted."""

    LOCAL_FENCE_DENIED = "local_fence_denied"
    LOCAL_FENCE_UNAVAILABLE = "local_fence_unavailable"
    PROVIDER_REJECTED_BEFORE_ACCEPTANCE = "provider_rejected_before_acceptance"


class ProviderAcceptanceAmbiguityReason(StrEnum):
    """Reasons a possibly submitted provider request must remain quarantined."""

    SUBMISSION_TIMEOUT = "submission_timeout"
    SUBMISSION_CANCELLED = "submission_cancelled"
    SUBMISSION_EXCEPTION = "submission_exception"
    PROVIDER_RESULT_UNKNOWN = "provider_result_unknown"
    ORPHANED_PREPARED = "orphaned_prepared"


@dataclass(frozen=True, slots=True)
class ProviderAcceptanceIdentity:
    """Exact standing, safeguard, target, and provider request identity."""

    schema_version: Literal["1.0.0"]
    target_fence_digest: str
    family_id: str
    authorization_revision_id: str
    fencing_generation: int
    transition_digest: str
    lease_id: str
    lease_generation: int
    lease_valid_until: datetime
    action_digest: str
    target_digest: str
    provider_method: Literal["POST"]
    provider_api_version: str
    provider_endpoint_digest: str
    provider_resource_digest: str
    provider_body_digest: str
    source_revision_id: str
    safeguard_bundle_digest: str
    reservation_identity_digest: str
    target_fence_generation: int
    acceptance_generation: int
    client_request_id: str
    identity_digest: str
    execution_authority: Literal[False] = False
    effect_verification_authority: Literal[False] = False
    promotion_authority: Literal[False] = False
    production_eligible: Literal[False] = False

    def __post_init__(self) -> None:
        if self.schema_version != "1.0.0":
            raise AuthorizationLifecycleError("unsupported provider acceptance identity schema")
        for name, value in (
            ("target_fence_digest", self.target_fence_digest),
            ("authorization_revision_id", self.authorization_revision_id),
            ("transition_digest", self.transition_digest),
            ("lease_id", self.lease_id),
            ("action_digest", self.action_digest),
            ("target_digest", self.target_digest),
            ("provider_endpoint_digest", self.provider_endpoint_digest),
            ("provider_resource_digest", self.provider_resource_digest),
            ("provider_body_digest", self.provider_body_digest),
            ("safeguard_bundle_digest", self.safeguard_bundle_digest),
            ("reservation_identity_digest", self.reservation_identity_digest),
            ("identity_digest", self.identity_digest),
        ):
            require_digest(name, value)
        require_text("family_id", self.family_id)
        require_text("provider_api_version", self.provider_api_version)
        require_aware("lease_valid_until", self.lease_valid_until)
        if self.provider_method != _METHOD:
            raise AuthorizationLifecycleError("provider acceptance supports POST only")
        if _REVISION.fullmatch(self.source_revision_id) is None:
            raise AuthorizationLifecycleError(
                "provider acceptance source revision MUST be immutable"
            )
        for name, generation_value in (
            ("fencing_generation", self.fencing_generation),
            ("lease_generation", self.lease_generation),
            ("target_fence_generation", self.target_fence_generation),
            ("acceptance_generation", self.acceptance_generation),
        ):
            if isinstance(generation_value, bool) or generation_value < 1:
                raise AuthorizationLifecycleError(f"{name} MUST be positive")
        try:
            canonical_request_id = str(UUID(self.client_request_id))
        except ValueError as exc:
            raise AuthorizationLifecycleError(
                "provider client_request_id MUST be a canonical UUID"
            ) from exc
        if canonical_request_id != self.client_request_id.casefold():
            raise AuthorizationLifecycleError("provider client_request_id MUST be a canonical UUID")
        if any(
            (
                self.execution_authority,
                self.effect_verification_authority,
                self.promotion_authority,
                self.production_eligible,
            )
        ):
            raise AuthorizationLifecycleError(
                "provider acceptance identity MUST remain no-authority and ineligible"
            )
        if self.identity_digest != _payload_digest(
            self,
            "provider-acceptance-identity",
            digest_field="identity_digest",
        ):
            raise AuthorizationLifecycleError("provider acceptance identity digest mismatch")

    @classmethod
    def create(
        cls,
        *,
        target_fence_digest: str,
        family_id: str,
        authorization_revision_id: str,
        fencing_generation: int,
        transition_digest: str,
        lease_id: str,
        lease_generation: int,
        lease_valid_until: datetime,
        action_digest: str,
        target_digest: str,
        provider_api_version: str,
        provider_endpoint_digest: str,
        provider_resource_digest: str,
        provider_body_digest: str,
        source_revision_id: str,
        safeguard_bundle_digest: str,
        reservation_identity_digest: str,
        target_fence_generation: int,
        acceptance_generation: int,
    ) -> Self:
        """Build one exact provider acceptance identity."""

        values: dict[str, object] = {
            "schema_version": "1.0.0",
            "target_fence_digest": target_fence_digest,
            "family_id": family_id,
            "authorization_revision_id": authorization_revision_id,
            "fencing_generation": fencing_generation,
            "transition_digest": transition_digest,
            "lease_id": lease_id,
            "lease_generation": lease_generation,
            "lease_valid_until": aware_utc(lease_valid_until),
            "action_digest": action_digest,
            "target_digest": target_digest,
            "provider_method": _METHOD,
            "provider_api_version": provider_api_version,
            "provider_endpoint_digest": provider_endpoint_digest,
            "provider_resource_digest": provider_resource_digest,
            "provider_body_digest": provider_body_digest,
            "source_revision_id": source_revision_id,
            "safeguard_bundle_digest": safeguard_bundle_digest,
            "reservation_identity_digest": reservation_identity_digest,
            "target_fence_generation": target_fence_generation,
            "acceptance_generation": acceptance_generation,
            "execution_authority": False,
            "effect_verification_authority": False,
            "promotion_authority": False,
            "production_eligible": False,
        }
        request_seed = content_digest(
            {
                "domain": "provider-acceptance-client-request",
                "target_fence_digest": target_fence_digest,
                "provider_endpoint_digest": provider_endpoint_digest,
                "provider_resource_digest": provider_resource_digest,
                "provider_body_digest": provider_body_digest,
                "acceptance_generation": acceptance_generation,
            }
        )
        values["client_request_id"] = str(uuid5(NAMESPACE_URL, request_seed))
        values["identity_digest"] = _payload_digest(
            values,
            "provider-acceptance-identity",
            digest_field="identity_digest",
        )
        return cls(**values)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class ProviderSubmissionResult:
    """No-effect result returned by one scripted provider submission."""

    state: ProviderAcceptanceState
    evidence_digest: str
    non_acceptance_kind: ProviderNonAcceptanceEvidenceKind | None = None
    ambiguity_reason: ProviderAcceptanceAmbiguityReason | None = None
    effect_verified: Literal[False] = False
    execution_authority: Literal[False] = False
    result_digest: str = ""

    def __post_init__(self) -> None:
        if self.state is ProviderAcceptanceState.PREPARED:
            raise AuthorizationLifecycleError("provider submission result MUST be terminal")
        require_digest("evidence_digest", self.evidence_digest)
        if self.state is ProviderAcceptanceState.NOT_ACCEPTED:
            if self.non_acceptance_kind is None or self.ambiguity_reason is not None:
                raise AuthorizationLifecycleError(
                    "not-accepted result requires only non-acceptance evidence"
                )
        elif self.state is ProviderAcceptanceState.UNKNOWN:
            if self.ambiguity_reason is None or self.non_acceptance_kind is not None:
                raise AuthorizationLifecycleError(
                    "unknown result requires only an ambiguity reason"
                )
        elif self.non_acceptance_kind is not None or self.ambiguity_reason is not None:
            raise AuthorizationLifecycleError(
                "accepted result MUST NOT carry denial or ambiguity metadata"
            )
        if self.effect_verified is not False or self.execution_authority is not False:
            raise AuthorizationLifecycleError(
                "provider submission result MUST NOT claim authority or effect success"
            )
        expected = _payload_digest(
            self,
            "provider-submission-result",
            digest_field="result_digest",
        )
        if self.result_digest != expected:
            raise AuthorizationLifecycleError("provider submission result digest mismatch")

    @classmethod
    def create(
        cls,
        *,
        state: ProviderAcceptanceState,
        evidence_digest: str,
        non_acceptance_kind: ProviderNonAcceptanceEvidenceKind | None = None,
        ambiguity_reason: ProviderAcceptanceAmbiguityReason | None = None,
    ) -> Self:
        """Build one accepted, rejected, or ambiguous callback result."""

        values: dict[str, object] = {
            "state": state,
            "evidence_digest": evidence_digest,
            "non_acceptance_kind": non_acceptance_kind,
            "ambiguity_reason": ambiguity_reason,
            "effect_verified": False,
            "execution_authority": False,
        }
        values["result_digest"] = _payload_digest(
            values,
            "provider-submission-result",
            digest_field="result_digest",
        )
        return cls(**values)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class ProviderAcceptanceRecord:
    """Immutable current record for one target-fence acceptance generation."""

    schema_version: Literal["1.0.0"]
    identity: ProviderAcceptanceIdentity
    state: ProviderAcceptanceState
    revision: int
    prior_record_digest: str | None
    state_changed_at: datetime
    result: ProviderSubmissionResult | None
    record_digest: str
    execution_authority: Literal[False] = False
    effect_verification_authority: Literal[False] = False
    promotion_authority: Literal[False] = False
    production_eligible: Literal[False] = False

    def __post_init__(self) -> None:
        if self.schema_version != "1.0.0":
            raise AuthorizationLifecycleError("unsupported provider acceptance record schema")
        if type(self.identity) is not ProviderAcceptanceIdentity:
            raise AuthorizationLifecycleError(
                "provider acceptance record requires an exact identity"
            )
        if type(self.state) is not ProviderAcceptanceState:
            raise AuthorizationLifecycleError("provider acceptance state is invalid")
        if isinstance(self.revision, bool) or self.revision < 1:
            raise AuthorizationLifecycleError("provider acceptance revision MUST be positive")
        require_aware("state_changed_at", self.state_changed_at)
        if self.revision == 1:
            if (
                self.state is not ProviderAcceptanceState.PREPARED
                or self.prior_record_digest is not None
                or self.result is not None
            ):
                raise AuthorizationLifecycleError(
                    "initial provider acceptance record MUST be prepared"
                )
        else:
            require_digest(
                "prior_record_digest",
                self.prior_record_digest or "",
            )
            if self.state is ProviderAcceptanceState.PREPARED or self.result is None:
                raise AuthorizationLifecycleError("provider acceptance transition MUST be terminal")
            if type(self.result) is not ProviderSubmissionResult:
                raise AuthorizationLifecycleError(
                    "provider acceptance record requires an exact submission result"
                )
            if self.result.state is not self.state:
                raise AuthorizationLifecycleError(
                    "provider acceptance state MUST match submission result"
                )
            if (
                self.result.effect_verified is not False
                or self.result.execution_authority is not False
            ):
                raise AuthorizationLifecycleError(
                    "provider acceptance result MUST remain no-authority"
                )
        if any(
            (
                self.execution_authority,
                self.effect_verification_authority,
                self.promotion_authority,
                self.production_eligible,
            )
        ):
            raise AuthorizationLifecycleError(
                "provider acceptance record MUST remain no-authority and ineligible"
            )
        require_digest("record_digest", self.record_digest)
        if self.record_digest != _payload_digest(
            self,
            "provider-acceptance-record",
            digest_field="record_digest",
        ):
            raise AuthorizationLifecycleError("provider acceptance record digest mismatch")


def prepare_provider_acceptance(
    identity: ProviderAcceptanceIdentity,
    *,
    prepared_at: datetime,
) -> ProviderAcceptanceRecord:
    """Create the durable pre-I/O record for one acceptance attempt."""

    return _build_record(
        identity=identity,
        state=ProviderAcceptanceState.PREPARED,
        revision=1,
        prior_record_digest=None,
        state_changed_at=prepared_at,
        result=None,
    )


def complete_provider_acceptance(
    record: ProviderAcceptanceRecord,
    *,
    result: ProviderSubmissionResult,
    completed_at: datetime,
) -> ProviderAcceptanceRecord:
    """Move one prepared attempt to its immutable terminal state."""

    if record.state is not ProviderAcceptanceState.PREPARED or record.revision != 1:
        raise AuthorizationLifecycleError(
            "provider acceptance completion requires the initial prepared record"
        )
    return _build_record(
        identity=record.identity,
        state=result.state,
        revision=2,
        prior_record_digest=record.record_digest,
        state_changed_at=completed_at,
        result=result,
    )


def quarantine_orphaned_provider_acceptance(
    record: ProviderAcceptanceRecord,
    *,
    quarantined_at: datetime,
    evidence_digest: str,
) -> ProviderAcceptanceRecord:
    """Quarantine an orphaned prepared record without granting retry authority."""

    return complete_provider_acceptance(
        record,
        result=ProviderSubmissionResult.create(
            state=ProviderAcceptanceState.UNKNOWN,
            evidence_digest=evidence_digest,
            ambiguity_reason=ProviderAcceptanceAmbiguityReason.ORPHANED_PREPARED,
        ),
        completed_at=quarantined_at,
    )


def acceptance_effect_status(record: ProviderAcceptanceRecord) -> EffectStatus:
    """Map provider acceptance to the existing conservative effect-status vocabulary."""

    return {
        ProviderAcceptanceState.PREPARED: EffectStatus.UNKNOWN,
        ProviderAcceptanceState.ACCEPTED: EffectStatus.UNKNOWN,
        ProviderAcceptanceState.NOT_ACCEPTED: EffectStatus.NOT_COMMITTED,
        ProviderAcceptanceState.UNKNOWN: EffectStatus.UNKNOWN,
    }[record.state]


def validate_provider_acceptance_transition(
    prior: ProviderAcceptanceRecord,
    current: ProviderAcceptanceRecord,
) -> None:
    """Reject any transition except prepared to one immutable terminal state."""

    if (
        prior.identity != current.identity
        or prior.state is not ProviderAcceptanceState.PREPARED
        or prior.revision != 1
        or current.state is ProviderAcceptanceState.PREPARED
        or current.revision != 2
        or current.prior_record_digest != prior.record_digest
        or current.state_changed_at < prior.state_changed_at
    ):
        raise AuthorizationLifecycleError("provider acceptance transition is not monotonic")


def _build_record(
    *,
    identity: ProviderAcceptanceIdentity,
    state: ProviderAcceptanceState,
    revision: int,
    prior_record_digest: str | None,
    state_changed_at: datetime,
    result: ProviderSubmissionResult | None,
) -> ProviderAcceptanceRecord:
    values: dict[str, object] = {
        "schema_version": "1.0.0",
        "identity": identity,
        "state": state,
        "revision": revision,
        "prior_record_digest": prior_record_digest,
        "state_changed_at": aware_utc(state_changed_at),
        "result": result,
        "execution_authority": False,
        "effect_verification_authority": False,
        "promotion_authority": False,
        "production_eligible": False,
    }
    values["record_digest"] = _payload_digest(
        values,
        "provider-acceptance-record",
        digest_field="record_digest",
    )
    return ProviderAcceptanceRecord(**values)  # type: ignore[arg-type]


def _payload_digest(
    value: object,
    domain: str,
    *,
    digest_field: str,
) -> str:
    if is_dataclass(value) and not isinstance(value, type):
        payload: dict[str, object] = asdict(cast(Any, value))
    elif isinstance(value, dict):
        payload = dict(value)
    else:
        raise TypeError("provider acceptance digest input MUST be a dataclass or mapping")
    payload.pop(digest_field, None)
    payload["domain"] = domain
    return content_digest(_canonicalize(payload))


def _canonicalize(value: object) -> object:
    if is_dataclass(value) and not isinstance(value, type):
        return _canonicalize(asdict(value))
    if isinstance(value, datetime):
        return instant(value)
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, dict):
        return {
            str(key): _canonicalize(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, list):
        return [_canonicalize(item) for item in value]
    return value


__all__ = [
    "ProviderAcceptanceAmbiguityReason",
    "ProviderAcceptanceIdentity",
    "ProviderAcceptanceRecord",
    "ProviderAcceptanceState",
    "ProviderNonAcceptanceEvidenceKind",
    "ProviderSubmissionResult",
    "acceptance_effect_status",
    "complete_provider_acceptance",
    "prepare_provider_acceptance",
    "quarantine_orphaned_provider_acceptance",
    "validate_provider_acceptance_transition",
]
