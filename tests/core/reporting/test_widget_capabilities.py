from __future__ import annotations

import json
from pathlib import Path

from fdai.core.reporting.widgets import GROUP_LIKE_WIDGET_TYPES, default_widget_builders

ROOT = Path(__file__).resolve().parents[3]


def test_widget_capability_catalog_matches_upstream_registry_exactly() -> None:
    payload = json.loads(
        (ROOT / "rule-catalog" / "reports" / "widget-capabilities.json").read_text(encoding="utf-8")
    )
    entries = payload["widgets"]
    catalog_types = [entry["type"] for entry in entries]
    registry_types = {
        *(builder.type_name for builder in default_widget_builders()),
        *GROUP_LIKE_WIDGET_TYPES,
    }

    assert payload["schema_version"] == "1.0.0"
    assert len(catalog_types) == len(set(catalog_types))
    assert {entry["frontend"] for entry in entries} == {"render", "blocked"}
    assert set(catalog_types) == registry_types
    assert [entry["type"] for entry in entries if entry["frontend"] == "blocked"] == ["iframe"]
