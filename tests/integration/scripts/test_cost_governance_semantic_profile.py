from __future__ import annotations

import importlib.util
from copy import deepcopy
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
CHECKER_PATH = REPO_ROOT / "scripts/quality/architecture/check-cost-governance-semantic-profile.py"


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "check_cost_governance_semantic_profile",
        CHECKER_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def checker() -> ModuleType:
    return _load_module()


def test_repository_profile_and_f1_f8_corpus_are_valid(checker: ModuleType) -> None:
    assert checker.validate_repository() == {
        "ontology_release_digest": (
            "sha256:f422fe77b8c56129b037cec69a98f770c7e455d5cf3f46661051f27a75e4ed71"
        ),
        "semantic_profile_sha256": (
            "sha256:b44935a987f974e65429448e38fc4f780ce81f0f2d8acda5160ad1dd756701c0"
        ),
        "fixtures": 16,
        "positive": 8,
        "lowered": 8,
    }


def test_each_negative_case_lowers_exactly_one_semantic_defect(
    checker: ModuleType,
) -> None:
    profile = checker.load_profile()
    catalog = checker._load_catalog()
    link_endpoints = {
        item.name: (item.from_type, item.to_type)
        for item in catalog.link_types
        if item.name in checker.EXPECTED_LINKS
    }
    negatives = {
        fixture["fixture_id"]: checker.evaluate_fixture(
            fixture,
            profile,
            link_endpoints=link_endpoints,
        )
        for fixture in checker.load_fixtures()
        if fixture["case"] == "negative"
    }

    assert negatives == {
        fixture_id: {
            "autonomy_ceiling": "shadow_only",
            "reason_codes": [reason],
        }
        for fixture_id, reason in checker.NEGATIVE_REASON_BY_FIXTURE.items()
    }


def test_profile_content_mutation_invalidates_canonical_identity(
    checker: ModuleType,
) -> None:
    profile = deepcopy(checker.load_profile())
    profile["competency_gates"][0]["question"] += " "

    with pytest.raises(
        checker.SemanticProfileError,
        match="canonical_sha256 does not match canonical content",
    ):
        checker.validate_profile_data(profile)


@pytest.mark.parametrize(
    "authority_field",
    ["approval_authority", "execution_authority", "promotion_authority"],
)
def test_profile_cannot_grant_authority(
    checker: ModuleType,
    authority_field: str,
) -> None:
    profile = deepcopy(checker.load_profile())
    profile["safety"][authority_field] = True
    profile["canonical_sha256"] = checker.profile_content_sha256(profile)

    with pytest.raises(checker.SemanticProfileError, match=authority_field):
        checker.validate_profile_data(profile)


def test_cost_governance_types_preserve_existing_agent_ownership(
    checker: ModuleType,
) -> None:
    catalog = checker._load_catalog()
    owners = {
        item.name: item.lifecycle.owner.value
        for item in catalog.object_types
        if item.name
        in {
            "Budget",
            "CapacityForecast",
            "CostAnomaly",
            "CostObservation",
            "SizingRecommendation",
        }
    }

    assert owners == {
        "Budget": "Njord",
        "CapacityForecast": "Freyr",
        "CostAnomaly": "Njord",
        "CostObservation": "Njord",
        "SizingRecommendation": "Freyr",
    }
