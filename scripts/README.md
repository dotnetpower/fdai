# Repository Scripts

The `scripts/` tree contains repository automation grouped by the subsystem it
operates. Keep `verify.sh` at the root as the stable local and CI verification
entry point; place other scripts in the domain directories below.

## Layout

| Path | Responsibility |
|------|----------------|
| `verify.sh` | Stable facade for the fast and full repository gate suites. |
| `quality/architecture/` | Source-boundary, file-size, and subsystem fan-out gates. |
| `quality/localization/` | Translation, message-catalog, and derived-document checks and fixers. |
| `quality/repository/` | Repository-wide punctuation, GUID, and Markdown-link hygiene. |
| `integrity/` | Framework-surface protection, manifest generation, signing, and offline verification. |
| `governance/` | Architecture review, agent stewardship, governance transitions, and exemption expiry. |
| `catalog/` | Rule and chaos-scenario ingestion, generation, validation, execution, and evidence tools. |
| `deployment/local/` | Local pgvector and Redpanda development stack lifecycle. |
| `deployment/azure/` | Azure provisioning, deployment-plan, runner, and environment operations. |
| `deployment/release/` | Deployment bundle construction and productization verification. |
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
the old and new owning test areas run:

```bash
make test-changed
```

To test all changes on a branch, pass a Git diff range:

```bash
make test-changed DIFF=origin/main...HEAD
```

Changes to global Python test configuration, repository configuration data,
composition wiring, rule catalog data or loaders, shared contracts and provider
interfaces with cross-repository consumers, Python files outside a known source
layout, and mapped test paths that don't exist select the full suite. The
focused runner doesn't collect coverage and doesn't replace `make test` or
`bash scripts/verify.sh --full` before merging.

The runner executes non-integration tests first. It executes selected
`integration` tests only when `FDAI_DATABASE_URL` is set; otherwise it reports
that those tests were skipped. An integration-only change without a database
still exits successfully after confirming that integration tests were selected.

## Verification

Run the fast repository checks after changing script wiring:

```bash
bash scripts/verify.sh --fast
```

Use `bash scripts/verify.sh --full` before merging changes that alter shared
script behavior or cross-domain automation.
