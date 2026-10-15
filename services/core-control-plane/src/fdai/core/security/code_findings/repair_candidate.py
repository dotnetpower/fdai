"""Fail-closed validation for optional code-security repair candidates.

Candidates are inert suggestions. They carry no execution authority and become valid evidence only
after the existing diff guard, tests, exact-revision rescan, and displayed-path replay all pass.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Literal

from fdai.core.security.code_findings.diff_guard import evaluate_diff
from fdai.core.security.code_findings.models import CodeSecurityIssue, FlowStep
from fdai.core.security.code_findings.result_import import ValidationState
from fdai.core.security.code_findings.verification import FixVerdict, FixVerification

_REVISION = re.compile(r"^[0-9a-f]{40}([0-9a-f]{24})?$")


@dataclass(frozen=True, slots=True)
class RepairCandidateRequest:
    schema_version: Literal["1.0.0"]
    request_id: str
    issue_id: str
    baseline_revision: str
    weakness_class: str
    allowed_paths: tuple[str, ...]
    path_id: str
    path_digest: str
    graph_digest: str
    steps: tuple[FlowStep, ...]
    execution_authority: Literal[False] = False

    def canonical_bytes(self) -> bytes:
        return json.dumps(
            asdict(self), ensure_ascii=True, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")

    def digest(self) -> str:
        return f"sha256:{hashlib.sha256(self.canonical_bytes()).hexdigest()}"


@dataclass(frozen=True, slots=True)
class RepairCandidate:
    schema_version: Literal["1.0.0"]
    request_id: str
    issue_id: str
    baseline_revision: str
    candidate_revision: str
    path_id: str
    path_digest: str
    unified_diff: str
    test_validation: ValidationState
    execution_authority: bool = False


@dataclass(frozen=True, slots=True)
class RepairCandidateValidation:
    accepted: bool
    reasons: tuple[str, ...]
    diff_receipt: Mapping[str, object]
    execution_authority: Literal[False] = False


def build_repair_candidate_request(issue: CodeSecurityIssue) -> RepairCandidateRequest | None:
    """Build one source-free request from the governing displayed path, or abstain."""
    evidence = issue.analysis_evidence
    if evidence is None or not issue.code_flow:
        return None
    identity = {
        "issue_id": issue.issue_id,
        "revision": issue.revision,
        "path_id": evidence.path_id,
        "path_digest": evidence.path_digest,
        "graph_digest": evidence.graph_digest,
    }
    request_id = (
        "repair-request:"
        + hashlib.sha256(
            json.dumps(identity, separators=(",", ":"), sort_keys=True).encode("utf-8")
        ).hexdigest()
    )
    return RepairCandidateRequest(
        schema_version="1.0.0",
        request_id=request_id,
        issue_id=issue.issue_id,
        baseline_revision=issue.revision,
        weakness_class=issue.weakness_class,
        allowed_paths=(issue.fix_site.path,),
        path_id=evidence.path_id,
        path_digest=evidence.path_digest,
        graph_digest=evidence.graph_digest,
        steps=issue.code_flow,
    )


def validate_repair_candidate(
    request: RepairCandidateRequest,
    candidate: RepairCandidate,
    *,
    policy: Mapping[str, object],
    verification: FixVerification,
    rescan_revision: str,
    displayed_issue: CodeSecurityIssue,
) -> RepairCandidateValidation:
    """Validate an inert candidate against independent authoritative evidence."""
    reasons: list[str] = []
    if candidate.execution_authority:
        reasons.append("candidate_requests_execution_authority")
    if (
        candidate.request_id != request.request_id
        or candidate.issue_id != request.issue_id
        or candidate.baseline_revision != request.baseline_revision
    ):
        reasons.append("candidate_identity_mismatch")
    if candidate.path_id != request.path_id or candidate.path_digest != request.path_digest:
        reasons.append("candidate_path_mismatch")
    if (
        _REVISION.fullmatch(candidate.candidate_revision) is None
        or candidate.candidate_revision == request.baseline_revision
        or candidate.candidate_revision != rescan_revision
    ):
        reasons.append("candidate_revision_not_rescanned")
    if candidate.test_validation is not ValidationState.TESTS_PASSED:
        reasons.append("candidate_tests_not_passed")
    if (
        verification.issue_id != request.issue_id
        or verification.verdict is not FixVerdict.FIXED_VERIFIED
    ):
        reasons.append("candidate_fix_not_verified")
    evidence = displayed_issue.analysis_evidence
    if (
        displayed_issue.issue_id != request.issue_id
        or displayed_issue.revision != request.baseline_revision
        or evidence is None
        or evidence.path_id != request.path_id
        or evidence.path_digest != request.path_digest
        or evidence.graph_digest != request.graph_digest
        or displayed_issue.code_flow != request.steps
    ):
        reasons.append("displayed_path_replay_mismatch")
    diff_receipt = evaluate_diff(candidate.unified_diff, request.allowed_paths, policy)
    if not diff_receipt.get("ok") or diff_receipt.get("files_checked") != 1:
        reasons.append("candidate_diff_rejected")
    return RepairCandidateValidation(
        accepted=not reasons,
        reasons=tuple(reasons),
        diff_receipt=diff_receipt,
    )


__all__ = [
    "RepairCandidate",
    "RepairCandidateRequest",
    "RepairCandidateValidation",
    "build_repair_candidate_request",
    "validate_repair_candidate",
]
