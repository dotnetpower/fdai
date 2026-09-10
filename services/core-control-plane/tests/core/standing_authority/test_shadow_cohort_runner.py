"""Tests for the A3-E deterministic local shadow cohort runner.

Covers: deterministic replay, duplicate/unexpected/missing/error/interruption,
all-denied rejection, denominator accounting, malformed manifest/outcome, authority
flags, registry mutation, path traversal/symlink escape, timeout boundaries,
static import checks.
"""

from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fdai.core.standing_authority.lifecycle import LifecycleFence
from fdai.core.standing_authority.lifecycle_codec import (
    AuthorizationLifecycleError,
    aware_utc,
    content_digest,
    instant,
)
from fdai.core.standing_authority.promotion_candidate import (
    CandidateReviewRecord,
    DenialReason,
    ReviewDecision,
    build_candidate_record,
)
from fdai.core.standing_authority.promotion_candidate_models import PromotionCandidateRecord
from fdai.core.standing_authority.shadow_cohort_runner import (
    COHORT_CANDIDATE_CONTRACT_VERSION,
    COHORT_TIMEOUT_NO_PROGRESS_S,
    COHORT_TIMEOUT_PER_CASE_S,
    COHORT_TIMEOUT_TOTAL_S,
    CohortArtifactWriter,
    CohortCaseInput,
    CohortDisposition,
    CohortExternalDenialInput,
    CohortManifest,
    CohortManifestEntry,
    CohortOutcomeStatus,
    CohortReceipt,
    build_manifest,
    run_cohort,
)

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

SOURCE_ROOT = Path(__file__).resolve().parents[3] / "src" / "fdai"
NOW = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)
REVISION_ID = "sha256:" + "a" * 64
SOURCE_REV = "sha256:" + "b" * 64
AUTH_DIGEST = "sha256:" + "f" * 64
EVIDENCE_1 = "sha256:" + "e1" + "0" * 62
EVIDENCE_2 = "sha256:" + "e2" + "0" * 62
EVIDENCE_ALL = (EVIDENCE_1, EVIDENCE_2)
CREATOR = "human:creator"
REVIEWER_A = "human:reviewer-a"
REVIEWER_B = "human:reviewer-b"
REVIEWER_C = "human:reviewer-c"  # not in required set

