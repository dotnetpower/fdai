---
title: Bounded Task Workers
---

# Bounded Task Workers

This design defines short-lived, isolated workers for bounded read-only investigations. It covers
capability attenuation, context isolation, lifecycle budgets, durable state, parent synthesis,
completion handoff, and read-only operations.

> **Scope:** A task worker is not a Pantheon agent. It has no `AgentSpec`, role binding, owned
> object type, Pantheon topic, approval authority, execution identity, or persistent memory.

## Design at a glance

A parent creates a typed request from an existing answer plan. The runtime intersects requested
capabilities with parent-visible tools and a server-owned profile, then runs the worker with fresh
context. Only a bounded, untrusted terminal result returns to parent synthesis.

![Design at a glance. The main stages are Existing answer plan, Typed worker request, Capability intersection, Denied terminal result, Isolated worker runtime, Durable snapshot and branch events, Untrusted parent synthesis, Read-only projection, Completion handoff.](../../diagrams/generated/fdai-roadmap-agents-bounded-task-workers-01.en.svg)

## Worker identity and ownership

The Pantheon remains exactly 15 named agents. A task worker is a runtime helper under
`core/task_worker`, not an organization member. It cannot:

- Publish or subscribe to a Pantheon topic.
- Own a contract object or single-writer responsibility.
- Judge, approve, execute, audit, roll back, or arbitrate.
- Write operator memory, runtime skills, rules, schedules, or workflow definitions.
- Create another worker or ask the operator for clarification.

A read-only answer-planning provider receives token and cost ceilings and returns
`TaskWorkerPlanningResponse` with measured usage, including abstention. The original
`TaskWorkerPlanningProvider.contribute_bounded` seam remains compatible. Production additionally
requires `PreparedTaskWorkerPlanningProvider`: immutable preparation, durable reservation, then
one revalidated call. An unmetered `AnswerPlanningProvider` fails executor construction. The worker
does not inherit a provider's agent identity or authority.

## Request and isolated context

`TaskWorkerRequest` contains only:

- A stable worker ID, parent trace reference, and cancellation owner.
- One bounded goal.
- Selected evidence references.
- Explicit constraints.
- Requested tool names.
- A fixed wall-clock, token, cost, tool-call, and heartbeat budget.
- A timezone-aware creation time and fixed depth of one.

`isolated_context()` projects the goal, evidence references, constraints, and parent trace. It does
not carry the parent transcript, hidden reasoning, credentials, process environment, mutable
memory, unrelated evidence, or channel state.

## Capability attenuation

The allowed tool set is the intersection of three authorities:

1. Tools requested for this worker.
2. Tools visible to the parent.
3. Tools allowed by the server-owned worker profile.

The final dispatcher also checks that each tool is registered and has side-effect class `read`.
Clarification, memory, schedule, approval, action proposal, governance, mutation, execution,
delegation, and nested-worker capabilities are always denied before dispatch. A model request
cannot widen this intersection.

The detached `background.read-only` profile contains exactly `resolve_resource`,
`get_resource_state`, `query_resource_activity`, `query_resource_health`,
`query_guest_shutdown_events`, `query_network_security`, and `query_network_peerings`. Shell and
arbitrary-query capabilities remain denied even if a registry entry is accidentally labeled
`read`.

The current production registry binds `resolve_resource` and `get_resource_state` to recorded
PostgreSQL inventory. Each call requires one exact resource reference from a server-owned allowlist.
One SQL statement binds the active snapshot, resource, bounded state fields, observation time and
freshness. Missing, stale, future, expected-only or unreconciled target state remains unavailable.
The other five names explicitly return `source_unbound`; they do not query Azure. Registry
construction does not implement tool selection or the deferred parent-admission path.

## Lifecycle and budgets

The runtime uses these states:

```text
pending -> running -> succeeded | abstained | cancelled | timed_out |
                      budget_exhausted | denied | failed
```

- A semaphore bounds concurrent workers.
- Execution wall-clock timeout cancels the worker and records `timed_out`; queue time is separate.
- Token, cost, and tool-call limits produce `budget_exhausted`.
- Only the immutable cancellation owner can cancel a live worker.
- Heartbeats serialize current tool and planning usage with any unresolved reservation.
- Unsupported evidence or injection markers in output produce `denied`.
- A restart converts unresolved `pending` or `running` records to
  `failed(runtime_restart_interrupted)`. It does not rerun ambiguous work.

Every transition uses compare-and-swap state checks. Duplicate worker IDs are safe to retry only
when the complete request and attenuated capabilities match. Concurrent admission joins the
original task; queued cancellation also writes a terminal result. Recovery refuses to act on the
same runtime's active tasks.

The concrete Azure OpenAI adapter bounds complete UTF-8 request bytes plus framing allowance and
caps output before obtaining a token or making HTTP requests. Both ceilings must fit first. Cost
uses configured USD rates and returned input/output token counts, not summary length or invoice
evidence. The adapter makes one structured-output request with no retry, redirect or model fallback.

Before dispatch, the runtime persists `reserved_tokens`, `reserved_cost_microusd` and
`complete: false`. A valid usage envelope replaces this allowance with measured `tokens` and
`cost_microusd`, including empty or malformed-content responses. Missing usage, transport failure,
cancellation and timeout preserve the unresolved allowance instead of reporting a free call.
Heartbeat and restart cannot erase it. Complete usage retains the legacy three-field JSON shape;
incomplete records add reservation fields and completeness. Neither representation grants another
attempt or raises the immutable budget.

