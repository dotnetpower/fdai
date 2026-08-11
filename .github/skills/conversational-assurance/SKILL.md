---
name: conversational-assurance
description: "Continuous FDAI conversational reliability workflow. Use when the user says 대화개선, 채팅개선, 대화무한개선, 채팅무한개선, 대화개선 현황, 채팅개선 현황, conversation improvement, chat improvement, conversation assurance status, or continuous conversation assurance; or when building, operating, reviewing, or resuming the chat-quality watchdog, evaluating Azure-backed answers, hardening a failed answer, or checking generalization."
---

# FDAI Explicit Conversational Assurance

Use this skill to operate the local FDAI Conversation Assurance Watchdog. The watchdog continuously
generates unique FDAI questions within one explicit bounded campaign, measures real answers, and
proposes isolated fixes when objective contracts fail.

This skill is the single owner of conversation-assurance trigger semantics, campaign limits,
status behavior, evaluation rubrics, persistence, hardening, and stop conditions. Do not duplicate
these operational rules in the always-on Copilot instructions.

> Scope: This is a local development assurance loop. It does not join the Pantheon, execute an
> Azure mutation, approve an action, or merge a generated branch into `main`.

## Explicit campaign contract

The process starts only when the operator explicitly requests `대화개선`, `채팅개선`,
`대화무한개선`, `채팅무한개선`, `conversation improvement`, `chat improvement`, or
`continuous conversation assurance`. It MUST NOT start from systemd, login, boot, a recurring
timer, stale-activity recovery, or any other implicit scheduler.

- One normal explicit trigger starts one campaign. An explicit request for 100 or more evaluations
   starts one parent series composed of bounded child campaigns.
- One campaign evaluates at most 20 new questions and starts at most 20 hardening attempts.
- These limits belong to the campaign id, not a UTC date. A later explicit trigger creates a new
  campaign id with fresh limits.
- A parent series never raises a child budget. It runs enough sequential child campaigns to reach
   the requested target, which defaults to 100 and MUST be at least 100. Every child has its own id
   and ledger records. An incomplete or held child stops the parent without starting another child.
- `.improve/STOP` is the immediate local stop switch.
- A failed cycle that cannot make progress ends the campaign without busy-looping.
- Malformed or non-JSON Copilot generation output is retried inside the bounded cycle. Exhausted
   retries produce a redacted `cycle_hold` ledger record and a successful cycle exit, so one
   transient generation failure cannot obscure the campaign result.

Before each cycle, skip without generating a question only when any of these conditions is true:

- Another improvement runner owns the lock.
- The campaign question or hardening budget is exhausted.
- `.improve/STOP` exists.

A dirty primary worktree or active developer session does not block measurement. Hardening starts
from committed `HEAD` in a separate worktree and must not read, stage, overwrite, or archive the
primary worktree's uncommitted changes. The explicit operator-triggering Copilot session does not
block campaign hardening; the runner lock and isolated worktree prevent overlap with another
candidate. Each campaign resumes the newest unresolved evaluation before generating another
question.

The explicit campaign runs with the project's virtual-environment Python and inherited tool
`PATH`, so candidate verification uses the same Python and Node toolchain as local development.
Every started hardening attempt appends a bounded terminal `hardening_result` record for verified,
failed, or exceptional completion. Error records contain the exception type, not provider output.

## Campaign start and focus

The trigger phrases are `대화개선`, `채팅개선`, `대화무한개선`, `채팅무한개선`,
`conversation improvement`, `chat improvement`, and `continuous conversation assurance`.
When one appears:

1. Use the persisted SRE, ARB, Change Management, DR, Chaos, or Balanced focus.
2. Select SRE when no focus is stored; update the focus when the operator names one explicitly.
3. Persist the choice in ignored `.improve/chat-watchdog/config.json` with mode `0600`.
4. Run `chat_watchdog.py --campaign` for a normal request. For an explicit 100+ request, run
   `chat_watchdog.py --campaign-series --series-questions <target>` once.
5. Continue bounded cycles within that campaign until 20 questions, 20 hardening attempts,
   `.improve/STOP`, or a no-progress hold ends it.

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
8. **Continue immediately**: the same explicit campaign starts its next bounded cycle after the
   current cycle ends, subject to the campaign limits.

## Multidimensional answer gate

Every terminal answer is assessed by exactly ten named rubrics. Each rubric scores `0` or `1`, so
the total is an integer in `[0, 10]`. A cycle passes at `9/10` or `10/10`; any lower score records
the failed dimensions and enters the guarded hardening path. A later passing evaluation of the same
challenge and normalized question resolves the historical failure without deleting its audit row.