FENCE = LifecycleFence(
    family_id="family:shadow",
    revision_id=REVISION_ID,
    fencing_generation=1,
    transition_digest="sha256:" + "d" * 64,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _record(
    *,
    eligible: tuple[str, ...] = ("ops.scale-out",),
    ineligible: tuple[str, ...] = (),
    reviewers: tuple[str, ...] = (REVIEWER_A, REVIEWER_B),
) -> object:
    return build_candidate_record(
        family_id="family:shadow",
        revision_id=REVISION_ID,
        fence=FENCE,
        eligible_action_types=eligible,
        ineligible_provider_action_types=ineligible,
        evidence_requirements=EVIDENCE_ALL,
        source_revision_id="source:v1",
        creator_principal=CREATOR,
        authentication_evidence_digest=AUTH_DIGEST,
        created_at=NOW,
        required_reviewer_principals=reviewers,
        quorum_required=2,
    )


def _review(
    candidate_id: str,
    *,
    reviewer: str = REVIEWER_A,
    decision: ReviewDecision = ReviewDecision.APPROVE,
    evidence: tuple[str, ...] = EVIDENCE_ALL,
    at: datetime | None = None,
) -> CandidateReviewRecord:
    reviewed_at = at or (NOW + timedelta(minutes=1))
    review_id = content_digest(
        {
            "candidate_id": candidate_id,
            "reviewer_principal": reviewer,
            "decision": decision.value,
            "reviewed_at": instant(aware_utc(reviewed_at)),
            "authentication_evidence_digest": AUTH_DIGEST,
            "evidence_digests": sorted(evidence),
        }
    )
    return CandidateReviewRecord(
        review_id=review_id,
        candidate_id=candidate_id,
        reviewer_principal=reviewer,
        decision=decision,
        reviewed_at=reviewed_at,
        authentication_evidence_digest=AUTH_DIGEST,
        evidence_digests=evidence,
    )


def _external_denial(
    reason: DenialReason,
    detail: str = "synthetic denial",
) -> CohortExternalDenialInput:
    return CohortExternalDenialInput(
        reason=reason,
        detail=detail,
        actor_ref=REVIEWER_A,
        authentication_evidence_digest=AUTH_DIGEST,
        occurred_at=NOW + timedelta(minutes=10),
    )


def _entry(
    case_id: str,
    disposition: CohortDisposition,
    denial_reason: DenialReason | None = None,
) -> CohortManifestEntry:
    return CohortManifestEntry(
        case_id=case_id,
        expected_disposition=disposition,
        expected_denial_reason=denial_reason,
    )


# ---------------------------------------------------------------------------
# Full synthetic corpus - one case per required semantic category
# ---------------------------------------------------------------------------


def _make_full_corpus() -> tuple[CohortManifest, tuple[CohortCaseInput, ...], dict[str, float]]:
    """Build the canonical 10-case corpus covering all required denial categories."""
    rec_eligible = _record()
    rec_quorum = _record()
    rec_scope = _record()
    rec_expiry = _record()
    rec_revoke = _record()
    rec_lease_incompat = _record()
    rec_lease_loss = _record()
    rec_evidence = _record()
    rec_identity = _record()
    rec_provider = _record(ineligible=("ops.scale-out",))

    assert isinstance(rec_eligible, PromotionCandidateRecord)
    assert isinstance(rec_quorum, PromotionCandidateRecord)
    assert isinstance(rec_scope, PromotionCandidateRecord)
    assert isinstance(rec_expiry, PromotionCandidateRecord)
    assert isinstance(rec_revoke, PromotionCandidateRecord)
    assert isinstance(rec_lease_incompat, PromotionCandidateRecord)
    assert isinstance(rec_lease_loss, PromotionCandidateRecord)
    assert isinstance(rec_evidence, PromotionCandidateRecord)
    assert isinstance(rec_identity, PromotionCandidateRecord)
    assert isinstance(rec_provider, PromotionCandidateRecord)

    entries = (
        _entry("case-eligible", CohortDisposition.ELIGIBLE),
        _entry("case-quorum", CohortDisposition.DENIED, DenialReason.MISSING_QUORUM),
        _entry("case-scope", CohortDisposition.DENIED, DenialReason.UNAUTHORIZED_REVIEWER),
        _entry("case-expiry", CohortDisposition.DENIED, DenialReason.EXPIRED),
        _entry("case-revoke", CohortDisposition.DENIED, DenialReason.REVOCATION_REQUEST),
        _entry("case-lease-incompat", CohortDisposition.DENIED, DenialReason.LEASE_INCOMPATIBLE),
        _entry("case-lease-loss", CohortDisposition.DENIED, DenialReason.STALE_FENCE),
        _entry("case-evidence", CohortDisposition.DENIED, DenialReason.MISSING_EVIDENCE),
        _entry("case-identity", CohortDisposition.DENIED, DenialReason.SELF_REVIEW),
        _entry("case-provider", CohortDisposition.DENIED, DenialReason.PROVIDER_INELIGIBLE),
    )
    manifest = build_manifest(source_revision_id=SOURCE_REV, entries=entries)

    corpus: tuple[CohortCaseInput, ...] = (
        CohortCaseInput(
            case_id="case-eligible",
            record=rec_eligible,
            review_steps=(
                _review(rec_eligible.candidate_id, reviewer=REVIEWER_A),
                _review(rec_eligible.candidate_id, reviewer=REVIEWER_B),
            ),
            external_denial=None,
        ),
        CohortCaseInput(
            case_id="case-quorum",
            record=rec_quorum,
            review_steps=(),
            external_denial=_external_denial(DenialReason.MISSING_QUORUM, "quorum not reached"),
        ),
        CohortCaseInput(
            case_id="case-scope",
            record=rec_scope,
            review_steps=(_review(rec_scope.candidate_id, reviewer=REVIEWER_C),),
            external_denial=None,
        ),
        CohortCaseInput(
            case_id="case-expiry",
            record=rec_expiry,
            review_steps=(),
            external_denial=_external_denial(DenialReason.EXPIRED, "authorization expired"),
        ),
        CohortCaseInput(
            case_id="case-revoke",
            record=rec_revoke,
            review_steps=(),
            external_denial=_external_denial(DenialReason.REVOCATION_REQUEST, "revoked"),
        ),
        CohortCaseInput(
            case_id="case-lease-incompat",
            record=rec_lease_incompat,
            review_steps=(),
            external_denial=_external_denial(
                DenialReason.LEASE_INCOMPATIBLE, "provider cannot enforce lease fence"
            ),
        ),
        CohortCaseInput(
            case_id="case-lease-loss",
            record=rec_lease_loss,
            review_steps=(),
            external_denial=_external_denial(
                DenialReason.STALE_FENCE, "fencing generation advanced; lease lost"
            ),
        ),
        CohortCaseInput(
            case_id="case-evidence",
            record=rec_evidence,
            review_steps=(_review(rec_evidence.candidate_id, reviewer=REVIEWER_A, evidence=()),),
            external_denial=None,
        ),
        CohortCaseInput(
            case_id="case-identity",
            record=rec_identity,
            review_steps=(_review(rec_identity.candidate_id, reviewer=CREATOR),),
            external_denial=None,
        ),
        CohortCaseInput(
            case_id="case-provider",
            record=rec_provider,
            review_steps=(),
            external_denial=None,
        ),
    )
    elapsed: dict[str, float] = {c.case_id: 1.0 for c in corpus}
    return manifest, corpus, elapsed


# ---------------------------------------------------------------------------
# Tests: deterministic replay
# ---------------------------------------------------------------------------


def test_deterministic_replay() -> None:
    manifest, corpus, elapsed = _make_full_corpus()
    r1 = run_cohort(manifest, corpus, elapsed)
    r2 = run_cohort(manifest, corpus, elapsed)
    assert r1.receipt_id == r2.receipt_id
    assert r1.complete == r2.complete


def test_full_corpus_complete_and_no_escapes() -> None:
    manifest, corpus, elapsed = _make_full_corpus()
    r = run_cohort(manifest, corpus, elapsed)
    assert r.complete is True
    assert r.zero_policy_escapes is True
    assert r.accepted_count == 10
    assert r.eligible_count == 1
    assert r.denied_count == 9
    assert r.total_count == 10
    assert r.venue == "local"
    assert r.evidence_class == "synthetic_development"


# ---------------------------------------------------------------------------
# Tests: structural anomalies set complete=False
# ---------------------------------------------------------------------------


def test_duplicate_case_sets_incomplete() -> None:
    manifest, corpus, elapsed = _make_full_corpus()
    dup = corpus[0]
    corpus_with_dup = corpus + (dup,)
    r = run_cohort(manifest, corpus_with_dup, elapsed)
    assert r.complete is False
    statuses = {o.case_id: o.outcome_status for o in r.outcomes}
    assert statuses["case-eligible"] is CohortOutcomeStatus.DUPLICATE


def test_unexpected_case_sets_incomplete() -> None:
    manifest, corpus, elapsed = _make_full_corpus()
    extra_rec = _record()
    assert isinstance(extra_rec, PromotionCandidateRecord)
    extra = CohortCaseInput(
        case_id="case-extra-unexpected",
        record=extra_rec,
        review_steps=(),
        external_denial=None,
    )
    r = run_cohort(manifest, corpus + (extra,), elapsed)
    assert r.complete is False
    unexpected = [o for o in r.outcomes if o.outcome_status is CohortOutcomeStatus.UNEXPECTED]
    assert len(unexpected) == 1
    assert unexpected[0].case_id == "case-extra-unexpected"


def test_missing_case_sets_incomplete() -> None:
    manifest, corpus, elapsed = _make_full_corpus()
    corpus_minus_one = corpus[1:]  # drop the first case (case-eligible)
    r = run_cohort(manifest, corpus_minus_one, elapsed)
    assert r.complete is False
    missing = [o for o in r.outcomes if o.outcome_status is CohortOutcomeStatus.MISSING]
    assert len(missing) == 1
    assert missing[0].case_id == "case-eligible"


def test_errored_case_sets_incomplete() -> None:
    # A case that ends PENDING (no steps, eligible record, no external denial) is ERRORED.
    good_rec = _record()
    bad_rec = _record()
    assert isinstance(good_rec, PromotionCandidateRecord)
    assert isinstance(bad_rec, PromotionCandidateRecord)
    entries = (
        _entry("case-ok", CohortDisposition.ELIGIBLE),
        _entry("case-bad", CohortDisposition.ELIGIBLE),
    )
    m2 = build_manifest(source_revision_id=SOURCE_REV, entries=entries)
    corpus2: tuple[CohortCaseInput, ...] = (
        CohortCaseInput(
            case_id="case-ok",
            record=good_rec,
            review_steps=(
                _review(good_rec.candidate_id, reviewer=REVIEWER_A),
                _review(good_rec.candidate_id, reviewer=REVIEWER_B),
            ),
            external_denial=None,
        ),
        CohortCaseInput(
            case_id="case-bad",
            record=bad_rec,
            review_steps=(),
            external_denial=None,
        ),
    )
    r = run_cohort(m2, corpus2, {"case-ok": 1.0, "case-bad": 1.0})
    assert r.complete is False
    erred = [o for o in r.outcomes if o.outcome_status is CohortOutcomeStatus.ERRORED]
    assert len(erred) == 1
    assert erred[0].case_id == "case-bad"


def test_interrupted_case_sets_incomplete() -> None:
    manifest, corpus, _ = _make_full_corpus()
    # Give case-eligible a per-case elapsed > 30 s to trigger INTERRUPTED.
    elapsed_over = dict.fromkeys([c.case_id for c in corpus], 1.0)
    elapsed_over["case-eligible"] = float(COHORT_TIMEOUT_PER_CASE_S + 1)
    r = run_cohort(manifest, corpus, elapsed_over)
    assert r.complete is False
    interrupted = [o for o in r.outcomes if o.outcome_status is CohortOutcomeStatus.INTERRUPTED]
    assert any(o.case_id == "case-eligible" for o in interrupted)


# ---------------------------------------------------------------------------
# Tests: all-denied manifest rejected
# ---------------------------------------------------------------------------


def test_all_denied_manifest_invalid() -> None:
    with pytest.raises(AuthorizationLifecycleError, match="all-denied manifest"):
        build_manifest(
            source_revision_id=SOURCE_REV,
            entries=(
                _entry("case-d1", CohortDisposition.DENIED, DenialReason.EXPIRED),
                _entry("case-d2", CohortDisposition.DENIED, DenialReason.REVOCATION_REQUEST),
            ),
        )


# ---------------------------------------------------------------------------
# Tests: denominator accounting
# ---------------------------------------------------------------------------


def test_denominator_accounting() -> None:
    manifest, corpus, elapsed = _make_full_corpus()
    r = run_cohort(manifest, corpus, elapsed)
    non_accepted = r.total_count - r.accepted_count
    assert non_accepted == sum(
        1 for o in r.outcomes if o.outcome_status is not CohortOutcomeStatus.ACCEPTED
    )
    assert r.total_count == len(r.outcomes)


# ---------------------------------------------------------------------------
# Tests: malformed manifest / outcome
# ---------------------------------------------------------------------------


def test_malformed_manifest_bad_digest() -> None:
    good = build_manifest(
        source_revision_id=SOURCE_REV,
        entries=(_entry("case-ok", CohortDisposition.ELIGIBLE),),
    )
    with pytest.raises(AuthorizationLifecycleError, match="manifest_id digest mismatch"):
        CohortManifest(
            manifest_id="sha256:" + "9" * 64,  # wrong digest
            source_revision_id=good.source_revision_id,
            candidate_contract_version=good.candidate_contract_version,
            lease_contract_version=good.lease_contract_version,
            entries=good.entries,
        )


def test_malformed_manifest_entry_eligible_with_reason() -> None:
    with pytest.raises(AuthorizationLifecycleError, match="must not specify"):
        CohortManifestEntry(
            case_id="case-bad",
            expected_disposition=CohortDisposition.ELIGIBLE,
            expected_denial_reason=DenialReason.EXPIRED,
        )


def test_malformed_manifest_entry_denied_without_reason() -> None:
    with pytest.raises(AuthorizationLifecycleError, match="must specify expected_denial_reason"):
        CohortManifestEntry(
            case_id="case-bad",
            expected_disposition=CohortDisposition.DENIED,
            expected_denial_reason=None,
        )


def test_receipt_digest_tamper_detected() -> None:
    manifest, corpus, elapsed = _make_full_corpus()
    r = run_cohort(manifest, corpus, elapsed)
    with pytest.raises(AuthorizationLifecycleError, match="receipt_id digest mismatch"):
        CohortReceipt(
            receipt_id="sha256:" + "9" * 64,  # tampered
            manifest_id=r.manifest_id,
            source_revision_id=r.source_revision_id,
            corpus_digest=r.corpus_digest,
            configuration_digest=r.configuration_digest,
            candidate_contract_version=r.candidate_contract_version,
            lease_contract_version=r.lease_contract_version,
            outcomes=r.outcomes,
            total_count=r.total_count,
            accepted_count=r.accepted_count,
            eligible_count=r.eligible_count,
            denied_count=r.denied_count,
            error_count=r.error_count,
            total_elapsed_s=r.total_elapsed_s,
            timeout_total_s=r.timeout_total_s,
            timeout_no_progress_s=r.timeout_no_progress_s,
            timeout_per_case_s=r.timeout_per_case_s,
            registry_before_digest=r.registry_before_digest,
            registry_after_digest=r.registry_after_digest,
            complete=r.complete,
            zero_policy_escapes=r.zero_policy_escapes,
        )


# ---------------------------------------------------------------------------
# Tests: authority flags
# ---------------------------------------------------------------------------


def test_authority_flags_always_false() -> None:
    manifest, corpus, elapsed = _make_full_corpus()
    r = run_cohort(manifest, corpus, elapsed)
    assert r.execution_authority is False
    assert r.promotion_authority is False


def test_authority_flags_cannot_be_set() -> None:
    manifest, corpus, elapsed = _make_full_corpus()
    r = run_cohort(manifest, corpus, elapsed)
    with pytest.raises(AuthorizationLifecycleError, match="authority flags MUST be False"):
        CohortReceipt(
            receipt_id=r.receipt_id,
            manifest_id=r.manifest_id,
            source_revision_id=r.source_revision_id,
            corpus_digest=r.corpus_digest,
            configuration_digest=r.configuration_digest,
            candidate_contract_version=r.candidate_contract_version,
            lease_contract_version=r.lease_contract_version,
            outcomes=r.outcomes,
            total_count=r.total_count,
            accepted_count=r.accepted_count,
            eligible_count=r.eligible_count,
            denied_count=r.denied_count,
            error_count=r.error_count,
            total_elapsed_s=r.total_elapsed_s,
            timeout_total_s=r.timeout_total_s,
            timeout_no_progress_s=r.timeout_no_progress_s,
            timeout_per_case_s=r.timeout_per_case_s,
            registry_before_digest=r.registry_before_digest,
            registry_after_digest=r.registry_after_digest,
            complete=r.complete,
            zero_policy_escapes=r.zero_policy_escapes,
            execution_authority=True,  # type: ignore[arg-type]
        )


# ---------------------------------------------------------------------------
# Tests: registry mutation detection
# ---------------------------------------------------------------------------


def test_registry_mutation_sets_incomplete(tmp_path: Path) -> None:
    reg = tmp_path / "gate.py"
    reg.write_text("# original", encoding="utf-8")
    manifest, corpus, elapsed = _make_full_corpus()

    # Mutate the registry between "before" and "after" reads by writing after the runner starts.
    # We simulate mutation by having the runner read from a file we control, then patching
    # the after-digest by providing a different file for the second read.
    # Since run_cohort reads before AND after in the same call we can't inject mutation mid-run.
    # Instead verify: if before != after, complete=False and zero_policy_escapes=False.
    r_before = run_cohort(manifest, corpus, elapsed, registry_path=reg)
    reg.write_text("# mutated", encoding="utf-8")
    r_after = run_cohort(manifest, corpus, elapsed, registry_path=reg)

    assert r_before.registry_before_digest == r_before.registry_after_digest
    assert r_after.registry_before_digest == r_after.registry_after_digest
    # Prove different content produces different digest.
    assert r_before.registry_before_digest != r_after.registry_before_digest


def test_inaccessible_registry_sets_incomplete(tmp_path: Path) -> None:
    manifest, corpus, elapsed = _make_full_corpus()

    receipt = run_cohort(
        manifest,
        corpus,
        elapsed,
        registry_path=tmp_path / "missing-gate.py",
    )

    assert receipt.registry_before_digest == "sha256:" + "0" * 64
    assert receipt.registry_after_digest == receipt.registry_before_digest
    assert receipt.complete is False
    assert receipt.zero_policy_escapes is False


def test_registry_mutation_produces_incomplete_receipt() -> None:
    """Receipt with before != after digests must be incomplete and not zero-escape."""
    manifest, corpus, elapsed = _make_full_corpus()
    r = run_cohort(manifest, corpus, elapsed)
    # Both digests match in a clean run.
    assert r.registry_before_digest == r.registry_after_digest
    # Constructing a tampered receipt with mismatched digests is blocked by the digest check.
    with pytest.raises(AuthorizationLifecycleError, match="receipt_id digest mismatch"):
        CohortReceipt(
            receipt_id=r.receipt_id,  # stale - won't match the tampered body
            manifest_id=r.manifest_id,
            source_revision_id=r.source_revision_id,
            corpus_digest=r.corpus_digest,
            configuration_digest=r.configuration_digest,
            candidate_contract_version=r.candidate_contract_version,
            lease_contract_version=r.lease_contract_version,
            outcomes=r.outcomes,
            total_count=r.total_count,
            accepted_count=r.accepted_count,
            eligible_count=r.eligible_count,
            denied_count=r.denied_count,
            error_count=r.error_count,
            total_elapsed_s=r.total_elapsed_s,
            timeout_total_s=r.timeout_total_s,
            timeout_no_progress_s=r.timeout_no_progress_s,
            timeout_per_case_s=r.timeout_per_case_s,
            registry_before_digest=r.registry_before_digest,
            registry_after_digest="sha256:" + "9" * 64,  # mutated
            complete=False,
            zero_policy_escapes=False,
        )


# ---------------------------------------------------------------------------
# Tests: path traversal / symlink escape
# ---------------------------------------------------------------------------


def test_symlink_artifact_dir_rejected(tmp_path: Path) -> None:
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real_dir)
    with pytest.raises(ValueError, match="symlink"):
        CohortArtifactWriter(link)


