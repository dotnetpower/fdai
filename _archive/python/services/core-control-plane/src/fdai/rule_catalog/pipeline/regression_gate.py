"""Regression gate - decide promote-vs-rollback for a candidate rule set.

Phase 2 continuous-update pipeline stage 4 (see
[`docs/roadmap/phases/phase-2-quality-and-t1.md § Regression gate`]).

Contract
--------

Given a :class:`ShadowEvalReport` (and a **baseline** report from the
last-known-good rule set), decide whether the candidate:

- **passes** - no policy-violation escapes, coverage did not regress
  below the guard threshold, no forbidden guard breach.
- **fails** - one of the above tripped; the pipeline MUST roll back.

The gate is a pure function: same inputs → same decision. Config
thresholds are injected at construction so a fork tightens them without
editing ``core/`` (guard the enforce path with narrower bars).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final

from fdai.rule_catalog.pipeline.shadow_eval import ShadowEvalReport

_DEFAULT_MAX_POLICY_ESCAPES: Final[int] = 0
_DEFAULT_MIN_COVERAGE_RATIO: Final[float] = 0.95
"""Candidate coverage MUST reach 95% of the baseline coverage (floor of
0 when the baseline itself is zero - a fresh rollout starts at 0)."""

_DEFAULT_MAX_MISSING_EXPECTED_RULES: Final[int] = 0


class RegressionOutcome(StrEnum):
    """Gate outcomes."""

    PASS = "pass"  # noqa: S105 - gate outcome literal, not a secret
    FAIL = "fail"


@dataclass(frozen=True, slots=True)
class RegressionGateConfig:
    """Thresholds the gate enforces.

    Every value has a documented default so the pipeline runs standalone
    without a fork tuning it. A fork tightens by supplying its own
    :class:`RegressionGateConfig`; loosening (raising escape allowance,
    lowering coverage floor) is deliberately awkward because that's an
    audited governance change, not a code tweak
    (see ``docs/roadmap/rules-and-detection/rule-governance.md``).
    """

    max_policy_escapes: int = _DEFAULT_MAX_POLICY_ESCAPES
    """Absolute cap on ``policy_violation_escapes`` in the report."""

    min_coverage_ratio: float = _DEFAULT_MIN_COVERAGE_RATIO
    """Candidate coverage MUST be at least ``ratio`` × baseline coverage."""

    max_missing_expected_rules: int = _DEFAULT_MAX_MISSING_EXPECTED_RULES
    """Cap on scenarios whose ``expected.citing_rule_ids`` are NOT matched."""


@dataclass(frozen=True, slots=True)
class RegressionDecision:
    """Frozen record produced by :class:`RegressionGate.evaluate`.

    Consumed by the promotion controller and written to audit; the
    caller MUST NOT rewrite it between gate + audit (tests assert
    frozen-ness).
    """

    outcome: RegressionOutcome
    scenario_set_id: str
    candidate_rule_ids: tuple[str, ...]
    baseline_coverage: float
    candidate_coverage: float
    policy_violation_escapes: int
    missing_expected_rules: int
    reasons: tuple[str, ...] = field(default_factory=tuple)
    """List of every threshold that failed. Empty on PASS."""


class RegressionGate:
    """Compute a :class:`RegressionDecision` from candidate + baseline reports."""

    def __init__(self, *, config: RegressionGateConfig | None = None) -> None:
        cfg = config or RegressionGateConfig()
        if cfg.max_policy_escapes < 0:
            raise ValueError("max_policy_escapes MUST be >= 0")
        if not 0.0 <= cfg.min_coverage_ratio <= 1.0:
            raise ValueError("min_coverage_ratio MUST be in [0.0, 1.0]")
        if cfg.max_missing_expected_rules < 0:
            raise ValueError("max_missing_expected_rules MUST be >= 0")
        self._config = cfg

    def evaluate(
        self,
        *,
        candidate: ShadowEvalReport,
        baseline: ShadowEvalReport | None = None,
    ) -> RegressionDecision:
        """Return the gate decision.

        ``baseline`` is optional - a first-run rollout has no prior
        known-good report, in which case the coverage-ratio check is
        skipped (there is nothing to regress against).
        """
        reasons: list[str] = []

        if candidate.policy_violation_escapes > self._config.max_policy_escapes:
            reasons.append(
                f"policy_violation_escapes={candidate.policy_violation_escapes} "
                f"> max={self._config.max_policy_escapes}"
            )

        if candidate.missing_expected_rules > self._config.max_missing_expected_rules:
            reasons.append(
                f"missing_expected_rules={candidate.missing_expected_rules} "
                f"> max={self._config.max_missing_expected_rules}"
            )

        baseline_coverage = 0.0 if baseline is None else baseline.coverage
        if baseline is not None and baseline_coverage > 0:
            floor = self._config.min_coverage_ratio * baseline_coverage
            if candidate.coverage < floor:
                reasons.append(
                    f"coverage={candidate.coverage:.4f} < floor="
                    f"{floor:.4f} (ratio={self._config.min_coverage_ratio}, "
                    f"baseline={baseline_coverage:.4f})"
                )

        outcome = RegressionOutcome.FAIL if reasons else RegressionOutcome.PASS
        return RegressionDecision(
            outcome=outcome,
            scenario_set_id=candidate.scenario_set_id,
            candidate_rule_ids=candidate.candidate_rule_ids,
            baseline_coverage=baseline_coverage,
            candidate_coverage=candidate.coverage,
            policy_violation_escapes=candidate.policy_violation_escapes,
            missing_expected_rules=candidate.missing_expected_rules,
            reasons=tuple(reasons),
        )


__all__ = [
    "RegressionDecision",
    "RegressionGate",
    "RegressionGateConfig",
    "RegressionOutcome",
]
