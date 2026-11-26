"""Adapter fixtures, request builders, and run-store seeding for governed chaos tests."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

import yaml
from fdai.core.chaos.factory import ScenarioFactory
from fdai.core.chaos.run_state import ChaosRunState
from fdai.core.chaos.run_store import ChaosRunStore
from fdai.core.chaos.scenario_catalog import CatalogEntry
from fdai.delivery.chaos.governed import GovernedChaosExecutionAdapter
from fdai.delivery.chaos.governed_bindings import ChaosApprovalEvidence, GovernedChaosBindings
from fdai.rule_catalog.schema.action_type import load_action_type_from_mapping
from fdai.shared.contracts.models import (
    ActionStopCondition,
    Mode,
    OntologyActionType,
    StopConditionKind,
)
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.providers.resource_lock import ResourceLock
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai.shared.providers.tool import ToolCallRequest

from tests.delivery.chaos.governed_doubles import (
    APPROVAL,
    ENFORCED,
    ENTRY,
    NOW,
    RUN_ID,
    SCENARIO_ID,
    Dispatcher,
    DistributedLock,
    EvidenceCollector,
    Injector,
    Planner,
    Probe,
    Registry,
    Verifier,
    instant_sleep,
    ledger,
    run_plan,
)

_ACTION_TYPE_PATH = (
    Path(__file__).resolve().parents[5]
    / "rule-catalog"
    / "action-types"
    / "tool.run-chaos-experiment.yaml"
)


def chaos_action_type() -> OntologyActionType:
    """Load the catalog chaos ActionType, including its authoritative tier ceilings."""

    raw = yaml.safe_load(_ACTION_TYPE_PATH.read_text(encoding="utf-8"))
    return load_action_type_from_mapping(raw, schema_registry=PackageResourceSchemaRegistry())


@dataclass
class GovernedFixture:
    adapter: GovernedChaosExecutionAdapter
    injector: Injector
    dispatcher: Dispatcher
    planner: Planner
    verifier: Verifier
    state_store: InMemoryStateStore
    bindings: GovernedChaosBindings


def governed_fixture(
    *,
    injector: Injector | None = None,
    planner: Planner | None = None,
    approval: ChaosApprovalEvidence | None = APPROVAL,
    eligible: bool = True,
    enforced: frozenset[str] = ENFORCED,
    dispatcher: Dispatcher | None = None,
    collector: EvidenceCollector | None = None,
    state_store: InMemoryStateStore | None = None,
    sleeper: Any = instant_sleep,
    lock: ResourceLock | None = None,
    detects: bool = True,
    entry: CatalogEntry = ENTRY,
) -> GovernedFixture:
    live_injector = injector or Injector()
    factory = ScenarioFactory()
    factory.register_injector("test", lambda _entry, _context: live_injector)
    factory.register_probe("pod_restart", lambda _entry, _context: Probe(detects=detects))
    store = state_store or InMemoryStateStore()
    run_planner = planner or Planner(run_plan())
    verifier = Verifier(approval)
    recovery = dispatcher or Dispatcher()
    bindings = GovernedChaosBindings(
        state_store=store,
        action_registry=Registry(enforced),
        scenario_ledger=ledger(eligible=eligible, entry=entry),
        approval_verifier=verifier,
        planner=run_planner,
        recovery_dispatcher=recovery,
        evidence_collector=collector or EvidenceCollector(),
        target_lock=lock or DistributedLock(),
    )
    adapter = GovernedChaosExecutionAdapter(
        entries=(entry,),
        promoted_ids=frozenset({entry.id}),
        factory=factory,
        context={},
        bindings=bindings,
        action_type=chaos_action_type(),
        clock=lambda: NOW,
        sleeper=sleeper,
        lock_timeout_seconds=1.0,
    )
    return GovernedFixture(adapter, live_injector, recovery, run_planner, verifier, store, bindings)


def enforce_request(
    *,
    mode: Mode = Mode.ENFORCE,
    approval_ref: str = "approval-1",
    time_box: bool = True,
    targets: tuple[str, ...] = ("pod-a",),
    action_type_name: str = "tool.run-chaos-experiment",
    tier: str | None = "t0",
    key: str = "chaos-key-1",
    scenario_id: str = SCENARIO_ID,
) -> ToolCallRequest:
    metadata = {"approval_ref": approval_ref}
    if tier is not None:
        metadata["tier"] = tier
    return ToolCallRequest(
        action_id=UUID("00000000-0000-0000-0000-000000000094"),
        idempotency_key=key,
        action_type_name=action_type_name,
        rule_ids=(scenario_id,),
        tool_ref=scenario_id,
        arguments={"scenario_id": scenario_id, "targets": list(targets)},
        labels=("enforce",) if mode is Mode.ENFORCE else ("shadow",),
        mode=mode,
        stop_conditions=(
            (ActionStopCondition(kind=StopConditionKind.TIME_BOX_EXCEEDED_SECONDS, seconds=600),)
            if time_box
            else ()
        ),
        metadata=metadata,
    )


async def run_state(fixture: GovernedFixture) -> ChaosRunState | None:
    snapshot = await ChaosRunStore(state_store=fixture.state_store).get(RUN_ID)
    return snapshot.state if snapshot is not None else None


async def seed_run(store: InMemoryStateStore, last: ChaosRunState) -> None:
    run_store = ChaosRunStore(state_store=store)
    snapshot = await run_store.create(run_id=RUN_ID, at=NOW)
    for state in (
        ChaosRunState.IMPACT_CHECKED,
        ChaosRunState.DRY_RUN_VERIFIED,
        ChaosRunState.APPROVED,
        ChaosRunState.INJECTING,
        ChaosRunState.OBSERVING,
    ):
        snapshot = await run_store.transition(
            snapshot,
            target=state,
            idempotency_key=f"{RUN_ID}:{state.value}",
            at=NOW,
        )
        if state is last:
            return


def audit_kinds(fixture: GovernedFixture) -> list[str]:
    return [str(item["entry"]["action_kind"]) for item in fixture.state_store.audit_entries]
