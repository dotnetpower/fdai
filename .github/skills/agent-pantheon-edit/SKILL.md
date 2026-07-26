---
name: agent-pantheon-edit
description: |
  Safe-edit workflow for the FDAI 15-agent pantheon under
  `src/fdai/agents/**`. The pantheon is fixed (Odin, Thor, Forseti,
  Huginn, Heimdall, Var, Vidar, Bragi, Saga, Mimir, Norns, Muninn,
  Njord, Freyr, Loki) and its role bindings are fork-locked. This
  skill walks through the AgentSpec + layout + role-invariant
  checklist and points at the machine-readable source of truth
  (`PANTHEON_SPECS` in `src/fdai/agents/_framework/pantheon.py`).
  Load when you are about to edit any file under `src/fdai/agents/**`,
  when you see a `test_framework_layout.py` failure, or when adding
  an ActionType binding.
version: 1.0.0
scope: repository
---

# Agent Pantheon Safe-Edit

The short-form contract is
[.github/instructions/agent-pantheon.instructions.md](../../instructions/agent-pantheon.instructions.md)
(auto-loaded for `src/fdai/agents/**`). The design of record is
[docs/roadmap/agents/agent-pantheon.md](../../../docs/roadmap/agents/agent-pantheon.md).
This skill is the runnable checklist you follow before touching a
pantheon file, plus the traps that trip up cross-agent edits.

## Preflight (Answer These First)

1. Is your change **adding, removing, or renaming** an agent? If yes,
   STOP. That is an upstream design PR against `agent-pantheon.md`,
   never a code-only edit. The pantheon is exactly 15 members.
2. Would your change move a pantheon member out of the flat top-level
   layout of `src/fdai/agents/`, or move a framework helper INTO the
   flat layout? If yes, STOP. The layout is enforced by
   [`tests/agents/test_framework_layout.py`](../../../tests/agents/test_framework_layout.py):
   pantheon members flat, framework code under `_framework/`.
3. Is your change ambiguous about which agent is the executor / judge /
   approver / auditor / initiator for an ActionType? If yes, STOP.
   Those five role fields are **fork-locked**; upstream design change
   only.

## The 15 Agents (canonical)

Machine-readable source of truth: `PANTHEON_SPECS` in
[`src/fdai/agents/_framework/pantheon.py`](../../../src/fdai/agents/_framework/pantheon.py).
`tests/agents/test_pantheon_doc_parity.py` pins the docs to this list.

| Agent | Layer | Role summary |
|-------|-------|--------------|
| Odin | governance | Master planner + cross-vertical arbiter (final tie-break). |
| Thor | pipeline | **Sole privileged executor.** Dispatches; MUST NOT judge. |
| Forseti | pipeline | Judge (Verdict issuer). Reports to Odin, not Thor. |
| Huginn | pipeline | Event collector. Deterministic; no synchronous LLM in hot-path. |
| Heimdall | pipeline | Observer / signal gatherer. Deterministic; no synchronous LLM in hot-path. |
| Vidar | pipeline | Recovery / rollback / DR. |
| Var | pipeline | HIL approval principal. **Distinct from Thor** (no self-approval). |
| Bragi | pipeline | Narrator = translator only. **A Bragi that calls an executor directly is a defect.** |
| Saga | governance | Append-only auditor + handoff-to-issue executor. |
| Mimir | governance | Rule steward. |
| Norns | governance | Learner. |
| Muninn | governance | Memory. |
| Njord | domain | Cost specialist (advisory to Forseti, does not execute). |
| Freyr | domain | Capacity specialist (advisory). |
| Loki | domain | Chaos specialist (advisory). |

## Role Invariants (MUST NOT Violate)

- **Thor is the sole privileged executor.** Thor MUST NOT judge.
- **Forseti issues the verdict.** Forseti reports to Odin, not Thor.
- **Var is a distinct approver.** No self-approval. Var != Thor.
- **Bragi is a translator only.** Bragi calling an executor directly
  is a defect.
