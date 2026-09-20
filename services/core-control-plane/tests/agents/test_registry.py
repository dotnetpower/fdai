"""Pantheon registry hard invariants.

These tests enforce contracts declared in `docs/roadmap/agents/agent-pantheon.md`.
Any change here MUST reflect a corresponding doc change (docs-first).
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest
from fdai.agents import (
    HARD_DEPENDENCY_AGENTS,
    LLM_HOT_PATH_ALLOWLIST,
    PANTHEON_NAMES,
    PANTHEON_SPECS,
    load_pantheon,
)
from fdai.agents._framework.registry import PantheonRegistryError
from fdai.rule_catalog.schema.action_type import load_action_type_catalog
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry

_REPO_ROOT = Path(__file__).resolve().parents[4]
_AGENTS_ROOT = _REPO_ROOT / "services/core-control-plane/src/fdai/agents"


def _producer_topics() -> set[str]:
    topics: set[str] = set()
    for path in _AGENTS_ROOT.rglob("*.py"):
        relative = path.relative_to(_REPO_ROOT / "services/core-control-plane/src")
        module_name = ".".join(relative.with_suffix("").parts)
        module = importlib.import_module(module_name)
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for function in (
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        ):
            for call in (
                node
                for node in ast.walk(function)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            ):
                topic_index = 0 if call.func.attr == "_publish_proposal" else 1
                if (
                    call.func.attr not in {"publish", "_publish_proposal"}
                    or len(call.args) <= topic_index
                ):
                    continue
                topic = call.args[topic_index]
                if isinstance(topic, ast.Constant) and isinstance(topic.value, str):
                    if topic.value.startswith("object."):
                        topics.add(topic.value)
                elif isinstance(topic, ast.Name):
                    value = getattr(module, topic.id, None)
                    if isinstance(value, str) and value.startswith("object."):
                        topics.add(value)
                elif isinstance(topic, ast.Attribute):
                    topic_expression = ast.dump(topic)
                    for comparison in (
                        node for node in ast.walk(function) if isinstance(node, ast.Compare)
                    ):
                        expressions = (comparison.left, *comparison.comparators)
                        if not any(ast.dump(item) == topic_expression for item in expressions):
                            continue
                        topics.update(
                            item.value
                            for item in expressions
                            if isinstance(item, ast.Constant)
                            and isinstance(item.value, str)
                            and item.value.startswith("object.")
                        )
    return topics


def test_pantheon_has_exactly_fifteen_named_agents() -> None:
    # docs/roadmap/agents/agent-pantheon.md \u00a74
    assert len(PANTHEON_SPECS) == 15
    assert len(PANTHEON_NAMES) == 15


def test_canonical_pantheon_names() -> None:
    # Fork boundary: adding / removing / renaming any of these is an
    # upstream change per docs/roadmap/agents/agent-pantheon.md \u00a710.
    expected = {
        "Odin",
        "Thor",
        "Forseti",
        "Huginn",
        "Heimdall",
        "Vidar",
        "Var",
        "Bragi",
        "Saga",
        "Mimir",
        "Muninn",
        "Norns",
        "Njord",
        "Freyr",
        "Loki",
    }
    assert PANTHEON_NAMES == expected


def test_hard_dependency_agents_are_saga_and_vidar() -> None:
    # docs/roadmap/agents/agent-pantheon.md \u00a74.3
    assert HARD_DEPENDENCY_AGENTS == {"Saga", "Vidar"}


def test_llm_hot_path_allowlist_is_bragi_forseti_norns() -> None:
    # docs/roadmap/agents/agent-pantheon.md \u00a78
    assert LLM_HOT_PATH_ALLOWLIST == {"Bragi", "Forseti", "Norns"}


def test_registry_loads_cleanly() -> None:
    reg = load_pantheon()
    assert reg.names() == PANTHEON_NAMES


def test_action_type_bindings_resolve_in_shipped_catalog() -> None:
    catalog = load_action_type_catalog(
        _REPO_ROOT / "rule-catalog" / "action-types",
        schema_registry=PackageResourceSchemaRegistry(),
    )
    shipped = {action.name for action in catalog}
    bound = {
        action_type for spec in PANTHEON_SPECS for action_type in (*spec.executes, *spec.initiates)
    }
    assert bound <= shipped, f"undeclared AgentSpec ActionTypes: {sorted(bound - shipped)}"


def test_owns_sets_are_pairwise_disjoint() -> None:
    # Single-writer invariant (docs/roadmap/agents/agent-pantheon.md \u00a76.1)
    seen: dict[str, str] = {}
    for spec in PANTHEON_SPECS:
        for obj in spec.owns:
            assert obj not in seen, (
                f"ObjectType {obj!r} is owned by both {seen[obj]!r} and {spec.name!r}"
            )
            seen[obj] = spec.name


def test_publishes_matches_owns_topic_form() -> None:
    # AgentSpec.__post_init__ derives publishes from owns; a spec whose
    # two lists diverged would be a defect.
    for spec in PANTHEON_SPECS:
        assert len(spec.publishes) == len(spec.owns)
        assert all(t.startswith("object.") for t in spec.publishes)


def test_every_owned_topic_has_a_concrete_producer_path() -> None:
    owned = {topic for spec in PANTHEON_SPECS for topic in spec.publishes}
    produced = _producer_topics()

    assert owned <= produced, f"owned topics without producer paths: {sorted(owned - produced)}"
    assert produced <= owned, f"producer paths without owned topics: {sorted(produced - owned)}"


def test_reports_to_resolves() -> None:
    # Every reports_to must reference a known agent (Odin is the root).
    for spec in PANTHEON_SPECS:
        if spec.name == "Odin":
            assert spec.reports_to is None
        else:
            assert spec.reports_to in PANTHEON_NAMES


def test_registry_lookup_owner_of_object_type() -> None:
    reg = load_pantheon()
    assert reg.owner_of_object_type("ActionRun") == "Thor"
    assert reg.owner_of_object_type("Verdict") == "Forseti"
    assert reg.owner_of_object_type("Rollback") == "Vidar"
    assert reg.owner_of_object_type("AuditEntry") == "Saga"
    assert reg.owner_of_object_type("Rule") == "Mimir"
    assert reg.owner_of_object_type("Change") == "Huginn"
    assert reg.owner_of_object_type("RetrievalValidation") == "Heimdall"


def test_registry_lookup_owner_of_topic() -> None:
    reg = load_pantheon()
    assert reg.owner_of_topic("object.action-run") == "Thor"
    assert reg.owner_of_topic("object.verdict") == "Forseti"
    assert reg.owner_of_topic("object.audit-entry") == "Saga"
    assert reg.owner_of_topic("object.change") == "Huginn"
    assert reg.owner_of_topic("object.retrieval-validation") == "Heimdall"


def test_publish_authorization_accepts_owner() -> None:
    reg = load_pantheon()
    # Owner is allowed
    reg.assert_can_publish("Thor", "object.action-run")
    reg.assert_can_publish("Forseti", "object.verdict")
    reg.assert_can_publish("Saga", "object.audit-entry")
    reg.assert_can_publish("Bragi", "object.handoff-escalation")
    reg.assert_can_publish("Heimdall", "object.retrieval-validation")


def test_publish_authorization_rejects_non_owner() -> None:
    reg = load_pantheon()
    with pytest.raises(PantheonRegistryError, match="not the owner"):
        reg.assert_can_publish("Bragi", "object.action-run")
    with pytest.raises(PantheonRegistryError, match="not the owner"):
        reg.assert_can_publish("Loki", "object.verdict")


def test_publish_authorization_rejects_unknown_topic() -> None:
    reg = load_pantheon()
    with pytest.raises(PantheonRegistryError, match="no declared owner"):
        reg.assert_can_publish("Thor", "object.does-not-exist")
