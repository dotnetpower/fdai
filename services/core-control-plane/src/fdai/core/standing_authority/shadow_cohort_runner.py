"""Deterministic local A3-E shadow cohort runner and canonical receipt.

Shadow-only: no execution authority, no promotion-registry mutation, no network,
no Azure, no delivery provider, no executor. Receipt is ``venue=local`` and
``evidence_class=synthetic_development``; it cannot satisfy runtime promotion.

FDAI-CONST-008 remains non-implemented. A governed live/pinned cohort and
independent promotion review remain separately authorized (#632).
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Final, Literal

from fdai.core.standing_authority.lifecycle_codec import (
    AuthorizationLifecycleError,
    content_digest,
    require_aware,
    require_digest,
    require_text,
)
from fdai.core.standing_authority.promotion_candidate_models import (
    LEASE_CONTRACT_VERSION,
    CandidateReviewRecord,
    CandidateStatus,
    DenialReason,
    PromotionCandidateRecord,
)
from fdai.core.standing_authority.promotion_candidate_ops import (
    plan_create_transition,
    plan_external_denial,
    plan_review_transition,
)

# ---------------------------------------------------------------------------
# Timeout constants - fixed contract; deterministic inputs, no wall-clock reads
# ---------------------------------------------------------------------------

COHORT_TIMEOUT_TOTAL_S: Final[int] = 1800
COHORT_TIMEOUT_NO_PROGRESS_S: Final[int] = 120
COHORT_TIMEOUT_PER_CASE_S: Final[int] = 30
COHORT_CANDIDATE_CONTRACT_VERSION: Final[str] = "a3e-candidate-v1"

# ActionPromotionRegistry lives here; digest proves no mutation.
_REGISTRY_PATH: Final[Path] = Path(__file__).resolve().parents[1] / "risk_gate" / "gate.py"
_SENTINEL_DIGEST: Final[str] = "sha256:" + "0" * 64


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class CohortDisposition(StrEnum):
    """Terminal disposition produced by one cohort case."""

    ELIGIBLE = "eligible"
    """Candidate reached APPROVED status without denial."""

    DENIED = "denied"
    """Candidate terminated with a typed DenialReason."""


class CohortOutcomeStatus(StrEnum):
    """How a manifest-declared case was handled by the runner."""

    ACCEPTED = "accepted"
    """Case ran to a terminal disposition."""

    DUPLICATE = "duplicate"
    """Case ID appeared more than once in the corpus."""

    UNEXPECTED = "unexpected"
    """Case ID found in corpus but not declared in manifest."""

    MISSING = "missing"
    """Case ID declared in manifest but absent from corpus."""

    ERRORED = "errored"
    """Case raised an unexpected exception during execution."""

    INTERRUPTED = "interrupted"
    """Case exceeded a timeout boundary (total, no-progress, or per-case)."""


# ---------------------------------------------------------------------------
# Manifest - content-digested; must include at least one ELIGIBLE entry
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CohortManifestEntry:
    """One declared case with its expected terminal disposition."""

    case_id: str
    expected_disposition: CohortDisposition
    expected_denial_reason: DenialReason | None

    def __post_init__(self) -> None:
        require_text("case_id", self.case_id)
        if (
            self.expected_disposition is CohortDisposition.ELIGIBLE
            and self.expected_denial_reason is not None
        ):
            raise AuthorizationLifecycleError(
                "ELIGIBLE cases must not specify expected_denial_reason"
            )
        if (
            self.expected_disposition is CohortDisposition.DENIED
            and self.expected_denial_reason is None
        ):
            raise AuthorizationLifecycleError("DENIED cases must specify expected_denial_reason")


@dataclass(frozen=True, slots=True)
class CohortManifest:
    """Content-digested manifest predeclaring all expected cases.

    At least one ELIGIBLE entry is required; an all-denied manifest is invalid.
    """

    manifest_id: str
    source_revision_id: str
    candidate_contract_version: str
    lease_contract_version: str
    entries: tuple[CohortManifestEntry, ...]

    def __post_init__(self) -> None:
        require_digest("manifest_id", self.manifest_id)
        require_text("source_revision_id", self.source_revision_id)
        if not self.entries:
            raise AuthorizationLifecycleError("manifest must declare at least one case")
        if not any(e.expected_disposition is CohortDisposition.ELIGIBLE for e in self.entries):
            raise AuthorizationLifecycleError(
                "all-denied manifest is invalid; at least one ELIGIBLE entry required"
            )
        ids = [e.case_id for e in self.entries]
        if len(set(ids)) != len(ids):
            raise AuthorizationLifecycleError("manifest entries must have distinct case_ids")
        expected = _manifest_digest(
            self.source_revision_id,
            self.candidate_contract_version,
            self.lease_contract_version,
            self.entries,
        )
        if self.manifest_id != expected:
            raise AuthorizationLifecycleError("manifest_id digest mismatch")


def build_manifest(
    *,
    source_revision_id: str,
    entries: tuple[CohortManifestEntry, ...],
) -> CohortManifest:
    """Build a manifest deriving ``manifest_id`` from content."""
    mid = _manifest_digest(
        source_revision_id,
        COHORT_CANDIDATE_CONTRACT_VERSION,
        LEASE_CONTRACT_VERSION,
        entries,
    )
    return CohortManifest(
        manifest_id=mid,
        source_revision_id=source_revision_id,
        candidate_contract_version=COHORT_CANDIDATE_CONTRACT_VERSION,
        lease_contract_version=LEASE_CONTRACT_VERSION,
        entries=entries,
    )


def _manifest_digest(
    source_revision_id: str,
    candidate_contract_version: str,
    lease_contract_version: str,
    entries: tuple[CohortManifestEntry, ...],
) -> str:
    sorted_entries = sorted(entries, key=lambda e: e.case_id)
    return content_digest(
        {
            "source_revision_id": source_revision_id,
            "candidate_contract_version": candidate_contract_version,
            "lease_contract_version": lease_contract_version,
            "entries": [
                {
                    "case_id": e.case_id,
                    "expected_disposition": e.expected_disposition.value,
                    "expected_denial_reason": (
                        e.expected_denial_reason.value if e.expected_denial_reason else None
                    ),
                }
                for e in sorted_entries
            ],
        }
    )


# ---------------------------------------------------------------------------
# Case inputs
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CohortExternalDenialInput:
    """Parameters for an external denial step (expiry, revocation, lease, etc.)."""

    reason: DenialReason
    detail: str
    actor_ref: str
    authentication_evidence_digest: str
    occurred_at: datetime

    def __post_init__(self) -> None:
        require_text("detail", self.detail)
        if not self.actor_ref.startswith("human:"):
            raise AuthorizationLifecycleError(
                "external denial actor_ref must be a human: principal"
            )
        require_digest("authentication_evidence_digest", self.authentication_evidence_digest)
        require_aware("occurred_at", self.occurred_at)


@dataclass(frozen=True, slots=True)
class CohortCaseInput:
    """Synthetic inputs for one cohort case. No authority, network, or provider calls."""

    case_id: str
    record: PromotionCandidateRecord
    review_steps: tuple[CandidateReviewRecord, ...]
    external_denial: CohortExternalDenialInput | None

    def __post_init__(self) -> None:
        require_text("case_id", self.case_id)


# ---------------------------------------------------------------------------
# Outcome
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CohortCaseOutcome:
    """Recorded outcome for one cohort case."""

    case_id: str
    outcome_status: CohortOutcomeStatus
    actual_disposition: CohortDisposition | None
    actual_denial_reason: DenialReason | None
    disposition_matched: bool
    detail: str
    per_case_elapsed_s: float


# ---------------------------------------------------------------------------
# Receipt - canonical, content-addressed, authority-free
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CohortReceipt:
    """Canonical content-addressed shadow cohort receipt.

    ``venue=local``, ``evidence_class=synthetic_development``.
    All authority flags are False. Cannot satisfy runtime promotion.
    """

    receipt_id: str
    manifest_id: str
    source_revision_id: str
    corpus_digest: str
    configuration_digest: str
    candidate_contract_version: str
    lease_contract_version: str
    outcomes: tuple[CohortCaseOutcome, ...]
    total_count: int
    accepted_count: int
    eligible_count: int
    denied_count: int
    error_count: int
    total_elapsed_s: float
    timeout_total_s: int
    timeout_no_progress_s: int
    timeout_per_case_s: int
    registry_before_digest: str
    registry_after_digest: str
    complete: bool
    zero_policy_escapes: bool
    venue: Literal["local"] = "local"
    evidence_class: Literal["synthetic_development"] = "synthetic_development"
    execution_authority: Literal[False] = False
    promotion_authority: Literal[False] = False

    def __post_init__(self) -> None:
        require_digest("receipt_id", self.receipt_id)
        require_digest("manifest_id", self.manifest_id)
        require_digest("corpus_digest", self.corpus_digest)
        require_digest("configuration_digest", self.configuration_digest)
        require_digest("registry_before_digest", self.registry_before_digest)
        require_digest("registry_after_digest", self.registry_after_digest)
        if self.execution_authority is not False or self.promotion_authority is not False:
            raise AuthorizationLifecycleError("authority flags MUST be False")
        expected = content_digest(_receipt_body_dict(self))
        if self.receipt_id != expected:
            raise AuthorizationLifecycleError("receipt_id digest mismatch")


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _compute_registry_digest(path: Path) -> str:
    try:
        return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return _SENTINEL_DIGEST


def _compute_corpus_digest(corpus: tuple[CohortCaseInput, ...]) -> str:
    sorted_corpus = sorted(corpus, key=lambda ci: ci.case_id)
    return content_digest(
        {
            "cases": [
                {
                    "case_id": ci.case_id,
                    "candidate_id": ci.record.candidate_id,
                    "review_ids": [review.review_id for review in ci.review_steps],
                    "external_denial": (
                        {
                            "reason": ci.external_denial.reason.value,
                            "detail": ci.external_denial.detail,
                            "actor_ref": ci.external_denial.actor_ref,
                            "authentication_evidence_digest": (
                                ci.external_denial.authentication_evidence_digest
                            ),
                            "occurred_at": ci.external_denial.occurred_at.isoformat(),
                        }
                        if ci.external_denial is not None
                        else None
                    ),
                }
                for ci in sorted_corpus
            ]
        }
    )


def _compute_configuration_digest() -> str:
    return content_digest(
        {
            "timeout_total_s": COHORT_TIMEOUT_TOTAL_S,
            "timeout_no_progress_s": COHORT_TIMEOUT_NO_PROGRESS_S,
            "timeout_per_case_s": COHORT_TIMEOUT_PER_CASE_S,
            "candidate_contract_version": COHORT_CANDIDATE_CONTRACT_VERSION,
            "lease_contract_version": LEASE_CONTRACT_VERSION,
        }
    )


def _outcome_body(o: CohortCaseOutcome) -> dict[str, object]:
    return {
        "case_id": o.case_id,
        "outcome_status": o.outcome_status.value,
        "actual_disposition": (o.actual_disposition.value if o.actual_disposition else None),
        "actual_denial_reason": (o.actual_denial_reason.value if o.actual_denial_reason else None),
        "disposition_matched": o.disposition_matched,
        "detail": o.detail,
        "per_case_elapsed_s": o.per_case_elapsed_s,
    }


def _receipt_body_dict(r: CohortReceipt) -> dict[str, object]:
    return {
        "manifest_id": r.manifest_id,
        "source_revision_id": r.source_revision_id,
        "corpus_digest": r.corpus_digest,
        "configuration_digest": r.configuration_digest,
        "candidate_contract_version": r.candidate_contract_version,
        "lease_contract_version": r.lease_contract_version,
        "outcomes": [_outcome_body(o) for o in r.outcomes],
        "total_count": r.total_count,
        "accepted_count": r.accepted_count,
        "eligible_count": r.eligible_count,
        "denied_count": r.denied_count,
        "error_count": r.error_count,
        "total_elapsed_s": r.total_elapsed_s,
        "timeout_total_s": r.timeout_total_s,
        "timeout_no_progress_s": r.timeout_no_progress_s,
        "timeout_per_case_s": r.timeout_per_case_s,
        "registry_before_digest": r.registry_before_digest,
        "registry_after_digest": r.registry_after_digest,
        "complete": r.complete,
        "zero_policy_escapes": r.zero_policy_escapes,
        "venue": r.venue,
        "evidence_class": r.evidence_class,
    }


def _check_complete(
    outcomes: list[CohortCaseOutcome],
    before_digest: str,
    after_digest: str,
) -> bool:
    if _SENTINEL_DIGEST in (before_digest, after_digest):
        return False
    if before_digest != after_digest:
        return False
    return all(o.outcome_status is CohortOutcomeStatus.ACCEPTED for o in outcomes)


def _interrupted_outcome(case_id: str, detail: str, elapsed: float) -> CohortCaseOutcome:
    return CohortCaseOutcome(
        case_id=case_id,
        outcome_status=CohortOutcomeStatus.INTERRUPTED,
        actual_disposition=None,
        actual_denial_reason=None,
        disposition_matched=False,
        detail=detail,
        per_case_elapsed_s=elapsed,
    )


def _run_one_case(
    entry: CohortManifestEntry,
    case_input: CohortCaseInput,
    per_case_elapsed_s: float,
) -> CohortCaseOutcome:
    """Execute one case through the promotion-candidate ops. Fail closed on exception."""
    try:
        result = plan_create_transition(case_input.record)
        current_snapshot = result.snapshot

        for review in case_input.review_steps:
            if current_snapshot.status is not CandidateStatus.PENDING:
                break
            result = plan_review_transition(
                record=case_input.record,
                snapshot=current_snapshot,
                review=review,
            )
            current_snapshot = result.snapshot

        if (
            case_input.external_denial is not None
            and current_snapshot.status is CandidateStatus.PENDING
        ):
            ed = case_input.external_denial
            result = plan_external_denial(
                record=case_input.record,
                snapshot=current_snapshot,
                reason=ed.reason,
                detail=ed.detail,
                actor_ref=ed.actor_ref,
                authentication_evidence_digest=ed.authentication_evidence_digest,
                occurred_at=ed.occurred_at,
            )
            current_snapshot = result.snapshot

        final_snap = result.snapshot
        if final_snap.status is CandidateStatus.APPROVED:
            actual_disposition: CohortDisposition = CohortDisposition.ELIGIBLE
            actual_denial_reason: DenialReason | None = None
        elif final_snap.status is CandidateStatus.DENIED:
            actual_disposition = CohortDisposition.DENIED
            denial = result.denial
            actual_denial_reason = denial.denial_reason if denial is not None else None
        else:
            return CohortCaseOutcome(
                case_id=entry.case_id,
                outcome_status=CohortOutcomeStatus.ERRORED,
                actual_disposition=None,
                actual_denial_reason=None,
                disposition_matched=False,
                detail="case did not reach a terminal status (still PENDING)",
                per_case_elapsed_s=per_case_elapsed_s,
            )

        matched = (
            actual_disposition is entry.expected_disposition
            and actual_denial_reason is entry.expected_denial_reason
        )
        return CohortCaseOutcome(
            case_id=entry.case_id,
            outcome_status=CohortOutcomeStatus.ACCEPTED,
            actual_disposition=actual_disposition,
            actual_denial_reason=actual_denial_reason,
            disposition_matched=matched,
            detail="",
            per_case_elapsed_s=per_case_elapsed_s,
        )
    except Exception as exc:  # noqa: BLE001
        return CohortCaseOutcome(
            case_id=entry.case_id,
            outcome_status=CohortOutcomeStatus.ERRORED,
            actual_disposition=None,
            actual_denial_reason=None,
            disposition_matched=False,
            detail=f"exception: {type(exc).__name__}: {exc}",
            per_case_elapsed_s=per_case_elapsed_s,
        )


# ---------------------------------------------------------------------------
# Runner - pure in-memory; no default filesystem write, no network/provider
# ---------------------------------------------------------------------------


def run_cohort(
    manifest: CohortManifest,
    corpus: tuple[CohortCaseInput, ...],
    per_case_elapsed_s: Mapping[str, float],
    *,
    registry_path: Path | None = None,
) -> CohortReceipt:
    """Run the cohort deterministically.

    No wall-clock reads, no side effects, no registry mutation. ``registry_path``
    defaults to the canonical ActionPromotionRegistry source; before/after digests
    prove no mutation occurred during the run.
    """
    reg_path = registry_path or _REGISTRY_PATH
    before_digest = _compute_registry_digest(reg_path)

    corpus_ids_seen: dict[str, int] = {}
    for ci in corpus:
        corpus_ids_seen[ci.case_id] = corpus_ids_seen.get(ci.case_id, 0) + 1
    corpus_by_id: dict[str, CohortCaseInput] = {ci.case_id: ci for ci in corpus}
    manifest_ids = {e.case_id for e in manifest.entries}

    outcomes: list[CohortCaseOutcome] = []

    # Record unexpected corpus cases (not in manifest) first.
    seen_unexpected: set[str] = set()
    for ci in corpus:
        if ci.case_id not in manifest_ids and ci.case_id not in seen_unexpected:
            seen_unexpected.add(ci.case_id)
            outcomes.append(
                CohortCaseOutcome(
                    case_id=ci.case_id,
                    outcome_status=CohortOutcomeStatus.UNEXPECTED,
                    actual_disposition=None,
                    actual_denial_reason=None,
                    disposition_matched=False,
                    detail="case not declared in manifest",
                    per_case_elapsed_s=per_case_elapsed_s.get(ci.case_id, 0.0),
                )
            )

    cumulative_s = 0.0
    last_accepted_s = 0.0

    for entry in manifest.entries:
        elapsed = per_case_elapsed_s.get(entry.case_id, 0.0)

        # Total timeout check.
        if cumulative_s >= COHORT_TIMEOUT_TOTAL_S:
            outcomes.append(_interrupted_outcome(entry.case_id, "total timeout exceeded", elapsed))
            continue

        # No-progress timeout check (after at least one case has run).
        if cumulative_s > 0.0 and (cumulative_s - last_accepted_s) > COHORT_TIMEOUT_NO_PROGRESS_S:
            outcomes.append(
                _interrupted_outcome(entry.case_id, "no-progress timeout exceeded", elapsed)
            )
            cumulative_s += elapsed
            continue

        # Per-case timeout check.
        if elapsed > COHORT_TIMEOUT_PER_CASE_S:
            outcomes.append(
                _interrupted_outcome(entry.case_id, "per-case timeout exceeded", elapsed)
            )
            cumulative_s += elapsed
            continue

        # Duplicate in corpus check.
        if corpus_ids_seen.get(entry.case_id, 0) > 1:
            outcomes.append(
                CohortCaseOutcome(
                    case_id=entry.case_id,
                    outcome_status=CohortOutcomeStatus.DUPLICATE,
                    actual_disposition=None,
                    actual_denial_reason=None,
                    disposition_matched=False,
                    detail="case_id appears more than once in corpus",
                    per_case_elapsed_s=elapsed,
                )
            )
            cumulative_s += elapsed
            continue

        # Missing from corpus check.
        case_input = corpus_by_id.get(entry.case_id)
        if case_input is None:
            outcomes.append(
                CohortCaseOutcome(
                    case_id=entry.case_id,
                    outcome_status=CohortOutcomeStatus.MISSING,
                    actual_disposition=None,
                    actual_denial_reason=None,
                    disposition_matched=False,
                    detail="declared in manifest but absent from corpus",
                    per_case_elapsed_s=elapsed,
                )
            )
            cumulative_s += elapsed
            continue

        outcome = _run_one_case(entry, case_input, elapsed)
        outcomes.append(outcome)
        cumulative_s += elapsed
        if outcome.outcome_status is CohortOutcomeStatus.ACCEPTED:
            last_accepted_s = cumulative_s

    after_digest = _compute_registry_digest(reg_path)

    corpus_digest = _compute_corpus_digest(corpus)
    configuration_digest = _compute_configuration_digest()
    total_elapsed_s = sum(o.per_case_elapsed_s for o in outcomes)
    accepted_count = sum(1 for o in outcomes if o.outcome_status is CohortOutcomeStatus.ACCEPTED)
    eligible_count = sum(1 for o in outcomes if o.actual_disposition is CohortDisposition.ELIGIBLE)
    denied_count = sum(1 for o in outcomes if o.actual_disposition is CohortDisposition.DENIED)
    error_count = sum(
        1
        for o in outcomes
        if o.outcome_status in (CohortOutcomeStatus.ERRORED, CohortOutcomeStatus.INTERRUPTED)
    )

    complete = _check_complete(outcomes, before_digest, after_digest)
    zero_policy_escapes = complete and all(o.disposition_matched for o in outcomes)

    # Build the body dict directly to compute receipt_id before CohortReceipt is constructed.
    outcomes_tuple = tuple(outcomes)
    body_for_id: dict[str, object] = {
        "manifest_id": manifest.manifest_id,
        "source_revision_id": manifest.source_revision_id,
        "corpus_digest": corpus_digest,
        "configuration_digest": configuration_digest,
        "candidate_contract_version": manifest.candidate_contract_version,
        "lease_contract_version": manifest.lease_contract_version,
        "outcomes": [_outcome_body(o) for o in outcomes_tuple],
        "total_count": len(outcomes_tuple),
        "accepted_count": accepted_count,
        "eligible_count": eligible_count,
        "denied_count": denied_count,
        "error_count": error_count,
        "total_elapsed_s": total_elapsed_s,
        "timeout_total_s": COHORT_TIMEOUT_TOTAL_S,
        "timeout_no_progress_s": COHORT_TIMEOUT_NO_PROGRESS_S,
        "timeout_per_case_s": COHORT_TIMEOUT_PER_CASE_S,
        "registry_before_digest": before_digest,
        "registry_after_digest": after_digest,
        "complete": complete,
        "zero_policy_escapes": zero_policy_escapes,
        "venue": "local",
        "evidence_class": "synthetic_development",
    }
    receipt_id = content_digest(body_for_id)

    return CohortReceipt(
        receipt_id=receipt_id,
        manifest_id=manifest.manifest_id,
        source_revision_id=manifest.source_revision_id,
        corpus_digest=corpus_digest,
        configuration_digest=configuration_digest,
        candidate_contract_version=manifest.candidate_contract_version,
        lease_contract_version=manifest.lease_contract_version,
        outcomes=outcomes_tuple,
        total_count=len(outcomes_tuple),
        accepted_count=accepted_count,
        eligible_count=eligible_count,
        denied_count=denied_count,
        error_count=error_count,
        total_elapsed_s=total_elapsed_s,
        timeout_total_s=COHORT_TIMEOUT_TOTAL_S,
        timeout_no_progress_s=COHORT_TIMEOUT_NO_PROGRESS_S,
        timeout_per_case_s=COHORT_TIMEOUT_PER_CASE_S,
        registry_before_digest=before_digest,
        registry_after_digest=after_digest,
        complete=complete,
        zero_policy_escapes=zero_policy_escapes,
    )


# ---------------------------------------------------------------------------
# Artifact writer - explicit seam; no default write in the runner
# ---------------------------------------------------------------------------


def _receipt_to_dict(receipt: CohortReceipt) -> dict[str, object]:
    body = dict(_receipt_body_dict(receipt))
    body["receipt_id"] = receipt.receipt_id
    body["execution_authority"] = receipt.execution_authority
    body["promotion_authority"] = receipt.promotion_authority
    return body


class CohortArtifactWriter:
    """Explicit writer seam. The runner never writes to disk by default.

    Resolved path containment is validated before writing. A symlink
    ``artifact_dir`` is rejected to prevent symlink-escape attacks.
    """

    def __init__(self, artifact_dir: Path) -> None:
        if artifact_dir.is_symlink():
            raise ValueError(f"artifact_dir must not be a symlink: {artifact_dir}")
        self._dir = artifact_dir.resolve()

    def write_receipt(self, receipt: CohortReceipt) -> Path:
        """Write the receipt as JSON under the declared artifact directory."""
        filename = f"cohort-receipt-{receipt.receipt_id[7:15]}.json"
        out = self._dir / filename
        self._dir.mkdir(parents=True, exist_ok=True)
        directory_flags = os.O_RDONLY | os.O_DIRECTORY
        if hasattr(os, "O_NOFOLLOW"):
            directory_flags |= os.O_NOFOLLOW
        file_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            file_flags |= os.O_NOFOLLOW
        directory_fd = os.open(self._dir, directory_flags)
        try:
            file_fd = os.open(filename, file_flags, 0o600, dir_fd=directory_fd)
            with os.fdopen(file_fd, "w", encoding="utf-8") as stream:
                stream.write(
                    json.dumps(
                        _receipt_to_dict(receipt),
                        sort_keys=True,
                        indent=2,
                        ensure_ascii=True,
                    )
                )
        finally:
            os.close(directory_fd)
        return out


__all__ = [
    "COHORT_CANDIDATE_CONTRACT_VERSION",
    "COHORT_TIMEOUT_NO_PROGRESS_S",
    "COHORT_TIMEOUT_PER_CASE_S",
    "COHORT_TIMEOUT_TOTAL_S",
    "CohortArtifactWriter",
    "CohortCaseInput",
    "CohortCaseOutcome",
    "CohortDisposition",
    "CohortExternalDenialInput",
    "CohortManifest",
    "CohortManifestEntry",
    "CohortOutcomeStatus",
    "CohortReceipt",
    "build_manifest",
    "run_cohort",
]
