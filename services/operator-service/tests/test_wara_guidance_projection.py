"""Guidance is detail-only public reference, not mutable assessment data."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fdai_operator_service.families.workflow.contracts import (
    WorkflowOperation,
    WorkflowReadRequest,
)
from fdai_operator_service.family_adapters import PostgresWorkflowAdapters
from fdai_operator_service.postgres_family_store import PostgresFamilyStore
from fdai_operator_service.workflow_framework_projection import _wara_catalog_payload
from fdai_service_contracts.catalog_canonical import canonical_digest
from fdai_service_contracts.wara_guidance import load_wara_guidance, packaged_wara_guidance
from starlette.exceptions import HTTPException


def _request(operation, recommendation_id="", **query):
    return WorkflowReadRequest(
        operation=operation,
        principal_id="reader-example",
        path_parameters={"recommendation_id": recommendation_id},
        query=query,
    )


def _stored():
    catalog = packaged_wara_guidance()
    controls = [
        {
            "id": guide.recommendation_id,
            "title": guide.title.en,
            "source_revision": guide.source_revision,
            "source_digest": guide.source_digest,
            "lifecycle": guide.lifecycle,
            "resource_type": "test-provider/type",
            "recommendation_control": "HighAvailability",
            "impact": "Medium",
            "product_group_verified": False,
            "automation_available": False,
            "satisfaction": "unknown",
            "evaluation_status": "not_evaluated",
            "execution_authority": False,
        }
        for guide in catalog.entries
    ]
    return {
        "controls": controls,
        "inventory": {
            "active_recommendations": 393,
            "disabled_recommendations": 63,
            "resource_types": 80,
            "automated_recommendations": 143,
            "manual_recommendations": 250,
        },
        "evaluation_source": "not_connected",
        "source_revision": catalog.framework_revision,
        "crosswalk_digest": "sha256:" + "a" * 64,
    }


def test_list_does_not_embed_the_illustrated_corpus() -> None:
    stored = _stored()
    response = _wara_catalog_payload(stored, _request(WorkflowOperation.WARA_LIST))
    assert response["total"] == 456
    assert all("guidance" not in item for item in response["controls"])
    assert len(response["controls"]) <= 100


def test_exact_detail_outside_search_filter_keeps_source_and_assessment_independent() -> None:
    stored = _stored()
    framework = json.loads(
        (
            Path(__file__).resolve().parents[3] / "rule-catalog/collected/wara-aprl/azure-wara.json"
        ).read_text()
    )
    identity = next(
        control["id"]
        for area in framework["areas"]
        for control in area["controls"]
        if control["title"].startswith("Use maintenance configurations for the Dedicated")
    )
    selected = next(row for row in stored["controls"] if row["id"] == identity)
    before = deepcopy(stored)
    response = _wara_catalog_payload(
        stored, _request(WorkflowOperation.WARA_DETAIL, selected["id"], q="dns")
    )
    assert response["id"] == selected["id"]
    assert response["guidance"]["recommendation_id"] == selected["id"]
    assert response["satisfaction"] == "unknown"
    assert response["execution_authority"] is False
    assert response["guidance"]["diagram"]["nodes"]
    assert stored == before


@pytest.mark.parametrize("field", ["source_revision", "source_digest", "lifecycle"])
def test_stale_catalog_record_cannot_display_a_different_source_guide(field) -> None:
    stored = _stored()
    selected = stored["controls"][0]
    selected[field] = "different-source"
    with pytest.raises(HTTPException) as error:
        _wara_catalog_payload(stored, _request(WorkflowOperation.WARA_DETAIL, selected["id"]))
    assert error.value.status_code == 503
    assert error.value.detail == "WARA guidance source validation failed"


def test_unknown_selected_identity_is_still_404() -> None:
    with pytest.raises(HTTPException) as error:
        _wara_catalog_payload(_stored(), _request(WorkflowOperation.WARA_DETAIL, "unknown"))
    assert error.value.status_code == 404


async def test_detail_revision_changes_with_public_guidance_without_changing_assessment() -> None:
    stored = _stored()
    stored["_revision"] = "catalog-revision-example"
    selected = stored["controls"][0]
    request = _request(WorkflowOperation.WARA_DETAIL, selected["id"])
    store = Mock(spec=PostgresFamilyStore)
    store.read_projection = AsyncMock(return_value=stored)
    adapter = PostgresWorkflowAdapters(store=store)
    first = await adapter.read(request)
    material = packaged_wara_guidance().model_dump(mode="json", by_alias=True, exclude_none=True)
    guide = material["entries"][0]
    guide["rationale"]["en"] += " The public explanation has a new reviewed revision."
    guide["content_digest"] = "sha256:" + canonical_digest(
        {key: value for key, value in guide.items() if key != "content_digest"}
    )
    material["catalog_digest"] = "sha256:" + canonical_digest(
        {key: value for key, value in material.items() if key != "catalog_digest"}
    )
    updated = load_wara_guidance(json.dumps(material).encode())
    with patch("fdai_service_contracts.wara_guidance.packaged_wara_guidance", return_value=updated):
        second = await adapter.read(request)
    assert first.provenance.revision != second.provenance.revision
    assert first.payload["satisfaction"] == second.payload["satisfaction"] == "unknown"
    assert first.payload["execution_authority"] is second.payload["execution_authority"] is False


async def test_guidance_digest_cannot_hide_a_missing_authoritative_catalog_revision() -> None:
    stored = _stored()
    store = Mock(spec=PostgresFamilyStore)
    store.read_projection = AsyncMock(return_value=stored)
    with pytest.raises(HTTPException) as error:
        await PostgresWorkflowAdapters(store=store).read(
            _request(WorkflowOperation.WARA_DETAIL, stored["controls"][0]["id"])
        )
    assert error.value.status_code == 503
    assert error.value.detail == "authoritative workflow projection has no revision"
