---
name: conversational-assurance
description: "Explicit FDAI conversation-assurance workflow. Operate a campaign only when the user says 대화개선, 채팅개선, 대화무한개선, 채팅무한개선, conversation improvement, chat improvement, or continuous conversation assurance; report status only for 대화개선 현황, 채팅개선 현황, or conversation assurance status. Also use as implementation guidance when the user explicitly asks to change or review the watchdog itself."
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
timer, stale-activity recovery, a failed implementation check, an inconclusive Console answer, or
any other implicit trigger. Loading this skill for watchdog implementation or review does not
authorize a campaign or a live Azure/model call.

- One normal explicit trigger starts one campaign. An explicit request for 100 or more evaluations
   starts one parent series composed of bounded child campaigns.
- One campaign evaluates at most 20 new questions and starts at most 20 hardening attempts.
- These limits belong to the campaign id, not a UTC date. A later explicit trigger creates a new
  campaign id with fresh limits.
- A parent series never raises a child budget. It runs enough sequential child campaigns to reach
   the requested target, which defaults to 100 and MUST be at least 100. Every child has its own id
   and ledger records. A failed hardening attempt is terminal for that candidate within the child,
   but it does not consume or cancel the child's new-question budget. A child stops the parent only
   when question generation or live measurement cannot make progress.
- `.improve/STOP` is the immediate local stop switch.
- A failed cycle that cannot make progress ends the campaign without busy-looping.
- Malformed or non-JSON Copilot generation output is retried inside the bounded cycle. Exhausted
   retries produce a redacted `cycle_hold` ledger record and a successful cycle exit, so one
   transient generation failure cannot obscure the campaign result.
- A live question receives one measurement attempt per cycle. A T2 retry is expected only when the
  effective `conversation.t2_escalation.aggressive_enabled` setting admits the recorded typed
  trigger. An unconfigured retry, more than one retry for a stage, provider `429`/`503`, timeout, or
  deadline expiry records `cycle_hold` and ends that cycle. The session MUST NOT relaunch the cycle,
  the campaign, or the same question to obtain a different result.

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
The watchdog prepends the active worktree's Core and service-contract source roots before importing
readiness contracts. It must not resolve those contracts from an older editable install when
`PYTHONPATH` is absent.
Every started hardening attempt appends a bounded terminal `hardening_result` record for verified,
failed, or exceptional completion. Error records contain the exception type, not provider output.
A bounded hardening exception is a failed candidate result, not a campaign-process exception.

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

1. **Select a challenge**: choose the least-used contract whose read capability is
   `evidence_ready` in the current ephemeral runtime receipt, and alternate English and Korean.
   A declaration or environment flag is never readiness. Keep unavailable challenge definitions
   as coverage backlog; do not score them as answer failures.
2. **Generate one question**: use the tool-disabled Copilot CLI wrapper. Reject exact and near
   duplicates from the local ledger.
3. **Measure the real answer**: start an ephemeral Azure-backed Operator API with server-owned scope.
4. **Evaluate every quality dimension**: inspect the terminal `/chat/stream` `done` payload for
   answer-contract coverage, verification, presentation, observed work, and timing.
5. **Hold or harden**: a deterministic failure may start one isolated hardening candidate. A
   provider outage, quota event, timeout, unexpected T2 fallback, or unavailable evidence is not a
   code defect by itself and ends the cycle as a hold without live retry.
6. **Verify generalization**: measure the original question and its persisted similar-question
   cohort after the fix.
7. **Preserve for review**: retain a verified branch, remove the generated worktree, and never
   merge to `main` automatically.
8. **Continue immediately**: the same explicit campaign starts its next bounded cycle after the
   current cycle ends, subject to the campaign limits.

## Aggressive T2 recovery tuning

When the runtime setting enables aggressive T2 recovery, treat it as a bounded answer-recovery
experiment rather than permission to weaken evidence checks:

1. Record the T1 terminal candidate, typed escalation trigger, T2 outcome, total model calls,
   latency, verification status, and final answer score.
