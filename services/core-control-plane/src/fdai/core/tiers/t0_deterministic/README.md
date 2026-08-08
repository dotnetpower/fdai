# `src/fdai/core/tiers/t0_deterministic`

Deterministic engine. Runs OPA/Rego policies, what-if simulation, and drift checks;
emits a verdict plus citing rule ids. Part of the safety core (≥90% coverage gate).

## P1 W-2 Skeleton

- [`models.py`](models.py) - `PipelineStage` (`L1_evaluate` / `L1_simulate` / `abstain`),
  `Finding`, `Verdict`, `AuditHint`. Vocabulary matches
  [docs/roadmap/architecture/llm-strategy.md § Pipeline Stages](../../../../../docs/roadmap/architecture/llm-strategy.md).
- [`index.py`](index.py) - `RuleIndex` builds an O(indexed) lookup keyed on
  `resource_type`, with severity-desc ordering matching
  [phase-1 § Precedence](../../../../../docs/roadmap/phases/phase-1-rule-catalog-t0.md).
- [`engine.py`](engine.py) - `T0Engine` orchestrator plus the `PolicyEvaluator`
  Protocol; the default `AbstainEvaluator` is a fail-closed placeholder until the
  OPA/Rego runner lands in P1 W-3. `evaluate()` always emits an `AuditHint` in
  `Mode.SHADOW` - the engine never mutates state.

## Safety invariants held here

- **Shadow-only** - every `AuditHint` carries `Mode.SHADOW`; P1 has no enforce path.
- **Fail-closed on evaluator error** - an exception from `PolicyEvaluator.evaluate`
  downgrades that rule to an abstain, so one bad rule cannot silence the catalog.
- **Deterministic ordering** - findings sort by severity desc, then rule_id.
- **No I/O** - the engine is pure; adapters (audit writer, inventory reader) are
  the caller's responsibility.
