"""Revalidate the exact context used by a queued decision without granting execution."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from fdai.core.operational_evidence.owner_outcome import (
    UNAVAILABLE_ATTEMPT,
    OperationalEvidenceAttempt,
    OperationalEvidenceRequester,
    request_operational_evidence,
)
from fdai.shared.providers.decision_evidence_verifier import (
    DecisionEvidenceAdmission,
    DecisionEvidenceAdmissionProvider,
    assess_decision_evidence_admission,
)

from .test_context import TestContextSource

DISPATCH_HOLD_OUTCOME = "test_context_changed_before_dispatch"


class TestContextDispatchBinding(BaseModel):
    """Immutable source identity retained with the ActionRun, not an authorization grant."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    target_ref: Annotated[str, Field(min_length=1, max_length=512)]
    access_scope_digest: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    signal_code: Annotated[str, Field(min_length=1, max_length=512)]
    context_digest: Annotated[str, Field(pattern=r"^sha256:[a-f0-9]{64}$")]


@dataclass(slots=True)
class TestContextDispatchHold:
    """Why one dispatch was held; only a proven evidence class replaces the generic reason."""

    attempt: OperationalEvidenceAttempt = UNAVAILABLE_ATTEMPT

    @property
    def outcome(self) -> str:
        return self.attempt.hold_reason(DISPATCH_HOLD_OUTCOME)

    @property
    def rejection_ref(self) -> str | None:
        return self.attempt.rejection_digest


class TestContextDispatchGuard:
    """Hold changed, unavailable, unreviewed, or expired context immediately before dispatch."""

    def __init__(
        self,
        *,
        source: TestContextSource,
        admission: DecisionEvidenceAdmissionProvider | None,
        clock: Callable[[], datetime] | None = None,
        evidence: OperationalEvidenceRequester | None = None,
    ) -> None:
        self._source, self._admission = source, admission
        self._clock = clock or (lambda: datetime.now(UTC))
        self._evidence = evidence

    async def current(
        self,
        binding: TestContextDispatchBinding,
        *,
        target_ref: str | None,
        hold: TestContextDispatchHold | None = None,
    ) -> bool:
        """Check source and independent admission under one deadline; cancellation propagates.

        When the unchanged context lacks an admission because the verifier recorded an explicit
        class, ``hold`` receives that attempt; every other hold keeps the generic reason.
        """
        if target_ref != binding.target_ref or self._admission is None:
            return False
        try:
            async with asyncio.timeout(5):
                query = {
                    "target_ref": binding.target_ref,
                    "access_scope_digest": binding.access_scope_digest,
                    "signal_code": binding.signal_code,
                }
                claim = await self._source.read(**query, at=self._clock())
                if (
                    claim is None
                    or claim.state != "reviewed"
                    or claim.digest != binding.context_digest
                ):
                    return False
                attempt = await request_operational_evidence(
                    self._evidence,
                    evidence_digest=claim.digest,
                    scope_digest="sha256:" + binding.access_scope_digest,
                    purpose_id="operational-test-context",
                    source_revision=claim.policy_revision,
                    locator={
                        "context_id": claim.context_id,
                        "target_ref": binding.target_ref,
                        "signal_code": binding.signal_code,
                    },
                    clock=self._clock,
                )
                receipt = await self._admission.admit(
                    evidence_digest=claim.digest,
                    scope_digest="sha256:" + binding.access_scope_digest,
                    purpose_id="operational-test-context",
                    source_revision=claim.policy_revision,
                )
                latest = await self._source.read(**query, at=self._clock())
                now = self._clock()
                if latest != claim or not claim.effective_from <= now < claim.effective_to:
                    return False
                if not isinstance(receipt, DecisionEvidenceAdmission):
                    if hold is not None:
                        hold.attempt = attempt
                    return False
                if now >= receipt.valid_until:
                    return False
                return not assess_decision_evidence_admission(
                    receipt,
                    expected_evidence_digest=claim.digest,
                    expected_scope_digest="sha256:" + binding.access_scope_digest,
                    expected_purpose_id="operational-test-context",
                    expected_source_revision=claim.policy_revision,
                    evaluated_at=now,
                )
        except Exception:  # noqa: BLE001
            return False
