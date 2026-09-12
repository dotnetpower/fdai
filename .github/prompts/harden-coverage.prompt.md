---
mode: agent
description: One coverage-driven hardening batch on an under-covered core module.
---

# /harden-coverage - one focused coverage-hardening batch

Follow the [coverage-driven recipe](../skills/coding-hardening/SKILL.md#coverage-driven-recipe):
pick one under-covered production module under `services/core-control-plane/src/fdai/core/`, add
tests for its missing branches, verify, commit. **One batch = one commit.**

## Rules

- **Never touch production code** in this loop. Tests only. The recipe is
  0-risk to the maintainer's WIP because production paths are unchanged.
- **Respect maintainer WIP**: check `git status --short` first. Do not
  stage anything the maintainer is editing. Add only files this batch
  creates or modifies (per-file `git add`, never `git add -A`).
- **Fail closed**: if the module cannot be tested without touching
  production, stop and report; do not silently patch source to make a
  test pass.

## Steps

1. Reuse the campaign candidate list or available coverage hints, excluding testing fakes.
   Without a report, choose one safety-core module and measure it with the recipe's single-module
   command. Do not run a whole-tree baseline merely to rank candidates.
2. Pick ONE measured module under 90% coverage. Read its Missing line ranges.
3. Add tests that exercise exactly those branches. Keep tests
   deterministic (seed randomness, no network, no wall clock).
4. Verify the completed logical batch with the recipe's focused coverage command. Follow
   [Testing](../instructions/coding-conventions.instructions.md#testing) for result reuse; unrelated
   edits and commit metadata alone do not require another run.
5. Per-file `git add`, then a Conventional Commit:
   `test(<scope>): cover <module> (<X% -> Y%>)`

The merge/release CI coverage gate remains authoritative. A campaign end, merge, or release is not
an explicit local whole-suite request.

## When to stop

- The picked module reaches "meaningful" coverage (usually >= 95% branch;
  90% is the enforced floor). Do not chase 100% on unreachable
  defensive branches - the recipe already notes several are structurally
  dead (routing / dotted-key introspect edges).
- Or: no module under 90% remains among production paths.
- Or: the maintainer says stop.

## Guardrails

- customer-agnostic strings only (no real sub id / tenant / customer name).
- Machine records (audit / events / log keys) SHOULD stay English in tests for
  replay; Korean prose is otherwise fine. Identifiers stay ASCII.
- Property-test invariants for safety-core modules must stay: "high-risk
  never auto-executes", "shadow mode never mutates", "re-apply is no-op".
