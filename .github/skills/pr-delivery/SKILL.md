---
name: pr-delivery
description: "Complete an explicitly authorized FDAI code delivery through commit, push, pull request handling, protected merge, and safe local topic-branch cleanup. Use when the operator asks to commit and push, publish completed work, land a change, merge a PR, or handle a PR through completion."
argument-hint: "Optional: PR number, issue number, or requested stopping point"
---

# Pull Request Delivery

Complete the repository delivery lifecycle instead of stopping after a branch push. This skill
coordinates the existing commit, sync, create/update PR, CI diagnosis, and merge workflows; it does
not replace their safety checks.

## Authorization contract

An unqualified request to `commit and push`, `publish`, `deliver`, or `land` completed work
authorizes the normal repository path through:

1. a task-owned local commit;
2. a non-force push to a topic branch;
3. creation or update of the pull request;
4. handling of deterministic CI failures and actionable review findings within the original scope;
5. protected merge when every required check and review permits it; and
6. cleanup of the merged local topic branch.

A request explicitly limited to `commit only`, `push only`, `open a PR`, or `do not merge` stops at
that boundary. Delivery authorization never implies deployment, release, live Azure access, secret
access, an admin bypass, or a force-push.

## Procedure

1. **Freeze the delivery scope.** Record the task-owned paths, current commit, topic branch, base
   branch, linked issue, and unrelated worktree changes. Preserve unrelated staged and unstaged
   edits. If no issue exists, create one with observable exit criteria before the first push or PR.
2. **Validate and commit locally.** Reuse unchanged focused evidence, review the task-owned diff,
   and commit with an explicit pathspec. Never bypass hooks or substitute a remote-created commit.
3. **Publish exactly.** Push the checked-out topic branch without force, set its upstream when
   needed, and verify that the remote ref resolves to the expected local commit.
4. **Create or update the PR.** Reuse an open PR for the same head branch; otherwise create one
   against the intended base. Include purpose, measured evidence, focused validation, operational
   caveats, and the closing issue reference. Verify the PR head SHA after creation.
5. **Drive the PR to a terminal outcome.**
   - Observe the exact PR head and its required checks once. Do not poll.
   - If checks are pending and repository policy supports auto-merge, enable protected auto-merge
     with the repository's established merge method. Record that external evidence is pending.
   - When Merge Queue is unavailable and delivery is authorized through merge, start the canonical
     one-time coordinator described below. The coordinator owns subsequent bounded observations and
     behind-branch updates; the interactive agent does not poll alongside it.
   - If a required check fails, use the `ci-diagnosis` skill on that exact attempt, fix only the
     established cause locally, rerun the narrowest falsifying check, commit, push, and update the
     existing PR.
   - Address actionable review comments within the authorized scope. Escalate ambiguous,
     scope-expanding, security-sensitive, or authority-changing requests instead of guessing.
   - Never use an admin override, dismiss a required review, weaken branch protection, or merge a
     non-green revision.
6. **Verify integration.** Treat the PR as delivered only after GitHub reports it merged and the
   remote base branch contains the resulting merge or squash revision. Do not claim completion
   from a successful branch push or from non-terminal checks.
7. **Clean up the local topic branch.** Fetch the base branch, confirm the exact PR head was merged,
   and inspect `git worktree list --porcelain`. Delete only the named local topic branch when it is
   not checked out anywhere and has no unpublished commits or task-owned recovery value. A squash
   merge may require explicit branch deletion after GitHub proves the exact head was merged. Never
   delete the current branch, a branch attached to another worktree, or a branch with ambiguous
   ownership. Preserve unrelated dirty files.
8. **Close the evidence loop.** Reconcile the linked issue and report commit SHA, PR, merge result,
   base revision, CI status, and branch-cleanup result separately.

## One-Time Delivery Coordinator

Use `scripts/automation/pr_delivery_daemon.py` only after the task commit is pushed, the PR exists,
its exact local and remote head match, and protected auto-merge is permitted. If the canonical
script is absent, first create it and its focused regressions as task-owned repository source,
validate that implementation, and resume delivery only from a checkout that contains it. Never
substitute an inline polling loop, downloaded executable, GitHub content API commit, or cloud agent.

Start it from the clean isolated topic-branch worktree with that worktree's selected Python:

```bash
.venv/bin/python scripts/automation/pr_delivery_daemon.py start \
  --repo <owner/repository> \
  --pr-number <number> \
  --topic-branch <topic-branch> \
  --base-branch <base-branch> \
  --worktree <absolute-worktree-path>
```

The `start` operation returns immediately after creating one detached, finite process. It writes a
private state record and log beneath the Git common directory and reuses an exact live process for
the same PR instead of starting a duplicate. Do not pass tokens, credentials, URLs containing
credentials, or environment dumps. Authentication comes only from the existing `gh` and Git
credential providers.

The coordinator may:

- Observe only the pinned PR every 30-300 seconds for at most two hours.
- Merge the latest named base locally when GitHub reports `BEHIND`.
- Push the exact local topic branch without force and verify the remote SHA.
- Restore the repository's existing protected auto-merge method.
- Verify that the reported merge commit is contained by the remote base.

It stops without repair when a check fails, the PR closes, a conflict occurs, local or remote
identity changes, the worktree becomes dirty, or a deadline expires. CI diagnosis, code changes,
review decisions, conflict resolution, branch protection, retries after provider errors, issue
closure, and worktree cleanup remain interactive `pr-delivery` responsibilities. On a later turn,
read status once with the same arguments and the `status` operation; do not tail or poll its log.

## Waiting and resumption

GitHub Actions and reviews are external evidence. Do not repeatedly query them interactively. When
checks are still running, enable auto-merge if allowed and either start the one-time coordinator or
record the exact PR and head SHA before leaving the work blocked on external evidence. Resume from
that same PR when the coordinator records a terminal outcome, a terminal notification arrives, or
a later operator turn begins; do not create a replacement PR or silently switch revisions.

## Example

- **Right:** `commit and push` commits only task-owned paths, publishes the topic branch, creates
  or updates its PR, enables protected auto-merge while checks run, verifies the eventual merge,
  and removes the now-unused local topic branch.
- **Wrong:** push the branch, report the task complete, leave no PR, or delete the local branch
  before GitHub proves that its exact head was merged.
