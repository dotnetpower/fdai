---
mode: agent
description: Resume where the previous session stopped - summarize recent sessions and surface unfinished work.
---

# /resume-session - resume the previous session

Use the chronicle skill and local session store to find what the
maintainer was working on most recently and give a short, actionable
summary so the next batch can start immediately.

## Steps

1. **Read the durable local handover and Git snapshot**:
   `bash scripts/automation/resume.sh`
2. **Use the chronicle skill only when needed**. Query recent sessions when no
   automatic handover exists or when the handover doesn't explain visible WIP.
3. **Check for in-progress todos** (`manage_todo_list`) and repo-memory
   backlog markers under `/memories/repo/`.
4. Produce a concise summary in this shape:
   - **Last commit topic**: <one line>
   - **Working tree**: N modified, M new. Names of top 5 files.
   - **Unpushed commits**: N. Topics.
   - **Open todos**: any in-progress from the todo list.
   - **Suggested next batch**: one concrete next step tied to the
     coding-ability or chat-improvement playbook, if applicable.

## Guardrails

- **Read-only.** Do not commit, do not stash, do not touch the working
  tree. This prompt just surfaces state.
- Treat the automatic handover as local evidence, not authority to skip focused
   checks or centralized validation.
- Do not push. Push is always a maintainer decision.
- If the working tree has WIP, remind the caller that autonomous
  batches must use per-file `git add`, never `git add -A`.
- customer-agnostic in the summary (no real sub / tenant / customer
  names, even if they appear in session titles or commit messages -
  redact them in the output).
