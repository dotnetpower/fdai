"""Cross-check the Python pantheon against the YAML Agent ObjectType.

The `Agent` YAML declares the property shape the ontology exposes; the
Python pantheon declares the runtime instances. These two SHOULD agree
on the fields a fork can inspect. This test guards against silent
divergence between the ontology contract and the runtime instances.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from fdai.agents import PANTHEON_NAMES, PANTHEON_SPECS
from fdai.shared.contracts.models import LifecycleOwner

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENT_YAML = REPO_ROOT / "rule-catalog" / "vocabulary" / "object-types" / "Agent.yaml"
ACTION_TYPE_SCHEMA = (
    REPO_ROOT / "src" / "fdai" / "shared" / "contracts" / "ontology" / "action-type.json"
)


def _load_yaml() -> dict[str, Any]:
    with AGENT_YAML.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    if not isinstance(raw, dict):
        raise TypeError("Agent ontology declaration MUST be an object")
    return {str(key): value for key, value in raw.items()}


def test_agent_yaml_declares_expected_properties() -> None:
    # docs/roadmap/agents/agent-pantheon.md \u00a75 spells the property shape.
    doc = _load_yaml()
    assert doc["name"] == "Agent"
    props = doc["properties"]
    for expected in (
        "id",
        "layer",
        "reports_to",
        "owns",
        "executes",
        "initiates",
        "subscribes",
        "publishes",
        "question_domains",
        "owns_code_paths",
        "llm_bindings",
        "rate_limits",
        "enabled",
    ):
        assert expected in props, f"Agent.yaml missing property {expected!r}"


def test_pantheon_names_are_ascii_capitalized() -> None:
    for name in PANTHEON_NAMES:
        assert name.isascii(), f"{name!r} is not ASCII"
        assert name[0].isupper(), f"{name!r} is not capitalized"


def test_lifecycle_owner_contract_matches_pantheon() -> None:
    assert {owner.value for owner in LifecycleOwner} == set(PANTHEON_NAMES)


def test_every_agent_has_at_least_one_owned_type_or_is_governance_planner() -> None:
    # Odin owns ArbitrationDecision. Domain / pipeline agents own at
    # least one topic. Wave 1 asserts none is empty; if we later admit
    # advisory-only agents, revisit this test.
    for spec in PANTHEON_SPECS:
        assert len(spec.owns) >= 1, f"agent {spec.name!r} owns no ObjectType"


def test_action_roles_are_global_and_not_redeclared_by_action_types() -> None:
    owned_by_agent = {spec.name: set(spec.owns) for spec in PANTHEON_SPECS}
    assert "Verdict" in owned_by_agent["Forseti"]
    assert "Approval" in owned_by_agent["Var"]
    assert {"ActionRun", "ActionAttempt"} <= owned_by_agent["Thor"]
    assert "AuditEntry" in owned_by_agent["Saga"]
    assert "Rollback" in owned_by_agent["Vidar"]
    assert "Change" in owned_by_agent["Huginn"]

    schema = json.loads(ACTION_TYPE_SCHEMA.read_text(encoding="utf-8"))
    assert schema["additionalProperties"] is False
    properties = schema["properties"]
    assert not {"initiators", "judge", "approver", "executor", "auditor"} & properties.keys()
