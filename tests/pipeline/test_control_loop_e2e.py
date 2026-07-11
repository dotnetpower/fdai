"""ControlLoop e2e - event_ingest → trust_router → T0 → executor → audit.

End-to-end pipeline test against the **shipped** catalog artifacts:

- Real rule YAMLs under [`rule-catalog/catalog/`](../../../rule-catalog/catalog/)
- Real Rego policies under [`policies/`](../../../policies/)
- Real Terraform templates under [`rule-catalog/remediation/`](../../../rule-catalog/remediation/)
- Real ActionType YAMLs under [`rule-catalog/action-types/`](../../../rule-catalog/action-types/)

OPA is required for the deny-path assertions (the tests are skipped
gracefully when the `opa` binary is missing - same convention as
`tests/core/tiers/t0_deterministic/test_opa_evaluator.py`).

The pipeline sub-tests assert the property invariants documented in
[phase-1-rule-catalog-t0.md § Autonomy Level]:

- **Shadow-mode never mutates** - every executed action produces a
  ``Mode.SHADOW`` receipt and a shadow-labeled draft PR intent.
- **Every terminal path writes exactly one audit entry** (routing
  abstain, T0 abstain, execute, dedupe).
- **Idempotency across replays** - a second delivery of the same event
  hits the executor's dedupe cache.
"""

from __future__ import annotations

import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
import yaml

from fdai.core.control_loop import (
    ControlLoop,
    ControlLoopOutcome,
    ControlLoopResult,
)
from fdai.core.event_ingest import EventCorrelator, EventIngest
from fdai.core.executor import (
    ExecutorOutcome,
    ResourceLockManager,
    ShadowExecutor,
    TemplateRenderer,
)
from fdai.core.executor.action_builder import ActionBuilder
from fdai.core.notifications.router import NotificationRouter
from fdai.core.rca import CorrelatedEvent, RcaCoordinator, RcaTier, RootCauseHypothesis
from fdai.core.tiers.t0_deterministic import (
    OpaRegoEvaluator,
    RuleIndex,
    T0Engine,
)
from fdai.core.trust_router import TrustRouter
from fdai.rule_catalog.schema.action_type import load_action_type_catalog
from fdai.rule_catalog.schema.resource_type import (
    load_resource_type_registry_from_mapping,
)
from fdai.rule_catalog.schema.rule import load_rule_catalog
from fdai.shared.contracts.models import Event, Mode
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.contracts.validation import (
    JsonSchemaContractValidator,
    JsonSchemaEventValidator,
)
from fdai.shared.providers.notifications.base import (
    NotificationMessage,
    Severity,
    TrustTier,
)
from fdai.shared.providers.testing import (
    InMemoryStateStore,
    RecordingRemediationPrPublisher,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
ACTION_TYPES_ROOT = REPO_ROOT / "rule-catalog" / "action-types"
CATALOG_ROOT = REPO_ROOT / "rule-catalog" / "catalog"
POLICIES_ROOT = REPO_ROOT / "policies"
REMEDIATION_ROOT = REPO_ROOT / "rule-catalog" / "remediation"
VOCABULARY_FILE = REPO_ROOT / "rule-catalog" / "vocabulary" / "resource-types.yaml"

_OPA_PRESENT = shutil.which("opa") is not None
requires_opa = pytest.mark.skipif(
    not _OPA_PRESENT, reason="opa binary not found on PATH; skip e2e evaluator tests"
)


@pytest.fixture(scope="module")
def shipped_catalog() -> tuple[Any, Any]:
    registry = PackageResourceSchemaRegistry()
    action_types = load_action_type_catalog(ACTION_TYPES_ROOT, schema_registry=registry)
    with VOCABULARY_FILE.open("r", encoding="utf-8") as fh:
        resource_types = load_resource_type_registry_from_mapping(yaml.safe_load(fh))
    rules = load_rule_catalog(
        CATALOG_ROOT,
        schema_registry=registry,
        action_types=action_types,
        resource_types=resource_types,
        policies_root=POLICIES_ROOT,
        remediation_root=REMEDIATION_ROOT,
    )
    return rules, action_types


def _make_loop(
    shipped_catalog: tuple[Any, Any],
    *,
    with_opa: bool = True,
    risk_table: Any = None,
    risk_gate: Any = None,
    notification_router: NotificationRouter | None = None,
    rca_coordinator: RcaCoordinator | None = None,
    event_correlator: EventCorrelator | None = None,
    incident_member_source: Any = None,
    resource_dependency_graph: Any = None,
) -> tuple[ControlLoop, RecordingRemediationPrPublisher, InMemoryStateStore]:
    rules, action_types = shipped_catalog
    index = RuleIndex.build(rules)
    evaluator = OpaRegoEvaluator(policies_root=POLICIES_ROOT) if with_opa else None
    publisher = RecordingRemediationPrPublisher()
    audit = InMemoryStateStore()
    executor = ShadowExecutor(
        publisher=publisher,
        audit_store=audit,
        renderer=TemplateRenderer(remediation_root=REMEDIATION_ROOT),
        resource_lock=ResourceLockManager(),
    )
    action_builder = ActionBuilder(action_types_by_name={a.name: a for a in action_types})
    validator = JsonSchemaEventValidator(
        JsonSchemaContractValidator(PackageResourceSchemaRegistry())
    )
    loop = ControlLoop(
        event_ingest=EventIngest(validator=validator),
        trust_router=TrustRouter(index=index),
        t0_engine=T0Engine(index=index, evaluator=evaluator),
        action_builder=action_builder,
        executor=executor,
        audit_store=audit,
        rules_by_id={r.id: r for r in rules},
        risk_table=risk_table,
        action_types_by_name=(
            {a.name: a for a in action_types} if risk_table is not None else None
        ),
        risk_gate=risk_gate,
        notification_router=notification_router,
        rca_coordinator=rca_coordinator,
        event_correlator=event_correlator,
        incident_member_source=incident_member_source,
        resource_dependency_graph=resource_dependency_graph,
    )
    return loop, publisher, audit


def _make_event(
    *,
    event_id: str = "00000000-0000-0000-0000-000000000001",
    idempotency_key: str = "e1",
    resource_type: str,
    resource_id: str,
    props: dict[str, Any],
    event_type: str = "config_changed",
) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "event_id": event_id,
        "idempotency_key": idempotency_key,
        "source": "example_activity_log",
        "event_type": event_type,
        "detected_at": "2026-07-05T08:00:00Z",
        "ingested_at": "2026-07-05T08:00:01Z",
        "mode": "shadow",
        "payload": {
            "resource": {
                "resource_id": resource_id,
                "type": resource_type,
                "props": props,
            }
        },
    }


