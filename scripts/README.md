# Repository Scripts

The `scripts/` tree contains repository automation grouped by the subsystem it
operates. Keep `verify.sh` at the root as the stable local and CI verification
entry point; place other scripts in the domain directories below.

## Layout

| Path | Responsibility |
|------|----------------|
| `verify.sh` | Stable facade for the fast and full repository gate suites. |
| `quality/architecture/` | Source-boundary, file-size, and subsystem fan-out gates. |
| `quality/localization/` | Translation, readable Korean, message-catalog, and derived-document checks and fixers. |
| `quality/repository/` | Repository-wide punctuation, GUID, and Markdown-link hygiene. |
| `integrity/` | Framework-surface protection, manifest generation, signing, and offline verification. |
| `governance/` | Architecture review, agent stewardship, governance transitions, and exemption expiry. |
| `catalog/` | Rule and chaos-scenario ingestion, generation, validation, execution, and evidence tools. |
| `deployment/local/` | Local pgvector and Redpanda development stack lifecycle. |
| `deployment/azure/` | Azure provisioning, deployment-plan, runner, and environment operations. |
| `deployment/release/` | Deployment bundle and offline kit staging, signing, license issuing, the air-gap drill, and productization verification. |
| `automation/` | Session, workflow, Git auto-pull, and diff-scoped test helpers. |
| `lib/` | Stable machine-readable support data shared by repository scripts. |

## Conventions

- Run scripts from the repository root unless their usage text says otherwise.
- Resolve the repository root without relying on the script's directory depth.
- Put a new script in the directory that owns its behavior. Do not add another
  root-level entry point unless it is a stable facade used across domains.
- Update CI workflows, Git hooks, tests, and documentation in the same change
  whenever a script path moves.
- Keep shell scripts executable and cover behavior-bearing Python scripts with
  focused tests under `tests/scripts/`.

## Run changed tests

Use the diff-scoped runner during the edit loop. It includes tracked, staged,
and untracked working-tree changes, then maps source and repository data to the
pytest paths that own them. Behavior-bearing script support data, including
design routes, framework surface lists, baselines, and allowlists, maps to the
script test suite. Renames are evaluated as a deletion plus an addition so both
the old and new owning test areas run. For Python sources, a static import graph
adds direct and transitive consumer tests outside the mirrored test directory:

```bash
make test-changed
```

To test all changes on a branch, pass a Git diff range:

```bash
make test-changed DIFF=origin/main...HEAD
```

Changes to global Python test configuration, repository configuration data,
database migrations, composition wiring, policy data, rule catalog data or
loaders, shared contracts and provider interfaces with cross-repository
consumers, Python files outside a known source layout, and mapped test paths
that don't exist select the full suite. The focused runner doesn't collect
coverage and doesn't replace `make test` or `bash scripts/verify.sh --all` at
a merge or release boundary.
Non-Python fixtures under `tests/` and package resources under `src/` also
select the full suite because their consumers can't be inferred from imports.

The runner executes non-integration tests first in a sanitized environment. It
executes selected `integration` tests only when
`FDAI_CHANGED_TEST_INTEGRATION=1` and `FDAI_DATABASE_URL` points to a disposable
test database; a configured local runtime database alone never opts in. An
integration-only change without opt-in still exits successfully after confirming
that integration tests were selected.
The exact repository inputs that CI classifies as Python-impacting are covered
by a regression test so local and CI selection can't drift silently.
Selections with at least 20 pytest paths use up to eight xdist workers by
default; smaller selections stay single-process to avoid worker startup cost.
Override the cutoff with `FDAI_CHANGED_TEST_PARALLEL_THRESHOLD` and the worker
cap with `FDAI_PYTEST_MAX_WORKERS`.

## Verification

Parallel worker sessions run focused tests only. Every successful commit is
automatically added to a queue under the shared Git common directory, so linked
worktrees feed the same validator without writing runtime state into the repository.

Open one VS Code chat with the `Integration Validator` custom agent. Inspect and
process the accumulated batch from that session:

```bash
make validation-status
make validation-run
```

The runner takes a non-blocking repository-wide lock, creates an isolated detached
worktree at the current integration `HEAD`, reuses local dependency caches, caps
changed-test workers at two by default, and runs changed tests plus the fast gates
once for the entire reachable pending batch. A failed gate leaves the commits
pending. A successful run writes per-commit receipts, and the pre-push hook blocks
outgoing commits without those receipts.

Run the whole repository suite only at an explicit merge or release boundary:

```bash
make validation-all
```

Worker sessions may still use `bash scripts/verify.sh --full <path>` for one
focused pytest target. Direct fast/all verification and unscoped test-tool runs
are denied by the workspace `PreToolUse` hook so parallel sessions cannot duplicate
the centralized load.
