# Contributing to FDAI

Thanks for picking up an FDAI issue. This file is the short procedural
guide. The **substantive contract** for what a PR MUST honor lives in
[.github/instructions/coding-conventions.instructions.md](.github/instructions/coding-conventions.instructions.md)
and the sibling files under `.github/instructions/`; read those first
if you have not already.

For the local environment checklist - Azure `az login`, the optional
private-network VPN, environment variables, and starting the local stack - see
[DEVELOPING.md](DEVELOPING.md).

## Prerequisites

- Python 3.13
  ([`pyproject.toml`](pyproject.toml) pins the target).
- [`uv`](https://docs.astral.sh/uv/) - the project's package manager.
- A POSIX shell (`bash`), `git`, and `make` are enough for the
  Python + docs workflow. `docker compose` is only needed for the
  optional local dev stack (`make dev-up`).

## One-time setup

```bash
uv sync --extra dev              # installs the runtime + dev deps
make hooks-install               # enable the shared tracked git hooks
```

`make hooks-install` points `core.hooksPath` at the tracked
[`.githooks/`](.githooks/) directory. The tracked `pre-commit` hook delegates
to [`.pre-commit-config.yaml`](.pre-commit-config.yaml), so every commit checks
Ruff lint and formatting plus the repository hygiene gates before it is
created. This avoids the unsupported combination of generating a hook under
`.git/hooks` while `core.hooksPath` points somewhere else.

Because we collaborate directly on `main` (no feature branches), the tracked
`pre-push` hook also keeps pushes safe and fast: it refuses to push when the
local branch is **behind** `origin` (pull --rebase first, so conflicts surface
locally instead of as a rejected push), blocks leftover merge-conflict
markers, and checks changed Python files. It is intentionally light - no full
test suite, no mypy, no build. Bypass once with `git push --no-verify` or
`FDAI_SKIP_PUSH_CHECKS=1 git push`.

Opening the repo in VS Code also runs two folderOpen tasks (see
[`.vscode/tasks.json`](.vscode/tasks.json)): `hooks: install` wires both
tracked hooks automatically, and `git: auto-pull` fetches every 10
minutes and rebases your local `main` **only when the working tree is
clean** - keeping everyone close to the remote. Run `git: pull now`
(rebase, autostash) from the task list any time you want to sync
manually. Allow automatic tasks when VS Code prompts.

## Everyday workflow

The [`Makefile`](Makefile) is the single entry point for local CI parity:

| Command | What it runs |
|--------|--------------|
| `make check` | `lint` + `gates` + `test` + `operator` - reproduces the CI merge gate. Run this before pushing. |
| `make lint`  | `ruff format --check` + `ruff check` + `mypy --strict`. |
| `make format`| `ruff format` + `ruff check --fix`. Mutates files - review the diff. |
| `make gates` | Repository hygiene, localization, and architecture boundary checks. |
| `make test`  | Parallel unit tests, serial live-DB integration tests, and the safety-core coverage floor. |
| `make operator` | Console and CLI tests, type checks, builds, and the console entry-bundle budget. |

The full CI pipeline lives in
[.github/workflows/ci.yml](.github/workflows/ci.yml); `make check` is
the fastest way to reproduce it without pushing.

### Prepare a release version

Run [automatic-version.yml](.github/workflows/automatic-version.yml) manually
from the `main` branch when you intend to prepare a release. Supply the exact
protected `origin/main` commit as `commit_sha`. With no existing semantic-version
tag, the workflow starts at `v0.1.1`; later runs increment the highest `vX.Y.Z`
tag by one patch (`v0.1.2`, `v0.1.3`, and so on). It updates the Python, console,
and CLI package metadata in lockstep, creates a `chore(release): vX.Y.Z` commit,
and publishes that commit plus an annotated tag atomically. Concurrent runs
recalculate the version and retry instead of reusing a tag.

Ordinary pushes to `main` don't change the package version or create a release
tag. Pull with rebase after preparing a release so the generated package-version
commit is present locally. The workflow requires GitHub Actions to have
`contents: write` permission and the `main` branch rules to allow the
repository's Actions identity to push.

### Coverage floor

`make test` fails when combined safety-core branch coverage falls below 90%.
The target list is defined once in [`pyproject.toml`](pyproject.toml) and the
shared runner at
[`scripts/quality/ci/run-python-tests.sh`](scripts/quality/ci/run-python-tests.sh)
is called by both local verification and CI.

The runner uses at most eight pytest-xdist workers for non-integration tests
and keeps live-DB integration tests serial. On 2026-07-18, the same 8,073
non-integration tests without coverage took 147.81 seconds serially and 38.92
seconds with the capped parallel configuration on the maintainer workstation.
The command always reports the 25 slowest tests so fixture and I/O regressions
remain visible.

Parallel Python jobs restore one shared uv cache, but only the `ruff • mypy` job writes it.
The other setup-uv steps set `save-cache: false`, preventing concurrent post-job cache
reservations without disabling cache restores.

Before running tests, `scripts/verify.sh` checks clean-checkout and Docker build
context contracts. It catches untracked required guard inputs, missing
Dockerfile `COPY` sources, a broken `services/core-control-plane/tests/scenarios/` re-include, an invalid
resolved model manifest, and live-DB tests that perform setup before their skip
guard.

### Docs are code

The
[docs-first / docs-after rule](.github/instructions/coding-conventions.instructions.md#documentation-workflow)
is enforced: every code change that touches behavior, a public
interface, a DI seam, a config key, or a schema updates the affected
doc in the same PR. Bilingual pairs (`foo.md` + `foo-ko.md` under
`docs/**/` and root `README.md`) are gated by
`scripts/quality/localization/check-translations.sh`; if you edit an English source, run
[`scripts/quality/localization/refresh-translation-sha.py`](scripts/quality/localization/refresh-translation-sha.py)
after updating the Korean sibling so the recorded
`translation_source_sha` matches.

### Optional: dev stack

The Postgres (pgvector) + Redpanda dev stack is not required for the
unit tests. Bring it up only when you want to exercise the persistence
layer end-to-end (`FDAI_DATABASE_URL` gates the `services/core-control-plane/tests/persistence/`
tests):

```bash
make dev-up                       # starts docker-compose
export FDAI_DATABASE_URL=postgresql://fdai:fdai@localhost:5432/fdai
make test
make dev-down                     # stops (volumes preserved)
```

## Planning and tracking work

Planning happens in GitHub issues; the
[FDAI delivery board](https://github.com/users/dotnetpower/projects/7) is the single view over
them. The issue body, labels, comments, and open or closed state are authoritative. The board is a
best-effort execution projection and never a prerequisite for local investigation, implementation,
focused validation, commit, push, or centralized validation. Every repository issue is added to
the board automatically, so an issue that is not on the board is synchronization drift to repair,
not a reason to stop delivery.

### Work item hierarchy

| Level | Label | Size | Owns |
|-------|-------|------|------|
| Epic | `type:epic` | one or more iterations | an outcome; child stories as GitHub sub-issues |
| Story | `type:story` | one iteration, one maintainer | a user-visible outcome with acceptance criteria |
| Task | `type:task` | one to three days | an implementation unit under a story, or standalone |
| Spike | `type:spike` | an explicit time box | a decision or a document, never shipped behavior |
| Bug | `bug` | whatever the defect costs | a reproduction plus the regression test that pins it |

Link children to their parent through **sub-issues** (`Add sub-issue` on the parent), not a manual
checklist in the body. The board's `Sub-issues progress` field then reports epic progress without
anyone updating it. Keep candidate story lines in an epic until they are scheduled or started;
do not pre-create the complete roadmap backlog. A story that cannot finish inside one iteration is
an epic that has not been split yet.

### Board columns

| Status | Meaning | Leaves the column when |
|--------|---------|------------------------|
| `Backlog` | accepted, not scheduled | triage assigns a `priority:` and a Size |
| `Ready` | triaged, sized, unblocked | someone explicitly starts the work |
| `In progress` | assigned and actively worked | the exit criteria are satisfied |
| `In review` | exit criteria met, evidence posted | the author or a reviewer confirms |
| `Blocked` | a named external dependency is missing | that dependency clears |
| `Done` | every exit criterion satisfied, issue closed | never |

`Blocked` requires the `blocked` label **and** a comment naming the dependency and who owns it.
"Waiting for a live Azure environment" is `needs-live-azure`, not `blocked`.

### Working agreement

- **Create the durable record before the durable change.** Read-only analysis and reproduction may
  start immediately. Reuse or open an issue before the first task-owned commit or external state
  change. An explicitly requested item may move directly from `Backlog` to `In progress`; `Ready`
  is a queue, not an approval gate.
- **Assignee means accountable owner.** An issue may be assigned while it is in `Backlog` or
  `Ready`. `Status = In progress`, not assignment alone, means work is active.
- **WIP limit is two active outcomes.** Count `Story` and `Bug` items per maintainer. Child `Task`
  items under those outcomes do not consume another outcome slot, so bounded parallel agents can
  work without turning the board into a concurrency lock.
- **Priority is a commitment, not a wish.** `priority:p0` blocks a release, a safety invariant, or
  another maintainer; `priority:p1` is committed to the current or next iteration; `priority:p2`
  and `priority:p3` are not scheduled.
- **A pull request closes its issue.** Write `Closes #<n>` in the PR body; merging moves the board
  item to `Done` automatically. A PR without a linked issue needs a one-line reason in its
  description.
- **Triage weekly.** Anything with an empty `Priority` or the `needs-triage` label is reviewed,
  given a type, a priority, an `area:`, and exit criteria, or closed as `not planned`.
- The board mirrors public issues only. Never put a tenant id, subscription id, resource name,
  endpoint, or secret in an issue, a comment, or a board field
  ([generic-scope.instructions.md](.github/instructions/generic-scope.instructions.md)).

### Non-blocking board operation

Keep the start path short. The hard issue contract is an outcome, an `area:`, one work type, and
observable Exit criteria. Priority, Size, Iteration, Quarter, Team, parent linkage, and a successful
Project API call are planning metadata that may be completed during triage.

Use the local helper for bounded Project updates:

```bash
python3 scripts/automation/project-board.py start <issue-number>
python3 scripts/automation/project-board.py sync
python3 scripts/automation/project-board.py sync --apply
```

`start` assigns the current maintainer and attempts to set `Status = In progress`, `Work type`, and
`Priority`. `sync` previews drift. `sync --apply` derives lifecycle-owned status from the issue and
copies canonical type and priority labels into Project fields. GitHub and Project failures emit a
warning and return success by default so local work continues. Use `--strict` only for a dedicated
board-health check. Never call the helper from pre-commit, pre-push, centralized validation, or a
test gate.

If GitHub is unavailable, continue local investigation, implementation, focused validation, and
task-owned commits. Record the deferred synchronization in the completion report and retry it when
GitHub returns. A security finding remains the exception: use the private advisory path and never
create a public tracking issue.

### Delivery milestones

Milestones are the release axis. Each one names an outcome and the evidence that closes it, and
each is measured against a machine-readable source rather than a status opinion.

| Milestone | Due | Outcome | Closes when |
|-----------|-----|---------|-------------|
| M1 - Evidence spine | 2026-08-31 | measurement becomes claimable | the SRE capability pack is complete and the recorded baseline is claim-eligible |
| M2 - Authority spine | 2026-09-30 | promotion becomes possible | the shared safeguard contract, A3-E authority, and the isolated executor are in place |
| M3 - Closure | 2026-10-30 | every capability carries a verdict | all coverage cells, all constitutional requirements, and every workflow promotion decision are closed |

Work is organized into four lanes that run in parallel through every milestone rather than in
sequence: **Evidence** (scenario coverage and baselines), **Authority** (safety contracts and
promotion), **Integration** (service decomposition and adapters), and **Experience** (console,
builder, and documentation). Each milestone has one epic per lane, so a slipping lane never blocks
the other three.

Sprints are two weeks and named after the increment they deliver, not numbered abstractly. A
milestone spans two sprints.

### Board fields

`Work type` and `Priority` mirror canonical issue labels. Closed issues project to `Done`; open
`completed` issues project to `In review`; `blocked` projects to `Blocked`; explicit `Ready` and
`In progress` states are preserved. Reopened or otherwise unclassified work returns to `Backlog`.
Project fields never override issue criteria, labels, evidence comments, or issue state.

Size is required only before an item is deliberately queued in `Ready`. `Iteration` applies only
to scheduled stories, tasks, spikes, and bugs. `Quarter`, `Start date`, and `Target date` apply to
epics when they are placed on a roadmap. Leave `Team` empty until real teams exist; use existing
`area:` labels rather than placeholder squads. Keep the Task Board focused on non-epic executable
work, the monthly roadmap on scheduled stories, and the quarterly roadmap on epics.

Issues that predate this scheme were mapped retrospectively: `Priority` came from the `[P0-2]`
style prefix where the title carried one, otherwise from the safety and security labels;
`Size` came from the exit-criteria count, falling back to discussion volume for issues opened
before exit criteria were required. Epics take their dates from the real created and closed
timestamps, and an open epic keeps an empty `Target date` rather than an invented one. Treat those
values as a starting point and correct any that read wrong.

## Opening issues

Issues are English-only project-tracking artifacts (never translated - see
[language.instructions.md](.github/instructions/language.instructions.md)).
Start from the form that matches the work - **Epic**, **User story**, **Bug report**, **Spike**, or
the generic **FDAI work item**. Each form applies its `type:` label and `needs-triage`, and each
one requires exit criteria. The generic work item is the fast path: scope and planned evidence may
be refined after creation without delaying explicitly requested work.
**Always apply at least one domain label** so triage and filtering work; the
catalog uses a `prefix:` convention so related labels group together.

Pick labels along these axes (add as many as apply):

| Group | Labels | When to use |
|-------|--------|-------------|
| `type:` (hierarchy) | `epic`, `story`, `task`, `spike` | the work-item level - applied by the issue form, one is expected |
| `priority:` | `p0`, `p1`, `p2`, `p3` | the scheduling commitment - assigned at triage, one is expected |
| `area:` (subsystem) | `core-engine`, `trust-router`, `rule-catalog`, `risk-gate`, `quality-gate`, `executor`, `deploy-preflight`, `assurance-twin`, `agents`, `operator-console`, `chatops`, `detection`, `infra`, `delivery` | the subsystem the issue touches - **at least one is expected** |
| `tier:` | `T0`, `T1`, `T2` | when the issue is specific to a trust tier |
| `vertical:` | `resilience`, `change-safety`, `cost-governance` | the product vertical it serves |
| safety / governance | `safety-invariant`, `shadow-mode`, `hil`, `security`, `rule-governance` | when a safety or governance concern is central |
| cross-cutting | `i18n`, `csp-neutral`, `discovery-loop`, `needs-live-azure`, `shadow-to-enforce` | translation, provider-neutrality, discovery, or work that needs a live Azure setup / an enforce-promotion gate |
| lifecycle | `needs-triage`, `needs-exit-criteria`, `blocked`, `completed`, `review-needed` | not triaged yet, invalid work-item contract, waiting on a named dependency, all criteria satisfied, or waiting for author/reviewer confirmation |
| nature (built-in) | `bug`, `enhancement`, `documentation`, `question`, `help wanted` | the nature of the work, orthogonal to `type:` |

Guidance:

- A good default is **one `type:` + one `priority:` + one `area:`**; add `tier:` / `vertical:` /
  safety labels when they are central to the issue.
- Use `needs-live-azure` for anything that cannot be validated without a live
  (or emulated) Azure policy / resource setup, so those are easy to batch.
- Do NOT invent one-off labels; extend the catalog with a short PR that also
  updates this table and the label set (`gh label create`).
- Never put customer-identifying values in an issue title, body, or label
  ([generic-scope.instructions.md](.github/instructions/generic-scope.instructions.md)).
- **Exit criteria are required.** Every issue body includes an `## Exit criteria` section with
  one or more observable, binary checkbox items (`- [ ] ...`). State the outcome that proves the
  work is complete, not only the implementation activity. An issue without exit criteria receives
  `needs-exit-criteria` and is not ready for implementation or closure.

Do NOT open a public issue for a security finding - see
[Reporting security issues](#reporting-security-issues) below.

## Working on issues

Every issue MUST end up with a trail of what happened to it. Two rules apply
whenever you act on an issue (writing code, investigating, or just reviewing):

- **Always comment (MUST).** When an issue is worked on or reviewed, add a
  comment describing what was done or found - the change, the files touched,
  the outcome, or why no change was needed. This holds even when the answer is
  "already implemented" or "will not fix". An issue that was acted on but
  carries no explanatory comment is incomplete. Comments are English-only,
  like every other issue field, and never carry customer-identifying values.
- **`review-needed` on others' issues (MUST).** When you address an issue that
  was **registered by someone other than the acting maintainer**, apply the
  `review-needed` label so the original author (or another maintainer) does a
  confirmation pass before it is closed. Do not self-close another person's
  issue silently. For an issue you opened yourself, the label is optional -
  close it directly once the comment trail shows it is done.
- **Residual work keeps the issue open (MUST).** Compare the implementation and verification
  evidence against every exit criterion. If any criterion remains unsatisfied, comment with the
  exact residual work and keep the issue open. Do not use `completed` for partial delivery.
- **Completed means evidenced and closable (MUST).** When every exit criterion is satisfied, add
  an English completion comment, apply `completed`, and close the issue only when no residual work
  remains. Use GitHub's `not planned` state plus an explanatory comment for `wontfix`, duplicate,
  or invalid closure; those outcomes do not receive `completed`.
- **Reopen resets completion (MUST).** Remove `completed` when an issue is reopened. Reapply it only
  after the current exit criteria are satisfied again.

These rules are enforced by the issue form, the lifecycle workflow, reviewer judgment, and agent
discipline.
Use `gh issue comment <n>`, `gh issue edit <n> --add-label completed`, and
`gh issue edit <n> --add-label review-needed` as applicable.

## Pull requests

Follow the
[`.github/PULL_REQUEST_TEMPLATE`](.github/PULL_REQUEST_TEMPLATE); it
enumerates the safety-mode declaration (shadow vs enforce), the four
safety invariants (stop-condition / rollback / blast-radius / audit),
and the docs-updated checkbox.

Commit format is Conventional Commits
(`type(scope): summary`, e.g. `feat(risk-gate): add prod-guard axis`);
CI does not enforce the format but reviewers will nudge you toward it.

## Reporting security issues

Do NOT open a public issue for a security finding. See the SECURITY
posture in
[`.github/instructions/coding-conventions.instructions.md § Safety`](.github/instructions/coding-conventions.instructions.md#safety)
and email the maintainer listed in
[LICENSE](LICENSE) / `pyproject.toml` `[project].authors`.

## License

FDAI ships under MIT (see [LICENSE](LICENSE)); by opening a PR you
agree to license your contribution under the same terms.
