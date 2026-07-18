# Contributing to FDAI

Thanks for picking up an FDAI issue. This file is the short procedural
guide. The **substantive contract** for what a PR MUST honor lives in
[.github/instructions/coding-conventions.instructions.md](.github/instructions/coding-conventions.instructions.md)
and the sibling files under `.github/instructions/`; read those first
if you have not already.

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
tracked hooks automatically, and `git: auto-pull` fetches every few
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

Before running tests, `scripts/verify.sh` checks clean-checkout and Docker build
context contracts. It catches untracked required guard inputs, missing
Dockerfile `COPY` sources, a broken `tests/scenarios/` re-include, an invalid
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
layer end-to-end (`FDAI_DATABASE_URL` gates the `tests/persistence/`
tests):

```bash
make dev-up                       # starts docker-compose
export FDAI_DATABASE_URL=postgresql://fdai:fdai@localhost:5432/fdai
make test
make dev-down                     # stops (volumes preserved)
```

## Opening issues

Issues are English-only project-tracking artifacts (never translated - see
[language.instructions.md](.github/instructions/language.instructions.md)).
**Always apply at least one domain label** so triage and filtering work; the
catalog uses a `prefix:` convention so related labels group together.

Pick labels along these axes (add as many as apply):

| Group | Labels | When to use |
|-------|--------|-------------|
| `area:` (subsystem) | `core-engine`, `trust-router`, `rule-catalog`, `risk-gate`, `quality-gate`, `executor`, `deploy-preflight`, `assurance-twin`, `agents`, `operator-console`, `chatops`, `detection`, `infra`, `delivery` | the subsystem the issue touches - **at least one is expected** |
| `tier:` | `T0`, `T1`, `T2` | when the issue is specific to a trust tier |
| `vertical:` | `resilience`, `change-safety`, `cost-governance` | the product vertical it serves |
| safety / governance | `safety-invariant`, `shadow-mode`, `hil`, `security`, `rule-governance` | when a safety or governance concern is central |
| cross-cutting | `i18n`, `csp-neutral`, `discovery-loop`, `needs-live-azure`, `shadow-to-enforce` | translation, provider-neutrality, discovery, or work that needs a live Azure setup / an enforce-promotion gate |
| type (built-in) | `bug`, `enhancement`, `documentation`, `question`, `help wanted` | the nature of the work |

Guidance:

- A good default is **one `area:` + one type** label; add `tier:` / `vertical:`
  / safety labels when they are central to the issue.
- Use `needs-live-azure` for anything that cannot be validated without a live
  (or emulated) Azure policy / resource setup, so those are easy to batch.
- Do NOT invent one-off labels; extend the catalog with a short PR that also
  updates this table and the label set (`gh label create`).
- Never put customer-identifying values in an issue title, body, or label
  ([generic-scope.instructions.md](.github/instructions/generic-scope.instructions.md)).

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

Both rules are enforced by convention (reviewer + agent discipline), not CI.
Use `gh issue comment <n>` and `gh issue edit <n> --add-label review-needed`.

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