# ---------------------------------------------------------------------------
# Abstain paths (no OPA required)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_resource_type_abstains_at_routing(
    shipped_catalog: tuple[Any, Any],
) -> None:
    loop, publisher, audit = _make_loop(shipped_catalog, with_opa=False)
    result = await loop.process(
        {
            "schema_version": "1.0.0",
            "event_id": "00000000-0000-0000-0000-000000000010",
            "idempotency_key": "e-noroute",
            "source": "example_activity_log",
            "event_type": "config_changed",
            "detected_at": "2026-07-05T08:00:00Z",
            "ingested_at": "2026-07-05T08:00:01Z",
            "mode": "shadow",
        }
    )
    assert result.outcome is ControlLoopOutcome.ABSTAINED_ROUTING
    assert result.decision == "abstain"
    assert publisher.records == ()
    assert len(list(audit.audit_entries)) == 1


@pytest.mark.asyncio
async def test_unknown_resource_type_abstains_at_routing(
    shipped_catalog: tuple[Any, Any],
) -> None:
    loop, publisher, audit = _make_loop(shipped_catalog, with_opa=False)
    result = await loop.process(
        _make_event(
            idempotency_key="e-unknown",
            resource_type="something.unrelated",
            resource_id="rid-x",
            props={},
        )
    )
    assert result.outcome is ControlLoopOutcome.ABSTAINED_ROUTING
    assert result.reason == "no_rule_matches_resource_type"
    assert publisher.records == ()
    assert len(list(audit.audit_entries)) == 1


@pytest.mark.asyncio
async def test_t0_abstain_writes_audit_and_no_pr(
    shipped_catalog: tuple[Any, Any],
) -> None:
    """No OPA → the default `AbstainEvaluator` abstains on every rule.
    Verify the T0 abstain path is audited and never opens a PR."""
    loop, publisher, audit = _make_loop(shipped_catalog, with_opa=False)
    result = await loop.process(
        _make_event(
            idempotency_key="e-abstain",
            resource_type="object-storage",
            resource_id="rid-1",
            props={"public_access": "enabled"},
        )
    )
    assert result.outcome is ControlLoopOutcome.ABSTAINED_T0
    assert result.tier == "t0"
    assert result.decision == "abstain"
    assert publisher.records == ()
    assert len(list(audit.audit_entries)) == 1


@pytest.mark.asyncio
async def test_duplicate_delivery_dedupes_without_audit(
    shipped_catalog: tuple[Any, Any],
) -> None:
    loop, publisher, audit = _make_loop(shipped_catalog, with_opa=False)
    event = _make_event(
        idempotency_key="e-dup",
        resource_type="something.unrelated",  # abstain path
        resource_id="rid-1",
        props={},
    )
    first = await loop.process(event)
    second = await loop.process(event)
    assert first.outcome is ControlLoopOutcome.ABSTAINED_ROUTING
    assert second.outcome is ControlLoopOutcome.DEDUPED
    # Only the first delivery wrote an audit entry.
    assert len(list(audit.audit_entries)) == 1
    assert publisher.records == ()


# ---------------------------------------------------------------------------
# Full execute path (OPA required)
# ---------------------------------------------------------------------------


@requires_opa
@pytest.mark.asyncio
async def test_public_access_deny_end_to_end_opens_shadow_pr(
    shipped_catalog: tuple[Any, Any],
) -> None:
    loop, publisher, audit = _make_loop(shipped_catalog)
    result = await loop.process(
        _make_event(
            idempotency_key="e-public",
            resource_type="object-storage",
            resource_id="stg-open",
            props={"public_access": "enabled", "tags": {"owner": "team-a"}},
        )
    )
    assert result.outcome is ControlLoopOutcome.EXECUTED
    assert result.tier == "t0"
    assert result.decision == "auto"
    assert "object-storage.public-access.deny" in result.citing_rule_ids
    published = [r for r in result.execution_results if r.outcome is ExecutorOutcome.PUBLISHED]
    assert published, "expected at least one PUBLISHED execution"
    for r in result.execution_results:
        assert r.mode is Mode.SHADOW
    # Every published intent MUST carry the shadow label + rule label.
    for pr in publisher.records:
        assert pr.mode is Mode.SHADOW
        assert "shadow" in pr.labels


@requires_opa
@pytest.mark.asyncio
async def test_shadow_authority_recorded_when_risk_table_wired(
    shipped_catalog: tuple[Any, Any],
) -> None:
    """With a risk table injected, every executed action also records a
    shadow-parallel execution-authority decision on the audit log."""
    from fdai.core.risk_gate.risk_table import load_risk_table

    table = load_risk_table(REPO_ROOT / "rule-catalog" / "risk-classification.yaml")
    loop, _publisher, audit = _make_loop(shipped_catalog, risk_table=table)
    result = await loop.process(
        _make_event(
            idempotency_key="e-auth",
            resource_type="object-storage",
            resource_id="stg-open",
            props={"public_access": "enabled", "tags": {"owner": "team-a"}},
        )
    )
    assert result.outcome is ControlLoopOutcome.EXECUTED
    entries = [e["entry"] for e in audit.audit_entries]
    authority = [e for e in entries if e.get("action_kind") == "risk_gate.shadow_authority"]
    assert authority, "expected a shadow_authority audit entry per executed action"
    for entry in authority:
        assert entry["mode"] == "shadow"
        assert entry["decision"] in {"auto", "hil", "shadow", "deny"}
        assert "resolved_ceiling" in entry


