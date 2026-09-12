---
mode: agent
description: Run focused FDAI verification for supplied paths or explicitly requested local whole-suite validation.
---

# /verify - run focused FDAI verification

Run the narrowest executable check that can falsify the current change and report its summary.
Use [Testing](../instructions/coding-conventions.instructions.md#testing) for scope, result reuse,
and the distinction between local evidence and authoritative pushed-SHA CI.

## Steps

1. Confirm the current working directory is the repo root
   (`git rev-parse --show-toplevel`). If not, cd there.
2. If a Python venv exists at `.venv/`, activate it so `ruff` and `pytest`
   are on PATH: `source .venv/bin/activate`.
3. If the user supplied pytest paths or node ids, run them directly in one invocation:
   `uv run pytest -q --no-cov <supplied-test-paths-or-node-ids>`.
4. Otherwise select the smallest test file, node id, typecheck, linter, or structural checker for
   the task-owned paths. Do not substitute `verify.sh --fast`, `verify.sh --all`, or an unscoped
   package/repository suite.
5. Run `make validation-all` only for an explicit local whole-suite request. A merge or release
   request alone does not trigger it or replace required CI. Reuse valid local evidence unless the
   user explicitly requests a fresh run; explain any missing evidence or necessary scope escalation.
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
