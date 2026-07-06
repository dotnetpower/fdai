# v2026.07 replay enrichment

The v2026.07 scenario set in [`tests/scenarios/v2026.07/`](../../v2026.07/)
is **frozen** for baseline comparison — its `citing_rule_ids` are
placeholder names like `example.tag.owner-required` and its `event`
objects intentionally omit `payload.resource` so any consumer must
supply concrete inputs. That keeps the frozen artifact reusable across
tiers as they land.

This directory carries the concrete-payload overlay needed to replay
each scenario through the real
[`ControlLoop`](../../../../src/aiopspilot/core/control_loop.py). One
`<scenario-id>.json` file per replayable scenario; a scenario without an
overlay is marked `xfail` in the harness with a documented reason (P2
T1/T2, P2 risk-gate, or "no shipped rule maps to this scenario yet").

The harness is
[`test_v2026_07_replay.py`](../../test_v2026_07_replay.py); it uses
the shipped rule catalog + Rego policies + IaC templates verbatim.
