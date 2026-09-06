"""Existing-deployment adoption preserves T1, independent review, and source evidence."""

from __future__ import annotations

import copy
import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fdai.composition.semantic_query_model_targets import t1_model_targets, t2_model_targets
from fdai.rule_catalog.schema.llm_resolver import ResolvedModels

_PATH = Path(__file__).resolve().parents[3] / "scripts/deployment/local/bind-existing-model.py"
_SPEC = importlib.util.spec_from_file_location("bind_existing_model", _PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
_NOW = datetime(2026, 9, 6, tzinfo=UTC)
_ID = (
    "/subscriptions/00000000-0000-0000-0000-000000000001/"
    "resourceGroups/rg-example/providers/Microsoft.CognitiveServices/accounts/example"
)


def _original():
    return {
        "schema_version": "1.0.0",
        "region": "exampleregion",
        "subscription_id": "example",
        "deployer_object_id": "example",
        "mixed_model_mode": "hil-only",
        "capabilities": [
            {
                "name": "t1.judge",
                "status": "resolved",
                "publisher": "OpenAI",
                "family": "small",
                "sku": "GlobalStandard",
                "capacity_tpm": 10000,
                "invocation": "always",
            },
            {
                "name": "t2.reasoner.primary",
                "status": "resolved",
                "publisher": "OpenAI",
                "family": "previous",
                "sku": "GlobalStandard",
                "capacity_tpm": 10000,
                "invocation": "on_novel_case",
            },
            {
                "name": "t2.reasoner.secondary",
                "status": "hil-only",
                "publisher": None,
                "family": None,
                "sku": None,
                "capacity_tpm": 0,
                "invocation": "always",
            },
        ],
        "narrator": {
            "endpoint": "https://models.example.com",
            "deployment": "small",
            "api_version": "2024-12-01-preview",
        },
        "endpoint_bindings": [],
    }


def _evidence():
    return {
        "observed_at": _NOW.isoformat(),
        "account": {
            "id": _ID,
            "name": "example",
            "properties": {"endpoint": "https://models.example.com/"},
        },
        "deployments": [
            {
                "id": _ID + "/deployments/existing-large",
                "name": "existing-large",
                "sku": {"name": "GlobalStandard", "capacity": 50},
                "properties": {
                    "provisioningState": "Succeeded",
                    "model": {"format": "OpenAI", "name": "large-example", "version": "1"},
                },
            }
        ],
    }


def test_binds_existing_t2_without_changing_t1_or_claiming_reviewer_readiness():
    import json

    original = _original()
    before = copy.deepcopy(original)
    result = _MODULE.bind_existing_model(
        original,
        _evidence(),
        family="large-example",
        now=_NOW,
    )
    assert original == before
    assert result["capabilities"][0] == before["capabilities"][0]
    assert result["capabilities"][2] == before["capabilities"][2]
    assert result["mixed_model_mode"] == "hil-only"
    assert result["narrator"] == original["narrator"]
    binding = result["endpoint_bindings"][0]
    assert binding["model"]["family"] == "large-example"
    assert binding["features"]["tool_calling"] is False
    assert binding["features"]["structured_output"] is False
    resolved = ResolvedModels.from_json(json.dumps(result))
    assert not resolved.reasoner_primary_candidates
    assert (
        t1_model_targets(resolved, endpoint=None, endpoint_resolver=None)[0].deployment == "small"
    )
    assert (
        t2_model_targets(
            resolved,
            endpoint=None,
            endpoint_resolver=lambda _: "https://models.example.com",
        )[0].deployment
        == "existing-large"
    )


@pytest.mark.parametrize("age", [-1, 301])
def test_refuses_stale_or_future_evidence(age):
    evidence = _evidence()
    evidence["observed_at"] = (_NOW - timedelta(seconds=age)).isoformat()
    with pytest.raises(ValueError, match="current"):
        _MODULE.bind_existing_model(_original(), evidence, family="large-example", now=_NOW)


def test_binding_cannot_collapse_an_existing_mixed_publisher_pair():
    original = _original()
    original["capabilities"][2].update(status="resolved", publisher="OpenAI")
    with pytest.raises(ValueError, match="distinct-publisher"):
        _MODULE.bind_existing_model(original, _evidence(), family="large-example", now=_NOW)


@pytest.mark.parametrize("failure", ["scope", "endpoint", "ambiguous", "failed", "capacity"])
def test_refuses_unverified_deployments(failure):
    evidence = _evidence()
    if failure == "scope":
        evidence["deployments"][0]["id"] = "/different/account/deployments/model"
    elif failure == "endpoint":
        evidence["account"]["properties"]["endpoint"] = "https://different.example.com"
    elif failure == "ambiguous":
        evidence["deployments"] *= 2
    elif failure == "failed":
        evidence["deployments"][0]["properties"]["provisioningState"] = "Failed"
    else:
        evidence["deployments"][0]["sku"]["capacity"] = 0
    with pytest.raises(ValueError):
        _MODULE.bind_existing_model(_original(), evidence, family="large-example", now=_NOW)
