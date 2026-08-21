---
mode: agent
description: Run the narrowest FDAI verification for a supplied path or an explicit merge/release boundary.
---

# /verify - run focused FDAI verification

Run the narrowest executable check that can falsify the current change and report its summary.

## Steps

1. Confirm the current working directory is the repo root
   (`git rev-parse --show-toplevel`). If not, cd there.
2. If a Python venv exists at `.venv/`, activate it so `ruff` and `pytest`
   are on PATH: `source .venv/bin/activate`.
3. If the user supplied a pytest path, run focused verification:
   `bash scripts/verify.sh --full ${ARGS}`.
4. Otherwise select the smallest test file, node id, typecheck, linter, or structural checker for
   the task-owned paths. Do not substitute `verify.sh --fast`, `verify.sh --all`, or an unscoped
   package/repository suite.
5. If the user explicitly identifies a merge or release boundary, run `make validation-all`
   exactly once. Do not wait for or rerun the same validation.
6. Print the relevant command summary. If any gate failed:
   - Name the failing gate.
   - Point at the individual `scripts/check-*.sh` or the offending pytest
     path so the caller can rerun in isolation.
7. Do NOT commit anything from this prompt. Verification only.

## Guardrails

- Never bypass a gate (no `--no-verify`, no gate skipping).
- Never edit the gate scripts to make them pass; treat a failure as a real
  finding.
- Do not touch untracked or WIP files while verifying.
- Do not validate one session by selecting unrelated files from a shared dirty
   worktree. Prefer a separate Git worktree for concurrent sessions.
