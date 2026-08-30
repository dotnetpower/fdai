"""Compose authoritative Pantheon campaign turns over the Operator transport."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from fdai_service_contracts import SemanticTurnRequest

from fdai.agents import PANTHEON_SPECS, PantheonRuntime
from fdai.core.conversation_assurance import (
    ConversationAssuranceCoordinator,
    ConversationTurnTraceReceipt,
    PantheonCensusCase,
    build_pantheon_census,
    content_digest,
    evaluate_pantheon_turn,
)

from .pantheon_assurance_evidence import (
    answer_text as _answer_text,
)
from .pantheon_assurance_evidence import (
    assessment_input as _assessment_input,
)
from .pantheon_assurance_evidence import (
    deliberation_answer as _deliberation_answer,
)
from .pantheon_assurance_evidence import (
    deliberation_participants as _deliberation_participants,
)
from .pantheon_assurance_evidence import diagnostic_case as _diagnostic_case
from .pantheon_assurance_evidence import hard_zero_violations as _hard_zero_violations
from .pantheon_assurance_evidence import non_negative_int as _non_negative_int
from .pantheon_assurance_evidence import observed_rubrics as _observed_rubrics
from .pantheon_assurance_evidence import optional_string as _optional_string
from .pantheon_assurance_evidence import (
    pantheon_semantic_reviews as _pantheon_semantic_reviews,
)
from .pantheon_assurance_evidence import participants as _participants
from .pantheon_assurance_evidence import string_tuple as _string_tuple

_PURPOSE_PREFIX = "conversation-assurance:"
_SESSION_PREFIX = "pantheon-assurance:"
_SOURCE_REVISION_ENV = "FDAI_CONVERSATION_ASSURANCE_SOURCE_REVISION"
_SOURCE_CONTENT_DIGEST_ENV = "FDAI_CONVERSATION_ASSURANCE_SOURCE_CONTENT_DIGEST"
_LATENCY_BUDGET_MS = 300_000


class RuntimePantheonConversationAssurance:
    """Evaluate one fixed census case through Bragi and persist its diagnostic."""

    def __init__(
        self,
        *,
        pantheon: PantheonRuntime,
        coordinator: ConversationAssuranceCoordinator,
        source_revision: str,
        source_content_digest: str,
    ) -> None:
        if len(source_revision) != 40 or any(
            value not in "0123456789abcdef" for value in source_revision
        ):
            raise ValueError("conversation assurance source revision MUST be a full Git SHA-1")
        if len(source_content_digest) != 64 or any(
            value not in "0123456789abcdef" for value in source_content_digest
        ):
            raise ValueError("conversation assurance source content digest MUST be SHA-256")
        self._pantheon = pantheon
        self._coordinator = coordinator
        self._source_revision = source_revision
        self._source_content_digest = source_content_digest
        self._cases = {case.case_id: case for case in build_pantheon_census(PANTHEON_SPECS).cases}
        self._specs = {spec.name: spec for spec in PANTHEON_SPECS}

    async def evaluate(
        self,
        request: SemanticTurnRequest,
        *,
        case_id: str,
    ) -> Mapping[str, object]:
        """Return one answer plus content-free trace and persisted assessment identity."""

        case = self._cases.get(case_id)
        if case is None or request.utterance != case.question or request.locale != case.locale:
            raise ValueError("conversation assurance case does not match the fixed census")
        campaign_id = _campaign_id(request.session_id)
        started = time.monotonic()
        if case.suite == "t2":
            answer, trace_fields = await self._deliberation_turn(request, case)
        else:
            answer, trace_fields = await self._agent_turn(request, case)
        latency_ms = max(0, round((time.monotonic() - started) * 1000))
        trace = ConversationTurnTraceReceipt(
            campaign_id=campaign_id,
            case_id=case.case_id,
            source_revision=self._source_revision,
            source_content_digest=self._source_content_digest,
            latency_ms=latency_ms,
            latency_budget_ms=_LATENCY_BUDGET_MS,
            terminal_status="completed",
            **trace_fields,
        )
        observations = _observed_rubrics(case, answer, trace, specs=self._specs)
        assessment_input = _assessment_input(request, answer, trace)
        review = await self._coordinator.review(assessment_input)
        semantic_reviews = _pantheon_semantic_reviews(review.evaluator_outputs)
        diagnostic = evaluate_pantheon_turn(
            case=_diagnostic_case(case),
            trace=trace,
            observed_results=observations,
            semantic_reviews=semantic_reviews,
        )
        record = await self._coordinator.persist(
            assessment_input,
            review,
            pantheon_diagnostic=diagnostic,
        )
        return {
            "schema_version": "1.0.0",
            "answer": answer,
            "assessment_id": record.assessment_id,
            "trace_receipt_id": trace.receipt_digest,
            "pantheon_trace": trace.to_dict(),
            "pantheon_observations": {rubric.value: passed for rubric, passed in observations},
            "pantheon_semantic_reviews": [
                {
                    "reviewer_identity": item.reviewer_identity,
                    "model_family": item.model_family,
                    "confidence": item.confidence,
                    "results": {rubric.value: passed for rubric, passed in item.results},
                }
                for item in semantic_reviews
            ],
            "pantheon_diagnostic": diagnostic.to_dict(),
            "execution_authority": False,
        }

    async def _agent_turn(
        self,
        request: SemanticTurnRequest,
        case: PantheonCensusCase,
    ) -> tuple[str, dict[str, Any]]:
        turn = await self._pantheon.ask(
            session_id=request.session_id,
            user_id=request.principal.subject_id,
            question=request.utterance,
            initiator_role=request.principal.roles[-1].value,
            allow_action_proposal=False,
            materialize_handoff=False,
        )
        if turn is None:
            raise RuntimeError("Pantheon conversation runtime is unavailable")
        answer = _answer_text(turn.answer)
        fragment = turn.answer.get("pantheon_trace_fragment")
        if not isinstance(fragment, Mapping):
            raise RuntimeError("Pantheon trace fragment is unavailable")
        participants = _participants(fragment.get("participants"), self._specs)
        hard_zero = _hard_zero_violations(turn.answer, answer)
        return answer, {
            "turn_digest": str(fragment["turn_digest"]),
            "session_digest": str(fragment["session_digest"]),
            "correlation_digest": str(fragment["correlation_digest"]),
            "locale": case.locale,
            "expected_primary_agent": case.expected_primary_agent,
            "actual_primary_agent": turn.primary_agent,
            "routing_method": turn.decision.method,
            "semantic_score": turn.decision.semantic_score,
            "semantic_margin": turn.decision.semantic_margin,
            "contributors": _string_tuple(fragment.get("contributors"))[:2],
            "handoff_owner": fragment.get("handoff_owner"),
            "participants": participants,
            "tool_ids": _string_tuple(fragment.get("tool_ids")),
            "evidence_ref_digests": _string_tuple(fragment.get("evidence_ref_digests")),
            "evidence_manifest_digest": str(fragment["evidence_manifest_digest"]),
            "answer_digest": content_digest(answer),
            "verification_status": str(
                fragment.get("reported_verification_status") or "unverified"
            ),
            "verification_authority": str(
                fragment.get("reported_verification_authority") or "agent_owned_projection"
            ),
            "t1_reason": "not_required",
            "t1_signal_count": 0,
            "t1_conflict_count": 0,
            "t1_conclusion_preserved": True,
            "t2_required": False,
            "t2_attempted": False,
            "t2_status": "not_required",
            "t2_model_family": None,
            "budget_reserved": False,
            "metering_receipt_digest": None,
            "hard_zero_violations": hard_zero,
            "execution_authority": False,
        }

    async def _deliberation_turn(
        self,
        request: SemanticTurnRequest,
        case: PantheonCensusCase,
    ) -> tuple[str, dict[str, Any]]:
        result = await self._pantheon.deliberate(
            question=request.utterance,
            requester="Bragi",
            correlation_id=request.turn_id,
        )
        answer = _deliberation_answer(result)
        participants, evidence_refs = _deliberation_participants(
            result,
            self._specs,
            locale=request.locale,
        )
        evaluation = result.get("t1_evaluation")
        t1 = evaluation if isinstance(evaluation, Mapping) else {}
        conflicts = t1.get("conflicts")
        conflict_count = len(conflicts) if isinstance(conflicts, list) else 0
        t2_status = str(result.get("t2_status") or "not_required")
        t2_attempted = t2_status in {
            "completed",
            "error",
            "abstained",
            "output_too_large",
            "sensitive_output",
        }
        actual_primary = result.get("primary_agent")
        semantic_score = result.get("semantic_score")
        semantic_margin = result.get("semantic_margin")
        return answer, {
            "turn_digest": content_digest(f"{request.session_id}\0{request.utterance}"),
            "session_digest": content_digest(request.session_id),
            "correlation_digest": content_digest(request.turn_id),
            "locale": case.locale,
            "expected_primary_agent": case.expected_primary_agent,
            "actual_primary_agent": actual_primary if isinstance(actual_primary, str) else None,
            "routing_method": "t1_semantic",
            "semantic_score": (
                float(semantic_score) if isinstance(semantic_score, int | float) else None
            ),
            "semantic_margin": (
                float(semantic_margin) if isinstance(semantic_margin, int | float) else None
            ),
            "contributors": tuple(item.agent for item in participants[1:3]),
            "handoff_owner": None,
            "participants": participants,
            "tool_ids": (),
            "evidence_ref_digests": tuple(content_digest(value) for value in evidence_refs),
            "evidence_manifest_digest": content_digest("\0".join(evidence_refs)),
            "answer_digest": content_digest(answer),
            "verification_status": "verified" if evidence_refs else "unverified",
            "verification_authority": "pantheon_owned_projection",
            "t1_reason": str(t1.get("reason") or result.get("reason") or "unavailable"),
            "t1_signal_count": _non_negative_int(t1.get("signal_count")),
            "t1_conflict_count": conflict_count,
            "t1_conclusion_preserved": bool(answer),
            "t2_required": conflict_count > 0,
            "t2_attempted": t2_attempted,
            "t2_status": t2_status,
            "t2_model_family": _optional_string(result.get("t2_model_family")),
            "budget_reserved": t2_attempted,
            "metering_receipt_digest": _optional_string(result.get("metering_receipt_digest")),
            "hard_zero_violations": _hard_zero_violations(result, answer),
            "execution_authority": False,
        }


def assurance_case_id(purpose: str) -> str | None:
    """Return the fixed census identity encoded in a diagnostic purpose."""

    if not purpose.startswith(_PURPOSE_PREFIX):
        return None
    case_id = purpose.removeprefix(_PURPOSE_PREFIX)
    return case_id if case_id else None


def runtime_source_identity(
    repo_root: Path,
    environment: Mapping[str, str],
) -> tuple[str, str] | None:
    """Resolve a pinned runtime source identity without trusting the campaign caller."""

    revision = environment.get(_SOURCE_REVISION_ENV, "").strip()
    digest = environment.get(_SOURCE_CONTENT_DIGEST_ENV, "").strip()
    if revision or digest:
        if not revision or not digest:
            raise RuntimeError("conversation assurance source identity MUST be configured together")
        return revision, digest
    git = shutil.which("git")
    if git is None:
        return None
    try:
        completed = subprocess.run(  # noqa: S603 - resolved fixed git command
            [git, "rev-parse", "HEAD"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        diff = subprocess.run(  # noqa: S603 - resolved fixed git command
            [git, "diff", "--binary", "HEAD"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            timeout=30,
        )
        untracked = subprocess.run(  # noqa: S603 - resolved fixed git command
            [git, "ls-files", "--others", "--exclude-standard", "-z"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    digest_builder = hashlib.sha256(completed.stdout.encode() + diff.stdout)
    for raw_path in sorted(value for value in untracked.stdout.split(b"\0") if value):
        relative = Path(os.fsdecode(raw_path))
        path = repo_root / relative
        digest_builder.update(raw_path)
        if _source_path_is_safe(relative) and path.is_file() and not path.is_symlink():
            with path.open("rb") as stream:
                while chunk := stream.read(64 * 1024):
                    digest_builder.update(chunk)
    source_digest = digest_builder.hexdigest()
    return completed.stdout.strip(), source_digest


def _source_path_is_safe(path: Path) -> bool:
    roots = (
        Path("services/core-control-plane/src"),
        Path("services/operator-service/src"),
        Path("packages/service-contracts/src"),
        Path("scripts/automation"),
        Path("console/src"),
    )
    return path.suffix in {".py", ".ts", ".tsx", ".json"} and any(
        path.is_relative_to(root) for root in roots
    )


def _campaign_id(session_id: str) -> str:
    if not session_id.startswith(_SESSION_PREFIX):
        raise ValueError("conversation assurance session identity is invalid")
    campaign_id = session_id.removeprefix(_SESSION_PREFIX)
    if not campaign_id:
        raise ValueError("conversation assurance campaign identity is missing")
    return campaign_id


__all__ = [
    "RuntimePantheonConversationAssurance",
    "assurance_case_id",
    "runtime_source_identity",
]
