---
mode: agent
description: Safe-edit checklist for any file under services/core-control-plane/src/fdai/agents/**.
---

# /pantheon-safe-edit - editing an agent under services/core-control-plane/src/fdai/agents/**

Any file under `services/core-control-plane/src/fdai/agents/**` is governed by
`.github/instructions/agent-pantheon.instructions.md` (auto-loaded for
that path) and the design in
`docs/roadmap/agents/agent-pantheon.md`. Follow this checklist before
touching anything.

## Pre-flight

1. **Identify the agent** you are about to change. The pantheon is
   exactly 15 named agents:
   Odin, Thor, Forseti, Huginn, Heimdall, Var, Vidar, Bragi, Saga,
   Mimir, Norns, Muninn, Njord, Freyr, Loki.
2. If your change would **add, remove, or rename** an agent: STOP.
   That is an upstream design PR against `agent-pantheon.md` first,
   not a code edit.
3. If your change would move an agent OUT of the flat top-level layout
   of `services/core-control-plane/src/fdai/agents/`, or a framework helper INTO the flat layout:
   STOP. The layout is enforced by
   `services/core-control-plane/tests/agents/test_framework_layout.py`. Pantheon members flat,
   framework code under `_framework/`.

## Role invariants (MUST NOT violate)

- **Thor** is the sole privileged executor. Thor MUST NOT judge.
- **Forseti** issues the verdict. Forseti reports to Odin, NOT Thor.
- **Var** is the HIL approval principal, distinct from Thor. No
  self-approval.
- **Bragi** is a translator only; a Bragi that calls an executor
  directly is a defect.
- **Huginn / Heimdall** are sensing agents; they MUST NOT invoke an
  LLM synchronously in the hot path.
- **Saga** is append-only audit; it MUST NOT mutate.

## Two-port contract

Every agent exposes:

- a typed pub/sub port (hot path, schema-checked, deterministic-first)
- a conversational port (natural language, LLM-backed, introspective)

A conversational request that asks for an action MUST re-enter the
typed pipeline. No bypass.

## Change process

1. Read the affected `AgentSpec` (name, layer, `owns`, `subscribes`,
   LLM flags, `hard_dependency`) and confirm your change keeps it
   consistent.
2. If the change touches an `ActionType` binding, remember five role
   fields are fork-locked: `initiators`, `judge`, `executor`,
   `approver`, `auditor`.
3. Run the layout test first:
   `pytest services/core-control-plane/tests/agents/test_framework_layout.py -q --no-cov`
4. Add / update tests for the specific role invariant your change
   affects. For safety-core agents (Forseti, Var, Thor) keep coverage
   at the 90% floor.
5. **Docs-first / docs-after**: if behavior or the AgentSpec changes,
   update `docs/roadmap/agents/agent-pantheon.md` in the same commit.
6. Verify: `bash scripts/verify.sh --fast`, then targeted pytest for
   the touched agent.
7. Per-file `git add`, then a Conventional Commit scoped to the agent
   name (e.g. `harden(forseti): ...`, `fix(thor): ...`).

## Common gotchas

- `mentioned()` in agent introspect uses `[a-z0-9-]+` word regex - it
  does NOT match underscore or dot. Use single-token bucket / scope
  names in tests (`rg-1`, `vms`, `keep`) to exercise action-scoped
  branches.
- The audit trail MUST NOT be side-channeled: handoff, security
  notifications, and privilege escalation all flow through Saga.
