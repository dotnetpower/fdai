from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from fdai.rule_catalog.schema.signal_type import (
    SignalTypeRegistryError,
    load_signal_type_registry_from_mapping,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _registry():  # type: ignore[no-untyped-def]
    raw = yaml.safe_load(
        (REPO_ROOT / "rule-catalog/vocabulary/signal-types.yaml").read_text(encoding="utf-8")
    )
    return load_signal_type_registry_from_mapping(raw)


def test_shipped_signal_types_resolve_exact_and_baseline_events() -> None:
    registry = _registry()

    assert registry.resolve("metric.cpu.spike") == frozenset({"resource.metric.observed"})
    assert registry.resolve("change.started") == frozenset({"change.observed"})
    assert registry.resolve("unknown.provider.event") == frozenset(
        {"resource.configuration.observed"}
    )


def test_signal_type_registry_requires_one_baseline() -> None:
    with pytest.raises(SignalTypeRegistryError, match="exactly one baseline"):
        load_signal_type_registry_from_mapping(
            {
                "schema_version": "1.0.0",
                "types": [
                    {
                        "id": "resource.metric.observed",
                        "dispatch_mode": "exact",
                        "event_type_patterns": ["metric.*"],
                        "description": "Metric evidence.",
                    }
                ],
            }
        )
