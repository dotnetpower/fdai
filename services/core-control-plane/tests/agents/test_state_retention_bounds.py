"""Retention bounds for state rows that were written without any bound."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest
from fdai.agents._framework import forseti_baseline_evaluation as baseline
from fdai.agents._framework import forseti_no_rule_fold as fold_module
from fdai.agents._framework.forseti_baseline_evaluation import (
    BASELINE_EVALUATION_OUTCOME_PREFIX,
    record_baseline_evaluation,
)
from fdai.agents._framework.forseti_no_rule_fold import NO_RULE_FOLD_PREFIX
from fdai.core.ontology_platform.aks_diagnostic_receipt_service import (
    AksDiagnosticReceiptService,
)
from fdai.core.tiers.t0_deterministic import PolicyResult, RuleIndex, T0Engine
from fdai.delivery import aks_diagnostic_receipts as receipts
from fdai.shared.providers.inventory import ResourceRecord
from fdai.shared.providers.testing.state_store import InMemoryStateStore

from tests.agents.test_forseti_baseline_evaluation import (
    CATALOG_A,
    NOW,
    _audit_binder,
    _Evaluator,
    _observation,
    _rule,
)
from tests.agents.test_judgment_execution_restart import _bus, _event, _forseti
from tests.delivery.test_aks_diagnostic_receipts import _context


async def _evaluate(store: InMemoryStateStore, generation: str, resources: int) -> None:
    rules = (_rule("rule.one"),)
    observation = _observation(
        *(
            ResourceRecord(
                resource_id=f"{generation}-resource-{index}",
                type="example.resource",
                props={"ready": True},
                last_seen=NOW.isoformat(),
            )
            for index in range(resources)
        )
    )
    await record_baseline_evaluation(
        observation=observation.__class__(
            generation=generation,
            resources=observation.resources,
            links=(),
            complete=True,
            recorded_at=NOW,
        ),
        engine=T0Engine(
            index=RuleIndex.build(rules),
            evaluator=_Evaluator({"rule.one": PolicyResult(denied=False, context={})}),
        ),
        rules=rules,
        catalog_revision=CATALOG_A,
        audit_binder=_audit_binder,
        state_store=store,
        evaluated_at=NOW,
    )


async def _outcome_generations(store: InMemoryStateStore) -> set[str]:
    rows = await store.read_states(BASELINE_EVALUATION_OUTCOME_PREFIX, limit=100_000)
    return {str(row["resource_ref"]).split("-resource-")[0] for row in rows}


async def test_baseline_retention_keeps_the_latest_generation_whole(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(baseline, "BASELINE_EVALUATION_MIN_RETENTION", 1)
    store = InMemoryStateStore()
    for generation in ("g1", "g2", "g3", "g4"):
        await _evaluate(store, generation, resources=5)

    rows = await store.read_states(BASELINE_EVALUATION_OUTCOME_PREFIX, limit=1000)
    refs = {str(row["resource_ref"]) for row in rows}

    assert len(rows) == 10
    assert all(any(f"g{n}-resource" in ref for ref in refs) for n in (3, 4))
    assert not any("g1-resource" in ref or "g2-resource" in ref for ref in refs)


async def test_baseline_retention_never_trims_below_the_minimum_window() -> None:
    store = InMemoryStateStore()
    for generation in ("g1", "g2", "g3"):
        await _evaluate(store, generation, resources=3)

    assert len(await store.read_states(BASELINE_EVALUATION_OUTCOME_PREFIX, limit=1000)) == 9


async def test_no_rule_fold_markers_are_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fold_module, "_SWEEP_MODULUS", 1)
    monkeypatch.setattr(fold_module, "NO_RULE_FOLD_RETENTION", 3)
    state = InMemoryStateStore()
    forseti = _forseti(state, _bus())

    for index in range(8):
        await forseti.judge(_event(f"corr-fold-{index}", "unknown_event"))

    markers = await state.read_states(NO_RULE_FOLD_PREFIX, limit=100)
    assert len(markers) == 3


async def test_no_rule_fold_marker_still_folds_a_repeat_inside_the_window() -> None:
    state = InMemoryStateStore()
    first_bus, second_bus = _bus(), _bus()
    await _forseti(state, first_bus).judge(_event("corr-window", "unknown_event"))
    restarted = _forseti(state, second_bus)
    await restarted.rehydrate()

    await restarted.judge(_event("corr-window", "unknown_event"))

    assert second_bus.messages_on("object.verdict") == []


async def test_aks_receipts_are_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(receipts, "_RETENTION_SAMPLE_MODULUS", 1)
    monkeypatch.setattr(receipts, "AKS_DIAGNOSTIC_RECEIPT_RETENTION", 2)
    store = InMemoryStateStore()
    writer = receipts.StateStoreAksDiagnosticReceiptWriter(store=store)
    context = _context()
    service = AksDiagnosticReceiptService(writer=writer)
    for step in range(6):
        await service.assess_and_persist(
            replace(context, cutoff=context.cutoff + timedelta(minutes=step))
        )

    kept = await store.read_states(receipts.AKS_DIAGNOSTIC_RECEIPT_PREFIX, limit=100)
    assert len(kept) == 2
