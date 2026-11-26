"""Executable verification for downstream fork seam recipes 5.1 through 5.17."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import yaml
from fdai.composition import (
    AzureWireOverrides,
    default_container,
    install_capability_bundle,
)
from fdai.core.capability_catalog import (
    Capability,
    CapabilityBinding,
    CapabilityBindingKind,
    CapabilityBundle,
    CapabilityCategory,
    SideEffectClass,
)
from fdai.core.executor import ShadowExecutor
from fdai.core.operator_memory import (
    HilRejectMaterial,
    HilRejectMaterializer,
    InMemoryOperatorMemoryStore,
    MemoryCategory,
    OperatorScope,
    ScopeKind,
)
from fdai.core.quality_gate.gate import QualityCandidate
from fdai.core.tiers.t0_deterministic import RuleIndex
from fdai.core.web_search import (
    NoOpWebSearchProvider,
    WebSearchPolicyConfig,
    WebSearchProvider,
)
from fdai.rule_catalog.pipeline.distill.orchestrator import build_distillation_plan
from fdai.rule_catalog.schema.action_type import load_action_type_catalog
from fdai.rule_catalog.schema.link_type import load_link_type_catalog
from fdai.rule_catalog.schema.object_type import load_object_type_catalog
from fdai.rule_catalog.schema.resource_type import load_resource_type_registry_from_mapping
from fdai.rule_catalog.schema.rule import load_rule_catalog
from fdai.shared.config.models import AppConfig
from fdai.shared.contracts.models import Mode, RollbackKind
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.providers.distiller import AbstainingDistiller, Distiller
from fdai.shared.providers.hil_channel import HilDecision, HilResponse
from fdai.shared.providers.manual_classifier import (
    AbstainingManualClassifier,
    ManualClassifier,
)
from fdai.shared.providers.manual_source import (
    DropDirectoryManualSource,
    EmptyManualSource,
    ManualSource,
)
from fdai.shared.providers.remediation_pr import (
    PublishReceipt,
    RemediationPr,
    RemediationPrPublisher,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
ACTION_TYPES_ROOT = REPO_ROOT / "rule-catalog" / "action-types"
OBJECT_TYPES_ROOT = REPO_ROOT / "rule-catalog" / "vocabulary" / "object-types"
LINK_TYPES_ROOT = REPO_ROOT / "rule-catalog" / "vocabulary" / "link-types"
RULES_ROOT = REPO_ROOT / "rule-catalog" / "catalog"
VOCABULARY_FILE = REPO_ROOT / "rule-catalog" / "vocabulary" / "resource-types.yaml"


def _registry() -> PackageResourceSchemaRegistry:
    return PackageResourceSchemaRegistry()


def _container():  # type: ignore[no-untyped-def]
    return default_container(
        AppConfig.model_validate(
            {
                "schema_version": "1.0.0",
                "azure": {
                    "tenant_id": "00000000-0000-0000-0000-000000000000",
                    "subscription_id": "00000000-0000-0000-0000-000000000000",
                    "region": "koreacentral",
                },
                "kafka": {
                    "bootstrap_servers": "events.example.com:9093",
                    "topic_events": "fdai.events",
                },
                "postgres": {"host": "postgres.example.com", "database": "fdai"},
                "runtime": {"env": "dev"},
                "llm": {"mode": "local-fake"},
            }
        )
    )


def test_recipe_5_1_llm_bindings_and_azure_wire_overrides() -> None:
    container = _container()
    assert container.llm_bindings is not None
    bindings = replace(container.llm_bindings, t2_proposer=None)
    overrides = AzureWireOverrides(
        endpoint="https://oai-example.openai.azure.com",
        catalog_root=REPO_ROOT / "rule-catalog",
        operator_memory_store=InMemoryOperatorMemoryStore(),
    )
    assert bindings.t2_proposer is None
    assert overrides.endpoint == "https://oai-example.openai.azure.com"


def test_recipe_5_2_operator_memory_store_round_trip() -> None:
    store = InMemoryOperatorMemoryStore()
    overrides = AzureWireOverrides(
        endpoint="https://oai-example.openai.azure.com",
        catalog_root=REPO_ROOT / "rule-catalog",
        operator_memory_store=store,
    )
    assert overrides.operator_memory_store is store


async def test_recipe_5_3_hil_reject_materializer_contract() -> None:
    now = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
    store = InMemoryOperatorMemoryStore(now_fn=lambda: now)
    materializer = HilRejectMaterializer(store=store, now_fn=lambda: now)
    resp = HilResponse(
        approval_id="req-1",
        decision=HilDecision.REJECT,
        approver_id="operator-one@example.com",
        reason="change freeze window active",
        received_at=now,
    )
    entry = await materializer.materialize(
        hil_response=resp,
        second_approver="operator-two@example.com",
        material=HilRejectMaterial(
            scope_kind=ScopeKind.RESOURCE_GROUP,
            scope_ref="rg-example",
            category=MemoryCategory.FORBIDDEN_ACTION,
            source_ref="hil.reject:req-1",
        ),
    )
    assert entry.scope_ref == "rg-example"
    active = await store.list_active_for_scope(
        scope_kind=ScopeKind.RESOURCE_GROUP,
        scope_ref="rg-example",
    )
    assert len(active) == 1


async def test_recipe_5_4_web_search_provider_and_policy() -> None:
    provider: WebSearchProvider = NoOpWebSearchProvider()
    policy = WebSearchPolicyConfig(enabled=True, novelty_threshold=0.7)
    assert policy.enabled is True
    assert policy.novelty_threshold == 0.7
    assert provider is not None


def test_recipe_5_5_hil_channel_protocol_binding() -> None:
    import fdai.__main__ as entry_mod

    assert callable(entry_mod._build_hil_channel)


def test_recipe_5_6_scope_resolver_contract() -> None:
    scope = OperatorScope(
        resource_group_ref="rg-example",
        resource_ref="vm-1",
    )
    candidate = QualityCandidate(
        action_type="ops.restart-pod",
        target_resource_ref="vm-1",
        params={"grace_period_seconds": 30},
        cited_rule_ids=("rule-1",),
        confidence_signals={"retrieval": 0.92},
    )
    assert scope.resource_group_ref == "rg-example"
    assert candidate.aggregate_confidence == 0.92


def test_recipe_5_7_critic_and_judge_debate_bindings() -> None:
    container = _container()
    assert container.llm_bindings is not None
    bindings = replace(container.llm_bindings, critic_model=None, judge_model=None)
    assert bindings.critic_model is None
    assert bindings.judge_model is None


def test_recipe_5_8_and_5_8a_rule_and_ontology_catalog_concatenation() -> None:
    registry = _registry()
    objects = load_object_type_catalog(OBJECT_TYPES_ROOT, schema_registry=registry)
    links = load_link_type_catalog(LINK_TYPES_ROOT, schema_registry=registry, object_types=objects)
    action_types = load_action_type_catalog(ACTION_TYPES_ROOT, schema_registry=registry)
    with VOCABULARY_FILE.open("r", encoding="utf-8") as fh:
        resource_types = load_resource_type_registry_from_mapping(yaml.safe_load(fh))
    rules = load_rule_catalog(
        RULES_ROOT,
        schema_registry=registry,
        action_types=action_types,
        resource_types=resource_types,
        object_types=objects,
    )
    index = RuleIndex.build(rules)
    assert len(objects) >= 5
    assert len(links) >= 5
    assert len(index.rules_for_type(resource_type="resource-group")) >= 1


def test_recipe_5_9_and_5_10_risk_overlay_and_abstain_contracts() -> None:
    container = _container()
    assert container.exemption_registry is not None
    assert container.contract_validator is not None


def test_recipe_5_11_and_5_12_action_type_catalog_and_e2e_container() -> None:
    registry = _registry()
    action_types = load_action_type_catalog(ACTION_TYPES_ROOT, schema_registry=registry)
    by_name = {a.name: a for a in action_types}
    assert "ops.publish-change-summary" in by_name
    at = by_name["ops.publish-change-summary"]
    assert at.default_mode is Mode.SHADOW
    assert at.rollback_contract is RollbackKind.PR_REVERT


def test_recipe_5_13_delivery_adapter_custom_publisher_protocol() -> None:
    class _ForkPublisher:
        async def publish(self, pr: RemediationPr) -> PublishReceipt:
            return PublishReceipt(
                pr_ref=f"fork-pr-{pr.idempotency_key}",
                url=f"https://example.com/pr/{pr.idempotency_key}",
                head_sha="0" * 40,
            )

    pub: RemediationPrPublisher = _ForkPublisher()
    assert isinstance(pub, RemediationPrPublisher)
    assert ShadowExecutor is not None


def test_recipe_5_14_and_5_15_console_read_panel_and_entry_point_seams() -> None:
    import fdai.__main__ as entry_mod

    assert callable(entry_mod.main)
    assert callable(entry_mod._build_publisher)
    container = _container()
    assert container.schema_registry is not None
    assert container.event_validator is not None


async def test_recipe_5_16_manual_distillation_seams(tmp_path: Path) -> None:
    empty_source: ManualSource = EmptyManualSource()
    drop_source: ManualSource = DropDirectoryManualSource(root=tmp_path)
    classifier: ManualClassifier = AbstainingManualClassifier()
    distiller: Distiller = AbstainingDistiller()
    assert await empty_source.list_candidates() == ()
    assert await drop_source.list_candidates() == ()
    plan = await build_distillation_plan(
        source=drop_source,
        classifier=classifier,
        distiller=distiller,
    )
    assert plan.distilled == ()


def test_recipe_5_17_capability_bundle_registration() -> None:
    base = _container()
    bundle = CapabilityBundle(
        capabilities=(
            Capability(
                capability_id="fork.change-summary",
                name="Change Summary",
                category=CapabilityCategory.REPORTING,
                summary="Reference fork capability",
                side_effect_class=SideEffectClass.EXECUTE,
                default_mode=Mode.SHADOW,
            ),
        ),
        bindings=(
            CapabilityBinding(
                capability_id="fork.change-summary",
                kind=CapabilityBindingKind.ACTION_TYPE,
                target_ref="ops.publish-change-summary",
            ),
        ),
    )
    registry = _registry()
    action_types = load_action_type_catalog(ACTION_TYPES_ROOT, schema_registry=registry)
    updated = install_capability_bundle(
        base,
        bundle,
        action_types=action_types,
    )
    assert updated is not base
    assert updated.capability_runtime.resolve("fork.change-summary").binding.target_ref == (
        "ops.publish-change-summary"
    )
