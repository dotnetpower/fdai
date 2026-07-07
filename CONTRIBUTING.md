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
uv run pre-commit install        # or: make pre-commit-install
```

`pre-commit install` wires
[`.pre-commit-config.yaml`](.pre-commit-config.yaml) into `.git/hooks`,
so every commit runs the same gates CI runs (ruff format + check,
plus the five repo-hygiene scripts under `scripts/check-*.sh`).

## Everyday workflow

The [`Makefile`](Makefile) is the single entry point for local CI parity:

| Command | What it runs |
|--------|--------------|
| `make check` | `lint` + `gates` + `test` - reproduces the CI merge gate. Run this before pushing. |
| `make lint`  | `ruff format --check` + `ruff check` + `mypy --strict`. |
| `make format`| `ruff format` + `ruff check --fix`. Mutates files - review the diff. |
| `make gates` | `scripts/check-*.sh` (english-only, punctuation, guids, translations, core-imports). |
| `make test`  | `pytest -q` with the safety-core coverage floor (`--cov-fail-under=90`, wired in [`pyproject.toml`](pyproject.toml)). |

The full CI pipeline lives in
[.github/workflows/ci.yml](.github/workflows/ci.yml); `make check` is
the fastest way to reproduce it without pushing.

### Coverage floor

`make test` fails when total coverage falls below 90%. The individual
safety-critical modules (T0 deterministic engine, risk gate, rule
catalog loader, provider adapters) sit near ceiling; if your change
drops a module, add unit tests in the same PR.

### Docs are code

The
[docs-first / docs-after rule](.github/instructions/coding-conventions.instructions.md#documentation-workflow)
is enforced: every code change that touches behavior, a public
interface, a DI seam, a config key, or a schema updates the affected
doc in the same PR. Bilingual pairs (`foo.md` + `foo-ko.md` under
`docs/**/` and root `README.md`) are gated by
`scripts/check-translations.sh`; if you edit an English source, run
[`scripts/refresh-translation-sha.py`](scripts/refresh-translation-sha.py)
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
