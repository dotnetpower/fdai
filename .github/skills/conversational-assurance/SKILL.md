---
name: conversational-assurance
description: "Continuous FDAI conversational reliability workflow. Use when building, operating, reviewing, or resuming the chat-quality watchdog; generating nonduplicate FDAI questions; evaluating Azure-backed answers; hardening a failed answer; checking idle-session behavior; or asking whether a fix generalizes to similar questions."
---

# FDAI Continuous Conversational Assurance

Use this skill to operate the local FDAI Conversation Assurance Watchdog. The watchdog continuously
generates unique FDAI questions, measures real answers, and proposes isolated fixes when objective
contracts fail.

> Scope: This is a local development assurance loop. It does not join the Pantheon, execute an
> Azure mutation, approve an action, or merge a generated branch into `main`.

## Continuous operation contract

The process runs indefinitely while the PC and user systemd session are available. Indefinite means
a recurring timer, not a busy loop:

- `fdai-chat-watchdog.timer` starts one bounded cycle every 20 minutes with jitter.
- `Persistent=true` resumes a missed cycle after sleep or restart when the user session returns.
- Daily question and hardening budgets reset by UTC day; they bound cost without ending the service.
- `.improve/STOP` is the immediate local stop switch.
- A failed or skipped cycle does not disable the next timer invocation.

Before each cycle, skip without generating a question when any of these conditions is true:

- A current Copilot transcript or legacy debug log changed inside the configured idle window.
- A Copilot CLI process or explicit FDAI session lease is active.
- Another improvement runner owns the lock.
- The primary worktree is dirty.
- The daily question or hardening budget is exhausted.
- `.improve/STOP` exists.

Do not infer idleness only from process names. Current VS Code builds record activity under
`GitHub.copilot-chat/transcripts/*.jsonl`; retain legacy `debug-logs/*/main.jsonl` support.

## Assurance loop

Run one cycle in this order:

1. **Select a challenge**: choose the least-used contract and alternate English and Korean.
2. **Generate one question**: use the tool-disabled Copilot CLI wrapper. Reject exact and near
   duplicates from the local ledger.
3. **Measure the real answer**: start an ephemeral Azure-backed read API with server-owned scope.
4. **Evaluate objectively**: check required concepts, forbidden fallback text, and expected
   authority. Subjective Copilot review is advisory only.
5. **Hold or harden**: a deterministic failure may start one isolated hardening candidate. A
   provider outage, quota event, or unavailable evidence is not a code defect by itself.
6. **Verify generalization**: measure the original question and its persisted similar-question
   cohort after the fix.
7. **Preserve for review**: retain a verified branch, remove the generated worktree, and never
   merge to `main` automatically.

## Question contract

Every generated question must be:

- Specific to FDAI roles, safety, ontology, evidence, or configured Azure read operations.
- Read-only and bounded to the server-configured scope.
- Free of tenant IDs, subscription IDs, resource names, endpoints, credentials, and secrets.
- Distinct from every prior ledger question by normalized fingerprint and lexical similarity.
- At most 400 characters.

Resource-state and Resource Health questions must not name or address a Pantheon agent. They target
server-owned inventory or health authority, not an agent conversational port.

The challenge set should cover at least:

- Fixed Pantheon role and authority boundaries.
- Safe-autonomy invariants and T2 quality gates.
- Shadow-mode and insufficient-evidence behavior.
- Ontology catalog counts and current-screen evidence.
- Current service outage and Resource Health.
- Current resource conditions such as stopped, deallocated, failed, degraded, and unavailable.
- Resource condition timing and customer-initiated versus platform-initiated cause.

## Similar-question generalization gate

A fix that answers only the original sentence is incomplete. Before hardening starts, generate and
persist at least three similar questions in the same language. The cohort must vary:

- Wording and synonyms.
- Word order.
- Formal, concise, and colloquial phrasing.

Every cohort question must preserve the original read-only intent, scope, and expected authority.
Reject exact duplicates, prior ledger questions, forbidden identifiers, and disallowed agent names.

After a candidate commits, the original question and every similar question must all pass the same
deterministic rubric and authority check. One failing paraphrase keeps the measurement at `0.0` and
the candidate cannot be reported as verified. Never special-case one prompt, keyword list, or
expected sentence.

## Hardening boundaries

One hardening candidate must:

- Reproduce the failed contract before editing.
- Fix the owning routing, evidence, verification, or rendering abstraction.
- Add source and regression-test changes.
- Include affected bilingual design documentation.
- Stay within 12 changed files and 800 changed lines unless an operator explicitly changes the
  local cap.
- Change only `src/fdai/`, `tests/`, and `docs/roadmap/` paths.
- Pass exact and similar-question live measurement, focused tests, fast verification, and the
  whole-suite gate.

Use a visible sibling worktree under `fdai-worktrees/auto-hardening`. Hidden `.improve` worktree
paths can invalidate path-sensitive repository tests. Link local-only `.venv`, model metadata, and
Node dependencies into the worktree and exclude those links from git status.

If the whole-suite gate fails on an unchanged baseline defect, retain the candidate branch with an
honest baseline-blocked verdict. Do not fix an unrelated baseline failure inside the chat candidate.

## Copilot CLI boundary

Question generation and advisory judging use the wrapper with shell, write, read, URL, remote,
custom-instruction, MCP, auto-update, and ask-user capabilities disabled. Generated text never
becomes a command or Azure query.

`--force` is evaluation-only. It may generate and measure a question while a developer is active,
but it must never start hardening.

## Operations

```bash
# Status
systemctl --user status fdai-chat-watchdog.timer --no-pager

# Recent cycles
journalctl --user -u fdai-chat-watchdog.service -n 100 --no-pager

# Stop and resume
touch .improve/STOP
rm .improve/STOP

# Preview without Copilot or Azure
python3 .improve/auto-hardening/chat_watchdog.py --project . --force --dry-run
```

The local question and verdict ledger is `.improve/chat-watchdog/questions.jsonl`. It may contain
environment-derived operational text and must remain ignored, mode `0600`, and uncommitted.

## Verification

Run the local safety contract after any watchdog change:

```bash
PYTHONPATH="$PWD/src" .venv/bin/pytest -q --no-cov \
  .improve/auto-hardening/test_chat_watchdog.py \
  .improve/auto-hardening/test_run_if_idle.py

.venv/bin/ruff check \
  .improve/auto-hardening/chat_watchdog.py \
  .improve/auto-hardening/measure.py \
  .improve/auto-hardening/run_if_idle.py \
  .improve/auto-hardening/test_chat_watchdog.py \
  .improve/auto-hardening/test_run_if_idle.py
```

Also verify the timer remains enabled and that a normal invocation during an active Copilot session
reports a session-based skip before it can generate a question.
