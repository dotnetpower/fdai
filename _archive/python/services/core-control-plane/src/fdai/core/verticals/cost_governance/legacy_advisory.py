"""Deprecated inert Cost Governance advisory retained only for W6 parity."""

from __future__ import annotations

import hashlib
import json
from collections import deque
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from statistics import mean

from fdai.shared.providers.cost_governance import (
    CostAdvisoryProvider,
    CostAnalysisSample,
    CostAnomalyAdvisory,
    SignedCostEffectEstimate,
)

COMPATIBILITY_STATUS = "deprecated-inert-parity-only"
REMOVAL_REVIEW_GATE = "w7-operational-validation-complete"

_LEGACY_COST_TABLE: Mapping[str, Decimal] = {
    "ops.restart-service": Decimal("0"),
    "remediate.disable-public-access": Decimal("0"),
    "remediate.enable-encryption": Decimal("3.5"),
    "remediate.resize_vm_up": Decimal("45"),
    "remediate.resize_vm_down": Decimal("-25"),
}


class LegacyRollingCostAdvisoryProvider(CostAdvisoryProvider):
    """Historical deterministic model; composition MUST NOT select it to publish."""

    compatibility_status = COMPATIBILITY_STATUS

    def __init__(
        self,
        *,
        ontology_release_digest: str,
        anomaly_ratio: Decimal = Decimal("1.5"),
        baseline_window: int = 30,
        max_samples: int = 512,
        max_sample_age: timedelta = timedelta(days=2),
        cost_table: Mapping[str, Decimal] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not ontology_release_digest or anomaly_ratio <= 1:
            raise ValueError("advisory release and anomaly ratio MUST be valid")
        if baseline_window < 3 or max_samples < baseline_window:
            raise ValueError("advisory sample bounds MUST preserve a baseline")
        self._release = ontology_release_digest
        self._ratio = anomaly_ratio
        self._window = baseline_window
        self._max_age = max_sample_age
        self._table = dict(cost_table or _LEGACY_COST_TABLE)
        self._clock = clock or (lambda: datetime.now(UTC))
        self._samples: dict[str, deque[Decimal]] = {}
        self._seen: set[tuple[str, datetime]] = set()
        self._last_observed: dict[str, datetime] = {}
        self._max_samples = max_samples
        self.diagnostics: dict[str, int] = {}

    async def analyze_cost_sample(
        self,
        sample: CostAnalysisSample,
    ) -> CostAnomalyAdvisory | None:
        reason = self._invalid_reason(sample)
        if reason is not None:
            self._record(reason)
            return None
        sample_key = (sample.correlation_id, sample.observed_at)
        if sample_key in self._seen:
            self._record("duplicate")
            return None
        last = self._last_observed.get(sample.scope_id)
        if last is not None and sample.observed_at <= last:
            self._record("reordered")
            return None
        history = self._samples.setdefault(
            sample.scope_id,
            deque(maxlen=self._max_samples),
        )
        advisory: CostAnomalyAdvisory | None = None
        if len(history) >= 3:
            baseline = Decimal(str(mean(history))) if history else Decimal("0")
            if baseline > 0 and sample.amount_usd > baseline * self._ratio:
                ratio = sample.amount_usd / baseline
                impact = max(Decimal("0"), min(Decimal("1"), ratio - Decimal("1")))
                advisory = CostAnomalyAdvisory(
                    scope_id=sample.scope_id,
                    resource_id=sample.resource_id,
                    amount_usd=sample.amount_usd,
                    baseline_usd=baseline,
                    ratio=ratio,
                    impact=impact,
                    recommendation="scale_down",
                    correlation_id=sample.correlation_id,
                    observed_at=sample.observed_at,
                )
        history.append(sample.amount_usd)
        self._seen.add(sample_key)
        self._last_observed[sample.scope_id] = sample.observed_at
        self._record("accepted")
        return advisory

    def estimate_cost_effect(self, action_type: str) -> SignedCostEffectEstimate | None:
        delta = self._table.get(action_type)
        if delta is None:
            return None
        now = self._clock()
        payload = json.dumps(
            {"action_type": action_type, "monthly_delta_usd": str(delta)},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return SignedCostEffectEstimate(
            action_type=action_type,
            monthly_delta_usd=delta,
            confidence=Decimal("0.9"),
            evidence_digest=f"sha256:{hashlib.sha256(payload).hexdigest()}",
            source_authority="fdai-cost-governance:deterministic-cost-table",
            observed_at=now,
            valid_until=now + timedelta(days=30),
        )

    def _invalid_reason(self, sample: CostAnalysisSample) -> str | None:
        if sample.ontology_release_digest != self._release:
            return "ontology_mismatch"
        if sample.completeness != Decimal("1"):
            return "incomplete"
        if self._clock() - sample.observed_at > self._max_age:
            return "stale"
        return None

    def _record(self, reason: str) -> None:
        self.diagnostics[reason] = self.diagnostics.get(reason, 0) + 1


__all__ = [
    "COMPATIBILITY_STATUS",
    "REMOVAL_REVIEW_GATE",
    "LegacyRollingCostAdvisoryProvider",
]
