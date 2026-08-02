"""Frozen-scenario metrics for the Command Deck atomic claim verifier."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from fdai.delivery.operator_api.routes.chat_claims import verify_screen_claims


@dataclass(frozen=True, slots=True)
class ClaimEvalCase:
    case_id: str
    answer: str
    view_context: Mapping[str, Any]
    expected_supported: bool


@dataclass(frozen=True, slots=True)
class ClaimEvalMetrics:
    total: int
    unsafe_total: int
    clean_total: int
    unsupported_claim_escapes: int
    clean_rejections: int

    @property
    def unsupported_claim_escape_rate(self) -> float:
        return self.unsupported_claim_escapes / self.unsafe_total if self.unsafe_total > 0 else 0.0

    @property
    def clean_rejection_rate(self) -> float:
        return self.clean_rejections / self.clean_total if self.clean_total > 0 else 0.0

    @property
    def passed(self) -> bool:
        return self.unsupported_claim_escapes == 0 and self.clean_rejections == 0


def evaluate_claim_cases(cases: Sequence[ClaimEvalCase]) -> ClaimEvalMetrics:
    """Evaluate a frozen labeled set with zero-escape, zero-rejection gates."""

    escapes = 0
    rejections = 0
    unsafe_total = 0
    clean_total = 0
    for case in cases:
        result = verify_screen_claims(case.answer, case.view_context)
        actual = result.supported and result.manifest.complete
        if case.expected_supported:
            clean_total += 1
            if not actual:
                rejections += 1
        else:
            unsafe_total += 1
            if actual:
                escapes += 1
    return ClaimEvalMetrics(
        total=len(cases),
        unsafe_total=unsafe_total,
        clean_total=clean_total,
        unsupported_claim_escapes=escapes,
        clean_rejections=rejections,
    )


__all__ = ["ClaimEvalCase", "ClaimEvalMetrics", "evaluate_claim_cases"]
