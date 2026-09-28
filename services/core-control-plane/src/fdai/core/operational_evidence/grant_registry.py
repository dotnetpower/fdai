"""Deployment-owned principal-to-case-scope and purpose grant registry.

Authorization is an explicit reviewed record, never an equality between digests. The verifier
takes the principal only from the Operator authentication receipt and requires one current
grant that covers the exact case scope, operation, and purpose together. A matching revoked or
expired grant denies even when another grant would allow, and overlapping grants never widen.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime

from fdai_service_contracts.ontology_query import content_digest
from fdai_service_contracts.operational_evidence import (
    OperationalEvidenceRejectionClass,
)
from fdai_service_contracts.operator_authentication import OperatorAuthenticationReceipt

from .registry_json import (
    ValidityWindow,
)

GRANT_REGISTRY_ID = "fdai.operational-evidence.case-scope-grants"
GRANT_OPERATIONS = frozenset(
    {"test-context.propose", "test-context.review", "test-context.revoke", "case-history.read"}
)


@dataclass(frozen=True, slots=True)
class CaseScope:
    """One opaque case scope, its resource selectors, purposes, and reviewed policy revision."""

    case_scope_id: str
    access_scope_digest: str
    resource_selectors: tuple[str, ...]
    purposes: frozenset[str]
    policy_revision: str
    window: ValidityWindow

    def contains(self, target_ref: str) -> bool:
        """Return whether one exact target belongs to this scope's reviewed selectors."""

        target = target_ref.casefold()
        for selector in self.resource_selectors:
            value = selector.casefold()
            if value.endswith("/*"):
                if target.startswith(value[:-1]) and len(target) > len(value) - 1:
                    return True
            elif target == value:
                return True
        return False


@dataclass(frozen=True, slots=True)
class PrincipalGrant:
    """One reviewed grant for a group or app-role selector; never a display identity."""

    grant_id: str
    selector_kind: str
    selector_value: str
    case_scopes: frozenset[str]
    operations: frozenset[str]
    purposes: frozenset[str]
    reviewer: str
    window: ValidityWindow

    def selects(self, receipt: OperatorAuthenticationReceipt) -> bool:
        """Return whether the receipt's exact groups or roles carry this selector."""

        values = receipt.groups if self.selector_kind == "group" else receipt.roles
        return self.selector_value in values


@dataclass(frozen=True, slots=True)
class ReuseGrant:
    """Case scopes whose immutable cases may be reused for events in one target scope."""

    grant_id: str
    case_scopes: frozenset[str]
    target_scope_digest: str
    window: ValidityWindow


@dataclass(frozen=True, slots=True)
class GrantDecision:
    """Result of one explicit authorization; allowance never grants execution."""

    allowed: bool
    rejection_class: OperationalEvidenceRejectionClass | None
    reasons: tuple[str, ...]
    case_scope: CaseScope | None = None
    matched_grants: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()

    @classmethod
    def deny(
        cls,
        rejection_class: OperationalEvidenceRejectionClass,
        reason: str,
        *,
        case_scope: CaseScope | None = None,
    ) -> GrantDecision:
        return cls(False, rejection_class, (reason,), case_scope=case_scope)