2. Accept the recovery only when T2 produces a verifier-approved read plan. If T2 remains ambiguous,
   the original T1 clarification must remain the terminal answer.
3. Classify repeated clarification, unavailable, rejected-frame, and rejected-plan outcomes
   separately. Change the smallest owning prompt fragment or deterministic validator boundary.
4. Keep recovery context compact: stage, typed trigger, and safe validation reason only. Do not add
   provider output, hidden reasoning, full logs, or the growing campaign history to the system
   prompt.
5. Verify the original question plus at least three semantic paraphrases before retaining a prompt
   or escalation-policy change. A one-sentence exception is rejected by the anti-hardcoding gate.
6. Keep `golden_campaign_no_t2` authoritative. The runtime setting cannot enable T2 for a Golden
   campaign, action draft, scope denial, authorization denial, or execution path.

Example: if T1 asks which Resource was intended even though the question contains a uniquely
grounded resource identity, retry the frame once with `frame_clarification` context. If T2 binds the
identity and the verifier accepts the plan, score the answer normally. If it guesses an identity or
still asks for one, retain the original clarification and harden the shared identity abstraction
instead of adding the question text to a prompt.

Before creating a candidate, classify the failed observation as exactly one of
`code_defect`, `provider_or_evidence_unavailable`, `authorization_or_configuration`,
`baseline_failure`, or `evaluation_contract_defect`. Only `code_defect` is hardenable. The other
classes append a terminal held result and the campaign continues with a new question.

## Multidimensional answer gate

Rubric version `conversation-assurance.v2` assesses every terminal answer with exactly ten named
rubrics. An applicable rubric scores `0` or `1`; an inapplicable rubric records `score=null` and
does not add to either `total_score` or `max_score`. The score gate requires at least 90% of
applicable points, but score alone never passes an answer.

The mandatory gate separately requires `appropriateness`, `completeness`, `grounding`,
`verification`, `authority_safety`, and `response_integrity` to pass. A challenge with an objective
oracle also requires that oracle to pass. One mandatory failure fails assurance even at `9/10`.
For an objective oracle, the watchdog independently computes the expected value from the current
authoritative source and exactly compares it with the answer's structured presentation value,
verification status, authority, and source. Semantic plausibility and matching prose cannot replace
that comparison.

Records distinguish `technical_verified` from `assurance_passed`; product verification is only one
mandatory input to assurance. An honest provider-unavailable answer may pass semantic honesty while
remaining technically unverified and unsuccessful for the question. Existing
`conversation-assurance.v1` rows remain byte-for-byte history and are never rescored or rewritten.
A later passing v2 evaluation resolves the same v2 challenge and normalized question without
deleting either row.

| Rubric | Required evidence |
|--------|-------------------|
| Appropriateness | An independent semantic review confirms relevance, directness, and honest uncertainty at confidence >= 0.85. Missing or low-confidence review fails closed and never becomes a passing score. Only a `medium` or `high` failure may enter hardening. |
| Completeness | The same independent review confirms every semantic expectation without requiring exact wording or keyword presence. Missing, undecided, or low-confidence review fails closed. |
| Grounding | The terminal response carries bounded evidence references that are present on completed schema-valid intent-graph goals, with no fallback source. |
| Verification | `unverified` is a failure with its authority and reason code recorded. `verified`, `consistent`, and `corrected` remain distinct outcomes. |
| Authority and safety | The observed authority is available and matches the challenge's expected server authority when declared. |
| Visualization | Applicable only when the challenge requires a chart or table. `answer_plan.format` must match the question. Chart answers require a schema-valid `chart_artifact`; table answers require complete Markdown rows. |
| Investigation | Applicable only when the challenge requires observed work. Operational investigation questions require schema-v1 `trajectory_detail` with agent, authority, status, label, and bounded branch/activity records. |
| Execution record | Applicable only when the challenge requires observed work. Observed commands or queries require `redacted=true`, tool, bounded command, output/truncation state when available, and duration. These are read-operation observations, not executor authority. |
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
   results, applicable score denominator, mandatory gate, objective oracle result,
   `technical_verified`, `assurance_passed`, verification, presentation, trajectory counts, total
   latency, every phase, and bottleneck.
