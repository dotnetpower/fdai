"""Tests for :func:`fdai.composition.load_pricing_table`."""

from __future__ import annotations

from pathlib import Path

import pytest

from fdai.composition import load_pricing_table

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SHIPPED = _REPO_ROOT / "rule-catalog" / "llm-pricing.yaml"


def test_loads_shipped_pricing_table() -> None:
    table = load_pricing_table(_SHIPPED)
    pricing = table.pricing_for("gpt-4o")
    assert pricing is not None
    assert pricing.input_per_1k > 0
    assert pricing.currency == "USD"


def test_rejects_missing_models_key(tmp_path: Path) -> None:
    bad = tmp_path / "p.yaml"
    bad.write_text("schema_version: '1.0.0'\n", encoding="utf-8")
    with pytest.raises(ValueError, match="models"):
        load_pricing_table(bad)


def test_rejects_non_mapping_file(tmp_path: Path) -> None:
    bad = tmp_path / "p.yaml"
    bad.write_text("- just\n- a\n- list\n", encoding="utf-8")
    with pytest.raises(ValueError, match="mapping"):
        load_pricing_table(bad)