| Rubric | Required evidence |
|--------|-------------------|
| Appropriateness | Required contract concepts plus an independent review of relevance, directness, and honest uncertainty. Only a `medium` or `high` failure at confidence >= 0.85 may enter hardening. |
| Completeness | Every required concept and result-row constraint for the selected challenge is present. |
| Grounding | The terminal response carries bounded evidence references and no fallback source. |
| Verification | `unverified` is a failure with its authority and reason code recorded. `verified`, `consistent`, and `corrected` remain distinct outcomes. |
| Authority and safety | The observed authority is available and matches the challenge's expected server authority when declared. |
| Visualization | `answer_plan.format` must match the question. Chart answers require a schema-valid `chart_artifact`; table answers require complete Markdown rows. |
| Investigation | Operational investigation questions require schema-v1 `trajectory_detail` with agent, authority, status, label, and bounded branch/activity records. |
| Execution record | Observed commands or queries require `redacted=true`, tool, bounded command, output/truncation state when available, and duration. These are read-operation observations, not executor authority. |
| Performance | Record total `latency_ms`, every `turn_timing` phase, the slowest phase, degraded/failed phases, and configured total/phase budget violations. |
| Response integrity | The answer is nonempty, bounded, free of forbidden fallback text, and emitted by a valid terminal response. |

Persist these dimensions in the local ledger so a repair is attributable to the exact failure.
Headless presentation validation proves the Console-facing artifact contract. A separate browser
canary remains responsible for CSS/layout rendering regressions; do not claim pixel parity from
the headless cycle alone.

## Evaluation and regression ledgers

Use three separate ignored, mode-`0600` JSONL files:

- `questions.jsonl` records cycle and hardening lifecycle events.
- `evaluations.jsonl` records every question, redacted answer, answer digest, all ten rubric
   results, total score, verification, presentation, trajectory counts, total latency, every phase,
   and bottleneck.
- `regressions.jsonl` records the original failed question and every generated similar question.

Every evaluated question enters `regressions.jsonl` immediately as a regression baseline. A failed
question expands into a cohort with its generated paraphrases before hardening. Duplicate rejection
reads all three ledgers. A generated original or paraphrase must never be used again as a new random
question, while the persisted regression cohort remains available for later candidate and release
checks. The original and every cohort question must each reach at least `9/10` before the failure is
resolved.

## Status reporting

When the operator asks `대화개선 현황`, `채팅개선 현황`, or `conversation assurance status`, run:

```bash
python3 .improve/auto-hardening/chat_watchdog.py --project . --status --top 20
```

Return the complete summary and latest 20 question-and-answer evaluation rows as a Markdown table.
This is a read-only report and must not start a cycle, change focus, or acquire the runner lock.

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
- Change only `services/core-control-plane/src/fdai/`, `services/core-control-plane/tests/`, and `docs/roadmap/` paths.
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
# Stop the current campaign
touch .improve/STOP

# Allow a later explicit campaign
rm .improve/STOP

# Preview without Copilot or Azure
python3 .improve/auto-hardening/chat_watchdog.py --project . --force --dry-run

# Start one explicit 20-question / 20-hardening campaign
python3 .improve/auto-hardening/chat_watchdog.py --project . --campaign --focus sre

# Start one explicit series of five or more bounded campaigns (100+ questions)
python3 .improve/auto-hardening/chat_watchdog.py --project . \
   --campaign-series --series-questions 100 --focus balanced

# Summary and latest 20 evaluations
python3 .improve/auto-hardening/chat_watchdog.py --project . --status --top 20

# Resume the newest unresolved score below 9/10 immediately
python3 .improve/auto-hardening/chat_watchdog.py --project . --harden-latest --allow-active
```

The local ledgers under `.improve/chat-watchdog/` may contain environment-derived operational text
and must remain ignored, mode `0600`, and uncommitted.

## Verification

Run the local safety contract after any watchdog change:

```bash
PYTHONPATH="$PWD/services/core-control-plane/src:$PWD/services/operator-service/src:$PWD/packages/service-contracts/src" \
   .venv/bin/pytest -q --no-cov \
  .improve/auto-hardening/test_chat_watchdog.py \
   .improve/auto-hardening/test_measure.py \
  .improve/auto-hardening/test_run_if_idle.py

.venv/bin/ruff check \
  .improve/auto-hardening/chat_watchdog.py \
  .improve/auto-hardening/measure.py \
  .improve/auto-hardening/run_if_idle.py \
  .improve/auto-hardening/test_chat_watchdog.py \
   .improve/auto-hardening/test_measure.py \
  .improve/auto-hardening/test_run_if_idle.py
```

Also verify that the legacy watchdog and supervisor systemd units do not exist, and that a normal
invocation without `--campaign` reports `explicit --campaign required` before it can generate a
question.
