"""Fail-closed readiness boundary for independently verified evidence."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from fdai_service_contracts.decision_evidence import (
    DecisionCriticalEvidenceReceipt,
    LiveEvidenceClaimRequirement,
    assess_live_evidence_claim,
)
from fdai_service_contracts.decision_evidence_verification import (
    DecisionEvidenceVerificationBundle,
    expected_verification_subjects,
)
from fdai_service_contracts.ontology_query import content_digest
from pydantic import ValidationError as PydanticValidationError

from fdai.core.readiness.models import AuthorityCeiling, ReadinessDecision, StartupReadinessReport
from fdai.core.readiness.report import ReadinessReport
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.decision_evidence_verifier import (
    DecisionEvidenceAdmission,
    DecisionEvidenceAdmissionProvider,
    DecisionEvidenceVerifierBinding,
    DecisionEvidenceVerifierRegistry,
    assess_decision_evidence_admission,
)

STARTUP_READINESS_EVIDENCE_PURPOSE = "startup-readiness"
OPERATIONAL_READINESS_EVIDENCE_PURPOSE = "operational-readiness"
_AUTHORITY_CEILING_RANK = {
    AuthorityCeiling.DISABLED: 0,
    AuthorityCeiling.DETERMINISTIC_FALLBACK: 1,
    AuthorityCeiling.SHADOW: 2,
    AuthorityCeiling.HUMAN_APPROVAL: 3,
    AuthorityCeiling.DEPLOYMENT: 4,
}


class DecisionEvidenceReadinessReason(StrEnum):
    """Why evidence is or is not eligible at a readiness boundary."""

    VERIFIED = "verified"
    PREFLIGHT_REJECTED = "preflight_rejected"
    VERIFIER_UNAVAILABLE = "verifier_unavailable"
    VERIFIER_FAILED = "verifier_failed"
    UNTRUSTED_VERIFIER = "untrusted_verifier"
    BUNDLE_MISMATCH = "bundle_mismatch"
    PROOF_MISMATCH = "proof_mismatch"
    PROOF_NOT_CURRENT = "proof_not_current"
    SELF_VERIFICATION = "self_verification"


@dataclass(frozen=True, slots=True)
class DecisionEvidenceReadinessResult:
    """Sanitized eligibility result with no execution or promotion authority."""

    eligible: bool
    reason: DecisionEvidenceReadinessReason
    receipt_digest: str
    verification_bundle_digest: str | None = None
    admission: DecisionEvidenceAdmission | None = None
    rejection_details: tuple[str, ...] = ()
    execution_authority: Literal[False] = False
    promotion_authority: Literal[False] = False

    def __post_init__(self) -> None:
        if self.execution_authority or self.promotion_authority:
            raise ValueError("decision evidence readiness MUST NOT grant authority")
        if self.eligible != (self.reason is DecisionEvidenceReadinessReason.VERIFIED):
            raise ValueError("decision evidence readiness eligibility mismatched its reason")
        if self.eligible != (self.admission is not None):
            raise ValueError("decision evidence readiness admission mismatched eligibility")
        if self.admission is not None and (
            self.admission.receipt_digest != self.receipt_digest
            or self.admission.verification_bundle_digest != self.verification_bundle_digest
        ):
            raise ValueError("decision evidence readiness admission mismatched result digests")


class DecisionEvidenceReadinessGate:
    """Authenticate and independently read back evidence before readiness use."""

    def __init__(
        self,
        *,
        registry: DecisionEvidenceVerifierRegistry,
        timeout_seconds: float = 10.0,
    ) -> None:
        if not 0 < timeout_seconds <= 30:
            raise ValueError("decision evidence verification timeout MUST be in (0, 30]")
        self._registry = registry
        self._timeout_seconds = timeout_seconds

    async def evaluate(
        self,
        receipt: DecisionCriticalEvidenceReceipt,
        requirement: LiveEvidenceClaimRequirement,
        *,
        evaluated_at: datetime,
    ) -> DecisionEvidenceReadinessResult:
        """Return eligible only after preflight and five independent proofs."""

        normalized_at = _aware_utc(evaluated_at)
        preflight = assess_live_evidence_claim(
            receipt,
            requirement,
            evaluated_at=normalized_at,
        )
        if not preflight.eligible_for_verification:
            return _rejected(
                receipt,
                DecisionEvidenceReadinessReason.PREFLIGHT_REJECTED,
                details=tuple(reason.value for reason in preflight.rejection_reasons),
            )
        binding = self._registry.resolve(
            authority_class=receipt.authority_class,
            method_id=receipt.method_id,
        )
        if binding is None:
            return _rejected(receipt, DecisionEvidenceReadinessReason.VERIFIER_UNAVAILABLE)
        if not binding.active_at(normalized_at):
            return _rejected(receipt, DecisionEvidenceReadinessReason.UNTRUSTED_VERIFIER)
        if binding.verifier_id in {receipt.source_identity, receipt.producer_id}:
            return _rejected(receipt, DecisionEvidenceReadinessReason.SELF_VERIFICATION)
        try:
            async with asyncio.timeout(self._timeout_seconds):
                bundle = await binding.verifier.verify(
                    receipt,
                    trust_anchor_id=binding.trust_anchor_id,
                )
        except (
            LookupError,
            OSError,
            TimeoutError,
            PydanticValidationError,
            RuntimeError,
            ValueError,
        ):
            return _rejected(receipt, DecisionEvidenceReadinessReason.VERIFIER_FAILED)
        return _evaluate_bundle(
            receipt,
            bundle=bundle,
            binding=binding,
            evaluated_at=normalized_at,
        )


async def apply_startup_readiness_admission(
    report: StartupReadinessReport,
    *,
    provider: DecisionEvidenceAdmissionProvider | None,
) -> StartupReadinessReport:
    """Bind startup readiness to verified evidence or lower every ceiling to shadow."""

    evidence_digest = startup_readiness_evidence_digest(report)
    scope_digest = startup_readiness_scope_digest(report)
    source_revision = startup_readiness_source_revision(report)
    admission = (
        await provider.admit(
            evidence_digest=evidence_digest,
            scope_digest=scope_digest,
            purpose_id=STARTUP_READINESS_EVIDENCE_PURPOSE,
            source_revision=source_revision,
        )
        if provider is not None
        else None
    )
    reasons = (
        ("admission_missing",)
        if admission is None
        else tuple(
            reason.value
            for reason in assess_decision_evidence_admission(
                admission,
                expected_evidence_digest=evidence_digest,
                expected_scope_digest=scope_digest,
                expected_purpose_id=STARTUP_READINESS_EVIDENCE_PURPOSE,
                expected_source_revision=source_revision,
                evaluated_at=report.generated_at,
            )
        )
    )
    if reasons:
        decision = (
            ReadinessDecision.BLOCKED
            if report.decision is ReadinessDecision.BLOCKED
            else ReadinessDecision.DEGRADED
        )
        ceilings = {
            capability: min(
                (ceiling, AuthorityCeiling.SHADOW),
                key=lambda item: _AUTHORITY_CEILING_RANK[item],
            )
            for capability, ceiling in report.authority_ceilings.items()
        }
        return report.model_copy(
            update={
                "decision": decision,
                "authority_ceilings": ceilings,
                "decision_evidence_receipt_digest": (
                    admission.receipt_digest if admission is not None else None
                ),
                "decision_evidence_verification_bundle_digest": (
                    admission.verification_bundle_digest if admission is not None else None
                ),
                "decision_evidence_rejection_reasons": reasons,
            }
        )
    if admission is None:  # pragma: no cover - reasons handles this branch
        raise RuntimeError("startup readiness admission invariant failed")
    return report.model_copy(
        update={
            "decision_evidence_receipt_digest": admission.receipt_digest,
            "decision_evidence_verification_bundle_digest": (admission.verification_bundle_digest),
            "decision_evidence_rejection_reasons": (),
        }
    )


async def apply_operational_readiness_admission(
    report: ReadinessReport,
    *,
    provider: DecisionEvidenceAdmissionProvider | None,
) -> ReadinessReport:
    """Bind an ORR verdict to verified evidence or force its gate to shadow."""

    evidence_digest = operational_readiness_evidence_digest(report)
    scope_digest = operational_readiness_scope_digest(report)
    source_revision = operational_readiness_source_revision(report)
    admission = (
        await provider.admit(
            evidence_digest=evidence_digest,
            scope_digest=scope_digest,
            purpose_id=OPERATIONAL_READINESS_EVIDENCE_PURPOSE,
            source_revision=source_revision,
        )
        if provider is not None
        else None
    )
    reasons = (
        ("admission_missing",)
        if admission is None
        else tuple(
            reason.value
            for reason in assess_decision_evidence_admission(
                admission,
                expected_evidence_digest=evidence_digest,
                expected_scope_digest=scope_digest,
                expected_purpose_id=OPERATIONAL_READINESS_EVIDENCE_PURPOSE,
                expected_source_revision=source_revision,
                evaluated_at=datetime.fromisoformat(report.generated_at.replace("Z", "+00:00")),
            )
        )
    )
    if reasons:
        return replace(
            report,
            mode=Mode.SHADOW,
            decision_evidence_receipt_digest=(
                admission.receipt_digest if admission is not None else None
            ),
            decision_evidence_verification_bundle_digest=(
                admission.verification_bundle_digest if admission is not None else None
            ),
            decision_evidence_rejection_reasons=reasons,
        )
    if admission is None:  # pragma: no cover - reasons handles this branch
        raise RuntimeError("operational readiness admission invariant failed")
    return replace(
        report,
        decision_evidence_receipt_digest=admission.receipt_digest,
        decision_evidence_verification_bundle_digest=admission.verification_bundle_digest,
        decision_evidence_rejection_reasons=(),
    )


def operational_readiness_evidence_digest(report: ReadinessReport) -> str:
    """Return the exact ORR evidence digest without authority mode or admission."""

    return content_digest(
        {
            "findings": [
                {
                    "blocking": finding.blocking,
                    "control_id": finding.control_id,
                    "dimension": finding.dimension,
                    "evidence": finding.evidence,
                    "requirement_refs": finding.requirement_refs,
                    "resolution": finding.resolution,
                    "resource": finding.resource,
                    "severity": finding.severity,
                    "source": finding.source,
                }
                for finding in report.findings
            ],
            "generated_at": report.generated_at,
            "scope": report.scope,
            "submitter": report.submitter,
            "target_environment": report.target_environment,
            "verdict": report.verdict.value,
        }
    )


def operational_readiness_scope_digest(report: ReadinessReport) -> str:
    """Return the exact handoff scope and target environment."""

    return content_digest(
        {
            "scope": report.scope,
            "target_environment": report.target_environment,
        }
    )


def operational_readiness_source_revision(report: ReadinessReport) -> str:
    """Return the replay-stable revision of ORR evidence sources and controls."""

    return content_digest(
        {
            "evidence": tuple(sorted(finding.evidence for finding in report.findings)),
            "schema": "operational-readiness-report:1",
            "sources": tuple(sorted({finding.source for finding in report.findings})),
        }
    )


def startup_readiness_evidence_digest(report: StartupReadinessReport) -> str:
    """Return the canonical report digest without downstream admission fields."""

    return content_digest(
        report.model_dump(
            mode="json",
            exclude={
                "decision_evidence_receipt_digest",
                "decision_evidence_verification_bundle_digest",
                "decision_evidence_rejection_reasons",
            },
        )
    )


def startup_readiness_scope_digest(report: StartupReadinessReport) -> str:
    """Return the exact probe and capability scope of one startup report."""

    return content_digest(
        {
            "capabilities": tuple(sorted(report.authority_ceilings)),
            "probe_ids": tuple(sorted(result.probe_id for result in report.results)),
        }
    )


def startup_readiness_source_revision(report: StartupReadinessReport) -> str:
    """Return the replay-stable revision of the evaluated startup probe set."""

    return content_digest(
        {
            "capabilities": tuple(sorted(report.authority_ceilings)),
            "probe_ids": tuple(sorted(result.probe_id for result in report.results)),
            "schema": "startup-readiness-report:1",
        }
    )


def _evaluate_bundle(
    receipt: DecisionCriticalEvidenceReceipt,
    *,
    bundle: DecisionEvidenceVerificationBundle,
    binding: DecisionEvidenceVerifierBinding,
    evaluated_at: datetime,
) -> DecisionEvidenceReadinessResult:
    if (
        bundle.receipt_digest != receipt.receipt_digest
        or bundle.verifier_id != binding.verifier_id
        or bundle.verifier_version != binding.verifier_version
        or bundle.trust_anchor_id != binding.trust_anchor_id
    ):
        return _rejected(receipt, DecisionEvidenceReadinessReason.BUNDLE_MISMATCH)
    if not bundle.verified_at <= evaluated_at <= bundle.valid_until:
        return _rejected(receipt, DecisionEvidenceReadinessReason.PROOF_NOT_CURRENT)
    expected = expected_verification_subjects(
        authentication_evidence_digest=receipt.authentication_evidence_digest,
        evidence_digest=receipt.evidence_digest,
        completeness_evidence_digest=receipt.completeness_evidence_digest,
        conflict_evidence_digest=receipt.conflict_evidence_digest,
        freshness_policy_digest=receipt.freshness_policy_digest,
    )
    actual = {proof.kind: proof.subject_digest for proof in bundle.proofs}
    if actual != expected:
        return _rejected(receipt, DecisionEvidenceReadinessReason.PROOF_MISMATCH)
    return DecisionEvidenceReadinessResult(
        eligible=True,
        reason=DecisionEvidenceReadinessReason.VERIFIED,
        receipt_digest=receipt.receipt_digest,
        verification_bundle_digest=bundle.bundle_digest,
        admission=DecisionEvidenceAdmission(
            receipt_digest=receipt.receipt_digest,
            verification_bundle_digest=bundle.bundle_digest,
            evidence_digest=receipt.evidence_digest,
            scope_digest=receipt.scope_digest,
            purpose_id=receipt.purpose_id,
            source_revision=receipt.source_revision,
            verified_at=bundle.verified_at,
            valid_until=bundle.valid_until,
        ),
    )


def _rejected(
    receipt: DecisionCriticalEvidenceReceipt,
    reason: DecisionEvidenceReadinessReason,
    *,
    details: tuple[str, ...] = (),
) -> DecisionEvidenceReadinessResult:
    return DecisionEvidenceReadinessResult(
        eligible=False,
        reason=reason,
        receipt_digest=receipt.receipt_digest,
        rejection_details=details,
    )


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("decision evidence readiness time MUST include a timezone")
    return value.astimezone(UTC)


__all__ = [
    "OPERATIONAL_READINESS_EVIDENCE_PURPOSE",
    "STARTUP_READINESS_EVIDENCE_PURPOSE",
    "DecisionEvidenceReadinessGate",
    "DecisionEvidenceReadinessReason",
    "DecisionEvidenceReadinessResult",
    "apply_startup_readiness_admission",
    "apply_operational_readiness_admission",
    "operational_readiness_evidence_digest",
    "operational_readiness_scope_digest",
    "operational_readiness_source_revision",
    "startup_readiness_evidence_digest",
    "startup_readiness_scope_digest",
    "startup_readiness_source_revision",
]