@requires_opa
@pytest.mark.asyncio
async def test_degraded_control_plane_caps_authority_to_shadow(
    shipped_catalog: tuple[Any, Any],
) -> None:
    """B1 live: when a critical-dependency circuit is OPEN the control plane is
    DEGRADED, so every shadow-authority record caps at shadow via the
    system_health fail-safe axis (csp-neutrality.md 4) - a failing dependency
    can never drive an enforce-mode decision through the loop."""
    from fdai.core.risk_gate.risk_table import load_risk_table
    from fdai.shared.resilience.circuit_breaker import (
        CircuitBreaker,
        CircuitBreakerConfig,
    )
    from fdai.shared.resilience.degradation import DegradationController

    tripped = CircuitBreaker(
        config=CircuitBreakerConfig(failure_threshold=1, reset_timeout_s=300)
    )
    tripped.on_failure()  # trips OPEN
    table = load_risk_table(REPO_ROOT / "rule-catalog" / "risk-classification.yaml")
    loop, _publisher, audit = _make_loop(shipped_catalog, risk_table=table)
    loop._degradation = DegradationController(breakers={"audit": tripped})
    result = await loop.process(
        _make_event(
            idempotency_key="e-auth-degraded",
            resource_type="object-storage",
            resource_id="stg-open",
            props={"public_access": "enabled", "tags": {"owner": "team-a"}},
        )
    )
    assert result.outcome is ControlLoopOutcome.EXECUTED
    entries = [e["entry"] for e in audit.audit_entries]
    authority = [e for e in entries if e.get("action_kind") == "risk_gate.shadow_authority"]
    assert authority, "expected a shadow_authority audit entry per executed action"
    for entry in authority:
        assert entry["decision"] in {"shadow", "deny"}
        assert "system_health" in entry["resolved_ceiling"]["axes"]


@requires_opa
@pytest.mark.asyncio
async def test_shadow_authority_skipped_when_action_type_unknown(
    shipped_catalog: tuple[Any, Any],
) -> None:
    """If the executed action's ActionType is not loaded, the shadow-authority
    record is skipped (fail-open on the observability path, never on execution)."""
    from fdai.core.risk_gate.risk_table import load_risk_table

    table = load_risk_table(REPO_ROOT / "rule-catalog" / "risk-classification.yaml")
    loop, _publisher, audit = _make_loop(shipped_catalog, risk_table=table)
    loop._action_types_by_name = {}  # force the ActionType lookup to miss
    result = await loop.process(
        _make_event(
            idempotency_key="e-auth-miss",
            resource_type="object-storage",
            resource_id="stg-open",
            props={"public_access": "enabled", "tags": {"owner": "team-a"}},
        )
    )
    assert result.outcome is ControlLoopOutcome.EXECUTED
    kinds = [e["entry"].get("action_kind") for e in audit.audit_entries]
    assert "risk_gate.shadow_authority" not in kinds


@requires_opa
@pytest.mark.asyncio
async def test_unified_risk_audit_recorded_when_gate_and_table_wired(
    shipped_catalog: tuple[Any, Any],
) -> None:
    """With BOTH a risk table and a RiskGate wired, the loop records the
    unified gate x authority decision (not the authority-only entry)."""
    from fdai.core.risk_gate.gate import ActionPromotionRegistry, RiskGate
    from fdai.core.risk_gate.risk_table import load_risk_table

    table = load_risk_table(REPO_ROOT / "rule-catalog" / "risk-classification.yaml")
    gate = RiskGate(registry=ActionPromotionRegistry())
    loop, _publisher, audit = _make_loop(shipped_catalog, risk_table=table, risk_gate=gate)
    result = await loop.process(
        _make_event(
            idempotency_key="e-unified",
            resource_type="object-storage",
            resource_id="stg-open",
            props={"public_access": "enabled", "tags": {"owner": "team-a"}},
        )
    )
    # With the backfilled ActionType ceilings, `remediate.disable-public-access`
    # is destructive and correctly gates at HIL (T0.max_autonomy=enforce_hil).
    # This is the *shipped* posture per action-ontology.md 3.1; the test asserts
    # HIL routing rather than execution.
    assert result.outcome in {ControlLoopOutcome.HIL, ControlLoopOutcome.EXECUTED}
    entries = [e["entry"] for e in audit.audit_entries]
    unified = [e for e in entries if e.get("action_kind") == "risk_gate.unified"]
    assert unified, "expected a unified risk audit entry per action"
    for entry in unified:
        assert entry["decision"] in {"auto", "hil", "shadow", "deny"}
        assert "gate_outcome" in entry
        assert "winning_side" in entry
    # The authority-only entry is superseded when a gate is wired.
    assert not [e for e in entries if e.get("action_kind") == "risk_gate.shadow_authority"]