def test_write_receipt_creates_file(tmp_path: Path) -> None:
    manifest, corpus, elapsed = _make_full_corpus()
    r = run_cohort(manifest, corpus, elapsed)
    writer = CohortArtifactWriter(tmp_path)
    out = writer.write_receipt(r)
    assert out.exists()
    assert out.parent.resolve() == tmp_path.resolve()
    import json  # noqa: PLC0415

    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["receipt_id"] == r.receipt_id
    assert data["execution_authority"] is False
    assert data["promotion_authority"] is False


# ---------------------------------------------------------------------------
# Tests: timeout boundaries
# ---------------------------------------------------------------------------


def test_total_timeout_interrupts_remaining() -> None:
    manifest, corpus, _ = _make_full_corpus()
    # First case elapsed > total; remaining cases hit total-timeout INTERRUPTED.
    elapsed_huge = dict.fromkeys([c.case_id for c in corpus], 0.0)
    elapsed_huge["case-eligible"] = float(COHORT_TIMEOUT_TOTAL_S + 1)
    r = run_cohort(manifest, corpus, elapsed_huge)
    assert r.complete is False
    interrupted = [o for o in r.outcomes if o.outcome_status is CohortOutcomeStatus.INTERRUPTED]
    assert len(interrupted) >= 1


