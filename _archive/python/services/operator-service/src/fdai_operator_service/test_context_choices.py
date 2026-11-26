"""Principal-scoped test-context choices from the reviewed grant registry."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal

from fdai_service_contracts.operational_evidence import OperationalEvidenceRejectionClass
from fdai_service_contracts.operational_evidence_grants import (
    CaseScope,
    CaseScopeGrantRegistry,
    GrantDecision,
    RegistryUnavailableError,
    content_pin,
    load_grant_registry,
)
from fdai_service_contracts.operator_authentication import (
    LOCAL_LOOPBACK_ISSUER,
    OperatorAuthenticationEvidenceClass,
    OperatorAuthenticationReceipt,
    role_mapping_revision,
    tenant_digest,
    token_id_digest,
)
from fdai_service_contracts.test_context import (
    TestContextChoiceProjection,
    TestContextPolicyChoice,
    TestContextRequest,
)

from fdai_operator_service.families.conversation.contracts import PrincipalScope

_ALLOWED_OPERATIONS: dict[str, tuple[str, str]] = {
    "review": ("test-context.review", "test-context-transition"),
    "revoke": ("test-context.revoke", "test-context-transition"),
}


class TestContextChoiceSource:
    """Resolve server-owned choices; absence is explicit and grants no authority."""

    def __init__(
        self,
        *,
        source_revision: str | None,
        registry: CaseScopeGrantRegistry | None = None,
        unavailable_reasons: tuple[str, ...] = (),
    ) -> None:
        self._source_revision = source_revision
        self._registry = registry
        self._unavailable_reasons = unavailable_reasons

    @classmethod
    def unavailable(cls, reason: str) -> TestContextChoiceSource:
        return cls(source_revision=None, unavailable_reasons=(reason,))

    @classmethod
    def from_json_text(cls, text: str) -> TestContextChoiceSource:
        try:
            data = text.encode("utf-8")
            pin = content_pin(data)
            registry = load_grant_registry(data, expected_pin=pin)
        except (RegistryUnavailableError, UnicodeEncodeError):
            return cls.unavailable("grant_registry_invalid")
        if not registry.case_scopes:
            return cls.unavailable("no_test_context_scope")
        return cls(source_revision=f"{pin}#{registry.revision}", registry=registry)

    def choices_for(
        self,
        principal: PrincipalScope,
        *,
        evaluated_at: datetime | None = None,
    ) -> TestContextChoiceProjection:
        now = (evaluated_at or datetime.now(UTC)).astimezone(UTC)
        reasons = set(self._unavailable_reasons)
        choices: list[TestContextPolicyChoice] = []
        if self._source_revision is None or self._registry is None:
            return TestContextChoiceProjection(
                choices=(),
                unavailable_reasons=tuple(sorted(reasons or {"grant_registry_unavailable"})),
            )
        try:
            receipt = _receipt_from_scope(principal, now=now)
        except ValueError:
            return TestContextChoiceProjection(
                source_revision=self._source_revision,
                choices=(),
                unavailable_reasons=("principal_scope_too_large",),
            )
        for scope in self._registry.case_scopes.values():
            operations: list[Literal["propose", "review", "revoke"]] = []
            if _scope_has_purpose(scope=scope, purpose_id="operator-test-context-command"):
                command = self._registry.authorize(
                    receipt,
                    access_scope_digest=scope.access_scope_digest,
                    operation="test-context.propose",
                    purpose_id="operator-test-context-command",
                    at=now,
                    policy_revision=scope.policy_revision,
                )
                transition = self._registry.authorize(
                    receipt,
                    access_scope_digest=scope.access_scope_digest,
                    operation="test-context.propose",
                    purpose_id="test-context-transition",
                    at=now,
                    policy_revision=scope.policy_revision,
                )
                if command.allowed and transition.allowed:
                    operations.append("propose")
                else:
                    reasons.update(_decision_reasons(command))
                    reasons.update(_decision_reasons(transition))
            for label, (operation, purpose) in _ALLOWED_OPERATIONS.items():
                if not _scope_has_purpose(scope=scope, purpose_id=purpose):
                    continue
                transition = self._registry.authorize(
                    receipt,
                    access_scope_digest=scope.access_scope_digest,
                    operation=operation,
                    purpose_id=purpose,
                    at=now,
                    policy_revision=scope.policy_revision,
                )
                command = self._registry.authorize(
                    receipt,
                    access_scope_digest=scope.access_scope_digest,
                    operation=operation,
                    purpose_id="operator-test-context-command",
                    at=now,
                    policy_revision=scope.policy_revision,
                )
                if transition.allowed and command.allowed:
                    operations.append(label)  # type: ignore[arg-type]
                else:
                    reasons.update(_decision_reasons(transition))
                    reasons.update(_decision_reasons(command))
            if operations:
                choices.append(
                    TestContextPolicyChoice(
                        case_scope_id=scope.case_scope_id,
                        access_scope_digest=scope.access_scope_digest,
                        target_selectors=scope.resource_selectors,
                        policy_revision=scope.policy_revision,
                        source_revision=self._source_revision,
                        allowed_operations=tuple(operations),
                    )
                )
        if not choices and not reasons:
            reasons.add("no_test_context_scope")
        if len(choices) > 128:
            return TestContextChoiceProjection(
                source_revision=self._source_revision,
                choices=(),
                unavailable_reasons=("principal_scope_too_large",),
            )
        return TestContextChoiceProjection(
            source_revision=self._source_revision,
            choices=tuple(choices),
            unavailable_reasons=tuple(sorted(reasons)) if not choices else (),
        )

    def may_transition(
        self,
        principal: PrincipalScope,
        request: TestContextRequest,
        *,
        evaluated_at: datetime | None = None,
    ) -> bool:
        """Return whether a reviewer can read and act on another principal's command."""
        if self._registry is None:
            return False
        now = (evaluated_at or datetime.now(UTC)).astimezone(UTC)
        try:
            receipt = _receipt_from_scope(principal, now=now)
        except ValueError:
            return False
        return any(
            self._registry.authorize(
                receipt,
                access_scope_digest=request.access_scope_digest,
                operation=operation,
                purpose_id="test-context-transition",
                at=now,
                target_ref=request.target_ref,
                policy_revision=request.policy_revision,
            ).allowed
            and self._registry.authorize(
                receipt,
                access_scope_digest=request.access_scope_digest,
                operation=operation,
                purpose_id="operator-test-context-command",
                at=now,
                target_ref=request.target_ref,
                policy_revision=request.policy_revision,
            ).allowed
            for operation in ("test-context.review", "test-context.revoke")
        )


