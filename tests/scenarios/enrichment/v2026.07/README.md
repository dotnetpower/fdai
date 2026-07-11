# v2026.07 replay enrichment

The v2026.07 scenario set in [`tests/scenarios/v2026.07/`](../../v2026.07/)
is **frozen** for baseline comparison - its `citing_rule_ids` are
placeholder names like `example.tag.owner-required` and its `event`
objects intentionally omit `payload.resource` so any consumer must
supply concrete inputs. That keeps the frozen artifact reusable across
tiers as they land.

This directory carries the concrete-payload overlay needed to replay
each scenario through the real
[`ControlLoop`](../../../../src/fdai/core/control_loop/orchestrator.py). One
`<scenario-id>.json` file per replayable scenario; a scenario without an
overlay is marked `xfail` in the harness with a documented reason (P2
T1/T2, P2 risk-gate, or "no shipped rule maps to this scenario yet").

The harness is
[`test_v2026_07_replay.py`](../../test_v2026_07_replay.py); it uses
the shipped rule catalog + Rego policies + IaC templates verbatim.

## Overlay fields

| Field | Required | Purpose |
|-------|----------|---------|
| `scenario_id` | yes | Frozen scenario this overlay enriches. |
| `shipped_rule_id` | yes | Real catalog rule the placeholder maps to. |
| `event_payload_resource` | yes | Concrete `payload.resource` block that fires the shipped rule. |
| `expected_control_loop_outcome` | yes | Expected `ControlLoopOutcome` (`executed`, `hil`, `denied`, ...). |
| `expected_decision` | yes | Expected `ControlLoopResult.decision` (`auto` / `hil` / `deny` / `abstain`). |
| `expected_citing_rule_id_present` | yes | Rule id that MUST appear in the P1 citing set. |
| `wire_risk_gate` | no (default `false`) | Opt this scenario into the risk-gate path (risk table + `RiskGate`). Set `true` for overlays asserting `hil`/`deny` routing. Left `false` keeps the shadow-PR posture (T0 judge-and-log); wiring the gate globally would fail-close every scenario to HIL because the harness passes no inventory age. |
| `note` | no | Human context for the mapping. |