Example: a provider request is cancelled after reservation but before usage is returned. The
terminal result stays cancelled with incomplete accounting. Reopening the runtime returns that
same result without another model call or a fabricated zero-cost measurement.

## Production composition

Core bootstrap owns `TaskWorkerRuntimeBinding` in `runtime/task_workers.py`. It composes the real
PostgreSQL store, scoped recorded-read registry and prepared Azure planning adapter. Startup does
not create work or probe a model. This source foundation remains opt-in because parent admission,
user-facing Settings, projections and detached completion are separate packages.

| Prerequisite | Behavior |
|--------------|----------|
| `FDAI_TASK_WORKERS_ENABLED` | Absent or false leaves the binding absent without loading dependencies. Invalid values fail startup. |
| `FDAI_STATE_STORE_DSN` | Requires both PostgreSQL login and current role to be `fdai_core`, the owned worker tables, and required read/write grants. Administrator `SET ROLE` is not equivalent. |
| `FDAI_TASK_WORKER_READ_SCOPE_JSON` | Requires exactly `scope_ref` and 1-64 unique exact `resource_refs`; no wildcard, prompt-derived scope or arbitrary query. Keep populated values outside source control. |
| Existing model resolution and endpoints | Reuses an eligible structured OpenAI `t1.judge` target for a Bragi presentation contribution, not judgment. Current model holds remain authoritative. |
| Workload identity, HTTP and pricing | All must be injected; missing or non-USD pricing fails startup. No in-memory store, unmetered provider or synthetic fallback is available. |

An exclusive PostgreSQL advisory lease permits one enabled worker-runtime owner per database.
A competing owner fails startup. Within a 30-second startup deadline, schema checks precede
recovery of up to ten batches of 1000 unresolved rows; terminal history cannot hide old work.
Lease loss fails later operations without reacquiring the lease. It is not an exactly-once HTTP
guarantee: a request already dispatched may remain unmeasured and is never replayed automatically.

Shutdown blocks admission, cancels and drains known work, and attempts unresolved-row recovery
before releasing owned resources. The binding has a 30-second drain deadline; failures propagate
while shared cleanup is still attempted. Database outage leaves durable recovery work, not a
successful completion claim. Local and deployed composition use the same opt-in contract.

## Durable records

PostgreSQL stores one current snapshot and append-only branch events. The snapshot includes
request metadata, attenuated tools, status, usage, heartbeat, and terminal result. Branch events
record creation, start, heartbeat, terminal reason, and completion-delivery failure.

Production writes the terminal snapshot and event in one transaction before the optional completion
sink runs. An event-write failure rolls back the terminal transition without refunding persisted
usage. The additive `RecoverableTaskWorkerStore` contract supplies atomic finish and unresolved-only
queries; legacy stores remain usable outside the production binding. A sink
failure cannot rewrite the terminal result or rerun the worker. Issue #40 can claim detached
completion, and issue #48 can deliver it through the reply ledger.

## Parent synthesis

`TaskWorkerSynthesis` consumes the existing `AnswerPlanningResult`; it does not compute another
route. Results sort by worker ID and preserve the original answer-planning object.

Only these bounded fields enter synthesis:

- Worker ID and terminal status.
- Summary for `succeeded` or `abstained` results only.
- Evidence references and caveats.
- Token, cost, and tool-call usage, including completeness and unresolved allowances.
- Terminal reason.

Every contribution carries `trusted: false`. Failed, denied, cancelled, timed-out, and
budget-exhausted workers contribute status and reason but no summary. Full branch events stay in
the worker store.

## Read-only operations

The Operator API declares these GET-only routes; their production store-backed materialization
remains a separate package:

- `/task-workers`
- `/task-workers/{worker_id}`
- `/task-workers/{worker_id}/events`

The authenticated principal becomes the owner predicate inside each store query. A worker owned
by another principal has the same 404 shape as a missing worker. List rows omit goal and
constraints; they expose status, budget, heartbeat, tools, evidence count, usage, and terminal
reason. Detail can include the bounded untrusted result. No create, cancel, approve, or execute
route is part of the Operator API.

## Failure behavior

- Empty attenuation produces a denied result before executor dispatch.
- Unknown or mutation-class tools are rejected before their handler runs.
- Provider abstention remains abstention.
- Executor exceptions become bounded failure reasons without stack traces in the result.
- Completion-sink failure appends an event after durable completion.
- Projection authorization happens in storage queries, not after broad reads.
- Missing PostgreSQL or provider dependencies leave the capability unavailable; they do not
  substitute synthetic worker evidence.

## Verification

Coverage includes exhaustive capability intersections, context isolation, forbidden tools,
injection, unsupported evidence, concurrency, heartbeats, timeout, cancellation ownership,
budgets, restart recovery, PostgreSQL compare-and-swap, owner-scoped reads, answer-planning
provider reuse, parent synthesis, completion handoff, and GET-only projections.
## Related docs

| To learn about | Read |
|----------------|------|
| Delivery status and remaining work | [Implementation ledger](../../roadmap-implementation/agents/bounded-task-workers.md) |
| Fixed agent roles and ownership | [Agent Pantheon](agent-pantheon.md) |
| Bounded answer planning | [Operator Console](../interfaces/operator-console.md) |
| Detached background sessions | [Issue #40](https://github.com/dotnetpower/fdai/issues/40) |
| Reply delivery durability | [Issue #48](https://github.com/dotnetpower/fdai/issues/48) |
