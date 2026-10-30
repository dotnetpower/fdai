"""Korean authoring overlays cannot replace effective English metadata."""

from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[3] / "scripts/catalog/wara_guidance_localization.py"
SPEC = importlib.util.spec_from_file_location("wara_locale_regression", SOURCE)
assert SPEC is not None and SPEC.loader is not None
LOCALIZATION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LOCALIZATION)


@pytest.mark.parametrize("field", ["title", "summary", "benefits"])
def test_overlay_preserves_effective_english_and_rejects_stale_source(field: str) -> None:
    entry = {
        "recommendation_id": "test-guid",
        "source_revision": "revision",
        "source_digest": "digest",
        field: {"en": "Effective reviewed source"},
    }
    records = {
        "test-guid": {
            "source_revision": "revision",
            "source_digest": "digest",
            "content": {field: {"en": "Old source", "ko": "검토한 원문"}},
        }
    }
    before = copy.deepcopy(entry)
    with pytest.raises(ValueError, match=f"English source drift for test-guid:{field}"):
        LOCALIZATION.apply_reader_text(entry, records)
    assert entry == before

    records["test-guid"]["content"][field]["en"] = "Effective reviewed source"
    LOCALIZATION.apply_reader_text(entry, records)
    assert entry[field] == {"en": "Effective reviewed source", "ko": "검토한 원문"}


@pytest.mark.parametrize(
    "name",
    [
        "Standard Load Balancer",
        "Application Gateway v2",
        "API Management Premium",
        "Azure Linux VM Agent",
        "Standard Virtual WAN",
        "Stream Analytics StandardV2",
        "VM Insights",
    ],
)
def test_official_product_name_labels_do_not_require_brand_translation(name: str) -> None:
    entry = {"recommendation_id": "test-guid", "label": {"en": name, "ko": name}}
    LOCALIZATION.assert_korean_reader_text([entry], {"test-guid"})
