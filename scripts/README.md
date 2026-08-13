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
  focused tests under `tests/integration/scripts/`.
- The background Git auto-pull checks local dirty, rebase, and centralized-validation
  state before contacting the remote. It fetches only when the checkout can safely rebase.

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
Non-Python fixtures under `services/core-control-plane/tests/` and package resources under `src/` also
select the full suite because their consumers can't be inferred from imports.

Known repository inputs can declare a narrower owner before that fail-safe. For
example, `config/service-decomposition.json` maps to `services/core-control-plane/tests/scripts`. When the
static import graph selects at least 250 test paths and every changed Python
source has exactly one owner in `services/core-control-plane/tests/service-suites.json`, the runner uses the
union of those service-owned suites and every impacted consumer outside them.
This collapses redundant in-service test files to their owner directory without
dropping cross-service consumers. Missing or overlapping ownership keeps the
original import-impact selection. Set `FDAI_TEST_IMPACT_SERVICE_THRESHOLD` to
a positive integer to tune the crossover without changing the fail-safe.

The runner executes non-integration tests first in a sanitized environment. It
executes selected `integration` tests only when
`FDAI_CHANGED_TEST_INTEGRATION=1` and `FDAI_DATABASE_URL` points to a dedicated
validation database; a configured local runtime database alone never opts in.
The local full-stack preparation starts an isolated PostgreSQL cluster on loopback
port `5433`, writes its ignored DSN as `FDAI_VALIDATION_DATABASE_URL`, and the
central validation queue maps only that value into integration-test processes. An
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

The pre-tool guard also reserves each edited repository path for the current agent session. A
second session is blocked only while that reservation is at most 30 minutes old and the target is
still dirty. The same session refreshes its reservation on each edit, and a clean target can be
claimed immediately. Reservations live under the Git directory and never enter a commit.

Open one VS Code chat with the `Integration Validator` custom agent. Inspect and
process the accumulated batch from that session:

```bash
make validation-status
make validation-run
```

The runner takes a non-blocking repository-wide lock and resets one persistent,
isolated detached worktree to the current integration `HEAD`. It reuses local
Python caches and the installed Console and CLI dependency trees from any
available linked worktree. Dependency synchronization is skipped when the
locked dependency files and selected Python interpreter have the same digest.

Post-commit wakeups update one latest-HEAD request and reuse one stable background drain worker.
The worker validates another batch only when a newer request arrived during the successful run;
failed runs stop for repair instead of retrying continuously. Background validation is limited to
180% CPU and at most two deterministic changed-test shards. A manual Integration Validator run
keeps the adaptive one-to-four-shard range based on CPU load and available memory. Set
`FDAI_PYTEST_MAX_WORKERS` to lower that foreground cap. Each shard records status, duration, and a
command-bound pass marker under the shared queue state. An identical retry skips completed shards
while rerunning failed ones. Fast gates use the commit diff to skip checks with unrelated declared
inputs. Repository-wide text checks and the design-impact check still run on every batch, and
running `verify.sh --fast` without `--diff` preserves the complete fast-gate suite.

Each stage records its duration and cache status in the run record and commit
receipts under `.git/fdai-validation-queue/`. If a late gate fails, a retry at
the same base, `HEAD`, mode, integration settings, database identity, and local
resolved-model digest reuses successful changed tests and individual gates.
Changing any of those inputs invalidates the matching cache. A failed gate
leaves the commits pending. A successful run writes per-commit receipts, and
the pre-push hook blocks outgoing commits without those receipts.

Central validation also runs the complete pre-push structural gate set and
binds its input digest to each receipt. Pre-push reuses that evidence only for
the exact current `HEAD` when the shared runner, every structural gate,
`pyproject.toml`, and `uv.lock` still match. Missing or stale evidence falls
back to the same shared gate runner in an isolated committed worktree. Exact
evidence skips isolated-worktree creation and the duplicate committed-snapshot
checks entirely.
The hook uses the remote ref that Git already negotiated for the push to check
fast-forward ancestry and the outgoing range. It doesn't issue a duplicate
network fetch before validation.

When changed tests fail and a descendant fix commit is queued, the runner keeps
the failed pytest node IDs outside the detached worktree. The next run combines
those failures with tests selected from the failed-`HEAD`-to-fix-`HEAD` delta
instead of repeating every test that already passed. Reuse requires the same
validation base, mode, dependency fingerprint, integration setting, database
identity, and local resolved-model digest. Changes to the selector, queue
runner, impact resolvers, or any `conftest.py` restart the complete changed-test
stage. Integration-enabled runs also restart the complete stage because their
two pytest phases don't yet provide a complete partial-run proof. Receipts
record the source `HEAD` and number of resumed failures.

Check whether one exact revision is ready for slow external follow-up work:

```bash
python3 scripts/automation/validation_queue.py check-commit HEAD
```