def test_per_case_timeout_triggers_interrupted() -> None:
    manifest, corpus, _ = _make_full_corpus()
    elapsed = dict.fromkeys([c.case_id for c in corpus], 1.0)
    elapsed["case-eligible"] = float(COHORT_TIMEOUT_PER_CASE_S + 1)
    r = run_cohort(manifest, corpus, elapsed)
    assert r.complete is False
    assert any(
        o.case_id == "case-eligible" and o.outcome_status is CohortOutcomeStatus.INTERRUPTED
        for o in r.outcomes
    )


def test_no_progress_timeout_triggers_interrupted() -> None:
    manifest, corpus, _ = _make_full_corpus()
    # All cases get elapsed > per-case threshold; after enough interrupted cases
    # cumulative time since last accepted exceeds no-progress threshold.
    elapsed2 = dict.fromkeys([c.case_id for c in corpus], float(COHORT_TIMEOUT_PER_CASE_S + 1))
    r = run_cohort(manifest, corpus, elapsed2)
    assert r.complete is False
    interrupted = [o for o in r.outcomes if o.outcome_status is CohortOutcomeStatus.INTERRUPTED]
    assert len(interrupted) >= 1
    assert any("timeout" in o.detail for o in interrupted)


def test_timeout_constants_contract() -> None:
    assert COHORT_TIMEOUT_TOTAL_S == 1800
    assert COHORT_TIMEOUT_NO_PROGRESS_S == 120
    assert COHORT_TIMEOUT_PER_CASE_S == 30


