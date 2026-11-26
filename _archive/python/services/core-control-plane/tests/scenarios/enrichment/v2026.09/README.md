# v2026.09 replay enrichment

The v2026.09 scenario set in [`services/core-control-plane/tests/scenarios/v2026.09/`](../../v2026.09/)
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
[`test_v2026_09_replay.py`](../../test_v2026_09_replay.py); it uses
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
| `effect_evidence` | no | Frozen independent effect evidence for generic `successful_full_loop` mechanics: the pre-dispatch prediction, one authoritative observation produced without the executor receipt, and the `missing` / `stale` / `incomplete` / `conflicting` / `not_yet_recorded` negative cases. Consumed by the MSCP expected-effect provider and independent effect observer the harness binds to the real `ControlLoop`. This field alone does not satisfy a capability-specific FDAI-CONST-005 outcome. |
| `note` | no | Human context for the mapping. |

## Effect evidence fields

| Field | Required | Purpose |
|-------|----------|---------|
| `prediction_id` | yes | Stable prediction identity for the frozen replay. |
| `metric` | yes | Metric the prediction and the authoritative observation agree on. |
| `acceptable_min` / `acceptable_max` | yes | Inclusive acceptance range the observation must fall in. |
| `predicted_at` / `observation_deadline` | yes | Frozen prediction time and its observation deadline. |
| `authoritative_observation` | yes | Independent observation (`observation_source`, `value`, `observed_at`) that closes the positive case. |
| `negative_cases` | yes | Fail-closed cases; each carries `kind`, an optional `observation` override (`null` means no observation), and the pinned `expected_verification_status`, `expected_verification_reason`, and `expected_response_label`. |

The frozen timestamps are read against the harness replay clock, which is
anchored on the scenario event rather than on wall clock, so `predicted_at`
precedes dispatch, the authoritative observation follows it, and the
`not_yet_recorded` case lands after the moment the comparison is recorded.

The overlay never carries an executor receipt, a PR reference, or a dispatch
outcome: closure has to come from the observation alone.

## Completion boundary

The manifest records each capability-specific FDAI-CONST-005 outcome separately
under `required_outcome`. Generic replay, failure recovery, conflict, and effect
evidence can remain nonempty while a pack stays `partial`. A pack becomes
`complete` only after all six coverage dimensions contain evidence,
`required_outcome.status` is `complete`, and its evidence array cites a passing
focused test for the domain outcome. Manifest schema version 1.3 requires this
block on every capability pack. The schema also binds each pack to its
capability-specific outcome ID and prevents pack or aggregate completion before
the corresponding outcomes are complete. Completion status is derived in both
directions, so fully evidenced packs and aggregates cannot remain `partial` or
`incomplete`.

Frozen safety checks scan each complete enrichment overlay recursively, including
`event_payload_resource`, for customer identifiers, non-example endpoints,
non-redacted secret values, and non-ASCII machine fields.
The same recursive checks cover the complete manifest, including free-text gap
descriptions and object keys, and reject duplicate JSON keys.