- **Huginn and Heimdall are sensing agents.** They MUST NOT invoke an
  LLM synchronously in the hot path.
- **Saga is append-only audit.** Saga MUST NOT mutate.
- **Njord / Freyr / Loki are advisory.** They do not execute; they
  raise findings that Forseti judges.

## Two-Port Contract

Every agent exposes:

- a **typed pub/sub port** (hot path, schema-checked, deterministic-first)
- a **conversational port** (natural language, LLM-backed, for
  introspection)

A conversational request that asks for an action MUST re-enter the
typed pipeline. No bypass.

## AgentSpec Fields

Each `AgentSpec` in `pantheon.py` carries:

| Field | Meaning |
|-------|---------|
| `name` | Canonical agent name (Odin, Thor, ...). |
| `layer` | `governance` / `pipeline` / `domain`. |
| `reports_to` | Parent in the org chart (Odin has none). |
| `owns` | Object types the agent is single-writer for. Only this agent MAY publish that object type's topic. |
| `executes` | ActionTypes this agent is the executor for. |
| `initiates` | ActionTypes this agent MAY initiate. |
| `subscribes` | Topics this agent reads. |
| `question_domains` | Bragi introspection scopes this agent answers. |
| `conversation` | Versioned bounded system prompt, purpose/fact-scoped read tools, and English/Korean semantic routing examples. |
| `owns_code_paths` | Files this agent is authoritative over. |
| `hard_dependency` | Boolean; hard-dep agents (Saga, Vidar) fail-safe closed. |

## Change Procedure

1. Read the affected `AgentSpec`. Confirm your change keeps it
   consistent.
2. If the change touches an `ActionType` binding, remember five
   role fields are fork-locked (`initiators`, `judge`, `executor`,
   `approver`, `auditor`).
3. Run the layout test first:
   ```
   pytest tests/agents/test_framework_layout.py -q --no-cov
   ```
4. Add / update tests for the specific role invariant your change
   affects. For safety-core agents (Forseti, Var, Thor) coverage must
   stay at the 90% floor.
5. **Docs-first / docs-after**: if behavior or the `AgentSpec`
   changes, update
   [`docs/roadmap/agents/agent-pantheon.md`](../../../docs/roadmap/agents/agent-pantheon.md)
   (and `-ko.md`) in the same commit.
6. Verify:
   ```
   bash scripts/verify.sh --fast
   pytest tests/agents/ -q --no-cov
   ```
7. Per-file `git add`, then a Conventional Commit scoped to the
   agent name:
   - `harden(forseti): ...`
   - `fix(thor): ...`
   - `test(var): ...`

## Common Gotchas

- **`mentioned()` word regex**: `[a-z0-9-]+` does NOT match underscore
  or dot. To exercise action-scoped introspect branches in tests, use
  single-token bucket / scope names (`rg-1`, `vms`, `keep`). Dotted or
  underscored real action keys are structurally unreachable through
  the introspect path.
- **Handoff / security notification / privilege escalation**: all flow
  through Saga's append-only audit machinery. No side channels.
- **Hard-dependency agents (Saga, Vidar) go down**: the runtime
  degrades fail-safe closed. No execution proceeds. Do not add
  fallbacks that let mutations continue without them.

## Related

- Runnable prompt:
  [.github/prompts/pantheon-safe-edit.prompt.md](../../prompts/pantheon-safe-edit.prompt.md).
- Auto-loaded contract:
  [.github/instructions/agent-pantheon.instructions.md](../../instructions/agent-pantheon.instructions.md).
- Full design:
  [docs/roadmap/agents/agent-pantheon.md](../../../docs/roadmap/agents/agent-pantheon.md).
- Parity regression:
  [tests/agents/test_pantheon_doc_parity.py](../../../tests/agents/test_pantheon_doc_parity.py).