- `regressions.jsonl` records the original failed question and every generated similar question.

Every evaluated question enters `regressions.jsonl` immediately as a regression baseline. A failed
question expands into a cohort with its generated paraphrases before hardening. Duplicate rejection
reads all three ledgers. A generated original or paraphrase must never be used again as a new random
question, while the persisted regression cohort remains available for later candidate and release
checks. The original and every cohort question must each set `assurance_passed=true` under the current
rubric version before the failure is resolved.

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
- Selectable only when every required function is `declared`, `bound`, `reachable`, and
  `evidence_ready` in order, and the challenge's expected authority exactly matches the authority
  provided by the runtime probe. Questions for planned but unavailable role, DR, rollback, or Chaos
  evidence stay in coverage backlog until that complete proof exists.
- Read-only and bounded to the server-configured scope.
- Free of tenant IDs, subscription IDs, resource names, endpoints, credentials, and secrets.
- Distinct from every prior ledger question by normalized fingerprint and lexical similarity.
- At most 400 characters.

Resource-state and Resource Health questions must not name or address a Pantheon agent. They target
server-owned inventory or health authority, not an agent conversational port.

Client-provided screen text is not authoritative evidence. A challenge may use a complete
server-issued screen selection token through the normal bound-context contract. Otherwise it must
ask against the current server-owned ontology, inventory, health, or metering source and must not
embed a synthetic or stale screen value in `view_context`.

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
An independent semantic-equivalence review at confidence >= 0.85 must also confirm the same
language, result shape, scope, and evidence authority. Prompt instructions alone are not proof of
equivalence.

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
- Change only Core conversation and conversation-assurance owners,
  `services/core-control-plane/src/fdai_core_service/`, Operator conversation owners, their
  adjacent Core or Operator tests, and directly related `docs/roadmap/` owners.
- Run validation as separate terminal stages: reproduction test, changed-boundary focused tests,
  Ruff, mypy, original plus paraphrase live cohort, and a baseline-independent final verdict.
- Apply a hard deadline to every stage. The edit stage has a separate no-progress deadline. A
  timeout or exception appends a terminal `hardening_result` and never prevents the campaign from
  moving to a new question.
- Treat an unchanged whole-repository or unrelated Console failure as `baseline_blocked`, not as a
  candidate defect. Whole-repository validation is never a default candidate gate and remains a
  merge or release responsibility.
- Pass an AST-delta anti-hardcoding gate. A candidate is rejected when it adds a compiled regular
   expression or compiled-pattern match, a static string collection or mapping, or a question or
   paraphrase literal to the product conversation source. This structural gate supplements, rather
   than replaces, semantic generalization measurement.

Use a visible sibling worktree under `fdai-worktrees/auto-hardening`. Hidden `.improve` worktree
paths can invalidate path-sensitive repository tests. Link local-only `.venv`, model metadata, and
Node dependencies into the worktree and exclude those links from git status.

Retain the branch only when every candidate stage is verified. Remove failed, timed-out,
provider-held, evaluation-defect, authorization/configuration, and `baseline_blocked` branches.
Never merge a retained branch automatically. Do not fix an unrelated baseline failure inside the
chat candidate.

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

An unavailable challenge appends `challenge_unavailable` with its highest proved readiness stage,
required functions, expected and provided authority, and a bounded reason. It never appends an
evaluation score. Provider absence, inaccessible authority, incomplete evidence, and authority
mismatch are availability outcomes, not answer-quality failures.

## Verification

Run the local safety contract after any watchdog change:

```bash
PYTHONPATH="$PWD/services/core-control-plane/src:$PWD/services/operator-service/src:$PWD/packages/service-contracts/src" \
   .venv/bin/pytest -q --no-cov \
  services/core-control-plane/tests/runtime/test_conversation_assurance_readiness.py \
  tests/integration/scripts/test_conversation_assurance_answer_gate.py \
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
