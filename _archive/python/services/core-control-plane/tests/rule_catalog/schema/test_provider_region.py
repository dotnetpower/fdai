"""The reviewed provider-region vocabulary is complete, sorted, and closed."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from fdai.composition.semantic_query_value_domains import resource_location_value_domains
from fdai.rule_catalog.schema.provider_region import load_provider_region_registry_from_mapping
from pydantic import ValidationError

_ROOT = Path(__file__).resolve().parents[5]


def _shipped() -> dict[str, object]:
    path = _ROOT / "rule-catalog" / "vocabulary" / "provider-regions.yaml"
    return dict(yaml.safe_load(path.read_text(encoding="utf-8")))


def test_the_shipped_region_vocabulary_binds_resource_location() -> None:
    registry = load_provider_region_registry_from_mapping(_shipped())
    (domain,) = resource_location_value_domains(registry)

    assert (domain.object_type, domain.property_name) == ("Resource", "location")
    assert {"koreacentral", "eastus2", "global"} <= set(domain.values)
    # Each code carries its display name as context for the choosing model.
    names = {group.id: group.terms for group in domain.groups}
    assert names["koreacentral"] == ("Korea Central",)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda raw: raw["regions"].reverse(),
        lambda raw: raw["regions"].append(dict(raw["regions"][0])),
        lambda raw: raw["regions"][0].update(id="Korea Central"),
    ],
)
def test_an_unsorted_duplicate_or_malformed_region_is_rejected(mutate: object) -> None:
    raw = _shipped()
    raw["regions"] = [dict(item) for item in raw["regions"]]  # type: ignore[union-attr]
    mutate(raw)  # type: ignore[operator]

    with pytest.raises(ValidationError):
        load_provider_region_registry_from_mapping(raw)
