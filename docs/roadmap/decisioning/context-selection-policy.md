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

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Deterministic policy contract, tiered adapter, and invariant wrapper | implemented | `services/core-control-plane/src/fdai/core/working_context/`; `services/core-control-plane/tests/core/working_context/test_policy_validation.py`; `services/core-control-plane/tests/core/working_context/test_working_context.py` | The frozen input, double execution, manifest checks, pinned-entry checks, and fail-closed behavior have focused coverage. |
| Policy registry and governance transitions | implemented | `services/core-control-plane/src/fdai/core/working_context/governance.py`; `services/core-control-plane/tests/core/working_context/test_policy_governance.py`; `services/core-control-plane/tests/core/capability_catalog/test_runtime.py` | Install, shadow enablement, explicit promotion, demotion, kill switch, rollback, and revision compare-and-set are implemented without automatic promotion. |
| Bounded shadow evaluation, comparison storage adapter, and approved-fixture replay | implemented | `services/core-control-plane/src/fdai/core/working_context/shadow.py`; `services/core-control-plane/src/fdai/core/working_context/evidence.py`; `services/core-control-plane/src/fdai/core/working_context/replay.py`; `services/core-control-plane/tests/core/working_context/test_policy_shadow.py`; `services/core-control-plane/tests/core/working_context/test_evidence.py` | The components and their failure isolation pass focused tests. This state does not claim that the production composition binds them. |
| Production shadow composition and durable comparison persistence | implemented | `services/core-control-plane/src/fdai/composition/wire_context_selection.py`; `services/core-control-plane/src/fdai/composition/_helpers.py`; `services/core-control-plane/tests/composition/test_wire_context_selection.py` | `bind_context_selection_shadow` binds the runner and the `StateStore` comparison store together, a bundle install rebinds the runner to the refreshed authority, and a normally assembled turn persists one bounded comparison. |
| Reader comparison API and Console view | implemented | `services/operator-service/src/fdai_operator_service/context_selection_projection.py`; `services/operator-service/src/fdai_operator_service/families/workflow/manifest.py`; `services/operator-service/tests/test_operator_workflow_family.py`; `console/src/routes/context-selection-comparisons.test.ts` | The Reader-gated `GET /context-selection-comparisons` route projects bounded durable records, a malformed record fails closed, and the Console decoder accepts the authoritative payload. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-13 | in-progress | Adopted the implementation ledger without reconstructing earlier provenance. Recorded the focused-test-backed core policy, governance, shadow, storage-adapter, and replay components as implemented, while separating missing production composition and Operator API delivery. | `current change`; source and focused tests listed in the scope table; `uv run pytest -q --no-cov services/core-control-plane/tests/core/working_context services/core-control-plane/tests/core/capability_catalog/test_runtime.py services/core-control-plane/tests/core/conversation/test_context_bridge.py services/core-control-plane/tests/core/conversation/test_assemble_turn_context.py` (`70 passed`); `npm --prefix console test -- --run src/routes/context-selection-comparisons.test.ts` (`3 passed`) | Bind and prove durable production shadow evaluation, expose the Reader-gated comparison route, and collect governed runtime evidence before claiming `validated`. |
| 2026-08-14 | implemented | Added the `bind_context_selection_shadow` composition seam, the paired `Container` invariant, and the Reader-gated Operator Service `GET /context-selection-comparisons` projection over the existing tracked-state prefix. | `current change`; `wire_context_selection.py`, `context_selection_projection.py`, workflow route manifest; focused checks passed 53 core composition cases, 34 Operator cases, and 5 Console decoder cases; task-scoped Ruff and strict mypy passed. | Record governed runtime evidence tracing one eligible shadow evaluation through durable persistence and Operator API retrieval before any scope row becomes `validated`. |

### Remaining work

- [x] Bound production shadow evaluation is composed through `bind_context_selection_shadow`, and an
   integration test proves a normally assembled turn schedules bounded candidate evaluation and
   persists its comparison through `StateStore`.
- [x] The Reader-gated Operator Service `GET /context-selection-comparisons` route is registered in
   the workflow family manifest; API integration tests and the Console decoder test pass against
   its authoritative response.
- [ ] Record governed runtime evidence that traces one eligible shadow evaluation through durable
   persistence and Operator API retrieval before changing any scope row to `validated`.
- [ ] Add bounded retention for durable comparison rows so a long-lived deployment can leave shadow
   evaluation enabled without unbounded tracked-state growth.

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

`bind_context_selection_shadow` is the composition seam that binds the runner and the durable store
together. `Container` rejects a half-bound pair, so a deployment cannot schedule evaluation without
somewhere to record it. Install every capability bundle first: a later `install_capability_bundle`
rebuilds the runner on the refreshed policy authority and keeps the same store.

Comparison rows are append-only and the store has no prune operation, so the binder is opt-in per
deployment: enabling it on a high-volume conversation surface grows the tracked-state table by one
row per candidate per turn. Bounded retention is tracked in remaining work; until it lands, enable
the binder for a measured evidence window rather than leaving it on indefinitely.

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
| Working-context tiers and prompt layers | [Evolving System Prompt](prompt-composition.md) |
| Conversation persistence and assembly | [Operator Console](../interfaces/operator-console.md) |
| Module and DI boundaries | [Project Structure](../architecture/project-structure.md) |
| Shadow and promotion safety | [Security and Identity](../architecture/security-and-identity.md) |
