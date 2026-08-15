---
mode: agent
description: Resume and execute unfinished FDAI work from durable handover evidence; use status for a read-only summary.
---

# /resume-session - resume unfinished work

Resume from durable repository evidence and continue the unfinished batch by default. Use the
chronicle skill only when local evidence is incomplete. Do not make the maintainer copy a handover
prompt into another session or send a second "continue" message.

## Modes

- **Default - resume and execute:** recover the current task, load only its controlling context,
  and continue through the next focused edit, validation, and task-owned commit.
- **`status` - inspect only:** report the recovered state without editing, committing, or changing
  external state.

## Steps

1. **Read the durable local handover and Git snapshot**:
   `bash scripts/automation/resume.sh`
2. **Reconcile visible state**. Check in-progress todos, task-relevant repo memory, the current
   issue, and task-owned working-tree paths. Treat unrelated dirty files as another session's work.
3. **Use chronicle only when needed**. Query recent FDAI sessions when the automatic handover does
   not identify the task, owning issue, last focused check, or remaining work.
4. **Load only controlling context**. Resolve the route-selected files for the recovered task once.
   Request required design documents with direct `read_file` calls so the pre-tool hook records
   them; keep ordinary exploration parallel.
5. **State one local hypothesis and one falsifying check**, then make the smallest grounded edit.
   Run that check immediately and continue autonomously while the recovered task remains feasible.
6. Keep the recovery summary concise:
   - **Last commit topic**: <one line>
   - **Working tree**: N modified, M new. Names of top 5 files.
   - **Unpushed commits**: N. Topics.
   - **Open todos**: any in-progress from the todo list.
   - **Resumed batch**: the concrete edit and focused check now in progress, or the exact blocker.

## Guardrails

- Do not stop after the summary or ask whether to continue in default mode. Stop only when the
  task is complete, genuinely blocked, or requires an irreversible decision that lacks authority.
- In `status` mode, stay read-only: do not edit, commit, or change external state.
- Treat the automatic handover as local evidence, not authority to skip focused
  checks or centralized validation.
- Do not push. Push is always a maintainer decision.
- Work directly on `main` unless real concurrent writing requires isolation. Never create a branch
  merely to resume a session.
- Commit only task-owned paths with an explicit pathspec; never stash or stage unrelated work.
- Keep every summary customer-agnostic. Redact tenant, subscription, customer, endpoint, and
  resource identifiers even when they appear in session history or commit messages.