def _scope_has_purpose(*, scope: CaseScope, purpose_id: str) -> bool:
    return purpose_id in scope.purposes


def _decision_reasons(decision: GrantDecision) -> tuple[str, ...]:
    if decision.allowed:
        return ()
    if decision.rejection_class is OperationalEvidenceRejectionClass.STALE:
        return tuple(
            "grant_missing" if reason.endswith("not_current") else reason
            for reason in decision.reasons
        )
    return decision.reasons


def _receipt_from_scope(
    principal: PrincipalScope, *, now: datetime
) -> OperatorAuthenticationReceipt:
    return OperatorAuthenticationReceipt.create(
        evidence_class=OperatorAuthenticationEvidenceClass.LOCAL_LOOPBACK,
        issuer=LOCAL_LOOPBACK_ISSUER,
        audience=LOCAL_LOOPBACK_ISSUER,
        tenant_digest=tenant_digest(LOCAL_LOOPBACK_ISSUER),
        subject_id=principal.subject_id,
        principal_kind=principal.principal_kind.value,
        groups=tuple(principal.groups),
        token_id_digest=token_id_digest("operator-choice-projection:" + principal.subject_id),
        issued_at=now,
        expires_at=now + timedelta(minutes=10),
        roles=tuple(principal.roles),
        role_mapping_revision=role_mapping_revision({role: role for role in principal.roles}),
    )


__all__ = ["TestContextChoiceSource"]
