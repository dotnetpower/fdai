from __future__ import annotations

from fdai.core.operational_planning import operational_planning_capability_status


def _status(**overrides: bool):
    values = {
        "ontology_release_available": True,
        "operational_context_available": True,
        "process_store_available": True,
        "effect_model_reader_available": True,
        "causal_verifier_available": True,
        "enabled": True,
    }
    values.update(overrides)
    return operational_planning_capability_status(**values)


def test_planning_status_requires_every_evidence_binding() -> None:
    status = _status(
        operational_context_available=False,
        causal_verifier_available=False,
    )

    assert status.available is False
    assert status.can_plan is False
    assert status.unavailable_reason == "missing planning prerequisites"
    assert status.missing_requirements == (
        "operational_context",
        "causal_evidence_verifier",
    )
    assert status.to_mapping()["mode"] == "shadow"


def test_planning_status_is_shadow_only_when_available() -> None:
    status = _status()

    assert status.available is True
    assert status.enabled is True
    assert status.can_plan is True
    assert status.unavailable_reason is None
    assert status.missing_requirements == ()


def test_disabled_pantheon_keeps_planning_unavailable() -> None:
    status = _status(enabled=False)

    assert status.available is True
    assert status.can_plan is False
    assert status.unavailable_reason == "pantheon runtime disabled"
