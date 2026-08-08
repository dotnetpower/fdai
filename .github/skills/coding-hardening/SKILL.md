---
name: coding-hardening
description: |
  FDAI coding-hardening loop: pick a safety-core or low-coverage module,
  find real defects honestly, harden one focused change, verify with the
  gate stack, and commit per file. Complements
  `.github/prompts/critique-batch.prompt.md` and
  `.github/prompts/harden-coverage.prompt.md` (the runnable slash-commands
  built on top of this skill). Load when doing "critique-and-harden" or
  "coverage hardening" work, when triaging a suspected bug, or when
  extending tests around the >= 90% safety-core coverage floor.
version: 1.2.0
scope: repository
---

# Coding Hardening Loop

The FDAI codebase runs a repeatable "critique -> harden -> verify -> commit"
loop on its safety-core modules. This skill is the long-form version of
that loop; the two prompt files above are the one-shot invocations. Use
this skill when a maintainer says "code hardening", "critique this
module", or asks you to add tests to raise coverage.

## When to Use This Skill

Use when you are asked to:

- Find and fix real bugs in a specific FDAI module (a critique batch).
- Add tests that lift a low-coverage module toward the 90% floor.
- Review a safety-core module (risk_gate / tiers / quality_gate /
  executor / event_ingest / trust_router / forseti / var / thor) for
  invariant violations.

Do NOT use for:

- Feature work with a design change (that is a docs-first PR).
- Any change under `src/fdai/agents/**` without also loading the
  Agent Pantheon safe-edit prompt.

## Priority Modules (safety core)

Pick one that has NOT been hardened in this session. See
[docs/roadmap/architecture/code-map.md](../../../docs/roadmap/architecture/code-map.md)
for the full 45-subsystem index.

- `src/fdai/core/risk_gate/`
- `src/fdai/core/tiers/{t0_deterministic,t1_lightweight,t2_reasoning}/`
- `src/fdai/core/quality_gate/`
- `src/fdai/core/executor/`
- `src/fdai/core/event_ingest/` (idempotency + dedup)
- `src/fdai/core/trust_router/`
- `src/fdai/agents/{forseti,var,thor,vidar,saga}.py`

## The Loop

**One batch = one focused change = one commit.**

### 1. Critique honestly

- Read the module and its adjacent modules (imports, callers).
- List real defects: safety-invariant violations (stop-condition /
  rollback / blast-radius / audit), off-by-one, ordering hazards,
  fail-open branches, missing idempotency, non-async where async is
  required (see the async-seam table below).
- **Do not fabricate.** If no real defect is found, say so and either
  pick a different module or switch to coverage-driven hardening
  (test-only, 0 production risk).
- Recording a "false-positive after verification" is a legitimate
  outcome. Example from repo memory: `lock.py::snapshot()` looked
  like a "dict changed size" hazard, but the asyncio single-thread
  execution model made it impossible. The finding was rejected as an
  "impossible-state defense" and no code was added.

### 2. Harden

- Fix ONE finding per batch. Do not blend fixes.
- **Fail closed**: ambiguity / verification failure / unexpected error
  MUST abstain or route HIL. Never fail open into an autonomous
  change.
- No empty catch, no bare `except`. Errors carry context and are
  logged with a correlation id.
- No defensive code for impossible states. Validate at system
  boundaries (event ingress / API / config / rule-catalog load) only.

### 3. Verify

- Run the most precise known pytest target immediately after each edit.
- When a batch spans multiple files or the owning test is unclear, run bare
  `make test-changed` only if the worktree contains that batch alone. Parallel
  hardening sessions SHOULD use separate Git worktrees. In a shared dirty
  worktree, run focused checks before committing only owned paths, then run
  `make test-changed DIFF=<commit>^..<commit>` for the exact hardening commit.
  For a committed branch range, run `make test-changed DIFF=<base>...HEAD`.
- Run fast gates: `bash scripts/verify.sh --fast`.
- Finish with `bash scripts/verify.sh --full <test-path>` for the touched
  slice when the focused pytest command has not already covered it.
- Do NOT run `bash scripts/verify.sh --all` after each batch. Run it once at
  the end of a campaign only when the user explicitly requested a local
  whole-repository check or the work is at a merge/release boundary. Reuse a
  green result for the same commit and environment.
- Diff-scoped tests do not replace full coverage/regression gates before
  merge or release; those authoritative gates may run in CI.
- For coverage-driven work, use the single-module coverage recipe below.
- Safety-core property tests MUST still pass unchanged:
  - "high-risk never auto-executes"
  - "shadow mode never mutates"
  - "re-applying an action is a no-op"

### 4. Docs-first / docs-after

- If behavior, a DI seam, a config key, or a schema changed, update
  the affected docs (English + `-ko.md`) in the same commit. Docs and
  code never drift.
