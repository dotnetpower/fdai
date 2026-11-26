"""Present bounded agent discussions only after independent installation read admission."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Protocol

from fdai.core.conversation.session import Principal, Role
from fdai.core.operational_evidence.owner_outcome import (
    OperationalEvidenceRequester,
    request_operational_evidence,
)
from fdai.shared.providers.decision_evidence_verifier import (
    DecisionEvidenceAdmission,
    DecisionEvidenceAdmissionProvider,
    assess_decision_evidence_admission,
)
from fdai_service_contracts import (
    AdaptiveAnswer,
    SemanticConversationModelTier,
    SemanticTurnDisposition,
    SemanticTurnRequest,
    SemanticTurnResult,
)
from fdai_service_contracts.adaptive_answer import AdaptiveGoalResult
from fdai_service_contracts.ontology_query import content_digest
from fdai_service_contracts.operational_evidence import agent_discussion_lookup_digests


class DiscussionRuntime(Protocol):
    async def deliberate(
        self,
        *,
        question: str,
        requester: str,
        correlation_id: str,
        locale: str,
        allow_t2: bool,
    ) -> dict[str, Any]: ...


class AgentDiscussionPresenter:
    """Use current independent read eligibility, never a role string alone."""

    def __init__(
        self,
        *,
        runtime: DiscussionRuntime,
        admission: DecisionEvidenceAdmissionProvider,
        evidence: OperationalEvidenceRequester,
        installation_ref: str,
        access_scope_digest: str,
        source_revision: str,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if (
            not installation_ref.strip()
            or not access_scope_digest.strip()
            or not source_revision.strip()
        ):
            raise ValueError("agent discussion presenter bindings MUST be non-empty")
        self._runtime = runtime
        self._admission = admission
        self._evidence = evidence
        self._installation = installation_ref
        self._scope = access_scope_digest
        self._revision = source_revision
        self._clock = clock or (lambda: datetime.now(UTC))

    async def present(
        self, request: SemanticTurnRequest, *, principal: Principal
    ) -> SemanticTurnResult:
        if (
            request.presentation_mode != "agent_discussion"
            or principal.role is not Role.OWNER
            or principal.id != request.principal.subject_id
            or principal.authentication_receipt_ref != request.authentication_receipt_ref
            or not principal.authentication_receipt_ref
            or not principal.authentication_request_ref
        ):
            return _held(request, "semantic_discussion_authentication_unavailable")
        if request.cancelled or self._clock() >= request.deadline_at:
            return _held(request, "semantic_discussion_deadline_exceeded")
        if request.locale not in {"en", "ko"} or len(request.utterance) > 2_000:
            return _held(request, "semantic_discussion_input_out_of_bounds")
        coordinates = {
            "installation_ref": self._installation,
            "principal_ref": principal.id,
            "request_ref": principal.authentication_request_ref,
            "case_scope_digest": self._scope,
            "authentication_receipt_ref": principal.authentication_receipt_ref,
            "principal_groups_digest": content_digest(sorted(principal.groups)),
            "purpose": "operations-review",
        }
        evidence_digest, scope_digest = agent_discussion_lookup_digests(coordinates)
        attempt = await request_operational_evidence(
            self._evidence,
            evidence_digest=evidence_digest,
            scope_digest=scope_digest,
            purpose_id="agent-discussion-read",
            source_revision=self._revision,
            locator=coordinates,
            clock=self._clock,
        )
        receipt = await self._admission.admit(
            evidence_digest=evidence_digest,
            scope_digest=scope_digest,
            purpose_id="agent-discussion-read",
            source_revision=self._revision,
        )
        if not isinstance(receipt, DecisionEvidenceAdmission) or assess_decision_evidence_admission(
            receipt,
            expected_evidence_digest=evidence_digest,
            expected_scope_digest=scope_digest,
            expected_purpose_id="agent-discussion-read",
            expected_source_revision=self._revision,
            evaluated_at=self._clock(),
        ):
            return _held(request, attempt.hold_reason("semantic_discussion_admission_unavailable"))
        if self._clock() >= min(receipt.valid_until, request.deadline_at):
            return _held(request, "semantic_discussion_admission_expired")
        discussion = await self._runtime.deliberate(
            question=request.utterance,
            requester="Bragi",
            correlation_id=principal.authentication_request_ref,
            locale=request.locale,
            allow_t2=request.conversation_model_tier is SemanticConversationModelTier.T2,
        )
        if (
            discussion.get("authority") != "presentation_only"
            or discussion.get("trace_ref") != principal.authentication_request_ref
        ):
            return _held(request, "semantic_discussion_authority_invalid")
        verification = discussion.get("synthesis_verification")
        conclusion = discussion.get("conclusion")
        verified = (
            request.conversation_model_tier is SemanticConversationModelTier.T2
            and isinstance(conclusion, str)
            and bool(conclusion.strip())
            and isinstance(verification, dict)
            and set(verification) == {"request_sha256", "conclusion_sha256", "evidence_refs"}
            and isinstance(verification["request_sha256"], str)
            and re.fullmatch(r"[a-f0-9]{64}", verification["request_sha256"]) is not None
            and verification["conclusion_sha256"] == hashlib.sha256(conclusion.encode()).hexdigest()
            and isinstance(verification["evidence_refs"], (list, tuple))
            and bool(verification["evidence_refs"])
            and all(
                isinstance(ref, str) and 0 < len(ref.strip()) <= 256
                for ref in verification["evidence_refs"]
            )
            and discussion.get("status") == "completed"
            and discussion.get("t2_status") == "completed"
        )
        presentation = dict(discussion)
        if not verified:
            presentation["conclusion"] = None
        answer = json.dumps(presentation, ensure_ascii=False, allow_nan=False, indent=2)
        if len(answer) > 64_000:
            return _held(request, "semantic_discussion_output_too_large")
        if not verified or len(answer) > 16_000:
            return _held(request, "semantic_discussion_conclusion_held", answer=answer)
        adaptive = AdaptiveAnswer(
            answer=answer,
            role_agent="Bragi",
            quality_status="limited",
            goals=(
                AdaptiveGoalResult(
                    goal_id="agent_discussion",
                    kind="operational",
                    status="answered",
                    required=True,
                    evidence_refs=("agent-owned-discussion:" + content_digest(discussion),),
                    limitation="agent_owned_projection_only",
                ),
            ),
        )
        return SemanticTurnResult(
            disposition=SemanticTurnDisposition.ADVISORY_RESPONSE,
            reason_code="semantic_advisory_response",
            semantic_route="semantic_advisory_response",
            session_id=request.session_id,
            turn_id=request.turn_id,
            turn_sequence=request.turn_sequence,
            answer=answer,
            adaptive_answer=adaptive,
        )


def _held(
    request: SemanticTurnRequest, reason: str, *, answer: str | None = None
) -> SemanticTurnResult:
    return SemanticTurnResult(
        disposition=SemanticTurnDisposition.HELD,
        reason_code=reason,
        unavailable_reason="authoritative_evidence_unavailable",
        session_id=request.session_id,
        turn_id=request.turn_id,
        turn_sequence=request.turn_sequence,
        answer=answer,
    )