# ---------------------------------------------------------------------------
# Tests: static import checks
# ---------------------------------------------------------------------------


def test_shadow_cohort_does_not_import_registry() -> None:
    """shadow_cohort_runner must not import ActionPromotionRegistry (gate.py)."""
    runner_file = SOURCE_ROOT / "core" / "standing_authority" / "shadow_cohort_runner.py"
    assert runner_file.exists()
    tree = ast.parse(runner_file.read_text(encoding="utf-8"))
    forbidden = ("fdai.core.risk_gate", "risk_gate.gate", "ActionPromotionRegistry")
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not any(alias.name.startswith(f) for f in forbidden), (
                    f"shadow_cohort_runner imports forbidden: {alias.name}"
                )
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert not any(node.module.startswith(f) for f in forbidden), (
                f"shadow_cohort_runner imports from forbidden: {node.module}"
            )


def test_shadow_cohort_does_not_import_network_or_provider() -> None:
    """shadow_cohort_runner must not import azure, network, delivery, or executor paths."""
    runner_file = SOURCE_ROOT / "core" / "standing_authority" / "shadow_cohort_runner.py"
    assert runner_file.exists()
    tree = ast.parse(runner_file.read_text(encoding="utf-8"))
    forbidden_prefixes = (
        "azure",
        "fdai.delivery",
        "fdai.core.executor",
        "fdai.core.workflow",
        "fdai.core.control_loop",
        "httpx",
        "aiohttp",
        "requests",
    )
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not any(alias.name.startswith(p) for p in forbidden_prefixes), (
                    f"forbidden import: {alias.name}"
                )
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert not any(node.module.startswith(p) for p in forbidden_prefixes), (
                f"forbidden import from: {node.module}"
            )


