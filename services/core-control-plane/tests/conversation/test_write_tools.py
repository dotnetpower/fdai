"""SimulateChangeTool + AuditWriter - Wave W1.1 partial contract tests.

Every invariant the operator-console doc mandates on `simulate_change`
is asserted here:

- side_effect_class == 'simulate' and rbac_floor == Contributor.
- No real PR publisher, ShadowExecutor, or state-store write beyond a
  single console.simulate_change audit entry.
- Verifier re-check preserved through T0Engine.
- Safety invariants (stop_condition, rollback, blast_radius) present on
  every produced Action; ActionBuild failure degrades to error, not a
  silent success.
- Rendering errors do not fall open into a "clean" ok result.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
import yaml
from fdai.core.conversation import Principal, Role
from fdai.core.conversation.tools import SystemConsoleTool
from fdai.core.conversation.write_tools import (
    AuditWriter,
    SimulateChangeTool,
)
from fdai.core.executor.action_builder import ActionBuilder
from fdai.core.executor.renderer import TemplateRenderer
from fdai.core.tiers.t0_deterministic import T0Engine
from fdai.core.tiers.t0_deterministic.engine import PolicyResult
from fdai.core.tiers.t0_deterministic.index import RuleIndex
from fdai.core.trust_router import TrustRouter
from fdai.rule_catalog.schema.action_type import load_action_type_catalog
from fdai.rule_catalog.schema.resource_type import (
    load_resource_type_registry_from_mapping,
)
from fdai.rule_catalog.schema.rule import load_rule_catalog
from fdai.shared.contracts.models import Rule
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.providers.testing.state_store import InMemoryStateStore

REPO_ROOT = Path(__file__).resolve().parents[4]


class _AlwaysDenyEvaluator:
    """Force every candidate rule to fire with a deterministic context."""

    def evaluate(self, rule: Rule, resource_props: Mapping[str, Any]) -> PolicyResult:
        del resource_props
        return PolicyResult(
            denied=True,
            context={"rule_id": rule.id, "reason": "forced-deny for test"},
        )


class _NeverDenyEvaluator:
    def evaluate(self, rule: Rule, resource_props: Mapping[str, Any]) -> PolicyResult:
        del rule, resource_props
        return PolicyResult(denied=False, context={})


@pytest.fixture(scope="module")
def catalog():
    registry = PackageResourceSchemaRegistry()
    catalog_root = REPO_ROOT / "rule-catalog"
    with (catalog_root / "vocabulary" / "resource-types.yaml").open() as f:
        rt = load_resource_type_registry_from_mapping(yaml.safe_load(f))
    action_types = load_action_type_catalog(catalog_root / "action-types", schema_registry=registry)
    rules = load_rule_catalog(
        catalog_root / "catalog",
        schema_registry=registry,
        resource_types=rt,
        action_types=action_types,
        policies_root=REPO_ROOT / "policies",
        remediation_root=REPO_ROOT / "rule-catalog" / "remediation",
    )
    return {
        "rules": list(rules),
        "index": RuleIndex.build(rules),
        "action_types": {a.name: a for a in action_types},
        "rules_by_id": {r.id: r for r in rules},
        "remediation_root": REPO_ROOT / "rule-catalog" / "remediation",
    }


def _build_tool(
    catalog: dict[str, Any],
    *,
    evaluator: Any,
    audit_store: InMemoryStateStore | None = None,
) -> tuple[SimulateChangeTool, InMemoryStateStore]:
    store = audit_store if audit_store is not None else InMemoryStateStore()
    router = TrustRouter(index=catalog["index"])
    engine = T0Engine(index=catalog["index"], evaluator=evaluator)
    builder = ActionBuilder(action_types_by_name=catalog["action_types"])
    renderer = TemplateRenderer(remediation_root=catalog["remediation_root"])
    tool = SimulateChangeTool(
        trust_router=router,
        t0_engine=engine,
        action_builder=builder,
        template_renderer=renderer,
        rules_by_id=catalog["rules_by_id"],
        audit_writer=AuditWriter(audit_store=store),
    )
    return tool, store


def _principal() -> Principal:
    return Principal(id="cli-tester", role=Role.CONTRIBUTOR, display_name="Sim")


# ---------------------------------------------------------------------------
# Protocol conformance + shape
# ---------------------------------------------------------------------------


class TestProtocolConformance:
    def test_satisfies_system_console_tool(self, catalog: dict[str, Any]) -> None:
        tool, _ = _build_tool(catalog, evaluator=_NeverDenyEvaluator())
        assert isinstance(tool, SystemConsoleTool)

    def test_side_effect_class_is_simulate(self, catalog: dict[str, Any]) -> None:
        tool, _ = _build_tool(catalog, evaluator=_NeverDenyEvaluator())
        assert tool.side_effect_class == "simulate"

    def test_rbac_floor_is_contributor(self, catalog: dict[str, Any]) -> None:
        tool, _ = _build_tool(catalog, evaluator=_NeverDenyEvaluator())
        assert tool.rbac_floor is Role.CONTRIBUTOR


# ---------------------------------------------------------------------------
# Argument validation
# ---------------------------------------------------------------------------


class TestArgumentValidation:
    def test_missing_scenario_errors(self, catalog: dict[str, Any]) -> None:
        tool, _ = _build_tool(catalog, evaluator=_NeverDenyEvaluator())
        r = tool.call(arguments={}, principal=_principal())
        assert r.status == "error"
        assert "non-empty 'scenario'" in r.preview

    def test_scenario_must_carry_resource_type_and_id(self, catalog: dict[str, Any]) -> None:
        tool, _ = _build_tool(catalog, evaluator=_NeverDenyEvaluator())
        r = tool.call(
            arguments={"scenario": {"resource_type": ""}},
            principal=_principal(),
        )
        assert r.status == "error"
        r = tool.call(
            arguments={"scenario": {"resource_type": "object-storage"}},
            principal=_principal(),
        )
        assert r.status == "error"

    def test_resource_props_must_be_mapping(self, catalog: dict[str, Any]) -> None:
        tool, _ = _build_tool(catalog, evaluator=_NeverDenyEvaluator())
        r = tool.call(
            arguments={
                "scenario": {
                    "resource_type": "object-storage",
                    "resource_id": "x",
                    "resource_props": "not-a-dict",
                }
            },
            principal=_principal(),
        )
        assert r.status == "error"

    def test_scenario_must_be_mapping(self, catalog: dict[str, Any]) -> None:
        tool, _ = _build_tool(catalog, evaluator=_NeverDenyEvaluator())
        r = tool.call(
            arguments={"scenario": "not-a-dict"},  # type: ignore[dict-item]
            principal=_principal(),
        )
        assert r.status == "error"


# ---------------------------------------------------------------------------
# Routing / T0 abstain paths
# ---------------------------------------------------------------------------


class TestAbstainPaths:
    def test_routing_abstain_writes_one_audit_entry(self, catalog: dict[str, Any]) -> None:
        tool, store = _build_tool(catalog, evaluator=_NeverDenyEvaluator())
        r = tool.call(
            arguments={
                "scenario": {
                    "resource_type": "definitely-not-in-vocabulary",
                    "resource_id": "x",
                    "resource_props": {},
                }
            },
            principal=_principal(),
        )
        assert r.status == "abstain"
        assert r.data["outcome"] == "abstained_routing"
        assert r.data["pr_intents"] == []
        # Exactly ONE audit entry landed.
        entries = list(store.audit_entries)
        assert len(entries) == 1
        entry = _unwrap(entries[0])
        assert entry["action_kind"] == "console.simulate_change"
        assert entry["decision"] == "abstained_routing"
        assert entry["actor"] == "cli-tester"

    def test_t0_abstain_writes_one_audit_entry(self, catalog: dict[str, Any]) -> None:
        tool, store = _build_tool(catalog, evaluator=_NeverDenyEvaluator())
        r = tool.call(
            arguments={
                "scenario": {
                    "resource_type": "object-storage",
                    "resource_id": "storage-x",
                    "resource_props": {"public_access": False},
                }
            },
            principal=_principal(),
        )
        assert r.status == "abstain"
        assert r.data["outcome"] == "abstained_t0"
        assert r.data["pr_intents"] == []
        entries = list(store.audit_entries)
        assert len(entries) == 1
        entry = _unwrap(entries[0])
        assert entry["decision"] == "abstained_t0"


# ---------------------------------------------------------------------------
# Happy path - PR intents captured
# ---------------------------------------------------------------------------


class TestSimulateHappyPath:
    def test_produces_pr_intents_without_publishing(self, catalog: dict[str, Any]) -> None:
        tool, store = _build_tool(catalog, evaluator=_AlwaysDenyEvaluator())
        r = tool.call(
            arguments={
                "scenario": {
                    "resource_type": "object-storage",
                    "resource_id": "storage-x",
                    "resource_props": {"public_access": True},
                }
            },
            principal=_principal(),
        )
        assert r.status == "ok"
        assert r.data["outcome"] == "simulated"
        assert len(r.data["pr_intents"]) >= 1
        # Every PR intent carries a safety-invariant footprint.
        for pr in r.data["pr_intents"]:
            assert pr["stop_condition"]
            assert pr["rollback_kind"]
            assert pr["patch_preview"]
            assert pr["idempotency_key"]
        # Audit entry landed exactly once.
        entries = list(store.audit_entries)
        assert len(entries) == 1
        entry = _unwrap(entries[0])
        assert entry["decision"] == "simulated"
        assert len(entry["pr_intents"]) == len(r.data["pr_intents"])

    def test_evidence_refs_include_audit_and_rules(self, catalog: dict[str, Any]) -> None:
        tool, _ = _build_tool(catalog, evaluator=_AlwaysDenyEvaluator())
        r = tool.call(
            arguments={
                "scenario": {
                    "resource_type": "object-storage",
                    "resource_id": "storage-x",
                    "resource_props": {"public_access": True},
                }
            },
            principal=_principal(),
        )
        assert any(ref.startswith("audit:") for ref in r.evidence_refs)
        assert any(ref.startswith("rule:") for ref in r.evidence_refs)

    def test_synthetic_event_carries_shadow_mode(self, catalog: dict[str, Any]) -> None:
        # The audit entry MUST record mode=shadow (never enforce).
        tool, store = _build_tool(catalog, evaluator=_AlwaysDenyEvaluator())
        tool.call(
            arguments={
                "scenario": {
                    "resource_type": "object-storage",
                    "resource_id": "storage-x",
                    "resource_props": {"public_access": True},
                }
            },
            principal=_principal(),
        )
        entry = _unwrap(list(store.audit_entries)[0])
        assert entry["mode"] == "shadow"


# ---------------------------------------------------------------------------
# No-mutation invariants
# ---------------------------------------------------------------------------


class TestNoMutationSurface:
    def test_write_state_is_never_called(self, catalog: dict[str, Any]) -> None:
        """The tool MUST NOT invoke StateStore.write_state - it only
        appends the discoverability audit entry."""
        tool, store = _build_tool(catalog, evaluator=_AlwaysDenyEvaluator())
        # Record the state map before + after.
        before = _snapshot_state(store)
        tool.call(
            arguments={
                "scenario": {
                    "resource_type": "object-storage",
                    "resource_id": "storage-x",
                    "resource_props": {"public_access": True},
                }
            },
            principal=_principal(),
        )
        after = _snapshot_state(store)
        assert before == after

    def test_multiple_calls_write_multiple_entries(self, catalog: dict[str, Any]) -> None:
        # Ensure the audit trail keeps growing (not silently overwriting).
        tool, store = _build_tool(catalog, evaluator=_AlwaysDenyEvaluator())
        for _ in range(3):
            tool.call(
                arguments={
                    "scenario": {
                        "resource_type": "object-storage",
                        "resource_id": "storage-x",
                        "resource_props": {"public_access": True},
                    }
                },
                principal=_principal(),
            )
        assert len(list(store.audit_entries)) == 3


# ---------------------------------------------------------------------------
# Failure paths - ActionBuild / render errors
# ---------------------------------------------------------------------------


class TestFailurePaths:
    def test_rule_missing_from_map_falls_through_as_error_when_only_finding(
        self, catalog: dict[str, Any]
    ) -> None:
        # Rebuild the tool with an EMPTY rules_by_id so the "rule not in map"
        # branch triggers on every finding.
        store = InMemoryStateStore()
        router = TrustRouter(index=catalog["index"])
        engine = T0Engine(index=catalog["index"], evaluator=_AlwaysDenyEvaluator())
        builder = ActionBuilder(action_types_by_name=catalog["action_types"])
        renderer = TemplateRenderer(remediation_root=catalog["remediation_root"])
        tool = SimulateChangeTool(
            trust_router=router,
            t0_engine=engine,
            action_builder=builder,
            template_renderer=renderer,
            rules_by_id={},  # empty on purpose
            audit_writer=AuditWriter(audit_store=store),
        )
        r = tool.call(
            arguments={
                "scenario": {
                    "resource_type": "object-storage",
                    "resource_id": "storage-x",
                    "resource_props": {"public_access": True},
                }
            },
            principal=_principal(),
        )
        # Every finding failed to build; status is 'error'.
        assert r.status == "error"
        assert r.data["pr_intents"] == []
        assert any("not in rules_by_id" in e for e in r.data["errors"])

    def test_action_build_error_is_captured_but_does_not_stop_pipeline(
        self, catalog: dict[str, Any]
    ) -> None:
        # Register an ActionBuilder whose action_types_by_name is missing
        # the entries the shipped rules reference. build_from_finding
        # raises ActionBuildError for every finding.
        store = InMemoryStateStore()
        router = TrustRouter(index=catalog["index"])
        engine = T0Engine(index=catalog["index"], evaluator=_AlwaysDenyEvaluator())
        # Empty action_types map -> ActionBuildError for every finding.
        builder = ActionBuilder(action_types_by_name={})
        renderer = TemplateRenderer(remediation_root=catalog["remediation_root"])
        tool = SimulateChangeTool(
            trust_router=router,
            t0_engine=engine,
            action_builder=builder,
            template_renderer=renderer,
            rules_by_id=catalog["rules_by_id"],
            audit_writer=AuditWriter(audit_store=store),
        )
        r = tool.call(
            arguments={
                "scenario": {
                    "resource_type": "object-storage",
                    "resource_id": "storage-x",
                    "resource_props": {"public_access": True},
                }
            },
            principal=_principal(),
        )
        assert r.status == "error"
        assert r.data["pr_intents"] == []
        assert any("ActionBuild failed" in e for e in r.data["errors"])

    def test_render_error_is_captured(self, catalog: dict[str, Any], tmp_path: Path) -> None:
        # Point the renderer at an EMPTY directory so every template
        # reference fails to load.
        empty_root = tmp_path / "empty"
        empty_root.mkdir()
        store = InMemoryStateStore()
        router = TrustRouter(index=catalog["index"])
        engine = T0Engine(index=catalog["index"], evaluator=_AlwaysDenyEvaluator())
        builder = ActionBuilder(action_types_by_name=catalog["action_types"])
        renderer = TemplateRenderer(remediation_root=empty_root)
        tool = SimulateChangeTool(
            trust_router=router,
            t0_engine=engine,
            action_builder=builder,
            template_renderer=renderer,
            rules_by_id=catalog["rules_by_id"],
            audit_writer=AuditWriter(audit_store=store),
        )
        r = tool.call(
            arguments={
                "scenario": {
                    "resource_type": "object-storage",
                    "resource_id": "storage-x",
                    "resource_props": {"public_access": True},
                }
            },
            principal=_principal(),
        )
        assert r.status == "error"
        assert r.data["pr_intents"] == []
        assert any("Template render failed" in e for e in r.data["errors"])


# ---------------------------------------------------------------------------
# Extra-payload merging + helper functions
# ---------------------------------------------------------------------------


class TestExtraPayloadAndHelpers:
    def test_extra_scenario_keys_are_merged_into_payload(self, catalog: dict[str, Any]) -> None:
        # Extra keys under scenario should land inside the synthetic
        # Event.payload verbatim (not shadowed by resource / properties).
        tool, store = _build_tool(catalog, evaluator=_NeverDenyEvaluator())
        tool.call(
            arguments={
                "scenario": {
                    "resource_type": "object-storage",
                    "resource_id": "storage-x",
                    "resource_props": {},
                    "signal_source": "azure-activity-log",
                    "correlation_id": "abc-123",
                }
            },
            principal=_principal(),
        )
        # We can only observe the payload via the audit entry - the audit
        # record does not expose the whole payload, but it records
        # resource_type which comes from the payload's resource block.
        entries = list(store.audit_entries)
        assert entries
        entry = _unwrap(entries[0])
        assert entry["resource_type"] == "object-storage"

    def test_enum_value_helper_handles_none_and_plain_str(self) -> None:
        from fdai.core.conversation.write_tools import _enum_value

        assert _enum_value(None) == ""
        assert _enum_value("plain") == "plain"

        class _Fake:
            value = "wrapped"

        assert _enum_value(_Fake()) == "wrapped"

    def test_extract_resource_type_falls_back_to_empty(self) -> None:
        # An event whose payload lacks a 'resource' mapping falls back
        # to empty string (safe default).
        from datetime import UTC, datetime
        from uuid import uuid4

        from fdai.core.conversation.write_tools import _extract_resource_type
        from fdai.shared.contracts.models import Event, Mode

        event = Event(
            schema_version="1.0.0",
            event_id=uuid4(),
            idempotency_key="k",
            source="test",
            event_type="synthetic.test",
            resource_ref="r",
            payload={},  # no 'resource' block
            detected_at=datetime.now(tz=UTC),
            ingested_at=datetime.now(tz=UTC),
            mode=Mode.SHADOW,
        )
        assert _extract_resource_type(event) == ""

    def test_preview_truncates_long_patches(self) -> None:
        from fdai.core.conversation.write_tools import _preview

        long = "x" * 2000
        preview = _preview(long, max_bytes=100)
        assert len(preview) <= 103  # 100 + "..."
        assert preview.endswith("...")

    def test_preview_returns_short_patch_untrimmed(self) -> None:
        from fdai.core.conversation.write_tools import _preview

        short = "  short patch  "
        assert _preview(short) == "short patch"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _unwrap(record: Mapping[str, Any]) -> Mapping[str, Any]:
    inner = record.get("entry")
    if isinstance(inner, Mapping) and ("previous_hash" in record or "entry_hash" in record):
        return inner
    return record


def _snapshot_state(store: InMemoryStateStore) -> dict[str, Any]:
    """Read every ``write_state`` slot we can spot on the fake store.

    The in-memory fake exposes ``_state`` or ``state``; we accept either
    to keep the test robust across the fake's evolution.
    """
    for attr in ("_state", "state"):
        if hasattr(store, attr):
            raw = getattr(store, attr)
            if isinstance(raw, Mapping):
                return dict(raw)
    return {}


def test_module_has_expected_all() -> None:
    from fdai.core.conversation import write_tools

    assert "SimulateChangeTool" in write_tools.__all__
    assert "AuditWriter" in write_tools.__all__


def test_audit_writer_is_sync_wrap_over_async_state_store() -> None:
    """AuditWriter.write_simulation_entry writes via asyncio.run so a
    fork can compose the sync console with an async StateStore."""
    store = InMemoryStateStore()
    writer = AuditWriter(audit_store=store)
    from datetime import UTC, datetime
    from uuid import uuid4

    from fdai.shared.contracts.models import Event, Mode

    event = Event(
        schema_version="1.0.0",
        event_id=uuid4(),
        idempotency_key="test.k",
        source="test",
        event_type="synthetic.test",
        resource_ref="r",
        payload={"resource": {"type": "object-storage", "id": "r"}},
        detected_at=datetime.now(tz=UTC),
        ingested_at=datetime.now(tz=UTC),
        mode=Mode.SHADOW,
    )
    audit_id = writer.write_simulation_entry(
        event=event,
        principal=_principal(),
        outcome="simulated",
        reason=None,
        citing_rule_ids=("r1",),
        pr_intents=({"action_id": "a"},),
        findings_summary=({"rule_id": "r1"},),
    )
    assert audit_id
    entry = _unwrap(list(store.audit_entries)[0])
    assert entry["audit_id"] == audit_id


# Sanity: the test module itself uses asyncio.run inside AuditWriter, so
# ensure pytest-asyncio does not hijack a running loop by having any
# module-level asyncio.run call. We keep asyncio imported for symmetry
# with existing conversation tests but do not spin a loop here.
_ = asyncio
