"""In-memory :class:`CostEstimator` for tests + local development.

Ships two behaviours through one class:

- fixed per-key returns, with ``seed`` (matches other testing fakes);
- one-shot error injection for the abstain-on-error path.

Keys are ``ActionType.name`` by default; callers can override with a
custom key extractor to test argument-dependent estimation.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from fdai.shared.contracts.models import OntologyActionType
from fdai.shared.providers.cost_estimator import (
    CostConfidence,
    CostEstimate,
    CostEstimator,
    CostEstimatorError,
)


class InMemoryCostEstimator(CostEstimator):
    """Deterministic fake with per-key estimates + one-shot error hook.

    Default behaviour is :attr:`CostConfidence.ABSTAIN` for any unseeded
    ActionType so a test that forgets to seed does not accidentally get
    a "definitely-cheap" verdict from the fake.
    """

    def __init__(
        self,
        *,
        estimator_id: str = "in-memory-cost",
        key_fn: Callable[[OntologyActionType, Mapping[str, Any]], str] | None = None,
    ) -> None:
        if not estimator_id:
            raise ValueError("estimator_id MUST be non-empty")
        self._estimator_id = estimator_id
        self._key_fn = key_fn or (lambda at, _args: at.name)
        self._seeds: dict[str, CostEstimate] = {}
        self._next_error: CostEstimatorError | None = None
        self._calls: list[tuple[str, Mapping[str, Any]]] = []

    def seed(
        self,
        key: str,
        monthly_usd: float,
        *,
        confidence: CostConfidence = CostConfidence.HIGH,
        rationale: str | None = None,
    ) -> None:
        """Register a grounded estimate for ``key``.

        ``key`` is whatever ``key_fn`` returns for the target
        ``(ActionType, arguments)``; when ``key_fn`` is the default,
        pass the ActionType name.
        """

        if confidence is CostConfidence.ABSTAIN:
            raise ValueError(
                "seed a real figure - call seed_abstain(key) to force an ABSTAIN response"
            )
        estimate = CostEstimate(
            monthly_usd=monthly_usd,
            confidence=confidence,
            estimator_id=self._estimator_id,
            rationale=rationale,
        )
        self._seeds[key] = estimate

    def seed_abstain(self, key: str, *, rationale: str | None = None) -> None:
        """Force :attr:`CostConfidence.ABSTAIN` for ``key``."""

        self._seeds[key] = CostEstimate(
            monthly_usd=None,
            confidence=CostConfidence.ABSTAIN,
            estimator_id=self._estimator_id,
            rationale=rationale,
        )

    def next_error(self, error: CostEstimatorError) -> None:
        """One-shot error injected into the next :meth:`estimate` call."""

        self._next_error = error

    @property
    def calls(self) -> tuple[tuple[str, Mapping[str, Any]], ...]:
        """Every ``(key, arguments)`` observed, in order."""

        return tuple(self._calls)

    async def estimate(
        self,
        action_type: OntologyActionType,
        arguments: Mapping[str, Any],
    ) -> CostEstimate:
        if self._next_error is not None:
            err = self._next_error
            self._next_error = None
            raise err

        key = self._key_fn(action_type, arguments)
        self._calls.append((key, dict(arguments)))
        seeded = self._seeds.get(key)
        if seeded is not None:
            return seeded
        return CostEstimate(
            monthly_usd=None,
            confidence=CostConfidence.ABSTAIN,
            estimator_id=self._estimator_id,
            rationale=f"no estimate seeded for key {key!r}",
        )


__all__ = ["InMemoryCostEstimator"]
