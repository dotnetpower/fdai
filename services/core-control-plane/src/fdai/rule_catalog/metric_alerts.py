"""Strict, non-authoritative metric alert catalog entries for push path #1.

A metric alert entry names one reviewed CSP-neutral metric, a static comparison, and the
Azure Monitor evaluation cadence that a deployment may materialize as a metric alert rule.
Entries are evidence sources only: every alert they produce reaches FDAI as a shadow-mode
Event through the existing webhook normalizer, and no entry grants detection, approval, or
execution authority. The shipped catalog carries no active entries; a deployment supplies its
own directory.
"""

from __future__ import annotations

import math
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from fdai.shared.contracts.models import OntologyProvenance

_ALERT_ID_PATTERN = r"^[a-z][a-z0-9.-]{2,95}$"
_METRIC_PATTERN = r"^[a-z][a-z0-9._-]{0,127}$"
_ARM_TYPE_PATTERN = r"^[A-Z][A-Za-z0-9.]{1,63}/[A-Za-z][A-Za-z0-9/]{1,127}$"
_MAX_DESCRIPTION_LENGTH = 512
MAX_METRIC_ALERT_ENTRIES = 256

WINDOW_MINUTES = {
    "PT1M": 1,
    "PT5M": 5,
    "PT15M": 15,
    "PT30M": 30,
    "PT1H": 60,
    "PT6H": 360,
    "PT12H": 720,
    "P1D": 1440,
}
FREQUENCY_MINUTES = {"PT1M": 1, "PT5M": 5, "PT15M": 15, "PT30M": 30, "PT1H": 60}


class MetricAlertComparison(StrEnum):
    """Static comparisons that Azure Monitor metric alerts evaluate natively."""

    ABOVE = "above"
    AT_OR_ABOVE = "at_or_above"
    BELOW = "below"
    AT_OR_BELOW = "at_or_below"


class MetricAlertCatalogError(ValueError):
    """A metric alert catalog directory or entry is malformed."""


class MetricAlertEntry(BaseModel):
    """One reviewed static-threshold alert over a reviewed CSP-neutral metric."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0.0"]
    alert_id: Annotated[str, Field(pattern=_ALERT_ID_PATTERN)]
    description: Annotated[str, Field(min_length=1, max_length=_MAX_DESCRIPTION_LENGTH)]
    metric: Annotated[str, Field(pattern=_METRIC_PATTERN)]
    resource_type: Annotated[str, Field(pattern=_ARM_TYPE_PATTERN)] | None = None
    comparison: MetricAlertComparison
    threshold: float
    window: Annotated[str, Field(min_length=3, max_length=8)]
    frequency: Annotated[str, Field(min_length=3, max_length=8)]
    severity: Annotated[int, Field(ge=0, le=4)]
    mode: Literal["shadow"] = "shadow"
    provenance: OntologyProvenance

    @model_validator(mode="after")
    def require_supported_evaluation(self) -> MetricAlertEntry:
        if not math.isfinite(self.threshold):
            raise ValueError("threshold MUST be finite")
        if self.window not in WINDOW_MINUTES:
            raise ValueError(f"window MUST be one of {sorted(WINDOW_MINUTES)}")
        if self.frequency not in FREQUENCY_MINUTES:
            raise ValueError(f"frequency MUST be one of {sorted(FREQUENCY_MINUTES)}")
        if FREQUENCY_MINUTES[self.frequency] > WINDOW_MINUTES[self.window]:
            raise ValueError("frequency MUST NOT exceed the evaluation window")
        return self


def load_metric_alert_catalog(directory: Path) -> tuple[MetricAlertEntry, ...]:
    """Load every ``*.yaml`` entry under ``directory`` in stable ``alert_id`` order.

    A missing directory yields no entries. Malformed YAML, schema violations, duplicate
    identifiers, or more than ``MAX_METRIC_ALERT_ENTRIES`` entries raise
    :class:`MetricAlertCatalogError`, so a partial catalog never materializes.
    """

    if not directory.exists():
        return ()
    if not directory.is_dir():
        raise MetricAlertCatalogError(f"metric alert catalog is not a directory: {directory}")
    paths = sorted(directory.glob("*.yaml"))
    if len(paths) > MAX_METRIC_ALERT_ENTRIES:
        raise MetricAlertCatalogError("metric alert catalog exceeds its entry limit")
    entries: dict[str, MetricAlertEntry] = {}
    for path in paths:
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            entry = MetricAlertEntry.model_validate(raw)
        except (OSError, yaml.YAMLError, ValidationError) as exc:
            raise MetricAlertCatalogError(f"invalid metric alert entry {path.name}") from exc
        if entry.alert_id in entries:
            raise MetricAlertCatalogError(f"duplicate metric alert id {entry.alert_id}")
        entries[entry.alert_id] = entry
    return tuple(entries[alert_id] for alert_id in sorted(entries))


__all__ = [
    "FREQUENCY_MINUTES",
    "MAX_METRIC_ALERT_ENTRIES",
    "WINDOW_MINUTES",
    "MetricAlertCatalogError",
    "MetricAlertComparison",
    "MetricAlertEntry",
    "load_metric_alert_catalog",
]