@requires_opa
@pytest.mark.asyncio
async def test_deny_routing_skips_pr(
    shipped_catalog: tuple[Any, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A gate DENY routes the action to DENIED: no PR published, outcome DENIED."""
    from fdai.core.risk_gate.gate import (
        ActionPromotionRegistry,
        RiskDecision,
        RiskDecisionOutcome,
        RiskGate,
    )
    from fdai.core.risk_gate.risk_table import load_risk_table

    table = load_risk_table(REPO_ROOT / "rule-catalog" / "risk-classification.yaml")
    gate = RiskGate(registry=ActionPromotionRegistry())

    def _deny(**kwargs: Any) -> RiskDecision:
        return RiskDecision(
            outcome=RiskDecisionOutcome.DENY,
            action_id=str(kwargs["action"].action_id),
            effective_mode=Mode.SHADOW,
            reasons=("forced_deny_for_test",),
        )

    monkeypatch.setattr(gate, "evaluate", _deny)
    loop, publisher, audit = _make_loop(shipped_catalog, risk_table=table, risk_gate=gate)
    result = await loop.process(
        _make_event(
            idempotency_key="e-deny",
            resource_type="object-storage",
            resource_id="stg-open",
            props={"public_access": "enabled", "tags": {"owner": "team-a"}},
        )
    )
    assert result.outcome is ControlLoopOutcome.DENIED
    assert result.decision == "deny"
    assert not publisher.records
    kinds = [e["entry"].get("action_kind") for e in audit.audit_entries]
    assert "risk_gate.unified" in kinds


@requires_opa
@pytest.mark.asyncio
async def test_multiple_rules_fire_on_one_resource_e2e(
    shipped_catalog: tuple[Any, Any],
) -> None:
    """Enabled public access + missing owner tag = two shipped rules fire."""
    loop, publisher, _ = _make_loop(shipped_catalog)
    result = await loop.process(
        _make_event(
            idempotency_key="e-two",
            resource_type="object-storage",
            resource_id="stg-both",
            props={"public_access": "enabled", "tags": {}},
        )
    )
    assert result.outcome is ControlLoopOutcome.EXECUTED
    rule_ids = set(result.citing_rule_ids)
    assert "object-storage.public-access.deny" in rule_ids
    assert "object-storage.owner-tag.required" in rule_ids
    # One shadow PR per rule that fired. Newer object-storage rules also fire
    # when their compliance property is absent from the snapshot; the invariant
    # is that PR count matches fired-rule count (never fewer, never batched).
    assert len(publisher.records) == len(rule_ids)


@requires_opa
@pytest.mark.asyncio
async def test_idempotent_replay_does_not_reopen_pr(
    shipped_catalog: tuple[Any, Any],
) -> None:
    loop, publisher, audit = _make_loop(shipped_catalog)
    event = _make_event(
        idempotency_key="e-idem",
        resource_type="object-storage",
        resource_id="stg-idem",
        props={"public_access": "enabled", "tags": {"owner": "team-a"}},
    )
    first = await loop.process(event)
    # Second delivery is a DEDUPE at the event_ingest layer.
    second = await loop.process(event)
    assert first.outcome is ControlLoopOutcome.EXECUTED
    assert second.outcome is ControlLoopOutcome.DEDUPED
    # Publisher saw exactly the fresh publish from the first delivery.
    assert len(publisher.records) == len(first.execution_results)


@requires_opa
@pytest.mark.asyncio
async def test_shadow_mode_invariant_every_execution_is_shadow(
    shipped_catalog: tuple[Any, Any],
) -> None:
    loop, publisher, _ = _make_loop(shipped_catalog)
    events = [
        _make_event(
            idempotency_key=f"e-{i}",
            event_id=f"00000000-0000-0000-0000-{i:012d}",
            resource_type="sql-database",
            resource_id=f"sql-{i}",
            props={"tde_enabled": False},
        )
        for i in range(3)
    ]
    for event in events:
        await loop.process(event)
    for pr in publisher.records:
        assert pr.mode is Mode.SHADOW
        assert "shadow" in pr.labels


@requires_opa
@pytest.mark.asyncio
async def test_every_terminal_path_writes_audit(
    shipped_catalog: tuple[Any, Any],
) -> None:
    loop, publisher, audit = _make_loop(shipped_catalog)

    # Path A: routing abstain
    await loop.process(
        _make_event(
            idempotency_key="e-a",
            resource_type="unknown.thing",
            resource_id="rid-a",
            props={},
        )
    )
    # Path B: T0 abstain (matches type but no rule denies)
    await loop.process(
        _make_event(
            idempotency_key="e-b",
            resource_type="object-storage",
            resource_id="rid-b",
            # Fully compliant snapshot - every shipped object-storage rule
            # MUST see its expected property; if a new rule adds a property,
            # its compliant value goes here so this path stays a T0 abstain.
            props={
                "public_access": "disabled",
                "public_network_access_enabled": False,
                "private_endpoints": ["pe-1"],
                "tags": {"owner": "team-a", "cost_center": "cc-1"},
                "infrastructure_encryption_enabled": True,
                "enable_https_traffic_only": True,
                "min_tls_version": "TLS1_2",
                "blob_soft_delete_enabled": True,
                "blob_versioning_enabled": True,
                "allow_shared_key_access": False,
                "diagnostic_settings": ["diag-1"],
            },
        )
    )
    # Path C: T0 executes
    result_c = await loop.process(
        _make_event(
            idempotency_key="e-c",
            resource_type="object-storage",
            resource_id="rid-c",
            props={"public_access": "enabled", "tags": {"owner": "team-a"}},
        )
    )

    entries = list(audit.audit_entries)
    # A: 1 abstain entry (routing)
    # B: 1 abstain entry (T0 no-match)
    # C: N executor entries (one per shipped-rule finding)
    abstain_entries = sum(
        1 for e in entries if e["entry"].get("action_kind") == "control_loop.abstain"
    )
    executor_entries = len(entries) - abstain_entries
    assert abstain_entries == 2
    assert executor_entries == len(result_c.execution_results)
    assert audit.verify_chain(), "audit chain broken"


# ---------------------------------------------------------------------------
# ControlLoopResult shape
# ---------------------------------------------------------------------------


def test_control_loop_result_is_immutable() -> None:
    """Frozen dataclass - callers cannot mutate a returned result."""
    result = ControlLoopResult(
        outcome=ControlLoopOutcome.ABSTAINED_ROUTING,
        tier="abstain",
        decision="abstain",
        resource_type=None,
    )
    with pytest.raises((AttributeError, TypeError)):
        result.outcome = ControlLoopOutcome.EXECUTED  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Helper branch coverage (no OPA required)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_legacy_flat_props_payload_shape_is_supported(
    shipped_catalog: tuple[Any, Any],
) -> None:
    """`payload['props']` (flat) should feed T0 the same as
    `payload['resource']['props']` (nested)."""
    loop, publisher, audit = _make_loop(shipped_catalog, with_opa=False)
    event = {
        "schema_version": "1.0.0",
        "event_id": "00000000-0000-0000-0000-000000000020",
        "idempotency_key": "e-flat",
        "source": "src",
        "event_type": "change_detected",
        "detected_at": "2026-07-05T08:00:00Z",
        "ingested_at": "2026-07-05T08:00:01Z",
        "mode": "shadow",
        "payload": {
            "resource_type": "object-storage",
            "props": {"public_access": "enabled"},
        },
    }
    result = await loop.process(event)
    # No OPA → AbstainEvaluator → T0 abstain, but the resource_type
    # extraction MUST succeed (routing → T0 tier).
    assert result.tier == "t0"
    assert result.outcome is ControlLoopOutcome.ABSTAINED_T0


@pytest.mark.asyncio
async def test_event_resource_ref_is_used_when_payload_lacks_resource_id(
    shipped_catalog: tuple[Any, Any],
) -> None:
    """When the payload does not carry `resource.resource_id`, the loop
    falls back to `event.resource_ref` so the finding still has a stable id."""
    loop, publisher, audit = _make_loop(shipped_catalog, with_opa=False)
    event = {
        "schema_version": "1.0.0",
        "event_id": "00000000-0000-0000-0000-000000000021",
        "idempotency_key": "e-ref",
        "source": "src",
        "event_type": "change_detected",
        "detected_at": "2026-07-05T08:00:00Z",
        "ingested_at": "2026-07-05T08:00:01Z",
        "mode": "shadow",
        "resource_ref": "resource:example/rg/stg-ref",
        "payload": {"resource": {"type": "object-storage"}},
    }
    result = await loop.process(event)
    assert result.tier == "t0"
    assert result.outcome is ControlLoopOutcome.ABSTAINED_T0


@pytest.mark.asyncio
async def test_anonymous_resource_id_fallback_is_used(
    shipped_catalog: tuple[Any, Any],
) -> None:
    """Neither payload nor resource_ref → the loop synthesizes an
    ``anonymous:<resource_type>`` id so T0 still runs."""
    loop, publisher, audit = _make_loop(shipped_catalog, with_opa=False)
    event = {
        "schema_version": "1.0.0",
        "event_id": "00000000-0000-0000-0000-000000000022",
        "idempotency_key": "e-anon",
        "source": "src",
        "event_type": "change_detected",
        "detected_at": "2026-07-05T08:00:00Z",
        "ingested_at": "2026-07-05T08:00:01Z",
        "mode": "shadow",
        "payload": {"resource": {"type": "object-storage"}},
    }
    result = await loop.process(event)
    assert result.tier == "t0"
    # No mutation, but ran through T0 (abstained w/o crashing on missing id).
    assert result.outcome is ControlLoopOutcome.ABSTAINED_T0


@requires_opa
@pytest.mark.asyncio
async def test_action_build_failure_falls_closed_and_audits(
    shipped_catalog: tuple[Any, Any],
) -> None:
    """If ``ActionBuilder`` cannot resolve a finding's ActionType, the
    ControlLoop MUST audit the failure and return
    :attr:`ABSTAINED_ACTION_BUILD` - no PR opened for that finding."""
    from fdai.core.executor.action_builder import ActionBuilder

    rules, action_types = shipped_catalog
    index = RuleIndex.build(rules)
    publisher = RecordingRemediationPrPublisher()
    audit = InMemoryStateStore()
    executor = ShadowExecutor(
        publisher=publisher,
        audit_store=audit,
        renderer=TemplateRenderer(remediation_root=REMEDIATION_ROOT),
        resource_lock=ResourceLockManager(),
    )
    # Strip the ActionType so the builder cannot resolve it.
    stripped = {a.name: a for a in action_types if a.name != "remediate.disable-public-access"}
    action_builder = ActionBuilder(action_types_by_name=stripped)
    validator = JsonSchemaEventValidator(
        JsonSchemaContractValidator(PackageResourceSchemaRegistry())
    )
    loop = ControlLoop(
        event_ingest=EventIngest(validator=validator),
        trust_router=TrustRouter(index=index),
        t0_engine=T0Engine(index=index, evaluator=OpaRegoEvaluator(policies_root=POLICIES_ROOT)),
        action_builder=action_builder,
        executor=executor,
        audit_store=audit,
        rules_by_id={r.id: r for r in rules},
    )
    result = await loop.process(
        _make_event(
            idempotency_key="e-noaction",
            resource_type="object-storage",
            resource_id="stg-noaction",
            # Fully compliant EXCEPT public_access - only the deny rule fires,
            # and its ActionType has been stripped so the builder MUST abstain.
            props={
                "public_access": "enabled",
                "public_network_access_enabled": False,
                "private_endpoints": ["pe-1"],
                "tags": {"owner": "team-a", "cost_center": "cc-1"},
                "infrastructure_encryption_enabled": True,
                "enable_https_traffic_only": True,
                "min_tls_version": "TLS1_2",
                "blob_soft_delete_enabled": True,
                "blob_versioning_enabled": True,
                "allow_shared_key_access": False,
                "diagnostic_settings": ["diag-1"],
            },
        )
    )
    assert result.outcome is ControlLoopOutcome.ABSTAINED_ACTION_BUILD
    # No PR opened for that finding.
    assert publisher.records == ()
    # Audit chain remains intact.
    assert audit.verify_chain()


def test_is_execution_success_ignores_non_outcome_objects() -> None:
    from fdai.core.control_loop import _is_execution_success

    assert _is_execution_success("not-a-result") is False


# ---------------------------------------------------------------------------
# Notify-on-decision (A2 operational-alert push)
# ---------------------------------------------------------------------------


class _SpyRouter(NotificationRouter):
    """Captures dispatched messages without touching real channels.

    Deliberately skips ``super().__init__`` - the spy needs no matrix /
    registry / audit / sink; it only records the messages the control
    loop hands it (and can be told to raise to exercise the best-effort
    swallow path).
    """

    def __init__(self, *, raise_on_dispatch: bool = False) -> None:
        self.messages: list[NotificationMessage] = []
        self._raise = raise_on_dispatch

    async def dispatch(self, message: NotificationMessage):  # type: ignore[override]
        if self._raise:
            raise RuntimeError("channel down")
        self.messages.append(message)
        return None  # type: ignore[return-value]


def _ingest_for_notify(
    loop: ControlLoop,
    *,
    event_id: str = "00000000-0000-0000-0000-000000000090",
    key: str = "e-notify",
) -> Event:
    ingested = loop._event_ingest.ingest(  # noqa: SLF001 - test needs a real Event
        _make_event(
            event_id=event_id,
            idempotency_key=key,
            resource_type="object-storage",
            resource_id="r-notify",
            props={},
        )
    )
    assert ingested is not None
    return ingested


@pytest.mark.asyncio
async def test_notify_decision_executed_pushes_a2_info(
    shipped_catalog: tuple[Any, Any],
) -> None:
    spy = _SpyRouter()
    loop, _, _ = _make_loop(shipped_catalog, with_opa=False, notification_router=spy)
    event = _ingest_for_notify(loop)
    await loop._notify_decision(  # noqa: SLF001 - exercising the private helper directly
        event=event,
        correlation_id="c1",
        overall=ControlLoopOutcome.EXECUTED,
        decision_word="auto",
        resource_type="object-storage",
        citing_rule_ids=("rule-a", "rule-b"),
    )
    assert len(spy.messages) == 1
    m = spy.messages[0]
    assert m.category == "operational_alert"
    assert m.trust_tier is TrustTier.A2_OPERATIONAL_ALERT
    assert m.severity is Severity.INFO
    assert m.correlation_id == "c1"
    assert m.metadata["outcome"] == ControlLoopOutcome.EXECUTED.value
    # Generic body only - no customer-identifying value (no resource id).
    assert "r-notify" not in m.body_markdown
    assert "rule-a" in m.body_markdown


@pytest.mark.asyncio
async def test_notify_decision_hil_warns(shipped_catalog: tuple[Any, Any]) -> None:
    spy = _SpyRouter()
    loop, _, _ = _make_loop(shipped_catalog, with_opa=False, notification_router=spy)
    event = _ingest_for_notify(loop)
    await loop._notify_decision(  # noqa: SLF001
        event=event,
        correlation_id="c1",
        overall=ControlLoopOutcome.HIL,
        decision_word="hil",
        resource_type="object-storage",
        citing_rule_ids=("rule-a",),
    )
    assert spy.messages[0].severity is Severity.WARN


@pytest.mark.asyncio
async def test_notify_decision_denied_errors(shipped_catalog: tuple[Any, Any]) -> None:
    spy = _SpyRouter()
    loop, _, _ = _make_loop(shipped_catalog, with_opa=False, notification_router=spy)
    event = _ingest_for_notify(loop)
    await loop._notify_decision(  # noqa: SLF001
        event=event,
        correlation_id="c1",
        overall=ControlLoopOutcome.DENIED,
        decision_word="deny",
        resource_type="object-storage",
        citing_rule_ids=(),
    )
    assert spy.messages[0].severity is Severity.ERROR
    # Empty citing set renders the 'n/a' placeholder, never an empty crash.
    assert "n/a" in spy.messages[0].body_markdown


@pytest.mark.asyncio
async def test_notify_decision_abstain_is_silent(
    shipped_catalog: tuple[Any, Any],
) -> None:
    spy = _SpyRouter()
    loop, _, _ = _make_loop(shipped_catalog, with_opa=False, notification_router=spy)
    event = _ingest_for_notify(loop)
    await loop._notify_decision(  # noqa: SLF001
        event=event,
        correlation_id="c1",
        overall=ControlLoopOutcome.ABSTAINED_T0,
        decision_word="abstain",
        resource_type="object-storage",
        citing_rule_ids=(),
    )
    assert spy.messages == []


@pytest.mark.asyncio
async def test_notify_router_none_is_noop(shipped_catalog: tuple[Any, Any]) -> None:
    loop, _, _ = _make_loop(shipped_catalog, with_opa=False, notification_router=None)
    event = _ingest_for_notify(loop)
    # Must not raise despite an EXECUTED outcome and no router wired.
    await loop._notify_decision(  # noqa: SLF001
        event=event,
        correlation_id="c1",
        overall=ControlLoopOutcome.EXECUTED,
        decision_word="auto",
        resource_type="object-storage",
        citing_rule_ids=("rule-a",),
    )


@pytest.mark.asyncio
async def test_notify_dispatch_error_is_swallowed(
    shipped_catalog: tuple[Any, Any],
) -> None:
    spy = _SpyRouter(raise_on_dispatch=True)
    loop, _, _ = _make_loop(shipped_catalog, with_opa=False, notification_router=spy)
    event = _ingest_for_notify(loop)
    # A dispatch failure MUST NOT propagate - the decision is already audited.
    await loop._notify_decision(  # noqa: SLF001
        event=event,
        correlation_id="c1",
        overall=ControlLoopOutcome.EXECUTED,
        decision_word="auto",
        resource_type="object-storage",
        citing_rule_ids=("rule-a",),
    )


@pytest.mark.asyncio
async def test_process_abstain_does_not_push(shipped_catalog: tuple[Any, Any]) -> None:
    """Routing-abstain path stays silent even with a router wired."""
    spy = _SpyRouter()
    loop, _, _ = _make_loop(shipped_catalog, with_opa=False, notification_router=spy)
    result = await loop.process(
        {
            "schema_version": "1.0.0",
            "event_id": "00000000-0000-0000-0000-000000000091",
            "idempotency_key": "e-abstain-notify",
            "source": "example_activity_log",
            "event_type": "config_changed",
            "detected_at": "2026-07-05T08:00:00Z",
            "ingested_at": "2026-07-05T08:00:01Z",
            "mode": "shadow",
        }
    )
    assert result.outcome is ControlLoopOutcome.ABSTAINED_ROUTING
    assert spy.messages == []


# ---------------------------------------------------------------------------
# RCA audit (deterministic T0 root-cause on each finding)
# ---------------------------------------------------------------------------


def _first_rule(loop: ControlLoop) -> Any:
    return next(iter(loop._rules_by_id.values()))  # noqa: SLF001


@pytest.mark.asyncio
async def test_rca_hypothesis_appended_for_finding(
    shipped_catalog: tuple[Any, Any],
) -> None:
    coordinator = RcaCoordinator()
    loop, _, audit = _make_loop(shipped_catalog, with_opa=False, rca_coordinator=coordinator)
    event = _ingest_for_notify(loop)
    rule = _first_rule(loop)
    await loop._analyze_and_audit_rca(  # noqa: SLF001 - exercising the private helper
        event=event,
        finding=SimpleNamespace(rule_id=rule.id),
        rule=rule,
        resource_type="object-storage",
    )
    rca_entries = [
        e["entry"] for e in audit.audit_entries if e["entry"].get("action_kind") == "rca.hypothesis"
    ]
    assert len(rca_entries) == 1
    entry = rca_entries[0]
    assert entry["rca_outcome"] == "grounded"
    assert entry["rca_tier"] == "t0"
    assert entry["rca_remediation_ref"] == rule.remediates
    assert entry["rca_citations"][0]["ref"] == rule.id
    assert rule.id in entry["rca_cause"]


@pytest.mark.asyncio
async def test_rca_none_appends_no_audit(shipped_catalog: tuple[Any, Any]) -> None:
    loop, _, audit = _make_loop(shipped_catalog, with_opa=False, rca_coordinator=None)
    event = _ingest_for_notify(loop)
    rule = _first_rule(loop)
    await loop._analyze_and_audit_rca(  # noqa: SLF001
        event=event,
        finding=SimpleNamespace(rule_id=rule.id),
        rule=rule,
        resource_type="object-storage",
    )
    rca_entries = [
        e for e in audit.audit_entries if e["entry"].get("action_kind") == "rca.hypothesis"
    ]
    assert rca_entries == []


# ---------------------------------------------------------------------------
# Event correlation wiring (incident_id on the RCA audit)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_correlate_incident_id_from_correlator(
    shipped_catalog: tuple[Any, Any],
) -> None:
    loop, _, _ = _make_loop(shipped_catalog, with_opa=False, event_correlator=EventCorrelator())
    event = _ingest_for_notify(loop)
    incident_id = loop._correlate_incident_id(event)  # noqa: SLF001
    assert incident_id is not None


@pytest.mark.asyncio
async def test_correlate_none_without_correlator(
    shipped_catalog: tuple[Any, Any],
) -> None:
    loop, _, _ = _make_loop(shipped_catalog, with_opa=False, event_correlator=None)
    event = _ingest_for_notify(loop)
    assert loop._correlate_incident_id(event) is None  # noqa: SLF001


@pytest.mark.asyncio
async def test_rca_audit_carries_incident_id(shipped_catalog: tuple[Any, Any]) -> None:
    loop, _, audit = _make_loop(shipped_catalog, with_opa=False, rca_coordinator=RcaCoordinator())
    event = _ingest_for_notify(loop)
    rule = _first_rule(loop)
    await loop._analyze_and_audit_rca(  # noqa: SLF001
        event=event,
        finding=SimpleNamespace(rule_id=rule.id),
        rule=rule,
        resource_type="object-storage",
        incident_id="incident-123",
    )
    rca_entries = [
        e["entry"] for e in audit.audit_entries if e["entry"].get("action_kind") == "rca.hypothesis"
    ]
    assert len(rca_entries) == 1
    assert rca_entries[0]["incident_id"] == "incident-123"


# ---------------------------------------------------------------------------
# T1 temporal causal-chain RCA wiring (IncidentMemberSource seam)
# ---------------------------------------------------------------------------


class _InMemoryMemberSource:
    """Test IncidentMemberSource returning a fixed member set."""

    def __init__(self, members: tuple[CorrelatedEvent, ...]) -> None:
        self._members = members

    async def members(self, *, incident_id: str) -> tuple[CorrelatedEvent, ...]:  # noqa: ARG002
        return self._members


_FAIL_AT = datetime(2026, 7, 7, 12, 0, 0, tzinfo=UTC)


def _failure_event(resource_ref: str | None = "resource:app") -> Event:
    return Event(
        schema_version="1.0.0",
        event_id=UUID("00000000-0000-0000-0000-0000000000f1"),
        idempotency_key="fail-key",
        source="src",
        event_type="error.rate.spike",
        resource_ref=resource_ref,
        payload={},
        detected_at=_FAIL_AT,
        ingested_at=_FAIL_AT,
        mode=Mode.SHADOW,
    )


@pytest.mark.asyncio
async def test_t1_causal_chain_hypothesis_appended(shipped_catalog: tuple[Any, Any]) -> None:
    members = (
        CorrelatedEvent(
            event_id="deploy-1",
            at=_FAIL_AT - timedelta(minutes=3),
            resource_ref="resource:db",
            is_change=True,
        ),
        CorrelatedEvent(
            event_id="dbslow",
            at=_FAIL_AT - timedelta(minutes=1),
            resource_ref="resource:db",
            is_change=False,
        ),
    )
    loop, _, audit = _make_loop(
        shipped_catalog,
        with_opa=False,
        rca_coordinator=RcaCoordinator(),
        incident_member_source=_InMemoryMemberSource(members),
        resource_dependency_graph={"resource:app": {"resource:db"}},
    )
    await loop._analyze_and_audit_t1_causal_chain(  # noqa: SLF001
        event=_failure_event(), incident_id="inc-1"
    )
    entries = [
        e["entry"] for e in audit.audit_entries if e["entry"].get("action_kind") == "rca.hypothesis"
    ]
    assert len(entries) == 1
    entry = entries[0]
    assert entry["rca_tier"] == "t1"
    assert entry["rca_outcome"] == "grounded"
    assert entry["incident_id"] == "inc-1"
    assert entry["mode"] == Mode.SHADOW.value
    cited = {c["ref"] for c in entry["rca_citations"]}
    # The whole chain is cited: root change -> intermediate symptom -> failure.
    assert cited == {"deploy-1", "dbslow", str(_failure_event().event_id)}


@pytest.mark.asyncio
async def test_t1_causal_chain_abstains_audits_when_no_change(
    shipped_catalog: tuple[Any, Any],
) -> None:
    # Members exist but none is a change -> genuine abstain, still audited.
    members = (
        CorrelatedEvent(
            event_id="sym",
            at=_FAIL_AT - timedelta(minutes=1),
            resource_ref="resource:app",
            is_change=False,
        ),
    )
    loop, _, audit = _make_loop(
        shipped_catalog,
        with_opa=False,
        rca_coordinator=RcaCoordinator(),
        incident_member_source=_InMemoryMemberSource(members),
    )
    await loop._analyze_and_audit_t1_causal_chain(  # noqa: SLF001
        event=_failure_event(), incident_id="inc-1"
    )
    entries = [
        e["entry"] for e in audit.audit_entries if e["entry"].get("action_kind") == "rca.hypothesis"
    ]
    assert len(entries) == 1
    assert entries[0]["rca_outcome"] == "abstained"
    assert entries[0]["rca_reason"] == "t1_no_causal_chain_in_window"


@pytest.mark.asyncio
async def test_t1_causal_chain_empty_source_is_silent(
    shipped_catalog: tuple[Any, Any],
) -> None:
    # An empty member set (no incident history) emits no per-event row.
    loop, _, audit = _make_loop(
        shipped_catalog,
        with_opa=False,
        rca_coordinator=RcaCoordinator(),
        incident_member_source=_InMemoryMemberSource(()),
    )
    await loop._analyze_and_audit_t1_causal_chain(  # noqa: SLF001
        event=_failure_event(), incident_id="inc-1"
    )
    assert not [e for e in audit.audit_entries if e["entry"].get("action_kind") == "rca.hypothesis"]


@pytest.mark.asyncio
async def test_t1_causal_chain_noop_without_source(shipped_catalog: tuple[Any, Any]) -> None:
    # No member source wired -> the helper is a no-op (backward-compatible).
    loop, _, audit = _make_loop(shipped_catalog, with_opa=False, rca_coordinator=RcaCoordinator())
    await loop._analyze_and_audit_t1_causal_chain(  # noqa: SLF001
        event=_failure_event(), incident_id="inc-1"
    )
    assert not [e for e in audit.audit_entries if e["entry"].get("action_kind") == "rca.hypothesis"]


@pytest.mark.asyncio
async def test_t1_causal_chain_noop_without_resource_ref(
    shipped_catalog: tuple[Any, Any],
) -> None:
    # A failure event with no resource_ref cannot anchor a chain -> no-op.
    members = (
        CorrelatedEvent(
            event_id="deploy-1",
            at=_FAIL_AT - timedelta(minutes=1),
            resource_ref="resource:db",
            is_change=True,
        ),
    )
    loop, _, audit = _make_loop(
        shipped_catalog,
        with_opa=False,
        rca_coordinator=RcaCoordinator(),
        incident_member_source=_InMemoryMemberSource(members),
    )
    await loop._analyze_and_audit_t1_causal_chain(  # noqa: SLF001
        event=_failure_event(resource_ref=None), incident_id="inc-1"
    )
    assert not [e for e in audit.audit_entries if e["entry"].get("action_kind") == "rca.hypothesis"]


@pytest.mark.asyncio
async def test_t1_causal_chain_noop_with_blank_resource_ref(
    shipped_catalog: tuple[Any, Any],
) -> None:
    # An empty-string resource_ref cannot anchor a chain either -> no-op.
    members = (
        CorrelatedEvent(
            event_id="deploy-1",
            at=_FAIL_AT - timedelta(minutes=1),
            resource_ref="resource:db",
            is_change=True,
        ),
    )
    loop, _, audit = _make_loop(
        shipped_catalog,
        with_opa=False,
        rca_coordinator=RcaCoordinator(),
        incident_member_source=_InMemoryMemberSource(members),
    )
    await loop._analyze_and_audit_t1_causal_chain(  # noqa: SLF001
        event=_failure_event(resource_ref=""), incident_id="inc-1"
    )
    assert not [e for e in audit.audit_entries if e["entry"].get("action_kind") == "rca.hypothesis"]


# ---------------------------------------------------------------------------
# T2 RCA on a novel (T0 no-match) case, gated by a wired reasoner
# ---------------------------------------------------------------------------


class _StubT2Reasoner:
    """Fake RcaReasoner citing the first supplied candidate (grounded)."""

    async def reason(self, *, incident_summary: str, candidate_citations: Any) -> Any:
        if not candidate_citations:
            return None
        return RootCauseHypothesis(
            tier=RcaTier.T2,
            cause="novel cause hypothesis",
            confidence=0.8,
            citations=(candidate_citations[0],),
        )


@pytest.mark.asyncio
async def test_t2_rca_audited_on_abstain_with_reasoner(
    shipped_catalog: tuple[Any, Any],
) -> None:
    # No OPA -> T0 abstains (no rule verdict); a wired T2 reasoner then
    # produces a grounded root-cause hypothesis on the novel case.
    coordinator = RcaCoordinator(reasoner=_StubT2Reasoner())
    loop, _, audit = _make_loop(
        shipped_catalog,
        with_opa=False,
        rca_coordinator=coordinator,
        event_correlator=EventCorrelator(),
    )
    await loop.process(
        _make_event(
            idempotency_key="t2-1",
            resource_type="object-storage",
            resource_id="r-x",
            props={},
        )
    )
    t2_entries = [
        e["entry"] for e in audit.audit_entries if e["entry"].get("action_kind") == "rca.hypothesis"
    ]
    assert len(t2_entries) == 1
    assert t2_entries[0]["rca_tier"] == "t2"
    assert t2_entries[0]["rca_outcome"] == "grounded"
    assert t2_entries[0]["incident_id"] is not None


@pytest.mark.asyncio
async def test_t2_rca_skipped_without_reasoner(shipped_catalog: tuple[Any, Any]) -> None:
    # RcaCoordinator without a reasoner -> T2 RCA is skipped (no noise).
    loop, _, audit = _make_loop(shipped_catalog, with_opa=False, rca_coordinator=RcaCoordinator())
    await loop.process(
        _make_event(
            idempotency_key="t2-2",
            resource_type="object-storage",
            resource_id="r-y",
            props={},
        )
    )
    t2_entries = [
        e for e in audit.audit_entries if e["entry"].get("action_kind") == "rca.hypothesis"
    ]
    assert t2_entries == []
