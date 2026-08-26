---
name: commit-readiness
description: |
  Prepare task-owned FDAI changes for a local commit without discovering known
  staged-snapshot defects inside `git commit`. Use when a commit is authorized,
  when `pre-commit: BLOCKED` appears, when a path may be both staged and
  unstaged, or when selecting pre-commit gates. Covers complete-file staging,
  hook-equivalent preflight, auto-fix restaging, and failure routing.
version: 1.0.0
scope: repository
---

# Commit Readiness

Use this skill only after implementation and focused validation are complete and a local commit is
authorized. It does not authorize a commit, replace behavior-focused tests, or permit hook bypasses.
The executable sources of truth are [`.githooks/pre-commit`](../../../.githooks/pre-commit) and
[`.pre-commit-config.yaml`](../../../.pre-commit-config.yaml).

## Before editing

Avoid predictable gate failures while choosing the change shape:

| Planned path or change | Required preparation |
|------------------------|----------------------|
| Root `README.md` or `docs/**/*.md` | Update the English/Korean pair together, preserve matching structure, and refresh `translation_source_sha` after the English content is final. Load the `i18n-catalog` skill. |
| User-facing doc derived from roadmap sources | Review and refresh its `derives_from[].sha` instead of changing only the source. |
| Behavior, contract, schema, structure, or config | Read route-selected design context directly and update the owning design in the same change when required. |
| `core/`, composition, shared providers/contracts, agents, schemas, or `.github/instructions/` | Determine whether the framework surface permits the edit. Load the owning domain skill; in a fork, load `fork-customization` before editing. |
| Rule, ActionType, risk table, or source catalog | Include the required runbook, risk-table evidence, or reference-only source update selected by `.pre-commit-config.yaml`. |
| Any tracked text | Use ASCII punctuation, readable NFC UTF-8 Korean, synthetic identifiers, and no customer or secret values. |

Do not wait for a failed commit to discover one of these companion changes.

## Build the staged snapshot

1. Inspect the worktree and identify the exact task-owned paths. Preserve unrelated staged,
   unstaged, and untracked changes.
2. Review the unstaged diff for each task-owned path, then stage the complete intended contents.
   The tracked hook deliberately rejects partial staging when the same path still has unstaged
   changes because pre-commit auto-fixes cannot be restored reliably in that state.
3. Review `git diff --cached -- <task-owned-paths>`. Confirm that the staged snapshot contains only
   the intended task and any required generated companion files.
4. Run the same overlap check as the tracked hook:

```bash
comm -12 \
  <(git diff --cached --name-only --diff-filter=ACMR | LC_ALL=C sort -u) \
  <(git diff --name-only --diff-filter=ACMR | LC_ALL=C sort -u)
```

The command MUST print nothing. If it prints a path, either stage that path's complete current
contents when every change in it belongs to this commit, or defer the whole path. Do not stage
another session's edits merely to make the intersection empty. If task-owned and unrelated edits
cannot be separated without partial staging, do not commit that path yet.

## Run the hook before `git commit`

Run the tracked hook explicitly against the prepared staged snapshot:

```bash
uv run pre-commit run --hook-stage pre-commit
```

This is the last development check, not a substitute for focused tests. If a hook changes a file:

1. Inspect the change and confirm it is task-owned and correct.
2. Stage that file again.
3. Re-run the overlap check.
4. Re-run the complete pre-commit command until it passes.
5. Review `git diff --cached --check` and the final staged diff, then commit without changing files
   between the successful preflight and `git commit`.

## Failure routing

| Failure | Correct response |
|---------|------------------|
| `uv is required` | Restore the repository development environment with `uv sync --extra dev`; do not bypass the hook. |
| `paths have both staged and unstaged changes` | Make each listed path complete in the staged snapshot or remove the whole path from this commit. Never stage unrelated changes. |
| Ruff, whitespace, or EOF failure | Apply or accept the narrow formatter fix, inspect it, re-stage it, and rerun the full preflight. |
| Translation, translation-quality, or derived-source failure | Update the paired or derived document semantically, refresh its recorded SHA, and run the localization checks before restaging. |
| Design-doc-impact failure | Read the route-selected owner document and add the required design update. Do not add an unrelated doc merely to satisfy path matching. |
| Framework integrity or protected-path failure | Stop and route through the approved framework or fork seam. Never disable, re-sign without authority, or bypass the guard. |
| GUID, punctuation, readable-Hangul, secret, or large-file failure | Remove the prohibited content at its source; do not add a broad exception to land the commit. |
| A baseline failure unrelated to the staged task | Record the exact command and failure, keep the task uncommitted, and resolve ownership before changing unrelated files. |

`git commit --no-verify`, temporary hook deletion, environment-based guard suppression, and broad
allowlist changes are not remediation paths.
