"""Cross-vertical per-resource serialization invariant.

Design reference:
[phase-3 § Unified Control Loop](../../docs/roadmap/phases/phase-3-integrated-loop.md)

> Actions that mutate the same resource are serialized on a per-resource
> key; the ``executor`` holds the per-resource lock for the whole action
> window. Concurrent mutations on one resource are mutually excluded
> across domains.

The unit tests in :mod:`tests.core.executor.test_lock` cover the lock
manager in isolation. This module proves the invariant at the
:class:`ControlLoop` seam:

- **Two concurrent events targeting the same resource** are serialized
  by :class:`ResourceLockManager` inside the executor. The second call
  runs only after the first has released the lock.
- **Two concurrent events targeting distinct resources** run in
  parallel. Isolation is per-resource, not global.

At the P1 level ``ControlLoop`` runs single-vertical events (there's no
risk-gate cross-vertical routing yet), so "cross-vertical" is expressed
here as two rules of different families landing on one resource. That
mirrors the P3 case where a Change and a FinOps action both target the
same object-storage id.
"""

from __future__ import annotations

import asyncio
import shutil
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
import yaml

from fdai.core.control_loop import ControlLoop, ControlLoopOutcome
from fdai.core.event_ingest import EventIngest
from fdai.core.executor import (
    ResourceLockManager,
    ShadowExecutor,
    TemplateRenderer,
)
from fdai.core.executor.action_builder import ActionBuilder
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
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.contracts.validation import (
    JsonSchemaContractValidator,
    JsonSchemaEventValidator,
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
    not _OPA_PRESENT,
    reason="opa binary not found on PATH; skip lock integration",
)


class _RecordingResourceLock(ResourceLockManager):
    """Wraps the real lock manager and records enter/exit order for probes."""

    def __init__(self, events: list[tuple[str, str]], hold: float = 0.0) -> None:
        super().__init__()
        self._events = events
        self._hold = hold

    @asynccontextmanager  # type: ignore[override]
    async def acquire(self, resource_id: str):  # type: ignore[override]
        async with super().acquire(resource_id):
            self._events.append(("enter", resource_id))
            if self._hold:
                await asyncio.sleep(self._hold)
            try:
                yield
            finally:
                self._events.append(("exit", resource_id))


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


def _loop_with_lock(
    shipped_catalog: tuple[Any, Any],
    lock: ResourceLockManager,
) -> tuple[ControlLoop, RecordingRemediationPrPublisher, InMemoryStateStore]:
    rules, action_types = shipped_catalog
    index = RuleIndex.build(rules)
    evaluator = OpaRegoEvaluator(policies_root=POLICIES_ROOT)
    publisher = RecordingRemediationPrPublisher()
    audit = InMemoryStateStore()
    executor = ShadowExecutor(
        publisher=publisher,
        audit_store=audit,
        renderer=TemplateRenderer(remediation_root=REMEDIATION_ROOT),
        resource_lock=lock,
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
    )
    return loop, publisher, audit


def _event(
    *,
    idempotency_key: str,
    resource_id: str,
    resource_type: str,
    props: dict[str, Any],
    event_id: str,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "event_id": event_id,
        "idempotency_key": idempotency_key,
        "source": "example_activity_log",
        "event_type": "config_changed",
        "detected_at": "2026-07-06T08:00:00Z",
        "ingested_at": "2026-07-06T08:00:01Z",
        "mode": "shadow",
        "payload": {
            "resource": {
                "resource_id": resource_id,
                "type": resource_type,
                "props": props,
            }
        },
    }


@requires_opa
@pytest.mark.asyncio
async def test_concurrent_events_on_same_resource_are_serialized(
    shipped_catalog: tuple[Any, Any],
) -> None:
    """Two events targeting the same resource_id MUST NOT interleave.

    The events fire distinct rules (public-access.deny + owner-tag);
    both actions target the same object-storage resource id, so the
    per-resource lock serializes them. Enter/exit order asserted via
    a probe wrapping :class:`ResourceLockManager`.
    """
    events_log: list[tuple[str, str]] = []
    lock = _RecordingResourceLock(events_log, hold=0.02)
    loop, publisher, _audit = _loop_with_lock(shipped_catalog, lock)

    event_a = _event(
        idempotency_key="lock-a",
        resource_id="stg-shared",
        resource_type="object-storage",
        props={
            "public_access": "enabled",
            "tags": {"owner": "team-a", "cost_center": "cc-1"},
        },
        event_id="00000000-0000-0000-0000-000000000301",
    )
    event_b = _event(
        idempotency_key="lock-b",
        resource_id="stg-shared",  # same resource id as event_a
        resource_type="object-storage",
        props={
            "public_access": "disabled",
            "tags": {"cost_center": "cc-1"},  # missing owner tag
        },
        event_id="00000000-0000-0000-0000-000000000302",
    )

    await asyncio.gather(loop.process(event_a), loop.process(event_b))

    # Only same-resource acquisitions are recorded — every enter MUST be
    # followed by its own exit before the next enter (serialization).
    same_resource = [entry for entry in events_log if entry[1] == "fdai:resource:stg-shared"]
    assert same_resource, "no lock acquisitions recorded on the shared resource"
    balance = 0
    for kind, _rid in same_resource:
        if kind == "enter":
            balance += 1
        else:
            balance -= 1
        assert balance <= 1, (
            f"lock held by more than one coroutine at once — series={same_resource}"
        )
    assert balance == 0

    # Both events published (or dedup on identical content). Shadow-mode
    # invariant holds.
    for pr in publisher.records:
        assert "shadow" in pr.labels


@requires_opa
@pytest.mark.asyncio
async def test_concurrent_events_on_different_resources_run_in_parallel(
    shipped_catalog: tuple[Any, Any],
) -> None:
    """Distinct resources MUST NOT block each other.

    Two events targeting different resource ids race — the lock
    guarantees no ordering. This is the counterexample to the previous
    test: isolation is per-resource, not global.
    """
    events_log: list[tuple[str, str]] = []
    lock = _RecordingResourceLock(events_log, hold=0.02)
    loop, publisher, _audit = _loop_with_lock(shipped_catalog, lock)

    event_a = _event(
        idempotency_key="par-a",
        resource_id="stg-alpha",
        resource_type="object-storage",
        props={
            "public_access": "enabled",
            "tags": {"owner": "team-a", "cost_center": "cc-1"},
        },
        event_id="00000000-0000-0000-0000-000000000303",
    )
    event_b = _event(
        idempotency_key="par-b",
        resource_id="stg-beta",
        resource_type="object-storage",
        props={
            "public_access": "enabled",
            "tags": {"owner": "team-b", "cost_center": "cc-2"},
        },
        event_id="00000000-0000-0000-0000-000000000304",
    )

    result_a, result_b = await asyncio.gather(loop.process(event_a), loop.process(event_b))
    assert result_a.outcome is ControlLoopOutcome.EXECUTED
    assert result_b.outcome is ControlLoopOutcome.EXECUTED

    # Different resources MAY interleave — enters MAY appear back-to-back
    # before any exit. Balance MAY go to 2.
    balance = 0
    peak = 0
    resource_events = [entry for entry in events_log if entry[1].startswith("fdai:resource:")]
    for kind, _rid in resource_events:
        if kind == "enter":
            balance += 1
            peak = max(peak, balance)
        else:
            balance -= 1
    assert peak >= 2, (
        f"distinct resources did not overlap under the lock — peak={peak} trace={resource_events}"
    )
    assert balance == 0

    # Shadow-mode invariant holds on both.
    assert publisher.records
    for pr in publisher.records:
        assert "shadow" in pr.labels
