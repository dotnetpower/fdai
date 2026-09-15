"""Revalidate the exact context used by a queued decision without granting execution."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from fdai.shared.providers.decision_evidence_verifier import (
    DecisionEvidenceAdmission,
    DecisionEvidenceAdmissionProvider,
    assess_decision_evidence_admission,
)

from .test_context import TestContextSource


class TestContextDispatchBinding(BaseModel):
    """Immutable source identity retained with the ActionRun, not an authorization grant."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    target_ref: Annotated[str, Field(min_length=1, max_length=512)]
    access_scope_digest: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    signal_code: Annotated[str, Field(min_length=1, max_length=512)]
    context_digest: Annotated[str, Field(pattern=r"^sha256:[a-f0-9]{64}$")]


class TestContextDispatchGuard:
    """Hold changed, unavailable, unreviewed, or expired context immediately before dispatch."""

    def __init__(
        self,
        *,
        source: TestContextSource,
        admission: DecisionEvidenceAdmissionProvider | None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._source, self._admission = source, admission
        self._clock = clock or (lambda: datetime.now(UTC))

    async def current(self, binding: TestContextDispatchBinding, *, target_ref: str | None) -> bool:
        """Check source and independent admission under one deadline; cancellation propagates."""
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
                receipt = await self._admission.admit(
                    evidence_digest=claim.digest,
                    scope_digest="sha256:" + binding.access_scope_digest,
                    purpose_id="operational-test-context",
                    source_revision=claim.policy_revision,
                )
                latest = await self._source.read(**query, at=self._clock())
                now = self._clock()
                return (
                    latest == claim
                    and isinstance(receipt, DecisionEvidenceAdmission)
                    and claim.effective_from <= now < min(claim.effective_to, receipt.valid_until)
                    and not assess_decision_evidence_admission(
                        receipt,
                        expected_evidence_digest=claim.digest,
                        expected_scope_digest="sha256:" + binding.access_scope_digest,
                        expected_purpose_id="operational-test-context",
                        expected_source_revision=claim.policy_revision,
                        evaluated_at=now,
                    )
                )
        except Exception:  # noqa: BLE001
            return False