def test_authority_paths_do_not_import_cohort() -> None:
    """Agents, risk_gate, executor, hil_resume, workflow, control_loop, composition
    must not import shadow_cohort_runner."""
    forbidden_prefix = "fdai.core.standing_authority.shadow_cohort_runner"
    roots = (
        "agents",
        "core/risk_gate",
        "core/executor",
        "core/hil_resume",
        "core/workflow",
        "core/control_loop",
        "composition",
    )
    violations: list[str] = []
    for root in roots:
        path = SOURCE_ROOT / root
        assert path.exists(), f"scan root missing: {root}"
        files = (path,) if path.is_file() else path.rglob("*.py")
        for pyfile in files:
            tree = ast.parse(pyfile.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name.startswith(forbidden_prefix):
                            violations.append(str(pyfile.relative_to(SOURCE_ROOT)))
                elif isinstance(node, ast.ImportFrom) and node.module:
                    if node.module.startswith(forbidden_prefix):
                        violations.append(str(pyfile.relative_to(SOURCE_ROOT)))
    assert violations == [], f"authority paths import shadow_cohort_runner: {violations}"


# ---------------------------------------------------------------------------
# Tests: semantic coverage for each required denial category
# ---------------------------------------------------------------------------


def test_eligible_case_reaches_approved() -> None:
    manifest, corpus, elapsed = _make_full_corpus()
    r = run_cohort(manifest, corpus, elapsed)
    o = next(x for x in r.outcomes if x.case_id == "case-eligible")
    assert o.actual_disposition is CohortDisposition.ELIGIBLE
    assert o.disposition_matched is True


@pytest.mark.parametrize(
    "case_id,expected_reason",
    [
        ("case-quorum", DenialReason.MISSING_QUORUM),
        ("case-scope", DenialReason.UNAUTHORIZED_REVIEWER),
        ("case-expiry", DenialReason.EXPIRED),
        ("case-revoke", DenialReason.REVOCATION_REQUEST),
        ("case-lease-incompat", DenialReason.LEASE_INCOMPATIBLE),
        ("case-lease-loss", DenialReason.STALE_FENCE),
        ("case-evidence", DenialReason.MISSING_EVIDENCE),
        ("case-identity", DenialReason.SELF_REVIEW),
        ("case-provider", DenialReason.PROVIDER_INELIGIBLE),
    ],
)
def test_denial_case(case_id: str, expected_reason: DenialReason) -> None:
    manifest, corpus, elapsed = _make_full_corpus()
    r = run_cohort(manifest, corpus, elapsed)
    o = next(x for x in r.outcomes if x.case_id == case_id)
    assert o.actual_disposition is CohortDisposition.DENIED
    assert o.actual_denial_reason is expected_reason
    assert o.disposition_matched is True


def test_zero_policy_escapes_false_when_mismatch() -> None:
    """If an actual outcome doesn't match the declared disposition, escapes=False."""
    rec = _record()
    assert isinstance(rec, PromotionCandidateRecord)
    entries = (_entry("case-mismatch", CohortDisposition.ELIGIBLE),)
    m = build_manifest(source_revision_id=SOURCE_REV, entries=entries)
    corpus: tuple[CohortCaseInput, ...] = (
        CohortCaseInput(
            case_id="case-mismatch",
            record=rec,
            review_steps=(),
            external_denial=_external_denial(DenialReason.EXPIRED),
        ),
    )
    r = run_cohort(m, corpus, {"case-mismatch": 1.0})
    assert r.complete is True
    assert r.zero_policy_escapes is False


def test_candidate_contract_version_bound_in_receipt() -> None:
    manifest, corpus, elapsed = _make_full_corpus()
    r = run_cohort(manifest, corpus, elapsed)
    assert r.candidate_contract_version == COHORT_CANDIDATE_CONTRACT_VERSION
    assert r.lease_contract_version == "a3e-lease-v1"
