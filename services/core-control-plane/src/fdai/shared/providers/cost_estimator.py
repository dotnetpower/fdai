"""Cost estimator Protocol - Wave W2.5.

CSP-neutral seam the Cost Governance vertical implements so the risk-
gate can consult a per-vertical estimator without importing that
vertical into ``core/``. The ``cost_impact_monthly`` scalar in
:mod:`fdai.core.risk_gate.feature` is where the resolved
estimate ultimately lands; this Protocol is how a caller resolves it
for a given ``(ActionType, arguments)`` pair when the ActionType is
cost-increasing (see
[execution-model.md](../../../../docs/roadmap/decisioning/execution-model.md)
section 2.8 on cost-increasing ops actions).

Design invariants
-----------------

- **Read-only, deterministic on inputs**: an estimator MUST NOT mutate
  state and MUST return the same estimate for the same inputs (up to
  the freshness of its underlying pricing data). Callers rely on this
  to reproduce the risk-gate decision from an audit entry.
- **Abstain-safe**: an estimator that cannot ground the answer returns
  a :class:`CostEstimate` with ``monthly_usd=None``. The risk-gate
  treats ``None`` as "unknown", which the Axis A gate MUST route to
  HIL (unknown cost never auto-executes) - the fail-closed rule in
  the doc.
- **No privileged identity in ``core/``**: real pricing lookups live
  behind a fork's :class:`CostEstimator` binding; the upstream ships
  the Protocol + a static fake for tests.
- **CSP-neutral**: the estimator sees only the CSP-neutral
  :class:`OntologyActionType` and a JSON-friendly arguments mapping.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from fdai.shared.contracts.models import OntologyActionType


class CostConfidence(StrEnum):
    """How confident the estimator is in the returned figure.

    The risk-gate never treats ``LOW`` confidence as sufficient for an
    ``auto`` verdict on a cost-gated ActionType; the fail-closed rule
    still applies.
    """

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    ABSTAIN = "abstain"


@dataclass(frozen=True, slots=True)
class CostEstimate:
    """One estimator's opinion for a single ``(ActionType, args)`` call.

    ``monthly_usd`` is ``None`` iff ``confidence`` is
    :attr:`CostConfidence.ABSTAIN`. The invariant is enforced in
    :meth:`__post_init__`.
    """

    monthly_usd: float | None
    confidence: CostConfidence
    estimator_id: str
    rationale: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.estimator_id:
            raise ValueError("estimator_id MUST be non-empty")
        if self.confidence is CostConfidence.ABSTAIN:
            if self.monthly_usd is not None:
                raise ValueError(
                    "monthly_usd MUST be None when confidence is ABSTAIN "
                    "(the estimator abstained; there is no grounded figure)"
                )
        else:
            if self.monthly_usd is None:
                raise ValueError("monthly_usd MUST be a float when confidence is not ABSTAIN")
            if self.monthly_usd < 0:
                raise ValueError("monthly_usd MUST be non-negative")

    @property
    def abstained(self) -> bool:
        """True when the estimator could not ground the answer."""

        return self.confidence is CostConfidence.ABSTAIN

    def to_dict(self) -> dict[str, Any]:
        """JSON-friendly serialization for audit entries."""

        return {
            "monthly_usd": self.monthly_usd,
            "confidence": self.confidence.value,
            "estimator_id": self.estimator_id,
            "rationale": self.rationale,
            "metadata": dict(self.metadata),
        }


class CostEstimatorError(RuntimeError):
    """Raised when an estimator hits a transport / pricing-data failure.

    Callers catch this and treat it identically to
    :attr:`CostConfidence.ABSTAIN` - the risk-gate never auto-executes
    on an estimator error.
    """


@runtime_checkable
class CostEstimator(Protocol):
    """Estimate the monthly USD cost impact of one autonomous action."""

    async def estimate(
        self,
        action_type: OntologyActionType,
        arguments: Mapping[str, Any],
    ) -> CostEstimate:
        """Return a :class:`CostEstimate` for ``(action_type, arguments)``.

        Implementations MUST:

        - be pure with respect to their input (a re-call with the same
          arguments returns the same figure until the pricing table
          refreshes);
        - return :attr:`CostConfidence.ABSTAIN` when they cannot ground
          the answer (unknown region, missing SKU, unknown resource);
        - raise :class:`CostEstimatorError` on a transport-level failure
          the caller should treat as abstain.
        """
        ...


async def resolve_cost_impact_monthly(
    estimator: CostEstimator | None,
    action_type: OntologyActionType,
    arguments: Mapping[str, Any] | None = None,
) -> float | None:
    """Adapter that surfaces the scalar the risk-gate consumes.

    Returns ``None`` when:

    - ``estimator`` is ``None`` (no vertical wired) - the risk-gate
      treats this as "unknown", per the fail-closed rule;
    - the estimator abstains;
    - the estimator raises :class:`CostEstimatorError`.

    Otherwise returns ``monthly_usd``. Never raises.
    """

    if estimator is None:
        return None
    try:
        estimate = await estimator.estimate(action_type, dict(arguments or {}))
    except CostEstimatorError:
        return None
    if estimate.abstained:
        return None
    return estimate.monthly_usd


__all__ = [
    "CostConfidence",
    "CostEstimate",
    "CostEstimator",
    "CostEstimatorError",
    "resolve_cost_impact_monthly",
]
