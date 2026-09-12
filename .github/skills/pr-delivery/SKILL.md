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

## Waiting and resumption

GitHub Actions and reviews are external evidence. Do not repeatedly query them. When checks are
still running, enable auto-merge if allowed, record the exact PR and head SHA, and leave the work
blocked on external evidence. Resume from that same PR when a terminal notification or a later
operator turn arrives; do not create a replacement PR or silently switch revisions.

## Example

- **Right:** `commit and push` commits only task-owned paths, publishes the topic branch, creates
  or updates its PR, enables protected auto-merge while checks run, verifies the eventual merge,
  and removes the now-unused local topic branch.
- **Wrong:** push the branch, report the task complete, leave no PR, or delete the local branch
  before GitHub proves that its exact head was merged.
