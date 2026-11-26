"""Immutable contracts for the full-authority development profile.

These records describe authority evidence; they never grant authority by
construction. Consumers must use the shared evaluator and revalidate the exact
runtime action at every durable boundary.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal, Self

from pydantic import Field, model_validator

from fdai.shared.contracts.development_authority_digest import (
    canonical_authority_digest,
    normalized_principal,
)

from ._base import IdempotencyKey, SemVer, _Base

Digest = Annotated[str, Field(pattern=r"^sha256:[a-f0-9]{64}$")]
AuthorityIdentifier = Annotated[
    str,
    Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$"),
]
Revision = Annotated[str, Field(min_length=1, max_length=256)]
PrincipalRef = Annotated[str, Field(min_length=1, max_length=256)]


class DevelopmentAuthorityScope(_Base):
    """Exact digest-only Azure scope selected by deployment configuration."""

    tenant_digest: Digest
    subscription_digest: Digest
    resource_group_digests: tuple[Digest, ...] = ()

    @model_validator(mode="after")
    def _resource_groups_are_canonical(self) -> Self:
        if tuple(sorted(set(self.resource_group_digests))) != self.resource_group_digests:
            raise ValueError("resource_group_digests MUST be sorted and unique")
        return self

    def covers(self, requested: DevelopmentAuthorityScope) -> bool:
        """Return whether ``requested`` stays inside this exact maximum scope."""

        if (
            self.tenant_digest != requested.tenant_digest
            or self.subscription_digest != requested.subscription_digest
        ):
            return False
        allowed = set(self.resource_group_digests)
        requested_groups = set(requested.resource_group_digests)
        if allowed and not requested_groups:
            return False
        return not allowed or requested_groups <= allowed


class RegisteredDevelopmentAction(_Base):
    """One exact registered ActionType eligible for development confirmation."""

    action_type: AuthorityIdentifier
    version: SemVer
    action_type_digest: Digest


class FullAuthorityDevelopmentProfile(_Base):
    """Deployment-injected maximum authority for one disposable test scope."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    profile_id: AuthorityIdentifier
    scope: DevelopmentAuthorityScope
    classification: Literal["disposable_development"]
    owner_principal: PrincipalRef
    executor_principal: PrincipalRef
    valid_from: datetime
    valid_until: datetime
    source_revision: Revision
    catalog_revision: Revision
    policy_revision: Revision
    registered_actions: Annotated[tuple[RegisteredDevelopmentAction, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def _profile_is_bounded(self) -> Self:
        _require_aware_interval(self.valid_from, self.valid_until, "profile")
        if normalized_principal(self.owner_principal) == normalized_principal(
            self.executor_principal
        ):
            raise ValueError("development Owner and executor principals MUST be distinct")
        identities = [
            (item.action_type, item.version, item.action_type_digest)
            for item in self.registered_actions
        ]
        if len(set(identities)) != len(identities):
            raise ValueError("registered development actions MUST be unique")
        if tuple(sorted(identities)) != tuple(identities):
            raise ValueError("registered development actions MUST be sorted")
        return self

    @property
    def digest(self) -> str:
        """Return the exact content identity used by confirmations and audit."""

        return canonical_authority_digest(self)


class DevelopmentActionSafeguards(_Base):
    """The unchanged seven safeguards plus independent effect observation."""

    stop_condition_digest: Digest
    rollback_contract_digest: Digest
    rollback_test_digest: Digest
    blast_radius_digest: Digest
    logical_target_lock_digest: Digest
    idempotency_key: IdempotencyKey
    two_phase_audit: Literal[True]
    audit_contract_digest: Digest
    observer_principal: PrincipalRef
    observer_source_digest: Digest


class DevelopmentActionBinding(_Base):
    """Exact action and safety material a human explicitly confirms."""

    action_type: AuthorityIdentifier
    action_type_version: SemVer
    action_type_digest: Digest
    action_id: Annotated[str, Field(min_length=1, max_length=256)]
    target_digest: Digest
    target_revision: Revision
    scope: DevelopmentAuthorityScope
    source_revision: Revision
    catalog_revision: Revision
    policy_revision: Revision
    params_digest: Digest
    action_digest: Digest
    dry_run_digest: Digest
    requester_principal: PrincipalRef
    executor_principal: PrincipalRef
    safeguards: DevelopmentActionSafeguards

    @model_validator(mode="after")
    def _binding_is_internally_consistent(self) -> Self:
        if self.safeguards.logical_target_lock_digest != self.target_digest:
            raise ValueError("logical target lock MUST bind the exact target digest")
        requester = normalized_principal(self.requester_principal)
        executor = normalized_principal(self.executor_principal)
        observer = normalized_principal(self.safeguards.observer_principal)
        if requester == executor:
            raise ValueError("development requester and executor principals MUST be distinct")
        if observer == executor:
            raise ValueError("development observer and executor principals MUST be distinct")
        if observer == requester:
            raise ValueError("development observer and requester principals MUST be distinct")
        if self.action_digest != self.expected_action_digest():
            raise ValueError("development action digest does not match its exact binding")
        return self

    def expected_action_digest(self) -> str:
        """Return the canonical digest of every action-bearing field."""

        return canonical_authority_digest(self.model_dump(mode="json", exclude={"action_digest"}))

    @classmethod
    def build(cls, **values: Any) -> DevelopmentActionBinding:
        """Build a binding and derive its non-self-referential action digest."""

        candidate = dict(values)
        candidate["scope"] = DevelopmentAuthorityScope.model_validate(candidate["scope"])
        candidate["safeguards"] = DevelopmentActionSafeguards.model_validate(
            candidate["safeguards"]
        )
        candidate["action_digest"] = "sha256:" + "0" * 64
        provisional = cls.model_construct(**candidate)
        candidate["action_digest"] = provisional.expected_action_digest()
        return cls.model_validate(candidate)

    @property
    def digest(self) -> str:
        return canonical_authority_digest(self)


class DevelopmentBindingVerification(_Base):
    """Trusted-source verification of one complete current action binding."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    binding: DevelopmentActionBinding
    source_id: AuthorityIdentifier
    source_revision: Revision
    verification_receipt_digest: Digest
    verified_at: datetime
    expires_at: datetime
    authoritative: Literal[True]

    @model_validator(mode="after")
    def _verification_is_bounded(self) -> Self:
        _require_aware_interval(self.verified_at, self.expires_at, "binding verification")
        return self

    @property
    def digest(self) -> str:
        return canonical_authority_digest(self)


class DevelopmentActionConfirmation(_Base):
    """Fresh authenticated Owner confirmation of one exact action binding."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    confirmation_id: AuthorityIdentifier
    profile_digest: Digest
    binding: DevelopmentActionBinding
    authenticated_principal: PrincipalRef
    authenticated_role: Literal["Owner"]
    authentication_evidence_digest: Digest
    authenticated_at: datetime
    confirmed_by: PrincipalRef
    confirmed_at: datetime
    expires_at: datetime
    explicit_confirmation: Literal[True]

    @model_validator(mode="after")
    def _confirmation_is_ordered(self) -> Self:
        _require_aware_interval(self.authenticated_at, self.expires_at, "confirmation")
        if self.confirmed_at.tzinfo is None or self.confirmed_at.utcoffset() is None:
            raise ValueError("confirmation time MUST be timezone-aware")
        if not self.authenticated_at <= self.confirmed_at < self.expires_at:
            raise ValueError("authentication, confirmation, and expiry MUST be ordered")
        authenticated = normalized_principal(self.authenticated_principal)
        confirmer = normalized_principal(self.confirmed_by)
        requester = normalized_principal(self.binding.requester_principal)
        if len({authenticated, confirmer, requester}) != 1:
            raise ValueError("authenticated Owner, confirmer, and requester MUST be identical")
        return self

    @property
    def digest(self) -> str:
        return canonical_authority_digest(self)


class DevelopmentAuthorityGrant(_Base):
    """Derived admission record that consumers must revalidate, never trust."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    profile_id: AuthorityIdentifier
    profile_digest: Digest
    confirmation_id: AuthorityIdentifier
    confirmation_digest: Digest
    action_binding_digest: Digest
    binding_verification_digest: Digest
    owner_principal: PrincipalRef
    executor_principal: PrincipalRef
    original_quorum: Annotated[int, Field(ge=1)]
    effective_quorum: Literal[1] = 1
    development_only: Literal[True] = True
    valid_until: datetime


class DevelopmentAuthorityEnvelope(_Base):
    """Exact wire record carried across authority-bearing runtime boundaries."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    confirmation: DevelopmentActionConfirmation
    binding_verification: DevelopmentBindingVerification
    grant: DevelopmentAuthorityGrant


class DevelopmentPromotionApproval(_Base):
    """Exact Owner review that can change only one development registry."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    profile_digest: Digest
    confirmation_digest: Digest
    binding_verification_digest: Digest
    promotion_action_type: AuthorityIdentifier
    target_action_type: AuthorityIdentifier
    target_action_type_version: SemVer
    target_action_type_digest: Digest
    promotion_target_digest: Digest
    reviewed_replay_digest: Digest
    fdai_revision: Revision
    scenario_set_version: Revision
    promotion_evidence_digest: Digest
    review_ref: Annotated[str, Field(min_length=1, max_length=512)]
    reviewer_principal: PrincipalRef
    approved_at: datetime
    valid_until: datetime
    development_only: Literal[True] = True
    production_ready: Literal[False] = False

    @model_validator(mode="after")
    def _promotion_is_bounded(self) -> Self:
        _require_aware_interval(self.approved_at, self.valid_until, "development promotion")
        return self

    @property
    def digest(self) -> str:
        return canonical_authority_digest(self)


def _require_aware_interval(start: datetime, end: datetime, name: str) -> None:
    if (
        start.tzinfo is None
        or start.utcoffset() is None
        or end.tzinfo is None
        or end.utcoffset() is None
    ):
        raise ValueError(f"{name} validity interval MUST be timezone-aware")
    if start >= end:
        raise ValueError(f"{name} validity interval MUST be non-empty")


__all__ = [
    "DevelopmentActionBinding",
    "DevelopmentActionConfirmation",
    "DevelopmentActionSafeguards",
    "DevelopmentBindingVerification",
    "DevelopmentAuthorityEnvelope",
    "DevelopmentAuthorityGrant",
    "DevelopmentAuthorityScope",
    "DevelopmentPromotionApproval",
    "FullAuthorityDevelopmentProfile",
    "RegisteredDevelopmentAction",
]
