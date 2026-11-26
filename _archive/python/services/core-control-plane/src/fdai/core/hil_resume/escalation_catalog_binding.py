"""Resolve reviewed approval timing without inventing human audience or urgency evidence."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from fdai.core.hil_resume.forecast_urgency import VerifiedForecastUrgency
from fdai.rule_catalog.schema.escalation_ladder import (
    EscalationCatalog,
    resolve_schedule,
    select_ladder,
)


@dataclass(frozen=True, slots=True)
class CatalogEscalationTiming:
    """Snapshot exact catalog windows for explicitly resolved, already authorized rungs."""

    catalog: EscalationCatalog
    environment: str
    audiences: Callable[[str], Sequence[str] | None] | None = None
    urgency_policy_id: str = "default-forecast-urgency"

    def resolve(
        self,
        context: Mapping[str, Any] | None,
        subjects: Sequence[str],
        *,
        at: datetime | None = None,
    ) -> Mapping[str, Any]:
        """Unknown source/audience is explicit; never guess which person a group represents."""
        if context is None:
            return {"catalog_status": "context_unavailable"}
        finding = context.get("finding_class")
        impact = context.get("impact")
        if (
            not isinstance(finding, str)
            or not isinstance(impact, str)
            or impact not in {"resource", "resource_group", "subscription"}
        ):
            return {"catalog_status": "context_unavailable"}
        ladder = select_ladder(
            self.catalog, environment=self.environment, finding_class=finding, impact=impact
        )
        if ladder is None:
            return {"catalog_status": "no_matching_ladder"}
        if self.audiences is None:
            return {"catalog_status": "audience_unavailable", "catalog_id": ladder.id}
        resolved = [self.audiences(rung.audience_group) for rung in ladder.rungs]
        normalized = [subject.strip().casefold() for subject in subjects]
        if len(resolved) != len(normalized) or any(
            audience is None or len(audience) != 1 or audience[0].strip().casefold() != subject
            for audience, subject in zip(resolved, normalized, strict=False)
        ):
            return {"catalog_status": "audience_mismatch", "catalog_id": ladder.id}
        verified = context.get("verified_forecast_urgency")
        lead = (
            verified.remaining_seconds(at)
            if isinstance(verified, VerifiedForecastUrgency) and at is not None
            else None
        )
        confidence = verified.confidence if isinstance(verified, VerifiedForecastUrgency) else None
        windows = resolve_schedule(
            ladder,
            policy=self.catalog.urgency_policy(self.urgency_policy_id),
            remaining_lead_time_seconds=lead,
            forecast_confidence=confidence,
        )
        return {
            "catalog_status": "resolved",
            "catalog_id": ladder.id,
            "catalog_overall_seconds": ladder.overall_deadline_seconds,
            "catalog_ttl_seconds": [window.effective_ttl_seconds for window in windows],
            "catalog_compressed": any(window.compressed for window in windows),
            "forecast_timing_status": "verified" if lead is not None else "unavailable",
            "forecast_timing_digest": (
                verified.source_digest
                if isinstance(verified, VerifiedForecastUrgency) and lead is not None
                else None
            ),
        }


__all__ = ["CatalogEscalationTiming"]
