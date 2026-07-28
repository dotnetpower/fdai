"""Best-practice checklist schema and loader tests."""

from __future__ import annotations

from copy import deepcopy

import pytest

from fdai.rule_catalog.schema.best_practice_loader import (
    BestPracticeLoadError,
    load_best_practice_from_mapping,
)
from fdai.shared.contracts.models import RequirementKind, RequirementMode


def _valid() -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "kind": "best-practice",
        "id": "azure-waf.reliability.re-09",
        "version": "1.0.0",
        "framework": "azure-waf",
        "control_id": "RE:09",
        "title": "Test disaster recovery",
        "rationale": "Recovery evidence must demonstrate that approved objectives are met.",
        "severity": "high",
        "category": "reliability",
        "requirements": [
            {"kind": "artifact", "ref": "disaster-recovery-plan", "freshness_days": 180},
            {"kind": "drill", "ref": "restore-failover-drill", "freshness_days": 180},
            {"kind": "approval", "ref": "reliability-owner"},
        ],
        "provenance": {
            "source_url": "https://learn.microsoft.com/azure/well-architected/reliability/checklist",
            "source_version": "2026-05-29",
            "resolved_ref": "example-revision",
            "content_hash": "sha256:example",
            "license": "CC-BY-4.0",
            "redistribution": "embeddable",
            "retrieved_at": "2026-07-29T00:00:00Z",
            "mapped_by": "catalog-team",
        },
    }


def test_loads_typed_best_practice() -> None:
    control = load_best_practice_from_mapping(_valid())

    assert control.control_id == "RE:09"
    assert control.requirement_mode is RequirementMode.ALL
    assert control.requirements[1].kind is RequirementKind.DRILL
    assert control.requirements[1].freshness_days == 180


def test_rejects_unknown_fields_and_invalid_freshness() -> None:
    raw = _valid()
    raw["unexpected"] = True
    requirements = raw["requirements"]
    assert isinstance(requirements, list)
    requirements[0]["freshness_days"] = 0

    with pytest.raises(BestPracticeLoadError) as error:
        load_best_practice_from_mapping(raw)

    keys = {issue.key for issue in error.value.issues}
    assert "<root>" in keys
    assert "requirements/0/freshness_days" in keys


def test_rejects_duplicate_requirement_references() -> None:
    raw = deepcopy(_valid())
    requirements = raw["requirements"]
    assert isinstance(requirements, list)
    requirements.append(dict(requirements[0]))

    with pytest.raises(BestPracticeLoadError, match="duplicate references"):
        load_best_practice_from_mapping(raw)
