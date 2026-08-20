"""Golden-first release orchestration and strict question assurance reduction."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from fdai.core.conversation.question_adequacy import (
    MetamorphicGroupReceipt,
    QuestionAdequacyReceipt,
    require_metamorphic_coverage,
)
from fdai.core.conversation.question_campaign import (
    QuestionCampaignState,
    QuestionCaseAttemptRecord,
)
from fdai.core.conversation.question_campaign_runner import QuestionCampaignRunResult
from fdai.core.conversation.question_golden import (
    GoldenCertificationReceipt,
    GoldenQuestionCorpus,
)
from fdai.core.conversation_assurance.models import AssuranceVerdict


class GoldenQuestionCertificationPort(Protocol):
    """Execute the immutable corpus through strict semantic transport."""

    async def certify(
        self,
        corpus: GoldenQuestionCorpus,
        *,
        ontology_release_digest: str,
        principal_manifest_digests: tuple[str, ...],
    ) -> GoldenCertificationReceipt: ...


class GeneratedQuestionCampaignPort(Protocol):
    """Execute one already bounded generated campaign."""

    async def run(self) -> QuestionCampaignRunResult: ...


@dataclass(frozen=True, slots=True)
class QuestionReleaseRunResult:
    """Ordered golden and optional generated execution result."""

    golden: GoldenCertificationReceipt
    generated: QuestionCampaignRunResult | None
    generated_started: bool
    reason: str


@dataclass(frozen=True, slots=True)
class QuestionReleaseAssuranceReceipt:
    """Strict final release decision over all question assurance evidence."""

    passed: bool
    reason: str
    ontology_release_digest: str
    generated_campaign_id: str | None
    golden_receipt_digest: str
    generated_receipt_digest: str | None
    adequacy_receipt_digests: tuple[str, ...]
    metamorphic_receipt_digests: tuple[str, ...]
    receipt_digest: str
    execution_authority: bool = False

    def __post_init__(self) -> None:
        if self.execution_authority:
            raise ValueError("question release assurance MUST NOT carry execution authority")
        _require_digest("question release ontology release", self.ontology_release_digest)
        if self.passed and self.generated_campaign_id is None:
            raise ValueError("passed question release assurance requires a generated campaign")
        if self.generated_campaign_id is not None and (
            len(self.generated_campaign_id) != 67
            or not self.generated_campaign_id.startswith("qs:")
        ):
            raise ValueError("question release generated campaign id is invalid")
        _require_digest("question release golden receipt", self.golden_receipt_digest)
        if self.generated_receipt_digest is not None:
            _require_digest(
                "question release generated receipt",
                self.generated_receipt_digest,
            )
        for name, digests in (
            ("adequacy", self.adequacy_receipt_digests),
            ("metamorphic", self.metamorphic_receipt_digests),
        ):
            for digest in digests:
                _require_digest(f"question release {name} receipt", digest)
        if self.receipt_digest != _digest(_release_assurance_body(self)):
            raise ValueError("question release receipt digest does not match content")


class QuestionReleaseAssuranceRunner:
    """Run immutable golden certification before any generated campaign."""

    def __init__(
        self,
        *,
        golden: GoldenQuestionCertificationPort,
        generated: GeneratedQuestionCampaignPort,
    ) -> None:
        self._golden = golden
        self._generated = generated

    async def run(
        self,
        corpus: GoldenQuestionCorpus,
        *,
        ontology_release_digest: str,
        principal_manifest_digests: tuple[str, ...],
    ) -> QuestionReleaseRunResult:
        """Block generated execution when any golden gate regresses."""

        golden_result = await self._golden.certify(
            corpus,
            ontology_release_digest=ontology_release_digest,
            principal_manifest_digests=principal_manifest_digests,
        )
        if golden_result.corpus_digest != corpus.corpus_digest:
            raise ValueError("golden certification binds a different corpus")
        if (
            golden_result.ontology_release_digest != ontology_release_digest
            or golden_result.principal_manifest_digests != principal_manifest_digests
        ):
            raise ValueError("golden certification binds different release evidence")
        if not golden_result.passed:
            return QuestionReleaseRunResult(
                golden=golden_result,
                generated=None,
                generated_started=False,
                reason="golden_certification_blocked",
            )
        generated_result = await self._generated.run()
        if generated_result.evaluation.ontology_release_digest != ontology_release_digest:
            raise ValueError("generated campaign binds a different ontology release")
        return QuestionReleaseRunResult(
            golden=golden_result,
            generated=generated_result,
            generated_started=True,
            reason="generated_campaign_completed",
        )


def evaluate_question_release_assurance(
    *,
    run: QuestionReleaseRunResult,
    adequacy_receipts: Sequence[QuestionAdequacyReceipt],
    metamorphic_receipts: Sequence[MetamorphicGroupReceipt],
) -> QuestionReleaseAssuranceReceipt:
    """Require semantic, evidence, transport, hard-zero, and relation closure."""

    generated = run.generated
    passed = True
    reason = "question_release_assurance_passed"
    if not run.golden.passed:
        passed = False
        reason = "golden_certification_blocked"
    elif generated is None or not run.generated_started:
        passed = False
        reason = "generated_campaign_missing"
    elif generated.state is not QuestionCampaignState.COMPLETED:
        passed = False
        reason = "generated_campaign_not_completed"
    elif not generated.evaluation.release_evidence_eligible:
        passed = False
        reason = "generated_campaign_ineligible"
    else:
        if not adequacy_receipts:
            raise ValueError("question release assurance requires adequacy receipts")
        require_metamorphic_coverage(metamorphic_receipts)
        terminal_case_ids = _latest_terminal_case_ids(generated)
        if any(item.campaign_id != generated.evaluation.campaign_id for item in adequacy_receipts):
            raise ValueError("question adequacy receipts bind a different generated campaign")
        adequacy_case_ids = tuple(item.case_id for item in adequacy_receipts)
        if (
            len(adequacy_case_ids) != generated.evaluation.terminal_case_count
            or len(set(adequacy_case_ids)) != len(adequacy_case_ids)
            or set(adequacy_case_ids) != terminal_case_ids
        ):
            raise ValueError(
                "question adequacy receipts MUST exactly cover generated terminal cases"
            )
        if any(
            item.campaign_id != generated.evaluation.campaign_id for item in metamorphic_receipts
        ):
            raise ValueError("metamorphic receipts bind a different generated campaign")
        metamorphic_case_ids = {
            case_id for item in metamorphic_receipts for case_id in item.case_ids
        }
        if metamorphic_case_ids != terminal_case_ids:
            raise ValueError("metamorphic receipts MUST exactly cover generated terminal cases")
        if any(item.verdict is not AssuranceVerdict.PASS for item in adequacy_receipts):
            passed = False
            reason = "answer_adequacy_not_passed"
        elif any(
            item.safety_critical_failure or item.reviewer_disagreement for item in adequacy_receipts
        ):
            passed = False
            reason = "answer_adequacy_safety_or_disagreement"
        elif any(not item.passed for item in metamorphic_receipts):
            passed = False
            reason = "metamorphic_assurance_not_passed"
    if reason in {
        "golden_certification_blocked",
        "generated_campaign_missing",
        "generated_campaign_not_completed",
        "generated_campaign_ineligible",
    } and (adequacy_receipts or metamorphic_receipts):
        raise ValueError(
            "downstream question assurance evidence requires an eligible generated campaign"
        )
    adequacy_digests = tuple(sorted(item.receipt_digest for item in adequacy_receipts))
    metamorphic_digests = tuple(sorted(item.receipt_digest for item in metamorphic_receipts))
    generated_digest = None if generated is None else generated.evaluation.receipt_digest
    generated_campaign_id = None if generated is None else generated.evaluation.campaign_id
    provisional = QuestionReleaseAssuranceReceipt.__new__(QuestionReleaseAssuranceReceipt)
    for name, value in {
        "passed": passed,
        "reason": reason,
        "ontology_release_digest": run.golden.ontology_release_digest,
        "generated_campaign_id": generated_campaign_id,
        "golden_receipt_digest": run.golden.receipt_digest,
        "generated_receipt_digest": generated_digest,
        "adequacy_receipt_digests": adequacy_digests,
        "metamorphic_receipt_digests": metamorphic_digests,
        "execution_authority": False,
    }.items():
        object.__setattr__(provisional, name, value)
    object.__setattr__(
        provisional,
        "receipt_digest",
        _digest(_release_assurance_body(provisional)),
    )
    return QuestionReleaseAssuranceReceipt(
        passed=passed,
        reason=reason,
        ontology_release_digest=run.golden.ontology_release_digest,
        generated_campaign_id=generated_campaign_id,
        golden_receipt_digest=run.golden.receipt_digest,
        generated_receipt_digest=generated_digest,
        adequacy_receipt_digests=adequacy_digests,
        metamorphic_receipt_digests=metamorphic_digests,
        receipt_digest=provisional.receipt_digest,
    )


def _latest_terminal_case_ids(generated: QuestionCampaignRunResult) -> set[str]:
    latest: dict[str, QuestionCaseAttemptRecord] = {}
    for attempt in generated.attempts:
        previous = latest.get(attempt.case_id)
        if previous is None or attempt.attempt_number > previous.attempt_number:
            latest[attempt.case_id] = attempt
    terminal_case_ids = {
        case_id for case_id, attempt in latest.items() if attempt.terminal_disposition is not None
    }
    if len(terminal_case_ids) != generated.evaluation.terminal_case_count:
        raise ValueError("generated terminal case count does not match campaign attempts")
    return terminal_case_ids


def _release_assurance_body(
    receipt: QuestionReleaseAssuranceReceipt,
) -> dict[str, object]:
    return {
        "passed": receipt.passed,
        "reason": receipt.reason,
        "ontology_release_digest": receipt.ontology_release_digest,
        "generated_campaign_id": receipt.generated_campaign_id,
        "golden_receipt_digest": receipt.golden_receipt_digest,
        "generated_receipt_digest": receipt.generated_receipt_digest,
        "adequacy_receipt_digests": receipt.adequacy_receipt_digests,
        "metamorphic_receipt_digests": receipt.metamorphic_receipt_digests,
        "execution_authority": receipt.execution_authority,
    }


def _require_digest(name: str, value: str) -> None:
    if len(value) != 71 or not value.startswith("sha256:"):
        raise ValueError(f"{name} MUST be a canonical SHA-256 value")
    try:
        int(value[7:], 16)
    except ValueError as error:
        raise ValueError(f"{name} MUST be a canonical SHA-256 value") from error


def _digest(value: object) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


__all__ = [
    "GeneratedQuestionCampaignPort",
    "GoldenQuestionCertificationPort",
    "QuestionReleaseAssuranceReceipt",
    "QuestionReleaseAssuranceRunner",
    "QuestionReleaseRunResult",
    "evaluate_question_release_assurance",
]
