---
name: pr-delivery
description: "Complete and continuously monitor an explicitly authorized FDAI code delivery through commit, push, pull request handling, CI remediation, protected merge, and safe local topic-branch cleanup. Use when the operator asks to commit and push, publish completed work, land a change, monitor until success, merge a PR, or handle a PR through completion."
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

## Local-first CI budget

GitHub Actions is final exact-SHA integration evidence, not an edit-loop test runner. One coherent
delivery should normally consume one workflow attempt.

- Before the first push, fetch the intended base and integrate any base movement locally. Do not
  knowingly publish a behind branch and spend a workflow attempt discovering an avoidable merge
  conflict.
- Build the local validation plan from the final committed diff and its design routes. Run the
  owning focused tests, every required official generator and artifact-equality check, and
  `make test-changed DIFF=<base>...HEAD` only when the already-passing focused tests do not cover
  the complete diff.
- Run the local fast and CI-enforced structural parity checks before publication:

  ```bash
  bash scripts/verify.sh --fast --diff <base>...HEAD
  FILE_LOC_MODE=enforce bash scripts/quality/architecture/check-file-loc.sh
  SUBSYSTEM_FANOUT_MODE=enforce bash scripts/quality/architecture/check-subsystem-fanout.sh
  bash scripts/quality/repository/check-doc-links.sh
  ```

  Use a clean immutable candidate. If an applicable check is genuinely CI-only, record that
  limitation instead of manufacturing a local pass.
- Freeze the candidate after this preflight. Related, already-authorized increments that share one
  owner, risk boundary, and validation plan MAY use one bounded PR rather than separate pushes;
  unrelated, authority-changing, deployment, or release changes remain separate.
- A second workflow attempt is exceptional. Use it only after an exact failed-attempt diagnosis,
  an actionable review change, or unavoidable post-push base drift. Fix deterministic failures
  locally, add or extend the local regression/gate that would have caught them, collect the complete
  bounded repair, and push once. Never rerun or push speculative changes to see what CI says.

## Procedure

1. **Freeze the delivery scope.** Record the task-owned paths, current commit, topic branch, base
   branch, linked issue, and unrelated worktree changes. Preserve unrelated staged and unstaged
   edits. If no issue exists, create one with observable exit criteria before the first push or PR.
2. **Validate and commit locally.** Reuse unchanged focused evidence, review the task-owned diff,
   and commit with an explicit pathspec. Apply the local-first CI budget to the final candidate
   after synchronizing its intended base. Never bypass hooks or substitute a remote-created commit.
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
     one-time coordinator described below, then attach its local-state waiter through an async
     terminal. The coordinator owns subsequent bounded GitHub observations and behind-branch
     updates; the waiter only reports its terminal state, and the interactive agent does not poll
     alongside either process.
   - If a required check fails, use the `ci-diagnosis` skill on that exact attempt, fix only the
     established cause locally, rerun the narrowest falsifying check, commit, push, and update the
     existing PR. Restore auto-merge, restart the coordinator, and attach a new waiter. Continue
     this bounded diagnose-fix-validate-publish-monitor loop until merge or a genuine blocker.
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

Immediately after `start` succeeds, run the matching local-state waiter with the agent terminal in
async mode so terminal completion returns control to the coding session without another GitHub
query:

```bash
.venv/bin/python scripts/automation/pr_delivery_daemon.py wait \
  --repo <owner/repository> \
  --pr-number <number> \
  --topic-branch <topic-branch> \
  --base-branch <base-branch> \
  --worktree <absolute-worktree-path>
```

The waiter reads only the private state file and verifies the daemon process identity. It exits zero
only for a verified merge and nonzero for failed checks, conflicts, closure, interruption, or bounded
timeouts. Do not use `get_terminal_output`, manual status loops, or additional GitHub reads while the
async waiter is active; terminal completion is the wake-up signal. On a nonzero result, read status
once, follow the failure route above, and attach a new waiter after the corrected head is published.

The `start` operation returns immediately after creating one detached, finite process. It writes a
private state record and log beneath the Git common directory and reuses an exact live process for
the same PR instead of starting a duplicate. Do not pass tokens, credentials, URLs containing
credentials, or environment dumps. Authentication comes only from the existing `gh` and Git
credential providers. When its own topic-branch push fails, the coordinator records at most 12
redacted `pre-push:`, `structural-gates:`, `error:`, `fatal:`, and `! [` lines in the
`failure_diagnostics` state field and private log, and discards all other command output. Read
that field through `status` before reproducing the failing gate locally.

The coordinator may:

- Observe only the pinned PR every 30-300 seconds for at most two hours.
- Merge the latest named base locally when GitHub reports `BEHIND`. It skips the merge and push
  when the fetched base already contains the topic head or its exact tree, or when the remote topic
  branch no longer matches the verified head. GitHub can still report `BEHIND` right after it merges
  the PR and deletes the branch, and pushing then would recreate the branch.
- Push the exact local topic branch without force and verify the remote SHA.
- Restore the repository's existing protected auto-merge method.
- Verify that the reported merge commit is contained by the remote base.

It stops without repair when a check fails, the PR closes, a conflict occurs, local or remote
identity changes, the worktree becomes dirty, or a deadline expires. CI diagnosis, code changes,
review decisions, conflict resolution, branch protection, retries after provider errors, issue
closure, and worktree cleanup remain interactive `pr-delivery` responsibilities. On a later turn,
read status once with the same arguments and the `status` operation; do not tail or poll its log.

After its own base merge and verified non-force push, the coordinator MAY wait for GitHub's PR
projection to catch up only when the PR still reports the exact pre-push head from the triggering
observation. This exception is limited to two normal observations and 300 seconds, remains subject
to the shorter existing deadline, and re-verifies a clean worktree plus exact local and Git remote
topic heads every time. It does not consume checks or mergeability from the stale snapshot. A third
SHA, changed local or remote head, dirty worktree, or expired bound stops fail-closed. A restarted
coordinator does not inherit the exception because it did not perform the verified push.

## Waiting and resumption

GitHub Actions and reviews are external evidence. Do not repeatedly query them interactively. When
checks are still running, enable auto-merge if allowed, start the one-time coordinator, and attach
the async local-state waiter. Do not report delivery complete or end an active delivery turn merely
because CI is pending. Resume from that same PR when the waiter emits a terminal notification. A
failed check, conflict, or behind-head update returns control for the bounded remediation loop; a
deadline, unavailable credential, ambiguous review, or scope-expanding repair is a genuine blocker
and must be reported instead of retried indefinitely. Do not create a replacement PR or silently
switch revisions.

## Example

- **Right:** `commit and push` commits only task-owned paths, publishes the topic branch, creates
  or updates its PR, enables protected auto-merge while checks run, verifies the eventual merge,
  and removes the now-unused local topic branch.
- **Wrong:** push the branch, report the task complete, leave no PR, or delete the local branch
  before GitHub proves that its exact head was merged.
