"""Current receipt-verified acceptance candidates and an additional pre-effect guard for Thor."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from fdai.agents import AnomalyActionCandidate

from fdai_aks_commerce.acceptance import OrderAcceptanceAnalyzer, OrderAcceptanceIntent

ACCEPTANCE_SIGNAL = "analyzer.aks_commerce.order_acceptance_unavailable.observed"


class AcceptanceAnomalyActionSource:
    """Re-read signed acceptance evidence instead of trusting action data in an anomaly."""

    def __init__(self, *, intent: OrderAcceptanceIntent, analyzer: OrderAcceptanceAnalyzer) -> None:
        self.intent = intent
        self._analyzer = analyzer

    async def resolve(self, *, event_type: str, resource_ref: str) -> AnomalyActionCandidate | None:
        """Return one bounded candidate; missing proof or competing writers withhold action."""
        if event_type != ACCEPTANCE_SIGNAL or resource_ref != self.intent.resource_ref:
            return None
        assessment = await self._analyzer.assess(
            resource_ref=resource_ref,
            window_seconds=self.intent.max_age_seconds,
        )
        proposal = assessment.proposal
        if assessment.status != "unavailable" or proposal is None:
            return None
        return AnomalyActionCandidate(
            event_type=event_type,
            resource_ref=resource_ref,
            action_type=proposal.action_type,
            arguments_json=json.dumps(
                dict(proposal.arguments), sort_keys=True, separators=(",", ":")
            ),
            evidence_ref=assessment.evidence_digest,
            observed_at=assessment.observed_at,
            expires_at=min(
                self.intent.valid_until,
                assessment.observed_at + timedelta(seconds=self.intent.max_age_seconds),
            ),
        )


class AcceptanceGuardedExecutor:
    """Add current-evidence checks to Thor's existing executor; never replace its safeguards.

    The downstream executor retains risk, promotion, immutable human approval, target lock,
    idempotency, dry-run, rollback and two-phase audit admission. This guard cannot grant them.
    """

    def __init__(
        self,
        *,
        source: AcceptanceAnomalyActionSource,
        execute: Callable[[dict[str, Any]], Awaitable[bool]],
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._source = source
        self._execute = execute
        self._clock = clock or (lambda: datetime.now(UTC))

    async def __call__(self, context: dict[str, Any]) -> bool:
        """Withhold configured-target calls on drift; unrelated targets keep their existing path."""
        run = context.get("run")
        if run is None:
            raise ValueError("acceptance dispatch requires the existing Thor ActionRun")
        if run.resource_id != self._source.intent.resource_ref:
            return await self._execute(context)
        await self.bind(context)()
        return await self._execute(context)

    def bind(self, context: dict[str, Any]) -> Callable[[], Awaitable[None]]:
        """Freeze approved arguments for repeatable admission at the final publication boundary."""
        run = context.get("run")
        if run is None or run.resource_id != self._source.intent.resource_ref:
            raise ValueError("acceptance guard requires its exact configured ActionRun target")
        bound_run: Any = run
        approved_resource = run.resource_id
        approved_type = run.action_type
        approved_arguments = json.dumps(
            run.params, sort_keys=True, separators=(",", ":"), allow_nan=False
        )

        async def check() -> None:
            candidate = await self._source.resolve(
                event_type=ACCEPTANCE_SIGNAL, resource_ref=approved_resource
            )
            if (
                candidate is None
                or context["run"] is not bound_run
                or approved_resource != bound_run.resource_id
                or approved_type != bound_run.action_type
                or approved_type != candidate.action_type
                or approved_arguments != candidate.arguments_json
                or not isinstance(bound_run.params, Mapping)
                or dict(bound_run.params) != candidate.arguments()
                or not candidate.observed_at <= self._clock() < candidate.expires_at
            ):
                raise ValueError(
                    "acceptance evidence changed before dispatch; a new proposal is required"
                )

        return check
