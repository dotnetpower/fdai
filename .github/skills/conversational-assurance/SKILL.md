---
name: conversational-assurance
description: "Continuous FDAI conversational reliability workflow. Use when the user says 대화개선, 채팅개선, 대화무한개선, 채팅무한개선, conversation improvement, chat improvement, or continuous conversation assurance; or when building, operating, reviewing, or resuming the chat-quality watchdog, evaluating Azure-backed answers, hardening a failed answer, or checking generalization."
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

- `fdai-chat-watchdog.timer` starts the next bounded cycle within one minute, with small jitter.
- `Persistent=true` resumes a missed cycle after sleep or restart when the user session returns.
- Daily question and hardening budgets reset by UTC day; they bound cost without ending the service.
- `.improve/STOP` is the immediate local stop switch.
- A failed or skipped cycle does not disable the next timer invocation.
- Malformed or non-JSON Copilot generation output is retried inside the bounded cycle. Exhausted
   retries produce a redacted `cycle_hold` ledger record and a successful service exit, so one
   transient generation failure cannot disable or obscure later timer invocations.

Before each cycle, skip without generating a question only when any of these conditions is true:

- Another improvement runner owns the lock.
- The daily question or hardening budget is exhausted.
- `.improve/STOP` exists.

A dirty primary worktree or active developer session does not block measurement. Hardening starts
from committed `HEAD` in a separate worktree and must not read, stage, overwrite, or archive the
primary worktree's uncommitted changes. The runner lock prevents overlapping generated candidates.

## Campaign start and focus

The trigger phrases are `대화개선`, `채팅개선`, `대화무한개선`, `채팅무한개선`,
`conversation improvement`, `chat improvement`, and `continuous conversation assurance`.
When one appears:

1. Ask once for SRE, ARB, Change Management, DR, Chaos, or Balanced focus.
2. Select SRE if the operator is unavailable.
3. Persist the choice in ignored `.improve/chat-watchdog/config.json` with mode `0600`.
4. Install or refresh the user-systemd timer with `--allow-active`.
5. Continue bounded cycles without asking again until `.improve/STOP` appears or focus changes.

The logical conversation id is `dev-discuss-<focus>`. Its wire kind remains `web`, so the harness
uses the same authorization, routing, evidence, verification, history, and terminal response
contract as the Console without inventing a second answer engine.

## Assurance loop

Run one cycle in this order:

1. **Select a challenge**: choose the least-used contract and alternate English and Korean.
2. **Generate one question**: use the tool-disabled Copilot CLI wrapper. Reject exact and near
   duplicates from the local ledger.
3. **Measure the real answer**: start an ephemeral Azure-backed Operator API with server-owned scope.
4. **Evaluate every quality dimension**: inspect the terminal `/chat/stream` `done` payload for
   answer-contract coverage, verification, presentation, observed work, and timing.
5. **Hold or harden**: a deterministic failure may start one isolated hardening candidate. A
   provider outage, quota event, or unavailable evidence is not a code defect by itself.
6. **Verify generalization**: measure the original question and its persisted similar-question
   cohort after the fix.
7. **Preserve for review**: retain a verified branch, remove the generated worktree, and never
   merge to `main` automatically.
8. **Continue immediately**: the next timer activation generates the next bounded question within
   one minute after the cycle ends.

## Multidimensional answer gate

Every terminal answer is assessed across all applicable dimensions:

| Dimension | Required evidence |
|-----------|-------------------|
| Appropriateness | Required contract concepts plus an independent review of relevance, directness, and honest uncertainty. Only a `medium` or `high` failure at confidence >= 0.85 may enter hardening. |
| Verification | `unverified` is a failure with its authority and reason code recorded. `verified`, `consistent`, and `corrected` remain distinct outcomes. |
| Visualization | `answer_plan.format` must match the question. Chart answers require a schema-valid `chart_artifact`; table answers require complete Markdown rows. |
| Investigation | Operational investigation questions require schema-v1 `trajectory_detail` with agent, authority, status, label, and bounded branch/activity records. |
| Execution record | Observed commands or queries require `redacted=true`, tool, bounded command, output/truncation state when available, and duration. These are read-operation observations, not executor authority. |
| Performance | Record total `latency_ms`, every `turn_timing` phase, the slowest phase, degraded/failed phases, and configured total/phase budget violations. |

Persist these dimensions in the local ledger so a repair is attributable to the exact failure.
Headless presentation validation proves the Console-facing artifact contract. A separate browser
canary remains responsible for CSS/layout rendering regressions; do not claim pixel parity from
the headless cycle alone.

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

# Start or change campaign focus
python3 .improve/auto-hardening/install_chat_watchdog_timer.py install --project . --focus sre
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