GitHub Actions investigation or reruns, Azure plan/apply/deploy operations, remote evaluation, and
container image build/push work begin only after this check passes. Short read-only context checks
such as `az account show` may run earlier. A later code edit creates a new revision and requires a
new receipt before another external run.

Preview completed worktrees that are eligible for conservative cleanup:

```bash
make worktree-maintenance
make worktree-cleanup MIN_AGE_HOURS=24
```

The default command is read-only. Apply mode removes only registered worktrees
that are clean, already reachable from `main`, older than the minimum activity
age, outside the primary and validator paths, and unused as a current directory
by any visible process. Dirty, unmerged, recent, and active worktrees stay in
place. Pending queue records for a removed path move to `retired/` only when the
same commit already has a validation receipt.

Every successful local commit writes a concise handover record under the Git
common directory at `.git/fdai-handovers/`. The record contains the commit,
subject, branch, source worktree, and changed repository paths. It doesn't copy
file contents, logs, prompts, credentials, or environment values. Start a new
session with:

```bash
bash scripts/automation/resume.sh
```

The report selects the newest recorded commit relevant to the current history
and resolves its validation state from the central receipt directory at read
time.

`make validation-status` lists only pending commits reachable from the current
`HEAD` and summarizes pending work on other branches or worktrees. Show every
pending id only when diagnosing queue history:

```bash
python3 scripts/automation/validation_queue.py status --all
```

Run the whole repository suite only at an explicit merge or release boundary:

```bash
make validation-all
```

Worker sessions may still use `bash scripts/verify.sh --full <path>` for one
focused pytest target. Direct fast/all verification and unscoped test-tool runs
are denied by the workspace `PreToolUse` hook so parallel sessions cannot duplicate
the centralized load. The pre-push hook runs Python structural gates with the
project interpreter selected by `uv`, so those gates parse the same supported
language version as centralized validation.

The same hook records route-selected design documents once per agent session and checks their
content hashes only for high-risk edits. Treat documentation synchronization as a batch boundary:
read the routed context once, iterate on code with focused checks, then update the affected design
documents once after behavior stabilizes and run the final focused validation. Docs-first requires
current design context before implementation; it does not require rewriting a document before each
code edit. The dispatcher can inspect nested parallel payloads, but current VS Code builds do not
invoke workspace hooks for wrapper-contained reads. Route-required documents therefore still use
individual `read_file` calls until the host forwards those payloads. Nested edits and commands are
checked before reads when a host does forward a batch, so a concurrent read cannot satisfy an edit
in the same batch. Docs-after is evaluated against the completed diff, not each intermediate tool
call.

## Roadmap implementation verification

The roadmap verification pipeline treats each canonical English document and its
Korean translation as one durable job. Queue state, leases, receipts, diagnostics,
and the append-only ledger live under the Git common directory at
`.git/fdai-roadmap-verification/`, so linked worktrees and process restarts share one
campaign without committing runtime state.

Synchronize the tracked `docs/roadmap/**/*.md` inventory and inspect progress:

```bash
make roadmap-verification-sync
make roadmap-verification-status
```

`report` mode gives Copilot read-only file discovery, search, and shell tools in
an isolated worktree but no write tool. It records `reviewed`, `gap_found`,
`designed`, `not_applicable`, or `blocked` evidence and removes the temporary
branch. Before returning a result, the worker confirms that every reported evidence
path exists exactly as written relative to the repository root:

```bash
make roadmap-verification-report
```

Retry one failed report job without claiming newer queued work:

```bash
make roadmap-verification-retry
```

`apply` mode is for the dedicated clean campaign worktree created by the timer
installer. It may implement a verified gap, add focused tests, update both document
variants, and commit. The orchestration layer then independently runs the diff-based
test selector and translation gate, checks `code_verification_status` and
`code_verified_at` frontmatter, and fast-forwards the campaign branch only when every
check passes:

```bash
make roadmap-verification-apply
```

Receipts retain the exact evidence paths, their content digest, the document blob,
the tested commit, and the independent checks. A later document, route mapping, code,
or test evidence change invalidates the receipt and returns the job to `queued`.
Ambiguous design stays `blocked`; it never receives an implementation receipt.

Install a persistent user-systemd timer in report mode first:

```bash
python3 scripts/automation/install_roadmap_verification_timer.py install
```

After reviewing report outcomes, reinstall in apply mode to use the cumulative
`roadmap-verification/campaign` worktree:

```bash
python3 scripts/automation/install_roadmap_verification_timer.py install --apply
```

Each timer tick exits after at most one document. Recent Copilot activity and fresh
`.improve/sessions/*.lease` files hold the cycle. If a process stops mid-job, the
lease expires and the next tick reclaims that same document before selecting another.
Create `.git/fdai-roadmap-verification/STOP` or `.improve/STOP` for an explicit pause.
Removing the timer leaves the campaign branch, receipts, and diagnostics intact:

```bash
python3 scripts/automation/install_roadmap_verification_timer.py remove
```
