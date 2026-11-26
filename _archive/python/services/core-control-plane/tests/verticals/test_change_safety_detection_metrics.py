"""Change-safety out-of-band detection precision/recall harness.

Phase-1 exit criterion (see
[phase-1-rule-catalog-t0.md](../../docs/roadmap/phases/phase-1-rule-catalog-t0.md)):

> Out-of-band detection reports **precision and recall against a labeled
> fixture set**, with the false-positive suppression rate recorded -
> establishing the detection baseline Phase 2 must not regress.

This module realizes the harness. It loads the labeled fixtures under
[`fixtures/change_safety_labeled/`](fixtures/change_safety_labeled/),
runs each through the real
:class:`~fdai.core.verticals.change_safety.detector.ChangeSafetyDetector`
under a deterministic clock, and computes:

- Per-class confusion matrix (AUTHORIZED / SUPPRESSED / OUT_OF_BAND).
- Precision + recall for OUT_OF_BAND (the class the phase-1 exit gate
  cares about).
- False-positive suppression rate: the share of non-OOB events that
  were suppressed / authorized rather than flagged OOB.

The current shipped detector is deterministic and every fixture is
authored to unambiguously map to one label, so the P1 baseline is
**perfect** (precision = recall = 1.0). The harness fails on any drift
so Phase 2 rule/tier changes cannot silently regress the detection
baseline.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from fdai.core.verticals.change_safety.detector import (
    ACTIVITY_LOG_SIGNAL_KIND,
    ChangeAttribution,
    ChangeSafetyDetector,
    ChangeSafetyDetectorConfig,
)
from fdai.shared.contracts.models import Event, Mode
from fdai.shared.providers.pipeline_principal import (
    InMemoryPipelinePrincipalRegistry,
)
from fdai.shared.providers.remediation_pr_ledger import (
    InMemoryRemediationPrLedger,
)
from fdai.shared.providers.testing import (
    InMemoryEventBus,
    InMemoryStateStore,
    RecordingRemediationPrPublisher,
)

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "change_safety_labeled"
_LABEL_TO_ATTRIBUTION: Mapping[str, ChangeAttribution] = {
    "AUTHORIZED": ChangeAttribution.AUTHORIZED,
    "SUPPRESSED": ChangeAttribution.SUPPRESSED,
    "OUT_OF_BAND": ChangeAttribution.OUT_OF_BAND,
}


# ---------------------------------------------------------------------------
# Fixture loading
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LabeledFixture:
    fixture_id: str
    label: ChangeAttribution
    event: Event


def _load_config() -> dict[str, Any]:
    return json.loads((FIXTURES_DIR / "_labeled_config.json").read_text(encoding="utf-8"))


def _build_event(payload_spec: Mapping[str, Any]) -> Event:
    """Materialize an :class:`Event` from a fixture's ``event`` spec."""
    resource_type: str = payload_spec["resource_type"]
    resource_id: str = payload_spec["resource_id"]
    actor: str | None = payload_spec.get("actor")
    correlation_id: str | None = payload_spec.get("correlation_id")
    detected_at = datetime.fromisoformat(payload_spec["detected_at"].replace("Z", "+00:00"))
    payload: dict[str, Any] = {
        "signal_kind": payload_spec.get("signal_kind", ACTIVITY_LOG_SIGNAL_KIND),
        "resource": {
            "resource_id": resource_id,
            "type": resource_type,
            "props": {},
        },
    }
    if actor is not None:
        payload["actor"] = {"principal_id": actor}
    return Event(
        schema_version="1.0.0",
        event_id=uuid4(),
        idempotency_key=payload_spec["idempotency_key"],
        correlation_id=correlation_id,
        source="azure_activity_log",
        event_type="config_changed",
        resource_ref=resource_id,
        payload=payload,
        detected_at=detected_at,
        ingested_at=detected_at + timedelta(milliseconds=250),
        mode=Mode.SHADOW,
    )


def _load_fixtures() -> list[LabeledFixture]:
    fixtures: list[LabeledFixture] = []
    for path in sorted(FIXTURES_DIR.glob("*.json")):
        if path.name.startswith("_"):
            continue
        raw = json.loads(path.read_text(encoding="utf-8"))
        label = _LABEL_TO_ATTRIBUTION[raw["label"]]
        event = _build_event(raw["event"])
        fixtures.append(
            LabeledFixture(
                fixture_id=raw["id"],
                label=label,
                event=event,
            )
        )
    return fixtures


# ---------------------------------------------------------------------------
# Detector build
# ---------------------------------------------------------------------------


def _build_detector() -> ChangeSafetyDetector:
    cfg_raw = _load_config()
    principals = InMemoryPipelinePrincipalRegistry(cfg_raw["known_pipeline_principals"])
    ledger = InMemoryRemediationPrLedger(cfg_raw["correlations"])
    settling_default = timedelta(seconds=int(cfg_raw["settling_windows_seconds"]["default"]))
    per_type = {
        resource_type: timedelta(seconds=int(seconds))
        for resource_type, seconds in cfg_raw["settling_windows_seconds"][
            "per_resource_type"
        ].items()
    }
    config = ChangeSafetyDetectorConfig(
        default_settling_window=settling_default,
        settling_windows=per_type,
    )
    clock_iso: str = cfg_raw["clock_wall_time"]
    fixed_now = datetime.fromisoformat(clock_iso.replace("Z", "+00:00"))
    return ChangeSafetyDetector(
        principal_registry=principals,
        ledger=ledger,
        publisher=RecordingRemediationPrPublisher(),
        event_bus=InMemoryEventBus(),
        audit_store=InMemoryStateStore(),
        config=config,
        clock=lambda: fixed_now,
    )


