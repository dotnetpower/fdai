"""Provider-neutral wire proofs for the seven execution safeguards."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from fdai_service_contracts.executor_models import ContractBase, Digest, ExecutionPath
from fdai_service_contracts.ontology_query import content_digest

SourceRevision = Annotated[str, Field(min_length=1, max_length=512)]


class SafeguardProofKind(StrEnum):
    """Constitutional proof classes in required pre-dispatch order."""

    STOP_CONDITION = "stop_condition"
    ROLLBACK = "rollback"
    IMPACT_SCOPE = "impact_scope"
    DRY_RUN = "dry_run"
    LOGICAL_TARGET_LOCK = "logical_target_lock"
    IDEMPOTENCY = "idempotency"
    AUDIT_INTENT = "audit_intent"


_REQUIRED_PROOF_KINDS = tuple(SafeguardProofKind)
_PROOF_ORDER = {kind: index for index, kind in enumerate(_REQUIRED_PROOF_KINDS)}


class SafeguardProof(ContractBase):
    """One content-addressed proof reference without validation authority."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    kind: SafeguardProofKind
    proof_digest: Digest


class _SafeguardProofBundleBody(ContractBase):
    schema_version: Literal["1.0.0"] = "1.0.0"
    action_id: UUID
    execution_path: ExecutionPath
    execution_fingerprint: Digest
    source_revision: SourceRevision
    recorded_at: datetime
    proofs: Annotated[tuple[SafeguardProof, ...], Field(min_length=7, max_length=7)]
    effect_verified: Literal[False] = False
    execution_authority: Literal[False] = False
    approval_authority: Literal[False] = False
    promotion_authority: Literal[False] = False

    @field_validator("recorded_at")
    @classmethod
    def _normalize_recorded_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("safeguard proof bundle recorded_at MUST include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _proofs_are_complete_and_canonical(self) -> _SafeguardProofBundleBody:
        kinds = tuple(proof.kind for proof in self.proofs)
        if kinds != _REQUIRED_PROOF_KINDS:
            raise ValueError("safeguard proof bundle requires seven ordered proof classes")
        digests = tuple(proof.proof_digest for proof in self.proofs)
        if len(digests) != len(set(digests)):
            raise ValueError("safeguard proof bundle proof digests MUST be unique")
        return self


class SafeguardProofBundle(_SafeguardProofBundleBody):
    """Canonical proof bundle that grants no authority and verifies no effect."""

    bundle_digest: Digest

    @model_validator(mode="after")
    def _digest_matches(self) -> SafeguardProofBundle:
        expected = content_digest(self.model_dump(mode="json", exclude={"bundle_digest"}))
        if self.bundle_digest != expected:
            raise ValueError("safeguard proof bundle digest mismatched")
        return self

    @classmethod
    def create(
        cls,
        *,
        action_id: UUID,
        execution_path: ExecutionPath,
        execution_fingerprint: str,
        source_revision: str,
        recorded_at: datetime,
        proofs: tuple[SafeguardProof, ...],
        effect_verified: bool = False,
        execution_authority: bool = False,
        approval_authority: bool = False,
        promotion_authority: bool = False,
    ) -> Self:
        """Create one canonical content-addressed bundle from seven proof references."""

        body = _SafeguardProofBundleBody.model_validate(
            {
                "action_id": action_id,
                "execution_path": execution_path,
                "execution_fingerprint": execution_fingerprint,
                "source_revision": source_revision,
                "recorded_at": recorded_at,
                "proofs": tuple(sorted(proofs, key=lambda proof: _PROOF_ORDER[proof.kind])),
                "effect_verified": effect_verified,
                "execution_authority": execution_authority,
                "approval_authority": approval_authority,
                "promotion_authority": promotion_authority,
            }
        )
        payload = body.model_dump(mode="json")
        return cls.model_validate({**payload, "bundle_digest": content_digest(payload)})


__all__ = [
    "SafeguardProof",
    "SafeguardProofBundle",
    "SafeguardProofKind",
    "SourceRevision",
]
