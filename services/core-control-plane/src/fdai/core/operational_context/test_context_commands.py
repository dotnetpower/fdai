"""Owner-separated test-context command admission and immutable transitions."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from fdai_service_contracts.ontology_query import content_digest
from fdai_service_contracts.test_context import TestContextApplication, TestContextCommand

from fdai.shared.providers.decision_evidence_verifier import (
    DecisionEvidenceAdmission,
    DecisionEvidenceAdmissionProvider,
    assess_decision_evidence_admission,
)

from .test_context import TestContextClaim
from .test_context_lifecycle import GovernedTestContextStore


class TestContextCommandHandler:
    """Validate authenticated commands; Var reviews and Mimir alone records policy revisions."""

    def __init__(
        self,
        *,
        contexts: GovernedTestContextStore,
        admission: DecisionEvidenceAdmissionProvider,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._contexts = contexts
        self._admission = admission
        self._clock = clock or (lambda: datetime.now(UTC))

    async def validate(self, payload: Mapping[str, Any]) -> TestContextCommand:
        """Check complete command identity and independent proof before accessing case scope."""
        command = TestContextCommand.model_validate(payload)
        digest = content_digest(command.model_dump(mode="json"))
        request = command.request
        admission = await self._admission.admit(
            evidence_digest=digest,
            scope_digest="sha256:" + request.access_scope_digest,
            purpose_id="operator-test-context-command",
            source_revision=request.policy_revision,
        )
        now = self._clock()
        if admission is None or not isinstance(admission, DecisionEvidenceAdmission):
            raise PermissionError("test context command identity or scope admission failed")
        if (
            assess_decision_evidence_admission(
                admission,
                expected_evidence_digest=digest,
                expected_scope_digest="sha256:" + request.access_scope_digest,
                expected_purpose_id="operator-test-context-command",
                expected_source_revision=request.policy_revision,
                evaluated_at=now,
            )
            or not command.requested_at <= admission.verified_at <= now < admission.valid_until
        ):
            raise PermissionError("test context command identity or scope admission failed")
        return command

    async def review(self, payload: Mapping[str, Any]) -> TestContextCommand:
        """Var validates a current independently authorized human review, never self-approval."""
        command = await self.validate(payload)
        request = command.request
        if request.operation == "propose":
            raise ValueError("a proposal is not an independent review")
        prior = await self._contexts.read_revision(
            context_id=request.context_id,
            target_ref=request.target_ref,
            access_scope_digest=request.access_scope_digest,
            revision=request.expected_revision,
        )
        if prior is None or prior.revision not in {
            request.expected_revision,
            request.expected_revision + 1,
        }:
            raise ValueError("context review references an unavailable revision")
        if prior.requested_by.strip().casefold() == command.actor_id.strip().casefold():
            raise PermissionError("test context requester cannot self-review")
        return command

    async def transition(
        self, payload: Mapping[str, Any], *, reviewed_by_var: bool
    ) -> dict[str, Any]:
        """Mimir applies an exact proposal or Var-reviewed command and returns audit fields."""
        command = await self.validate(payload)
        request = command.request
        if (request.operation != "propose") != reviewed_by_var:
            raise PermissionError("test context review must pass the Var-owned approval topic")
        if request.operation == "propose":
            if (
                request.expected_min is None
                or request.expected_max is None
                or request.effective_from is None
                or request.effective_to is None
            ):
                raise ValueError("test context proposal envelope is incomplete")
            claim = TestContextClaim(
                context_id=request.context_id,
                revision=1,
                access_scope_digest=request.access_scope_digest,
                target_ref=request.target_ref,
                signal_code=request.signal_code,
                expected_min=request.expected_min,
                expected_max=request.expected_max,
                effective_from=request.effective_from,
                effective_to=request.effective_to,
                recorded_at=command.requested_at,
                source_ref=request.source_ref,
                requested_by=command.actor_id,
                reviewed_by="",
                policy_revision=request.policy_revision,
                state="proposed",
            )
        else:
            prior = await self._contexts.read_revision(
                context_id=request.context_id,
                target_ref=request.target_ref,
                access_scope_digest=request.access_scope_digest,
                revision=request.expected_revision,
            )
            if prior is None or (prior.signal_code, prior.source_ref, prior.policy_revision) != (
                request.signal_code,
                request.source_ref,
                request.policy_revision,
            ):
                raise ValueError("test context review source no longer matches the proposal")
            if command.actor_id.strip().casefold() == prior.requested_by.strip().casefold():
                raise PermissionError(
                    "test context requester cannot review or revoke their own request"
                )
            claim = replace(
                prior,
                revision=request.expected_revision + 1,
                reviewed_by=command.actor_id,
                recorded_at=command.requested_at,
                state="reviewed" if request.operation == "review" else "revoked",
            )
        await self._contexts.record_transition(
            claim, expected_revision=request.expected_revision, now=self._clock()
        )
        return {
            "kind": "test_context_revision",
            "application": TestContextApplication(
                command_digest=content_digest(command.model_dump(mode="json")),
                actor_id=command.actor_id,
                request_key=command.idempotency_key,
                context_id=claim.context_id,
                access_scope_digest=claim.access_scope_digest,
                target_ref=claim.target_ref,
                policy_revision=claim.policy_revision,
                revision=claim.revision,
                state="proposed"
                if request.operation == "propose"
                else "reviewed"
                if request.operation == "review"
                else "revoked",
                context_digest=claim.digest,
            ).model_dump(mode="json"),
            "context_digest": claim.digest,
            "context_id": claim.context_id,
            "revision": claim.revision,
            "state": claim.state,
            "access_scope_digest": claim.access_scope_digest,
            "execution_authority": False,
            "idempotency_key": "test-context:" + claim.digest,
            "correlation_id": command.idempotency_key,
        }
