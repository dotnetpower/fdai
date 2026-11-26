import pytest
from fdai_operator_service.control_remediation_projection import (
    control_detail_revision,
    control_remediation,
)


def _catalog() -> dict[str, object]:
    return {
        "_revision": "rules:example",
        "details": {
            "active:example.rule": {
                "id": "example.rule",
                "origin": "active",
                "version": "1.0.0",
                "remediates": "example.fix",
            }
        },
    }


def test_exact_active_rule_binding_is_only_a_governed_candidate() -> None:
    projected = control_remediation(
        {"requirements": [{"kind": "rule", "ref": "example.rule"}]}, _catalog()
    )
    assert projected == {
        "status": "governed_candidates",
        "candidates": [{"rule_id": "example.rule", "action_type_ref": "example.fix"}],
        "limitations": ["rule_activation_runtime_support_and_safety_gates_required"],
        "execution_authority": False,
    }


@pytest.mark.parametrize(
    "detail",
    [
        {"requirements": [{"kind": "artifact", "ref": "example.rule"}]},
        {"crosswalk": [{"target_kind": "rule", "target_ref": "example.rule"}]},
        {"title": "Enable example.rule"},
    ],
)
def test_prose_and_crosswalk_neighbors_cannot_create_action_candidates(
    detail: dict[str, object],
) -> None:
    projected = control_remediation(detail, _catalog())
    assert projected["status"] == "manual_guidance"
    assert projected["candidates"] == []


def test_missing_rule_source_is_explicitly_unavailable() -> None:
    projected = control_remediation({"rule_ids": ["example.rule"]}, None)
    assert projected["status"] == "unavailable"
    assert projected["limitations"] == ["authoritative_rule_details_unavailable"]


def test_collected_rule_cannot_become_a_governed_candidate() -> None:
    projected = control_remediation(
        {"rule_ids": ["example.rule"]},
        {"_revision": "rules:example", "details": {"collected:example.rule": {}}},
    )
    assert projected["status"] == "unavailable"
    assert projected["candidates"] == []
    assert "rule_not_in_active_catalog" in projected["limitations"]


def test_wara_exact_rule_revision_is_preserved() -> None:
    projected = control_remediation(
        {"rule_ids": ["example.rule"], "rule_versions": {"example.rule": "2.0.0"}}, _catalog()
    )
    assert projected["candidates"] == []
    assert "rule_revision_drift" in projected["limitations"]


def test_detail_revision_changes_with_guidance_and_rule_source() -> None:
    detail = {"guidance": {"content_digest": "sha256:" + "1" * 64}}
    initial = control_detail_revision("catalog:example", detail, "rules:example")
    assert initial != control_detail_revision("catalog:example", detail, "rules:changed")
    assert initial != control_detail_revision(
        "catalog:example",
        {"guidance": {"content_digest": "sha256:" + "2" * 64}},
        "rules:example",
    )
