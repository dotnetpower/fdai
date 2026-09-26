"""Exact definition coverage for pinned WAF architecture-review pillars."""

from __future__ import annotations

from dataclasses import fields
from pathlib import Path

import pytest
import yaml
from fdai.core.architecture_review import pillar_coverage
from fdai.rule_catalog.schema.best_practice_catalog import load_best_practice_catalog
from fdai.rule_catalog.schema.framework_assessment import (
    FrameworkAssessmentCatalog,
    load_framework_assessment_catalog,
)
from fdai.rule_catalog.schema.framework_catalog import FrameworkDefinition
from fdai.shared.contracts.models import BestPractice

_ROOT = Path(__file__).resolve().parents[5]
_CATALOG_ROOT = _ROOT / "rule-catalog"


def _sources() -> tuple[FrameworkAssessmentCatalog, FrameworkDefinition, tuple[BestPractice, ...]]:
    catalog = load_framework_assessment_catalog(
        _CATALOG_ROOT / "framework-assessments/generated/azure-waf.json"
    )
    framework = FrameworkDefinition.model_validate(
        yaml.safe_load((_CATALOG_ROOT / "frameworks/azure-waf.yaml").read_text(encoding="utf-8"))
    )
    practices = load_best_practice_catalog(_CATALOG_ROOT / "best-practices", strict=False)
    return catalog, framework, practices


def test_pinned_catalog_accounts_for_every_control_and_evidence_definition() -> None:
    report = pillar_coverage.load_pillar_definition_coverage(_ROOT)
    by_pillar = {item.pillar: item for item in report.pillars}

    assert (report.control_count, report.evidence_count) == (59, 186)
    assert {
        name: (item.control_count, item.evidence_count) for name, item in by_pillar.items()
    } == {
        "reliability": (10, 39),
        "security": (12, 51),
        "cost-optimization": (14, 32),
        "operational-excellence": (11, 32),
        "performance-efficiency": (12, 32),
    }
    assert all(
        len(set(item.control_ids)) == item.control_count
        and len(set(item.evidence_keys)) == item.evidence_count
        for item in report.pillars
    )
    assert {field.name for field in fields(report)} == {
        "catalog_digest",
        "framework_definition_digest",
        "pillars",
    }
    assert {field.name for field in fields(report.pillars[0])} == {
        "pillar",
        "control_ids",
        "evidence_keys",
    }


def test_missing_duplicate_or_unsupported_control_fails_closed() -> None:
    catalog, framework, practices = _sources()
    first, second, *remaining = catalog.controls
    invalid = (
        (catalog.model_copy(update={"controls": (first, *remaining)}), "complete and uniquely"),
        (
            catalog.model_copy(update={"controls": (first, first, *remaining)}),
            "complete and uniquely",
        ),
        (
            catalog.model_copy(
                update={
                    "controls": (first.model_copy(update={"area": "unknown"}), second, *remaining)
                }
            ),
            "missing, misplaced, or unsupported",
        ),
        (
            catalog.model_copy(
                update={
                    "controls": (
                        first,
                        second.model_copy(update={"area": "reliability"}),
                        *remaining,
                    )
                }
            ),
            "missing, misplaced, or unsupported",
        ),
    )
    for malformed, message in invalid:
        with pytest.raises(ValueError, match=message):
            pillar_coverage.assess_pillar_definition_coverage(
                malformed, framework=framework, practices=practices
            )


def test_missing_duplicate_or_mismatched_evidence_fails_closed() -> None:
    catalog, framework, practices = _sources()
    control = catalog.controls[0]
    first, second, *remaining = control.evidence
    invalid = (
        control.model_copy(update={"evidence": (first, *remaining)}),
        control.model_copy(
            update={
                "evidence": (
                    first,
                    second.model_copy(update={"requirement_id": first.requirement_id}),
                    *remaining,
                )
            }
        ),
        control.model_copy(
            update={
                "evidence": (
                    first,
                    second.model_copy(update={"source_ref": first.source_ref, "kind": first.kind}),
                    *remaining,
                )
            }
        ),
        control.model_copy(
            update={
                "evidence": (
                    first.model_copy(update={"requirement_id": "artifact:wrong"}),
                    second,
                    *remaining,
                )
            }
        ),
        control.model_copy(
            update={
                "evidence": (
                    first.model_copy(update={"scope_contract": "exact-estate"}),
                    second,
                    *remaining,
                )
            }
        ),
        control.model_copy(
            update={
                "evidence": (
                    first,
                    second.model_copy(update={"freshness_ceiling_seconds": 86_400}),
                    *remaining,
                )
            }
        ),
        control.model_copy(update={"owner_slot": "wrong-owner"}),
    )
    for malformed_control in invalid:
        malformed = catalog.model_copy(
            update={"controls": (malformed_control, *catalog.controls[1:])}
        )
        with pytest.raises(ValueError, match="missing or ambiguous evidence definitions"):
            pillar_coverage.assess_pillar_definition_coverage(
                malformed, framework=framework, practices=practices
            )


def test_crosswalk_and_source_definition_drift_fail_closed() -> None:
    catalog, framework, practices = _sources()
    control = catalog.controls[0]
    invalid = catalog.model_copy(
        update={
            "controls": (
                control.model_copy(update={"crosswalk": control.crosswalk[1:]}),
                *catalog.controls[1:],
            )
        }
    )
    with pytest.raises(ValueError, match="ambiguous WAF crosswalk"):
        pillar_coverage.assess_pillar_definition_coverage(
            invalid, framework=framework, practices=practices
        )

    changed = next(item for item in practices if item.control_id == control.control_id)
    changed = changed.model_copy(update={"requirements": changed.requirements[1:]})
    with pytest.raises(ValueError, match="missing or ambiguous evidence"):
        pillar_coverage.assess_pillar_definition_coverage(
            catalog,
            framework=framework,
            practices=tuple(
                changed if item.control_id == control.control_id else item for item in practices
            ),
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("framework_definition_digest", "sha256:" + "0" * 64),
        ("source_revision_digest", "sha256:" + "0" * 64),
        ("framework_version", "2025-01-01"),
    ],
)
def test_stale_catalog_identity_is_rejected(
    monkeypatch: pytest.MonkeyPatch, field: str, value: str
) -> None:
    catalog, _, _ = _sources()
    monkeypatch.setattr(
        pillar_coverage,
        "load_framework_assessment_catalog",
        lambda path: catalog.model_copy(update={field: value}),
    )
    with pytest.raises(ValueError, match="identity differs"):
        pillar_coverage.load_pillar_definition_coverage(_ROOT)


def test_other_framework_or_unsupported_pillar_is_not_waf_coverage() -> None:
    catalog, framework, practices = _sources()
    with pytest.raises(ValueError, match="pinned WAF assessment identity"):
        pillar_coverage.assess_pillar_definition_coverage(
            catalog.model_copy(update={"framework_id": "azure-caf"}),
            framework=framework,
            practices=practices,
        )
    with pytest.raises(ValueError, match="missing or unsupported pillar"):
        pillar_coverage.assess_pillar_definition_coverage(
            catalog,
            framework=framework.model_copy(
                update={
                    "areas": (
                        framework.areas[0].model_copy(update={"id": "unknown"}),
                        *framework.areas[1:],
                    )
                }
            ),
            practices=practices,
        )
