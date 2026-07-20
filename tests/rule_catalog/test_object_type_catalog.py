"""Ontology ObjectType catalog loader tests.

Covers:
- The four upstream ObjectTypes load cleanly.
- Duplicate `name` across files fails-closed with an aggregated error.
- `key` MUST name a declared property (cross-reference the schema alone
  cannot express).
- JSON Schema violations surface with file + JSON pointer origin.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from fdai.agents.saga import compute_fingerprint
from fdai.rule_catalog.schema.object_type import (
    ObjectTypeCatalogError,
    load_object_type_catalog,
    load_object_type_from_mapping,
    object_type_names,
)
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry

REPO_ROOT = Path(__file__).resolve().parents[2]
CATALOG_ROOT = REPO_ROOT / "rule-catalog" / "vocabulary" / "object-types"


def _registry() -> PackageResourceSchemaRegistry:
    return PackageResourceSchemaRegistry()


def test_shipped_object_types_load() -> None:
    catalog = load_object_type_catalog(CATALOG_ROOT, schema_registry=_registry())
    names = object_type_names(catalog)
    # Four control-loop built-ins plus the ChangeSummary reference plus the
    # eight pantheon object types
    # (docs/roadmap/agents/agent-pantheon.md § 5,
    #  docs/roadmap/agents/agent-pantheon-implementation.md Wave 0)
    # plus the Process runtime object (docs/roadmap/decisioning/process-automation.md 3.1).
    assert names == {
        "Resource",
        "Rule",
        "Signal",
        "Finding",
        "ChangeSummary",
        # Pantheon (docs/roadmap/agents/agent-pantheon.md)
        "Agent",
        "Conversation",
        "Turn",
        "UserPreference",
        "SecurityEvent",
        "Issue",
        "RuleCandidate",
        "HandoffEscalation",
        # Process automation (docs/roadmap/decisioning/process-automation.md)
        "Process",
        # Governed Python task execution on managed compute.
        "PythonTask",
        "VmTaskRun",
        # Governed review workflow projection.
        "ReviewCase",
        "ReviewCheck",
        "EvidenceArtifact",
        "Principal",
        "Approval",
        "Decision",
        # Principal-scoped context, proactive briefing, and workflow ownership.
        "UserMemoryFact",
        "ConversationPolicy",
        "BriefingSubscription",
        "BriefingRun",
        "WorkflowDefinition",
        "WorkflowBinding",
    }


def test_every_shipped_object_type_has_id_key() -> None:
    catalog = load_object_type_catalog(CATALOG_ROOT, schema_registry=_registry())
    # The four built-ins all use `id` as their unique-instance key. A
    # fork MAY choose a different key for its own ObjectType; this test
    # only asserts the shipped invariant, not a universal rule.
    for entry in catalog:
        assert entry.key == "id", f"{entry.name}: shipped built-in must key on 'id'"


def test_issue_declares_authoritative_lifecycle_criteria() -> None:
    catalog = load_object_type_catalog(CATALOG_ROOT, schema_registry=_registry())
    issue = next(entry for entry in catalog if entry.name == "Issue")

    assert issue.lifecycle is not None
    assert issue.lifecycle.owner == "Saga"
    assert {criterion.code for criterion in issue.lifecycle.creation} == {
        "agent_handoff",
        "bragi_unhandled_query",
    }
    assert issue.lifecycle.deduplication is not None
    assert issue.lifecycle.deduplication.strategy == "deterministic fingerprint"
    assert issue.lifecycle.deduplication.fields == list(
        inspect.signature(compute_fingerprint).parameters
    )
    assert issue.lifecycle.deduplication.on_repeat.startswith("Append")
    assert issue.lifecycle.closure[0].code == "resolving_capability_promoted"


def test_key_must_name_a_declared_property() -> None:
    raw = {
        "schema_version": "1.0.0",
        "name": "BrokenType",
        "version": "1.0.0",
        "key": "not_declared",
        "properties": {
            "id": {"type": "string", "required": True},
        },
    }
    with pytest.raises(ObjectTypeCatalogError) as info:
        load_object_type_from_mapping(raw, schema_registry=_registry())
    joined = " ".join(i.message for i in info.value.issues).lower()
    assert "not_declared" in joined
    assert "not a declared property" in joined


def test_lifecycle_criterion_requires_authority_reference() -> None:
    raw = {
        "schema_version": "1.0.0",
        "name": "ExplainedType",
        "version": "1.0.0",
        "key": "id",
        "properties": {"id": {"type": "string", "required": True}},
        "lifecycle": {
            "owner": "Saga",
            "creation": [
                {
                    "code": "created",
                    "when": "A trigger fires.",
                    "result": "The object is created.",
                }
            ],
            "authority_refs": ["example.py#create"],
        },
    }

    with pytest.raises(ObjectTypeCatalogError) as info:
        load_object_type_from_mapping(raw, schema_registry=_registry())

    assert any("source_refs" in f"{issue.key} {issue.message}" for issue in info.value.issues)


def test_duplicate_name_across_files_fails(tmp_path: Path) -> None:
    body = (
        'schema_version: "1.0.0"\n'
        "name: Dupe\n"
        'version: "1.0.0"\n'
        "key: id\n"
        "properties:\n"
        "  id:\n"
        "    type: string\n"
        "    required: true\n"
    )
    (tmp_path / "one.yaml").write_text(body)
    (tmp_path / "two.yaml").write_text(body)

    with pytest.raises(ObjectTypeCatalogError) as info:
        load_object_type_catalog(tmp_path, schema_registry=_registry())
    joined = " ".join(i.message for i in info.value.issues).lower()
    assert "duplicate objecttype name 'dupe'" in joined


def test_invalid_name_pattern_fails(tmp_path: Path) -> None:
    # Name MUST start with a capital letter and be PascalCase.
    (tmp_path / "bad.yaml").write_text(
        'schema_version: "1.0.0"\n'
        "name: lowerBad\n"
        'version: "1.0.0"\n'
        "key: id\n"
        "properties:\n"
        "  id:\n"
        "    type: string\n"
    )
    with pytest.raises(ObjectTypeCatalogError) as info:
        load_object_type_catalog(tmp_path, schema_registry=_registry())
    keys = " ".join(i.key for i in info.value.issues)
    assert "bad.yaml:name" in keys


def test_top_level_must_be_a_mapping(tmp_path: Path) -> None:
    (tmp_path / "list.yaml").write_text("- not\n- a\n- mapping\n")
    with pytest.raises(ObjectTypeCatalogError) as info:
        load_object_type_catalog(tmp_path, schema_registry=_registry())
    joined = " ".join(i.message for i in info.value.issues).lower()
    assert "top-level must be a mapping" in joined