- New injectable seams are added to
  [project-structure.md § Customization via Dependency Injection](../../../docs/roadmap/architecture/project-structure.md#customization-via-dependency-injection).

### 5. Commit per file

- `git add <file>` (never `git add -A` while the tree is dirty).
- Conventional Commits, scope = touched subsystem:
  - `harden(<scope>): <what you fixed>` for a safety hardening.
  - `test(<scope>): cover <module> (<X% -> Y%>)` for coverage-only.
  - `fix(<scope>): <what you fixed>` for a plain bug fix.

### 6. Run external follow-up only after validation

- Do not watch, rerun, or troubleshoot GitHub Actions while a hardening batch is still being edited
  or while its focused checks are failing. Keep the critique loop local until the batch commits.
- Before any remote CI investigation, Azure operation, remote evaluation, or container image build,
  require the exact commit's centralized receipt:
  ```bash
  python3 scripts/automation/validation_queue.py check-commit HEAD
  ```
- A remote failure belongs to the exact tested commit. If fixing it changes code, stop remote
  polling, return to step 2, rerun the focused check, commit, and obtain a new receipt.
- Build container images from the receipted commit in a clean checkout or isolated worktree. Never
  let uncommitted hardening work leak into an image used for deployment.

## Coverage-Driven Recipe

The 0-risk companion to the critique loop: raise coverage without
touching production paths.

1. Establish the campaign baseline once, before the first batch:
   ```
   pytest -q -p no:cacheprovider --cov=src/fdai --cov-branch \
     --cov-report=term-missing
   ```
  Record the ordered under-covered module list in the session plan. Every
  later batch in the same campaign MUST reuse that list instead of rerunning
  the whole tree. An existing coverage report from another commit may guide
  candidate selection, but is not verification evidence.
2. Sort by lowest coverage (skip testing fakes):
   ```
   coverage report --skip-covered --sort=cover | grep -vE "/testing/"
   ```
3. Pick one module under 90%. Read its "Missing" line ranges.
4. Add tests that exercise exactly those branches. Deterministic:
   seed randomness, no network, no wall clock.
5. Verify the single module. The `--cov=` flag takes a **dotted
   module**, not a slash path; `-o addopts=""` drops the project's
   default `--cov` floor for this single-file check:
   ```
   pytest <testfile> --cov=fdai.<dotted.module> --cov-branch \
     --cov-report=term-missing --no-cov-on-fail -o addopts=""
   ```
6. Commit: `test(<scope>): cover <module> (<X% -> Y%>)`.

At the end of a multi-batch campaign, rely on the merge/release CI coverage
gate by default. Run `scripts/verify.sh --all` locally only under the explicit
whole-suite conditions in step 3 above.

## Async-Seam Table

Five provider Protocols are `async` (real backends block the event
loop otherwise); three are sync.

| Seam | Async? | Reason |
|------|--------|--------|
| EventBus | async | Kafka / Event Hub over `:9093` |
| StateStore | async | asyncpg / Postgres |
| SecretProvider | async | Key Vault + PE round-trip |
| WorkloadIdentity | async | OIDC token exchange |
| Inventory | async | Azure Resource Graph queries |
| SchemaRegistry | sync | in-process registry |
| ContractValidator | sync | Pydantic model validation |
| ConfigProvider | sync | startup-only load |

Do not flip either category. `pytest-asyncio` is configured with
`asyncio_mode = "auto"` in [`pyproject.toml`](../../../pyproject.toml)
so no per-test marker is required.

## Traps to Avoid

- **`git add -A` with maintainer WIP present**: stages the maintainer's
  in-progress files into your commit. Use per-file `git add`.
- **`replace_string_in_file` with escaped quotes**: writing `\"` inside
  the tool's `newString` parameter puts a literal backslash-quote in
  the file. Use real quotes and let the tool handle escaping. Grep for
  `\\"` after a big edit to catch this.
- **`ruff ... && ... && git commit` chain that silently stops**: ruff
  failure with no output leaves the chain half-done. After a chained
  commit, always run `git log --oneline -1` to confirm the commit
  landed.
- **`mentioned()` in agent introspection**: uses `[a-z0-9-]+`, does
  NOT match underscore or dot. For tests, use single-token bucket /
  scope names (`rg-1`, `vms`, `keep`).

## Related

- Runnable prompts:
  [.github/prompts/critique-batch.prompt.md](../../prompts/critique-batch.prompt.md),
  [.github/prompts/harden-coverage.prompt.md](../../prompts/harden-coverage.prompt.md).
- Rule contract:
  [.github/instructions/coding-conventions.instructions.md](../../instructions/coding-conventions.instructions.md).
- Agent-code rules (auto-loaded for `src/fdai/agents/**`):
  [.github/instructions/agent-pantheon.instructions.md](../../instructions/agent-pantheon.instructions.md).
