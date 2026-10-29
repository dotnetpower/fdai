from __future__ import annotations

import base64
import copy
import importlib.util
import json
from pathlib import Path

import pytest
from fdai.rule_catalog.schema.wara_assessment import (
    canonical_digest,
    load_wara_assessment_catalog,
)

ROOT = Path(__file__).resolve().parents[4]
ASSESSMENT = ROOT / "rule-catalog/collected/wara-aprl/assessment"
FRAMEWORK = ROOT / "rule-catalog/collected/wara-aprl/azure-wara.json"


def _generator():
    spec = importlib.util.spec_from_file_location(
        "build_wara_assessment", ROOT / "scripts/catalog/build_wara_assessment.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _published_snapshot() -> list[dict]:
    framework = json.loads(FRAMEWORK.read_text())
    queries = json.loads((ASSESSMENT / "queries.json").read_text())
    bodies = {
        body["aprl_guid"]: base64.b64decode(body["body_base64"]).decode()
        for body in queries["queries"] + queries["reference_queries"]
    }
    published = []
    for area in framework["areas"]:
        for control in area["controls"]:
            metadata = control["wara"]
            if metadata["state"] != "Active":
                continue
            published.append(
                {
                    "aprlGuid": control["id"],
                    "recommendationTypeId": metadata["recommendation_type_id"],
                    "recommendationControl": metadata["control"],
                    "recommendationImpact": metadata["impact"],
                    "recommendationResourceType": metadata["resource_type"],
                    "recommendationMetadataState": metadata["state"],
                    "pgVerified": metadata["product_group_verified"],
                    "automationAvailable": metadata["automation_available"],
                    "description": control["title"],
                    "longDescription": control["description"],
                    "potentialBenefits": metadata["potential_benefits"],
                    "tags": metadata["tags"],
                    "learnMoreLink": (
                        [{"name": metadata["learn_more_name"], "url": metadata["learn_more_url"]}]
                        if metadata["learn_more_name"] is not None
                        else []
                    ),
                    "query": bodies.get(control["id"]),
                }
            )
    return published


def _build_snapshot(snapshot: list[dict], tmp_path: Path):
    module = _generator()
    text = json.dumps(snapshot)
    path = tmp_path / "published.json"
    path.write_text(text)
    return module.build_catalog(
        FRAMEWORK,
        path,
        ROOT / "rule-catalog/vocabulary/resource-types.yaml",
        ROOT / "rule-catalog/sources/registry.yaml",
        published_object_digest=module._sha256_text(text),
    )


def test_generator_rebuilds_complete_source_partition_from_a_separate_byte_pin(
    tmp_path: Path,
) -> None:
    crosswalk, queries = _build_snapshot(_published_snapshot(), tmp_path)
    assert len(queries["queries"]) == 143
    assert len(queries["reference_queries"]) == 229
    assert len(queries["null_query_guids"]) == 21
    assert sum(record["automation_available"] for record in crosswalk["recommendations"]) == 143
    assert all(
        record["query_review"] is None
        for record in crosswalk["recommendations"]
        if not record["automation_available"]
    )
    assert crosswalk["published_active_digest"] != crosswalk["published_object_digest"]
    assert crosswalk["published_object_digest"] == queries["published_object_digest"]


@pytest.mark.parametrize("query_state", ["body", "null"])
def test_generator_checks_manual_source_digests_even_with_an_explicit_snapshot_pin(
    tmp_path: Path, query_state: str
) -> None:
    snapshot = _published_snapshot()
    manual = next(
        item
        for item in snapshot
        if not item["automationAvailable"] and (item["query"] is None) == (query_state == "null")
    )
    manual["query"] = "resources | project id"
    with pytest.raises(ValueError, match="query digest drift"):
        _build_snapshot(snapshot, tmp_path)


def test_generator_preserves_every_manual_source_without_execution_admission() -> None:
    _, queries = load_wara_assessment_catalog(
        ASSESSMENT / "crosswalk.json", ASSESSMENT / "queries.json"
    )
    framework = json.loads(FRAMEWORK.read_text())
    manual = {
        control["id"]: control["wara"]["query_digest"]
        for area in framework["areas"]
        for control in area["controls"]
        if control["wara"]["state"] == "Active" and not control["wara"]["automation_available"]
    }
    references = {body.aprl_guid: body for body in queries.reference_queries}
    assert {guid for guid, digest in manual.items() if digest is not None} == set(references)
    assert {guid for guid, digest in manual.items() if digest is None} == set(
        queries.null_query_guids
    )
    assert all(body.body_digest == manual[guid] for guid, body in references.items())
    assert not set(references) & {body.aprl_guid for body in queries.queries}
    assert (
        sum(
            any(
                line.strip() and not line.lstrip().startswith("//")
                for line in body.decoded_body().splitlines()
            )
            for body in references.values()
        )
        == 19
    )


@pytest.mark.parametrize("change", ["missing", "duplicate", "automated", "null_overlap"])
def test_reference_inventory_cannot_be_omitted_duplicated_or_executed(
    tmp_path: Path, change: str
) -> None:
    crosswalk = json.loads((ASSESSMENT / "crosswalk.json").read_text())
    queries = json.loads((ASSESSMENT / "queries.json").read_text())
    reference = queries["reference_queries"][0]
    if change == "missing":
        queries["reference_queries"].pop()
    elif change == "duplicate":
        queries["reference_queries"].append(reference)
    elif change == "automated":
        queries["queries"].append(queries["reference_queries"].pop())
    else:
        queries["null_query_guids"].append(reference["aprl_guid"])
    queries["queries_digest"] = canonical_digest(
        {key: value for key, value in queries.items() if key != "queries_digest"}
    )
    crosswalk["queries_digest"] = queries["queries_digest"]
    crosswalk["crosswalk_digest"] = canonical_digest(
        {key: value for key, value in crosswalk.items() if key != "crosswalk_digest"}
    )
    (tmp_path / "crosswalk.json").write_text(json.dumps(crosswalk))
    (tmp_path / "queries.json").write_text(json.dumps(queries))
    with pytest.raises(ValueError, match="partition|unique|exactly cover"):
        load_wara_assessment_catalog(tmp_path / "crosswalk.json", tmp_path / "queries.json")


def test_generator_requires_an_exact_published_object_pin(tmp_path: Path) -> None:
    path = tmp_path / "published.json"
    path.write_text("[]")
    with pytest.raises(ValueError, match="published WARA object digest"):
        _generator().build_catalog(
            FRAMEWORK,
            path,
            ROOT / "rule-catalog/vocabulary/resource-types.yaml",
            ROOT / "rule-catalog/sources/registry.yaml",
        )


def test_public_snapshot_metadata_drift_is_not_accepted_under_a_new_byte_pin() -> None:
    control = json.loads(FRAMEWORK.read_text())["areas"][0]["controls"][0]
    metadata = control["wara"]
    published = {
        "recommendationTypeId": metadata["recommendation_type_id"],
        "recommendationControl": metadata["control"],
        "recommendationImpact": metadata["impact"],
        "recommendationResourceType": metadata["resource_type"],
        "recommendationMetadataState": metadata["state"],
        "pgVerified": metadata["product_group_verified"],
        "automationAvailable": metadata["automation_available"],
        "description": control["title"],
        "longDescription": control["description"],
        "potentialBenefits": metadata["potential_benefits"],
        "tags": metadata["tags"],
        "learnMoreLink": [{"name": metadata["learn_more_name"], "url": metadata["learn_more_url"]}],
    }
    _generator()._validate_published_item(control, published)
    changed = copy.deepcopy(published)
    changed["automationAvailable"] = not published["automationAvailable"]
    with pytest.raises(ValueError, match="field drift"):
        _generator()._validate_published_item(control, changed)