@dataclass(frozen=True, slots=True)
class CaseScopeGrantRegistry:
    """One pinned revision of the three grant parts."""

    pin: str
    revision: int
    case_scopes: Mapping[str, CaseScope]
    principal_grants: tuple[PrincipalGrant, ...]
    reuse_grants: tuple[ReuseGrant, ...] = field(default_factory=tuple)

    def scope_for(self, access_scope_digest: str) -> CaseScope | None:
        """Return the one case scope for an opaque digest, or nothing."""

        return next(
            (
                scope
                for scope in self.case_scopes.values()
                if scope.access_scope_digest == access_scope_digest
            ),
            None,
        )

    def authorize(
        self,
        receipt: OperatorAuthenticationReceipt,
        *,
        access_scope_digest: str,
        operation: str,
        purpose_id: str,
        at: datetime,
        target_ref: str | None = None,
        policy_revision: str | None = None,
    ) -> GrantDecision:
        """Require one current grant covering scope, operation, and purpose together."""

        scope = self.scope_for(access_scope_digest)
        if scope is None:
            return GrantDecision.deny(
                OperationalEvidenceRejectionClass.CROSS_SCOPE, "case_scope_unknown"
            )
        scope_decision = _scope_current(scope, at=at)
        if scope_decision is not None:
            return scope_decision
        if purpose_id not in scope.purposes:
            return GrantDecision.deny(
                OperationalEvidenceRejectionClass.CROSS_SCOPE, "purpose_outside_case_scope"
            )
        if target_ref is not None and not scope.contains(target_ref):
            return GrantDecision.deny(
                OperationalEvidenceRejectionClass.CROSS_SCOPE, "target_outside_case_scope"
            )
        if policy_revision is not None and policy_revision != scope.policy_revision:
            return GrantDecision(
                False,
                OperationalEvidenceRejectionClass.CONFLICTING,
                ("policy_revision_superseded",),
                case_scope=scope,
                conflicts=tuple(
                    sorted(
                        {
                            content_digest({"policy_revision": policy_revision}),
                            content_digest({"policy_revision": scope.policy_revision}),
                        }
                    )
                ),
            )
        matching = [
            grant
            for grant in self.principal_grants
            if grant.selects(receipt)
            and scope.case_scope_id in grant.case_scopes
            and operation in grant.operations
            and purpose_id in grant.purposes
        ]
        return _single_grant_decision(matching, scope=scope, at=at)

    def authorize_reuse(
        self,
        *,
        case_scope_digest: str,
        target_scope_digest: str,
        at: datetime,
    ) -> GrantDecision:
        """Require one current reuse grant from a case scope into one target scope."""

        scope = self.scope_for(case_scope_digest)
        if scope is None:
            return GrantDecision.deny(
                OperationalEvidenceRejectionClass.CROSS_SCOPE, "case_scope_unknown"
            )
        scope_decision = _scope_current(scope, at=at)
        if scope_decision is not None:
            return scope_decision
        matching = [
            grant
            for grant in self.reuse_grants
            if scope.case_scope_id in grant.case_scopes
            and grant.target_scope_digest == target_scope_digest
        ]
        return _single_grant_decision(matching, scope=scope, at=at)

    def entry_windows(self) -> dict[tuple[str, str], ValidityWindow]:
        """Return every reviewed window keyed by entry kind and id for revision comparison."""

        windows: dict[tuple[str, str], ValidityWindow] = {
            ("case_scope", scope.case_scope_id): scope.window for scope in self.case_scopes.values()
        }
        windows.update(
            {("principal_grant", grant.grant_id): grant.window for grant in self.principal_grants}
        )
        windows.update(
            {("reuse_grant", grant.grant_id): grant.window for grant in self.reuse_grants}
        )
        return windows


def _scope_current(scope: CaseScope, *, at: datetime) -> GrantDecision | None:
    if scope.window.revoked:
        return GrantDecision.deny(
            OperationalEvidenceRejectionClass.REVOKED, "case_scope_revoked", case_scope=scope
        )
    if not scope.window.active_at(at):
        return GrantDecision.deny(
            OperationalEvidenceRejectionClass.STALE, "case_scope_not_current", case_scope=scope
        )
    return None


def _single_grant_decision(
    matching: Iterable[PrincipalGrant | ReuseGrant],
    *,
    scope: CaseScope,
    at: datetime,
) -> GrantDecision:
    """Deny on any revoked or expired match; a not-yet-valid match neither grants nor denies."""

    grants = tuple(matching)
    if any(grant.window.revoked for grant in grants):
        return GrantDecision.deny(
            OperationalEvidenceRejectionClass.REVOKED, "grant_revoked", case_scope=scope
        )
    if any(grant.window.valid_until <= at for grant in grants):
        return GrantDecision.deny(
            OperationalEvidenceRejectionClass.STALE, "grant_not_current", case_scope=scope
        )
    current = tuple(grant for grant in grants if grant.window.active_at(at))
    if not current:
        return GrantDecision.deny(
            OperationalEvidenceRejectionClass.CROSS_SCOPE, "grant_missing", case_scope=scope
        )
    return GrantDecision(
        True,
        None,
        (),
        case_scope=scope,
        matched_grants=tuple(sorted(grant.grant_id for grant in current)),
    )


__all__ = [
    "GRANT_OPERATIONS",
    "GRANT_REGISTRY_ID",
    "CaseScope",
    "CaseScopeGrantRegistry",
    "GrantDecision",
    "PrincipalGrant",
    "ReuseGrant",
]
