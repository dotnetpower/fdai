from __future__ import annotations

from pathlib import Path

from fdai.composition.readiness_catalog import load_runtime_best_practice_bindings

ROOT = Path(__file__).resolve().parents[4]


async def test_loads_complete_runtime_best_practice_bindings() -> None:
    controls, provider = load_runtime_best_practice_bindings(ROOT / "rule-catalog")

    assert len(controls) == 59
    outcomes = await provider.outcomes_for_scope("scope-example")
    assert outcomes
    assert all(outcome.scope == "scope-example" for outcome in outcomes)
