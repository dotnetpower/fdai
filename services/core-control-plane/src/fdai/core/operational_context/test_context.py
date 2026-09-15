"""Six-axis, authority-lowering evaluation of an independently reviewed test context."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol

from fdai.shared.providers.decision_evidence_verifier import (
    DecisionEvidenceAdmission,
    assess_decision_evidence_admission,
)


@dataclass(frozen=True, slots=True)
class TestContextClaim:
    """Typed operator claim; independent review does not turn it into execution authority."""

    context_id: str
    revision: int
    access_scope_digest: str
    target_ref: str
    signal_code: str
    expected_min: float
    expected_max: float
    effective_from: datetime
    effective_to: datetime
    recorded_at: datetime
    source_ref: str
    requested_by: str
    reviewed_by: str
    policy_revision: str
    state: Literal["proposed", "reviewed", "revoked", "conflicting"]

    def __post_init__(self) -> None:
        for name in (
            "context_id",
            "target_ref",
            "signal_code",
            "source_ref",
            "requested_by",
            "policy_revision",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip() or len(value) > 512:
                raise ValueError("test context text fields MUST be bounded and non-empty")
        if (
            not isinstance(self.reviewed_by, str)
            or len(self.reviewed_by) > 512
            or (self.state != "proposed" and not self.reviewed_by.strip())
        ):
            raise ValueError("reviewed test context requires a bounded reviewer")
        if (
            isinstance(self.revision, bool)
            or not isinstance(self.revision, int)
            or self.revision < 1
        ):
            raise ValueError("test context revision MUST be positive")
        if len(self.access_scope_digest) != 64 or any(
            character not in "0123456789abcdef" for character in self.access_scope_digest
        ):
            raise ValueError("test context scope MUST be lowercase SHA-256")
        if self.state not in {"proposed", "reviewed", "revoked", "conflicting"}:
            raise ValueError("test context state is unsupported")
        if any(
            value.utcoffset() is None
            for value in (self.effective_from, self.effective_to, self.recorded_at)
        ):
            raise ValueError("test context timestamps MUST be timezone-aware")
        if self.effective_to <= self.effective_from:
            raise ValueError("test context interval MUST be positive")
        if any(
            isinstance(value, bool) or not math.isfinite(value)
            for value in (self.expected_min, self.expected_max)
        ):
            raise ValueError("test context expected range MUST be finite")
        if self.expected_min > self.expected_max:
            raise ValueError("test context expected range MUST be ordered")

    @property
    def digest(self) -> str:
        """Bind the claim, exact policy, provenance, reviewer, and effective/recorded time."""
        payload = asdict(self)
        for key in ("effective_from", "effective_to", "recorded_at"):
            payload[key] = getattr(self, key).astimezone(UTC).isoformat()
        for key in ("expected_min", "expected_max"):
            payload[key] = float(getattr(self, key))
        return (
            "sha256:"
            + hashlib.sha256(
                json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
            ).hexdigest()
        )


@dataclass(frozen=True, slots=True)
class TestContextDecision:
    """Independent conclusions for one measured signal; never an execution grant."""

    observed_fact: Literal["observed", "unknown"]
    expected_condition: Literal["expected", "unexpected", "unknown"]
    service_impact: Literal["none", "affected", "unknown"]
    response_disposition: Literal["observe", "investigate", "hold"]
    learning_eligibility: Literal["test_cohort", "held"]
    execution_eligibility: Literal["ordinary_gates_required"]
    reason: str
    context_digest: str | None


class TestContextSource(Protocol):
    """Read a typed reviewed context from a governed source, not from model response text."""

    async def read(
        self,
        *,
        target_ref: str,
        access_scope_digest: str,
        at: datetime,
        signal_code: str | None = None,
    ) -> TestContextClaim | None: ...


def observation_context_digest(
    *,
    target_ref: str,
    access_scope_digest: str,
    signal_code: str,
    observed_value: float,
    observed_at: datetime,
    service_impact: str,
    protected_signal: bool,
) -> str:
    """Bind a measured signal and its impact classification separately from the operator claim."""
    payload = {
        "target_ref": target_ref,
        "access_scope_digest": access_scope_digest,
        "signal_code": signal_code,
        "observed_value": float(observed_value) or 0.0,
        "observed_at": observed_at.astimezone(UTC).isoformat(),
        "service_impact": service_impact,
        "protected_signal": protected_signal,
    }
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        ).hexdigest()
    )


def evaluate_test_context(
    claim: TestContextClaim | None,
    *,
    target_ref: str,
    access_scope_digest: str,
    signal_code: str,
    observed_value: float | None,
    observed_at: datetime,
    evaluated_at: datetime,
    service_impact: Literal["none", "affected", "unknown"],
    protected_signal: bool,
    admission: DecisionEvidenceAdmission | None,
    observation_admission: DecisionEvidenceAdmission | None = None,
) -> TestContextDecision:
    """Annotate only exact admitted expected signals; protect every unknown or exceeded limit."""
    valid_observation = (
        observed_at.utcoffset() is not None
        and evaluated_at.utcoffset() is not None
        and observed_at <= evaluated_at
        and observed_value is not None
        and not isinstance(observed_value, bool)
        and isinstance(observed_value, (int, float))
        and math.isfinite(observed_value)
    )
    digest = claim.digest if claim is not None else None

    def result(expected: str, response: str, learning: str, reason: str) -> TestContextDecision:
        return TestContextDecision(
            observed_fact="observed" if valid_observation else "unknown",
            expected_condition=expected,  # type: ignore[arg-type]
            service_impact=service_impact
            if service_impact in {"none", "affected", "unknown"}
            else "unknown",
            response_disposition=response,  # type: ignore[arg-type]
            learning_eligibility=learning,  # type: ignore[arg-type]
            execution_eligibility="ordinary_gates_required",
            reason=reason,
            context_digest=digest,
        )

    if not valid_observation or observed_value is None or type(protected_signal) is not bool:
        return result("unknown", "hold", "held", "observation_invalid")
    if protected_signal or service_impact == "affected":
        return result("unexpected", "investigate", "held", "protected_or_service_impact")
    if service_impact != "none":
        return result("unknown", "hold", "held", "service_impact_unknown")
    if claim is None:
        return result("unknown", "hold", "held", "context_missing")
    if claim.target_ref != target_ref or claim.access_scope_digest != access_scope_digest:
        return result("unknown", "hold", "held", "context_scope_mismatch")
    if (
        claim.state != "reviewed"
        or claim.requested_by.strip().casefold() == claim.reviewed_by.strip().casefold()
    ):
        return result("unknown", "hold", "held", "independent_review_required")
    if (
        not claim.recorded_at <= observed_at
        or not claim.effective_from <= observed_at <= evaluated_at < claim.effective_to
    ):
        return result("unknown", "hold", "held", "context_not_current_at_decision")
    if admission is None or not isinstance(admission, DecisionEvidenceAdmission):
        return result("unknown", "hold", "held", "context_admission_required")
    if (
        assess_decision_evidence_admission(
            admission,
            expected_evidence_digest=claim.digest,
            expected_scope_digest="sha256:" + access_scope_digest,
            expected_purpose_id="operational-test-context",
            expected_source_revision=claim.policy_revision,
            evaluated_at=evaluated_at,
        )
        or not claim.recorded_at <= admission.verified_at <= evaluated_at < admission.valid_until
    ):
        return result("unknown", "hold", "held", "context_admission_required")
    if (
        claim.signal_code != signal_code
        or not claim.expected_min <= observed_value <= claim.expected_max
    ):
        return result(
            "unexpected", "investigate", "test_cohort", "outside_expected_signal_envelope"
        )
    if not isinstance(observation_admission, DecisionEvidenceAdmission):
        return result("unknown", "hold", "held", "observation_admission_required")
    if (
        assess_decision_evidence_admission(
            observation_admission,
            expected_evidence_digest=observation_context_digest(
                target_ref=target_ref,
                access_scope_digest=access_scope_digest,
                signal_code=signal_code,
                observed_value=observed_value,
                observed_at=observed_at,
                service_impact=service_impact,
                protected_signal=protected_signal,
            ),
            expected_scope_digest="sha256:" + access_scope_digest,
            expected_purpose_id="operational-test-observation",
            expected_source_revision=claim.policy_revision,
            evaluated_at=evaluated_at,
        )
        or not observed_at
        <= observation_admission.verified_at
        <= evaluated_at
        < observation_admission.valid_until
    ):
        return result("unknown", "hold", "held", "observation_admission_required")
    return result("expected", "observe", "test_cohort", "within_reviewed_test_envelope")
