---
mode: agent
description: One coverage-driven hardening batch on the lowest-covered core module.
---

# /harden-coverage - one focused coverage-hardening batch

Follow the coverage-driven hardening recipe from the repo memory
(`/memories/repo/coding-ability.md`): pick the lowest-covered production
module under `services/core-control-plane/src/fdai/core/`, add tests that cover the exact missing
lines, verify, commit. **One batch = one commit.**

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

1. Reuse the under-covered module list already recorded for this hardening
  campaign. If no campaign baseline exists, run this whole-tree command once
  and record the ordered candidate list in the session plan:
   ```
   pytest -q -p no:cacheprovider --cov=src/fdai --cov-branch \
     --cov-report=term-missing
   ```
  Do not rerun it for later batches. A report from another commit is only a
  candidate-selection hint, not verification evidence.
2. Sort the one-time baseline by lowest coverage, excluding testing fakes:
   ```
   coverage report --skip-covered --sort=cover | grep -vE "/testing/"
   ```
3. Pick ONE module under 90% coverage. Read its Missing line ranges.
4. Add tests that exercise exactly those branches. Keep tests
   deterministic (seed randomness, no network, no wall clock).
5. Verify the single module:
   ```
   pytest <testfile> --cov=fdai.<dotted.module> --cov-branch \
     --cov-report=term-missing --no-cov-on-fail -o addopts=""
   ```
   Note: `--cov=` takes a **dotted module**, not a slash path. `-o addopts=""`
   drops the project's default `--cov` floor for this single-file check.
6. Run the fast gate suite: `bash scripts/verify.sh --fast`.
7. Per-file `git add`, then a Conventional Commit:
   `test(<scope>): cover <module> (<X% -> Y%>)`

Do not run the whole repository suite per batch. The merge/release CI coverage
gate is authoritative; local `scripts/verify.sh --all` is reserved for an
explicit user request or the end of a merge/release campaign.

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
