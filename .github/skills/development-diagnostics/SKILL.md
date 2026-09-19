---
name: development-diagnostics
description: "Operate FDAI's local development diagnostic channel when the user says dev discuss, runtime profile, runtime profiling, heap profile, memory profile, CPU profile, 런타임 프로파일, 힙 프로파일, 메모리 프로파일, or asks Copilot to diagnose a running Core or Operator bottleneck."
---

# FDAI Development Diagnostics

Use this workflow to capture bounded, content-free evidence from an explicitly profiled local Core
or Operator process and diagnose it against the exact matching workspace. This is a development
tool. It does not join the Pantheon, product conversation path, System Knowledge Service, channel
edge, deployment workflow, approval path, or executor.

## Activation

The standard task-backed local launcher always enables diagnostics for Core and Operator. Use
`dev discuss: start or restart profiled services` when that stack is stale or not running. The task
stops a verified supervisor from the same checkout and waits for its lock to be released before
starting the replacement. A direct process start outside the launcher must supply the complete
diagnostic source and digest binding; do not enable only the feature flag.

Check availability:

```bash
.venv/bin/python scripts/automation/dev-discuss.py status
```

Availability requires a successful bounded protocol response. A leftover socket file is reported
as unavailable.

## Capture

Prefer an immediate snapshot first:

```bash
.venv/bin/python scripts/automation/dev-discuss.py capture \
  --service core-control-plane
```

Use an explicit bounded profile only when the snapshot or question requires attribution:

```bash
.venv/bin/python scripts/automation/dev-discuss.py capture \
  --service core-control-plane \
  --duration-ms 5000
```

The maximum capture is 30 seconds. One process accepts one capture at a time. CPU and Python heap
capture are enabled by default for a timed profile. Never repeat a failed live capture without a
new hypothesis.

## GitHub Copilot Review

Export one question and packet:

```bash
.venv/bin/python scripts/automation/dev-discuss.py copilot-export \
  --service operator-service \
  --duration-ms 5000 \
  --question "Which measured stage and source location explain the current latency?"
```

Read the owner-only packet, verify its source and worktree digests, inspect only the cited matching
workspace, and write one owner-only JSON result with these fields:

```json
{
  "schema_version": "1.0.0",
  "review_id": "<packet review_id>",
  "review_digest": "<packet review_digest>",
  "packet_digest": "<profile packet_digest>",
  "severity": "low",
  "diagnosis": "Evidence-bound diagnosis without secrets or unsupported causation.",
  "code_refs": ["relative/path.py:123"]
}
```

Import it with `copilot-import`. The importer rejects revision, worktree, packet, or review drift.
The result has no qualification, merge, or execution authority. A finding never edits code,
creates a branch, opens a pull request, restarts a service, or deploys. Handle any accepted code
change as a separate normal repository task.

## Interpretation

- `heap_top` covers Python allocations tracked by `tracemalloc`, not native allocations.
- `untracked_memory_bytes` is a difference, not a causal attribution.
- `event_loop_lag_ms` includes capture overhead and scheduler delay.
- CPU rows report only repository-relative locations. Missing rows remain an explicit limitation.
- Development profile timing is diagnostic evidence and never replaces release latency or SLO
  evidence.

## Safety

- Do not request or retain heap objects, environment values, credentials, provider payloads,
  question-answer bodies from product traffic, or hidden reasoning.
- Do not expose the Unix socket through HTTP, browser, Teams, Slack, Event Bus, a container port,
  or a shared filesystem.
- Do not enable the channel outside the local execution venue.
- Stop after timeout, malformed evidence, digest drift, or provider unavailability. Do not infer a
  healthy state from missing evidence.
