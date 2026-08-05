"""Autonomy measurement summary read panel (``GET /kpi/autonomy``).

Projects the goals-and-metrics surface the Overview needs into one
read-only payload: the four success metrics against their reference
baseline, the guard metrics, a per-vertical split (Resilience / Change
Safety / Cost Governance), the tier mix against its target band, and a
short auto-resolution trend.

Two data provenances are combined, honestly labelled:

- **Audit-derived (live):** the per-vertical event split, per-vertical
  savings, and the tier mix are computed from the audit stream the read
  model already holds.
- **Measurement pipeline:** the success-metric baselines, the guard
  metrics beyond policy escapes, and the trend come from the
  goals-and-metrics measurement pipeline. That pipeline is not wired in
  the dev harness, so this panel accepts a synthetic ``measurement``
  mapping for dev/demo and reports ``synthetic: true``. A production
  composition root injects a real measurement source instead - the shape
  is identical, only the numbers become measured.

The synthetic dev values illustrate the *shape* and a plausible
"treatment beats a single-model baseline" story; they are NOT a measured
claim (see goals-and-metrics.md, Measurement-First Rule).

Read-only, like every :class:`~fdai.delivery.operator_api.routes.panels.ReadPanel`:
it renders GET-only data and exposes no action.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fdai.delivery.operator_api.projections.verticals import audit_vertical as _vertical_of
from fdai.delivery.operator_api.read_model import ConsoleReadModel

# Outcomes that mean a human was pulled in (not auto-resolved).
_INTERVENTION_OUTCOMES: frozenset[str] = frozenset(
    {"escalated_hil", "awaiting_approval", "hil_pending", "hil.await"}
)

_VERTICAL_KEYS: tuple[str, ...] = ("resilience", "change_safety", "cost")


# Synthetic dev/demo measurement. In production a real measurement source
# replaces this; the dev harness has no goals-and-metrics pipeline, so the
# panel reports ``synthetic: true`` and these values only illustrate the
# shape + a plausible story. They are NOT a measured claim.
_DEMO_MEASUREMENT: Mapping[str, Any] = {
    "window_days": 30,
    "sample_size": 1284,
    "confidence": 0.95,
    "source": {
        "name": "synthetic-dev-harness",
        "kind": "synthetic",
        "as_of": "2026-07-15T00:00:00Z",
    },
    "rules": {"active": 47, "candidates_30d": 6, "promoted_30d": 3},
    "success": {
        "auto_resolution_rate": {"value": 0.92, "baseline": 0.18, "direction": "higher"},
        "human_touchpoints_per_100": {"value": 1.1, "baseline": 5.8, "direction": "lower"},
        "mttr_seconds": {"value": 540, "baseline": 2700, "direction": "lower"},
        "change_lead_time_seconds": {"value": 1080, "baseline": 6300, "direction": "lower"},
        "cost_per_resolved_event_usd": {"value": 0.12, "baseline": 0.45, "direction": "lower"},
    },
    "leading": {
        "mixed_model_disagreement_rate": {"value": 0.01, "baseline": 0.03, "direction": "lower"},
        "verifier_failure_rate": {"value": 0.008, "baseline": 0.02, "direction": "lower"},
        "shadow_divergence_rate": {"value": 0.015, "baseline": 0.04, "direction": "lower"},
    },
    "guards": [
        {"key": "cfr", "value": 0.012, "baseline": 0.04, "threshold": 0.04, "ok": True},
        {"key": "false_positive", "value": 0.02, "baseline": 0.03, "threshold": 0.03, "ok": True},
        {"key": "false_negative", "value": 0.015, "baseline": 0.02, "threshold": 0.02, "ok": True},
        {"key": "rollback", "value": 0.008, "baseline": 0.02, "threshold": 0.02, "ok": True},
    ],
    "trend": {
        "auto_resolution_rate": [0.61, 0.64, 0.68, 0.72, 0.76, 0.80, 0.84, 0.87, 0.90, 0.92],
    },
}


class AutonomyMeasurementPanel:
    """ReadPanel serving ``GET /kpi/autonomy``.

    Combines an audit-derived vertical / tier split with an injected
    measurement mapping (synthetic in dev). Implements the
    :class:`~fdai.delivery.operator_api.routes.panels.ReadPanel` Protocol structurally
    (``path`` / ``name`` / ``render``); no import cycle with ``panels``.
    """

    def __init__(
        self,
        read_model: ConsoleReadModel,
        *,
        measurement: Mapping[str, Any] | None = None,
        path: str = "/kpi/autonomy",
        sample_size: int = 500,
    ) -> None:
        if not path.startswith("/"):
            raise ValueError(f"ReadPanel path MUST start with '/', got {path!r}")
        self._read_model = read_model
        self._measurement = measurement if measurement is not None else _DEMO_MEASUREMENT
        self._path = path
        self._sample_size = sample_size

    @property
    def path(self) -> str:
        return self._path

    @property
    def name(self) -> str:
        return "autonomy"

    async def render(self, *, params: Mapping[str, str]) -> Mapping[str, Any]:
        del params  # this panel takes no filters
        page = await self._read_model.list_audit(limit=self._sample_size)

        verticals: dict[str, dict[str, float]] = {
            key: {"events": 0, "auto_resolved": 0, "open_risks": 0, "monthly_savings": 0.0}
            for key in _VERTICAL_KEYS
        }
        by_tier: dict[str, int] = {}
        for item in page.items:
            outcome = str(item.entry.get("outcome", ""))
            bucket = verticals[_vertical_of(item.action_kind)]
            bucket["events"] += 1
            if outcome in _INTERVENTION_OUTCOMES:
                bucket["open_risks"] += 1
            elif outcome:
                bucket["auto_resolved"] += 1
            savings = item.entry.get("estimated_savings")
            if isinstance(savings, (int, float)) and not isinstance(savings, bool):
                bucket["monthly_savings"] += float(savings)
            tier = item.entry.get("tier")
            if tier is not None:
                key = str(tier)
                by_tier[key] = by_tier.get(key, 0) + 1

        tier_total = sum(by_tier.values()) or 1
        tier_mix = {key: by_tier.get(key, 0) / tier_total for key in ("t0", "t1", "t2")}
        attributed_events = sum(int(bucket["events"]) for bucket in verticals.values())
        sample_size = int(self._measurement.get("sample_size", 0))
        unattributed_events = max(0, sample_size - attributed_events)
        attribution_total = attributed_events + unattributed_events

        return {
            "synthetic": bool(
                self._measurement.get(
                    "synthetic",
                    self._measurement.get("source", {}).get("kind") == "synthetic",
                )
            ),
            "window_days": self._measurement.get("window_days", 30),
            "sample_size": attribution_total,
            "confidence": self._measurement.get("confidence"),
            "source": dict(self._measurement.get("source", {})),
            "rules": dict(self._measurement.get("rules", {})),
            "success": self._measurement.get("success", {}),
            "leading": self._measurement.get("leading", {}),
            "guards": list(self._measurement.get("guards", [])),
            "finalization": dict(
                self._measurement.get(
                    "finalization",
                    {
                        "finalized_events": 0,
                        "pending_events": 0,
                        "adverse_events": 0,
                    },
                )
            ),
            "attribution": {
                "attributed_events": attributed_events,
                "unattributed_events": unattributed_events,
                "coverage": (attributed_events / attribution_total if attribution_total else None),
            },
            "verticals": [
                {
                    "key": key,
                    "events": int(bucket["events"]),
                    "auto_resolved": int(bucket["auto_resolved"]),
                    "open_risks": int(bucket["open_risks"]),
                    "monthly_savings": round(bucket["monthly_savings"], 2),
                }
                for key, bucket in verticals.items()
            ]
            + [
                {
                    "key": "unattributed",
                    "events": unattributed_events,
                    "auto_resolved": 0,
                    "open_risks": 0,
                    "monthly_savings": 0.0,
                }
            ],
            "tier": {
                "mix": tier_mix,
                "bands": {"t0": [0.7, 0.8], "t1": [0.15, 0.2], "t2": [0.05, 0.1]},
            },
            "trend": self._measurement.get("trend", {}),
        }


__all__ = ["AutonomyMeasurementPanel"]
