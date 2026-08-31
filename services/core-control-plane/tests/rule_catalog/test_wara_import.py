from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from scripts.catalog.import_wara_aprl import import_catalog


def _recommendation(*, state: str, guid: str) -> dict[str, object]:
    return {
        "description": f"{state} recommendation",
        "aprlGuid": guid,
        "recommendationTypeId": None,
        "recommendationControl": "HighAvailability",
        "recommendationImpact": "High",
        "recommendationResourceType": "Microsoft.Example/widgets",
        "recommendationMetadataState": state,
        "longDescription": f"{state} recommendation details.",
        "potentialBenefits": "Improved availability",
        "pgVerified": True,
        "automationAvailable": state == "Active",
        "tags": [],
        "learnMoreLink": [
            {
                "name": "Learn more",
                "url": "https://learn.microsoft.com/azure/example",
            }
        ],
    }


def test_importer_retains_disabled_and_matches_published_active_set(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "aprl"
    source = source_root / "azure-resources/Example/widgets/recommendations.yaml"
    source.parent.mkdir(parents=True)
    active = _recommendation(
        state="Active",
        guid="00000000-0000-0000-0000-000000000001",
    )
    disabled = _recommendation(
        state="Disabled",
        guid="00000000-0000-0000-0000-000000000002",
    )
    source.write_text(
        yaml.safe_dump([active, disabled], sort_keys=False),
        encoding="utf-8",
    )
    published = tmp_path / "recommendations.json"
    published_item = {**active, "query": "resources | limit 1"}
    published.write_text(json.dumps([published_item]), encoding="utf-8")

    catalog = import_catalog(source_root, published)

    assert catalog["inventory"]["total_controls"] == 2
    assert catalog["inventory"]["active_controls"] == 1
    assert catalog["inventory"]["disabled_controls"] == 1
    controls = catalog["areas"][0]["controls"]
    assert controls[0]["wara"]["query_digest"].startswith("sha256:")
    assert controls[1]["wara"]["query_digest"] is None
    assert "2 APRL recommendations from 1 source files" in catalog["completeness_scope"]


def test_importer_rejects_empty_recommendation_file(tmp_path: Path) -> None:
    source_root = tmp_path / "aprl"
    source = source_root / "azure-resources/Example/widgets/recommendations.yaml"
    source.parent.mkdir(parents=True)
    source.write_text("[]\n", encoding="utf-8")
    published = tmp_path / "recommendations.json"
    published.write_text("[]\n", encoding="utf-8")

    with pytest.raises(ValueError, match="at least one recommendation"):
        import_catalog(source_root, published)