# ---------------------------------------------------------------------------
# Metric helpers (kept in-test - customer-agnostic, no product usage)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ConfusionCell:
    true_positive: int = 0
    false_positive: int = 0
    false_negative: int = 0
    true_negative: int = 0

    @property
    def precision(self) -> float:
        denom = self.true_positive + self.false_positive
        return 1.0 if denom == 0 else self.true_positive / denom

    @property
    def recall(self) -> float:
        denom = self.true_positive + self.false_negative
        return 1.0 if denom == 0 else self.true_positive / denom


def _one_vs_rest(
    labels: list[ChangeAttribution],
    predictions: list[ChangeAttribution],
    target: ChangeAttribution,
) -> ConfusionCell:
    tp = fp = fn = tn = 0
    for label, prediction in zip(labels, predictions, strict=True):
        is_target_label = label is target
        is_target_pred = prediction is target
        if is_target_label and is_target_pred:
            tp += 1
        elif is_target_pred and not is_target_label:
            fp += 1
        elif is_target_label and not is_target_pred:
            fn += 1
        else:
            tn += 1
    return ConfusionCell(
        true_positive=tp,
        false_positive=fp,
        false_negative=fn,
        true_negative=tn,
    )


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_out_of_band_detection_metrics_baseline() -> None:
    """P1 detection baseline - precision = recall = 1.0 on the labeled set.

    Any drift here (either a fixture becoming ambiguous or a detector
    change) breaks the baseline. Phase 2 rule / tier work MUST NOT
    regress this metric without an explicit, reviewed baseline bump.
    """
    fixtures = _load_fixtures()
    assert len(fixtures) >= 12, (
        f"labeled set is too small ({len(fixtures)}); the phase-1 exit "
        "gate expects a broad enough baseline"
    )

    detector = _build_detector()
    labels: list[ChangeAttribution] = []
    predictions: list[ChangeAttribution] = []
    per_fixture: list[tuple[str, ChangeAttribution, ChangeAttribution]] = []

    for fixture in fixtures:
        decision = await detector.detect(fixture.event)
        labels.append(fixture.label)
        predictions.append(decision.attribution)
        per_fixture.append((fixture.fixture_id, fixture.label, decision.attribution))

    # Per-class metrics
    metrics: dict[ChangeAttribution, ConfusionCell] = {
        target: _one_vs_rest(labels, predictions, target)
        for target in (
            ChangeAttribution.AUTHORIZED,
            ChangeAttribution.SUPPRESSED,
            ChangeAttribution.OUT_OF_BAND,
        )
    }

    # Report - printed on assertion failure only, keeps the test terse
    # when green.
    def _rendered() -> str:
        lines = ["\nper-fixture predictions:"]
        for fixture_id, expected, got in per_fixture:
            marker = "OK  " if expected is got else "MISS"
            lines.append(f"  {marker} {fixture_id}: expected {expected.value}, got {got.value}")
        lines.append("\nper-class metrics:")
        for attribution, cell in metrics.items():
            lines.append(
                f"  {attribution.value}: precision={cell.precision:.3f} "
                f"recall={cell.recall:.3f} tp={cell.true_positive} "
                f"fp={cell.false_positive} fn={cell.false_negative} "
                f"tn={cell.true_negative}"
            )
        return "\n".join(lines)

    oob_cell = metrics[ChangeAttribution.OUT_OF_BAND]
    assert oob_cell.precision == 1.0, (
        f"OUT_OF_BAND precision regressed to {oob_cell.precision:.3f} "
        f"(false positives = {oob_cell.false_positive})" + _rendered()
    )
    assert oob_cell.recall == 1.0, (
        f"OUT_OF_BAND recall regressed to {oob_cell.recall:.3f} "
        f"(missed OOB = {oob_cell.false_negative})" + _rendered()
    )

    # False-positive suppression rate - share of true-non-OOB events
    # that ended up suppressed or authorized (i.e. NOT flagged OOB).
    non_oob_total = sum(1 for label in labels if label is not ChangeAttribution.OUT_OF_BAND)
    non_oob_correctly_non_oob = sum(
        1
        for label, prediction in zip(labels, predictions, strict=True)
        if label is not ChangeAttribution.OUT_OF_BAND
        and prediction is not ChangeAttribution.OUT_OF_BAND
    )
    fp_suppression_rate = 1.0 if non_oob_total == 0 else non_oob_correctly_non_oob / non_oob_total
    assert fp_suppression_rate == 1.0, (
        f"false-positive suppression rate regressed to {fp_suppression_rate:.3f}" + _rendered()
    )

    # Per-class precision/recall must all be 1.0 on the P1 baseline.
    for attribution, cell in metrics.items():
        assert cell.precision == 1.0 and cell.recall == 1.0, (
            f"{attribution.value} class regressed: "
            f"precision={cell.precision:.3f} recall={cell.recall:.3f}" + _rendered()
        )


def test_fixture_class_balance() -> None:
    """Each ground-truth class MUST have at least four labeled fixtures.

    Ensures the baseline is not carried by a single class; small classes
    are the most likely to hide a detection regression.
    """
    fixtures = _load_fixtures()
    counts: dict[ChangeAttribution, int] = {
        ChangeAttribution.AUTHORIZED: 0,
        ChangeAttribution.SUPPRESSED: 0,
        ChangeAttribution.OUT_OF_BAND: 0,
    }
    for fixture in fixtures:
        counts[fixture.label] += 1
    for attribution, count in counts.items():
        assert count >= 4, (
            f"labeled class {attribution.value} has only {count} fixtures - "
            "need at least 4 for a meaningful baseline"
        )
