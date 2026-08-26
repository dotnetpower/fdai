---
name: commit-readiness
description: |
   Recover from an FDAI commit-hook failure or handle a task-owned file that also
   contains unrelated edits. Routine authorized commits use an explicit pathspec
   and do not load this skill. Covers shared-path conflicts and failure routing.
version: 1.0.0
scope: repository
---

# Commit Readiness

Load this skill only after the normal commit path fails or when one task-owned file also contains
unrelated edits. It does not authorize a commit, replace focused validation, or permit hook bypasses.
The executable sources of truth are [`.githooks/pre-commit`](../../../.githooks/pre-commit) and
[`.pre-commit-config.yaml`](../../../.pre-commit-config.yaml).

## Normal path

Once the commit is authorized and focused validation and diff review are complete, stage only new
task-owned files when necessary, then commit all task-owned paths explicitly:

```bash
git add -- <new-task-owned-paths>
git commit -m "<message>" -- <task-owned-paths>
git rev-parse HEAD
```

Omit `git add` when there are no new files. The explicit pathspec preserves unrelated staged and
unstaged work. Do not run pre-commit separately: `git commit` invokes the authoritative hook. Do not
repeat a successful check unless its relevant inputs changed.

## Shared-path conflict

An explicit pathspec commits the complete current contents of each named path. If one named file
contains both task-owned and unrelated edits, do not commit it until those edits can be separated
without losing either side. Never stage, revert, stash, or rewrite another session's edits merely
to make a commit pass.

## Failure routing

| Failure | Correct response |
|---------|------------------|
| `uv is required` | Restore the repository development environment with `uv sync --extra dev`; do not bypass the hook. |
| Shared-path or mixed-edit failure | Defer that path or separate only the task-owned edit without altering unrelated work. |
| Ruff, whitespace, or EOF failure | Apply the narrow fix, inspect it, and retry the same commit once. |
| Translation, translation-quality, or derived-source failure | Update the paired or derived document semantically and refresh its recorded SHA. |
| Design-doc-impact failure | Read the route-selected owner document and add the required design update. Do not add an unrelated doc merely to satisfy path matching. |
| Framework integrity or protected-path failure | Stop and route through the approved framework or fork seam. Never disable, re-sign without authority, or bypass the guard. |
| Content-safety or hygiene failure | Remove the prohibited content at its source; do not add a broad exception to land the commit. |
| Unrelated baseline failure | Report the exact blocker and leave unrelated files unchanged. |

`git commit --no-verify`, temporary hook deletion, environment-based guard suppression, and broad
allowlist changes are not remediation paths.
