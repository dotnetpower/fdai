---
title: Context Selection Policy
---
# Context Selection Policy

This document owns the policy boundary around bounded working-context selection. It preserves the
existing deterministic composer as the active default while allowing reviewed candidates to be
measured in shadow mode before an explicit, evidence-backed promotion.

> **Scope.** A policy selects pre-estimated entry ids and emits a manifest. Transcript persistence,
> summarization, retrieval, token estimation, prompt rendering, model calls, and answer generation
> stay outside this boundary.
>
> **Default.** `deterministic-tiered-v1@1.0.0` is immutable and authoritative. With no promoted
> candidate, the selected entries and `ContextManifest` remain byte-for-byte equivalent to the
> prior `compose_working_context` behavior.

## Design at a glance

`ContextSelectionInput` freezes candidate entries, their trust classes, the token budget, and model
capability metadata. A `ContextSelectionPolicy` can return only ordered selected entry ids and a
`ContextManifest`. The mandatory wrapper executes the policy twice on the exact same input,
validates every invariant, and reconstructs the selected immutable entries. No policy receives a
store, retriever, summarizer, renderer, model client, tool, or executor.
## Contract boundary

The core contract lives under `services/core-control-plane/src/fdai/core/working_context/`:

| Type | Responsibility |
|------|----------------|
| `ContextSelectionInput` | Immutable pre-estimated entries, trust classes, budget, and model metadata |
| `ContextSelectionOutput` | Ordered selected ids plus the existing manifest |
| `ContextSelectionPolicy` | Pure `select(input) -> output` Protocol |
| `DeterministicTieredPolicy` | Adapter over the existing tiered composer |
| `execute_context_selection_policy` | Mandatory deterministic replay and invariant wrapper |

The caller still owns all I/O. `assemble_turn_context` prepares entries through the existing
retrieval and operator-memory seams, freezes one input, obtains the authoritative selection, and
may schedule candidate evaluation after the active result is complete.

## Mandatory invariants

Every active or shadow result passes the same validator. The validator rejects:

- a missing, incomplete, or reordered pinned constraint;
- an invented id, duplicate selected id, or id assigned to multiple manifest tiers;
- token totals that do not match selected entries or exceed `history_budget`;
- a trust-class mismatch or prompt order that violates pinned and tier ordering;
- incomplete omission metadata or an id that cannot resolve to exactly one immutable input entry;
- different output from a second execution on the same frozen input;
- any policy exception.

An invariant error fails the current request closed. If a promoted candidate caused it, the policy
authority engages that policy's kill switch and restores its explicit rollback target for later
requests. The failed output never reaches prompt rendering or a model.

## Registry and promotion

Policy identity is the immutable pair `(policy_id, version)`. `CapabilityRuntime` has a
`context_selection_policy` reference binding so the existing capability registry remains the
installation authority. It registers an exact policy ref only; it does not load Python, download a
package, or grant a tool or execution capability.

`ContextSelectionPolicyAuthority` applies revision compare-and-set under a process lock:

1. **Install disabled.** The exact capability binding and policy ref must already be active.
2. **Enable shadow.** The candidate becomes measurable but cannot affect active output.
3. **Promote explicitly.** Promotion names the exact candidate version, a timezone-aware evidence
   window with at least one sample and zero invariant failures, and the current active policy as
   rollback target.
4. **Demote or kill.** A reviewed regression can demote. An invariant violation automatically
   engages the per-policy kill switch and rolls back. A stale revision loses the update race.

The authority never auto-promotes. It also cannot widen tools, roles, ActionTypes, Workflows, model
permissions, or executor identity.

## Shadow evaluation and evidence

`ContextSelectionShadowRunner` runs a bounded number of candidates with `asyncio.to_thread` and a
per-candidate timeout. Scheduling returns immediately from the async composition seam. The runner
uses the same `ContextSelectionInput` object as the baseline and never replaces, mutates, or returns
a candidate result to the active prompt path.

Each durable comparison records:

- baseline and candidate policy refs, manifests, and token use;
- input fingerprint, selected-id overlap, omissions, and pinned preservation;
- selected relevance mean and optional answer-quality evaluation linkage;
- measured latency and the exact exception, timeout, or invariant failure reason.

The production adapter stores these records under the existing `StateStore` tracked-state prefix.
This reuses PostgreSQL durability and atomic create semantics; no new table or Alembic migration is
required. Fan-out, pending runs, and timeouts are all bounded.

`bind_context_selection_shadow` is the composition seam that binds the runner. The runner owns its
durable store, so a deployment cannot schedule evaluation without somewhere to record it. Install
every capability bundle first: a later `install_capability_bundle` rebuilds the runner on the
refreshed policy authority and keeps the same store.

Comparison rows are append-only, so enabling the binder on a high-volume conversation surface adds
one row per candidate per turn. Retention bounds that growth: after each shadow batch the runner
prunes everything past `ContextShadowConfig.retain_evaluations` (500 rows by default), so the binder
can stay enabled instead of running only for a measured evidence window. Retention removes exactly
the rows a bounded newest-first read would never return, and it cannot name a key, so it can never
erase an authoritative record or an audit entry.

## Replay and console

`replay_approved_context_fixtures` runs only fixtures marked approved and compares the complete
ordered output and manifest. Replay performs the same double-execution invariant validation used by
live selection, so an unreplayable policy cannot pass offline evidence.

The console route `GET /context-selection-comparisons` is a Reader-gated `ReadPanel`. It shows token
use, overlap, omissions, pinned preservation, latency, and exact failures. The SPA contains no
install, enable, promote, demote, rollback, or kill-switch control. Governance transitions remain
server-side and audited through their owning command path.

The Operator Service serves that panel from the workflow route family. It reads the newest bounded
records under the tracked-state prefix, projects only the eleven presentation fields, and always
declares `read_only` with `mutation_controls: false` so the browser can reject any response that
would imply a governance control. An empty result is an authoritative answer, not an unavailable
projection; a malformed durable record fails closed with HTTP 503 rather than a partial panel.

## Failure posture

- Missing or malformed policy output fails closed before prompt rendering.
- Candidate exception or timeout is evidence only and never changes active selection.
- Registry update races require a fresh revision; last-writer-wins is not supported.
- A killed policy cannot re-enter shadow without a separately implemented reviewed recovery path.
- The built-in deterministic policy remains the fallback rollback target. If it ever violates an
  invariant, selection fails closed rather than bypassing validation.

## Related docs

| To learn about | Read |
|----------------|------|
| Delivery status and remaining work | [Implementation ledger](../../roadmap-implementation/decisioning/context-selection-policy.md) |
| Working-context tiers and prompt layers | [Evolving System Prompt](prompt-composition.md) |
| Conversation persistence and assembly | [Operator Console](../interfaces/operator-console.md) |
| Module and DI boundaries | [Project Structure](../architecture/project-structure.md) |
| Shadow and promotion safety | [Security and Identity](../architecture/security-and-identity.md) |
