# Pantheon five-round hardening review

This record tracks the 27 findings from the 2026-10-14 review against the fixed 15-agent
Pantheon. Source fixes, configured bindings, and operational acceptance are separate outcomes.
The starting source revision is `f393f28ced`. The initial focused review passed 772 tests.

## Scope and invariants

The five rounds review cumulative changes and repair demonstrated defects. Agent names,
`PANTHEON_SPECS`, topic ownership, judgment, approval, execution, audit, recovery, and shadow
promotion authority remain unchanged. Bragi remains a read-only conversational translator.
No push, deployment, live model call, provider mutation, or live identity is authorized here.
Synthetic tests never satisfy operational readiness or production promotion.

## Finding inventory

| Review ID | Finding | Current disposition and observable exit |
|-----------|---------|-----------------------------------------|
| 1 | Unsupported T2 conclusions | Concrete V-CLAIM and independent-model review implemented and default-bound in residual-work batch 2; exact owned snapshots, names, values, limitations and row coverage are verified. Live deployed quality remains open. |
| 2 | Lost failed discussion participants | Fixed in round 1: preserve all selected participants and reasons; block synthesis after partial evidence. |
| 3 | Peer critique does not consume the peer claim | Structured evidence critique implemented in residual-work batch 1: exact primary/reviewer attribution and both source sets with consistent/conflicting/not-comparable states. Free-prose entailment remains the independent verified-composition boundary. |
| 4 | Template operational answers | Open migration debt: use verified answer composition; keep fact views and role descriptions distinct from operational conclusions. |
| 5 | Remote target and locale are lost | Fixed in round 3 within client/server/Bragi: explicit target, validated locale and locale-bound replay identity. General Operator surface wiring remains open. |
| 6 | Operator group discussion is not wired | Backend and Console source connected in residual-work batches 3-4 with independent current Owner/exact-installation read admission, existing durable stream and explicit mode. Local backend: 541 passed; Console: 61 unit checks and 2 focused synthetic E2E passed. Actual verifier/model/authorization/cost acceptance remains open. |
| 7 | Concrete T2 synthesis is unbound | Implemented default source binding in residual-work batch 2 when exact independent targets, reviewed prompts, prices, identity/client and metering exist. Existing custom bindings are preserved; deployment receipts remain open. |
| 8 | Narrow structured conflict vocabulary | Bounded design, not proof of complete reasoning: add only typed, evidenced comparisons; never infer conflict from lexical prose. |
| 9 | Process-local discussion budget | Fixed for standard per-correlation bootstrap in round 4: policy-pinned StateStore CAS survives restart/replicas without eviction or memory fallback. Fleet totals and live provider receipts remain separate. |
| 10 | Freyr/Loki recurring bindings absent | Explicit reviewed-metric/current-inventory Freyr source and standard bootstrap binding added; 56 focused checks pass. Actual target/provider receipts and reviewed Loki schedule/adversarial sources remain open; no samples or Chaos authority are invented. |
| 11 | Mimir/Bragi maintenance bindings absent | Open integration work: bind reviewed source/regression/promotion/activation readers without granting activation authority. |
| 12 | Durable what-if and multi-target attempt model | Open design/implementation work: prove restart-safe retained inputs and per-target rollback plus aggregate audit. |
| 13 | Ordered poison halt persistence unbound | Standard Core source now binds the existing service-owned StateStore and receipt-gated clear handler; actual initialization and related durability checks pass. Governed provider restart/clear receipts remain open. |
| 14 | Saga replica and issue-operation identity residuals | Local StateStore adapter now globally binds operation id to fingerprint/content and restores legacy bindings before reuse. Replica-safe audit/publication and remote GitHub App operation identity remain open. |
| 15 | Development authority source absent | Reconciled: current runtime implements PreparedDevelopmentBindingRegistry and shares the selected source with ControlLoop and Pantheon; 26 existing composition/source checks pass. Actual selected profile/current Owner/live approval and execution receipts remain unverified; no authority is manufactured. |
| 16 | Workflow/KPI/effect/promotion evidence absent | Operational blocker: retain complete pinned live-shadow cohorts, independent effects, recovery and zero policy escapes. |
| 17 | Generic v1 placeholder ownership map | Intended upstream example, not readiness: a deployment supplies v2 live primary and distinct backup/escalation identities. |
| 18 | Free-prose handover interpreter absent | Open integration work: bind a grounded interpreter; structured input and explicit hold remain safe defaults. |
| 19 | Readiness report is permanently observation-only | Intentional authority boundary: add independent evidence evaluation without allowing a report to self-certify deployment. |
| 20 | GitHub App/merge/restart evidence absent | Operational blocker: retain real refresh, signature, idempotent PR, merge and restart observations. |
| 21 | Executor/replacement identity evidence absent | Operational blocker: retain current target-bound authorization and independent identity/role readback. |
| 22 | Membership recovery drills absent | Operational blocker: run explicitly authorized nonproduction inverse and rollback drills. |
| 23 | Notification/non-response evidence absent | Operational blocker: retain actual channel delivery and recipient progression without treating silence as approval. |
| 24 | Document ACL/deletion/performance evidence absent | Operational blocker: retain source ACL, withdrawal, deletion, legal hold and complete performance cohorts. |
| 25 | Exact-plan deployment acceptance absent | Operational blocker: select release/target and obtain exact-plan human approval outside this local task. |
| 26 | Task-level handover competence absent | Operational blocker: retain coverage, correctness, independent review and task acceptance cohorts. |
| 27 | Real speech/assistive evidence absent | Needs human: retain actual EN/KO speech and screen-reader results; browser simulations are insufficient. |

## Round evidence

Residual-work batch 1 implements evidence-attributed peer critique. Same, opposite and absent
recommendations produce consistent, conflicting and not-comparable results without prose matching
or invented consensus. Deliberation/layout checks passed 75 tests; Ruff and focused mypy passed.
All authority, promotion and operational evidence boundaries remain unchanged.

Residual-work batch 2 implements canonical immutable owned snapshots, locale-bound structured
synthesis and a concrete V-CLAIM/independent-review adapter. Standard bootstrap resolves the exact
existing independent models and reviewed prompt packs, reserves both calls, preserves custom
bindings and holds missing prerequisites. Reviewer and malformed-generation costs are measured.
The focused snapshot/synthesis/layout/bootstrap selection passed 138 tests; exact prompt registry
loading, Ruff and three-file mypy passed. The new composition file owns only this binding and has
an explicit 200-line structural ceiling. No live model, identity, deployment or quality claim was made.

| Round | Critique | Repair | Focused evidence | Residual |
|-------|----------|--------|------------------|----------|
| 1 | One failed peer disappeared while a three-participant discussion reported completion. | Preserve selected/attempted participant accounting and return partial or abstain; no synthesis of incomplete branches. | `pytest -q --no-cov test_prompt_deliberation.py test_framework_layout.py`: 60 passed; Ruff and focused mypy passed. | Synthesis grounding, remote dispatch, persistent limits, integrations, and operational acceptance remain open. |
| 2 | Generated prose passed only output-size and sensitivity checks; a fabricated 999-resource claim was accepted. | Require an independent verifier and exact request/conclusion/evidence receipt; hold on absence, rejection, substitution, self-verification or provider failure. | Focused deliberation/layout/bootstrap checks: 82 passed; Ruff and six-file mypy passed. | The verifier contract is tested, not a live independent entailment or production readiness claim. |
| 3 | Remote dispatch discarded its selected agent and locale; generic agent mentions could select the target. | Preserve exact canonical target and locale through Bragi, include locale in request identity and reject invalid inputs before startup. | Remote/deliberation/conversational checks: 196 passed; Ruff and three-file mypy passed. | No general Operator caller of this standalone client was found; group-chat invocation and live locale evidence remain open. |
| 4 | Per-correlation call reservations disappeared after process replacement. | Bind policy-pinned StateStore accounting to standard bootstrap; preserve exact costs and reject corruption, policy substitution, unsupported fleet totals and bounded CAS contention. | Persistent/default budget, deliberation and bootstrap checks: 95 passed; Ruff and two-file mypy passed. | Real durable-provider restart evidence, declared fleet windows and other operating bindings remain open. |
| 5 | A known structured conflict still reported completion and the primary position when synthesis was missing or failed; partial results also exposed a final conclusion. | Remove final conclusions from partial/held results; preserve all participant evidence and allow only independently verified conflict synthesis to close. Reconcile parent composition/profile authority boundaries. | Cumulative 31-selector Pantheon/conversation/budget/handover checks: 966 passed; Ruff, focused mypy and stewardship gate passed. | This is five completed local hardening rounds, not closure of every initial source integration or any live operational blocker. |

## Completion boundary

### Residual group-discussion design and critique

An additive `presentation_mode` on the existing semantic request selects ordinary operation or
explicit `agent_discussion`. Ordinary default requests keep their existing serialized shape.
The Operator continues to validate authentication, roles, session, deadline and idempotency; Core
admits the discussion only for an authenticated Owner. The fixed Bragi port and independent
verified synthesis remain read-only and cannot submit actions or accept assurance fixture facts.
The result is advisory or held and stays inside the existing durable result/projection path.
Cancellation and deadline bounds apply before any model call. Missing Pantheon or evidence is a
visible hold, not a lexical or template fallback. This is separate from live validation or promotion.

The first critique found that the regular semantic executor's authorization cannot be assumed
for a separate group branch. Discussion therefore adds a distinct independent
`agent-discussion-read` purpose and `agent-discussion.read` grant rather than reusing case-history
authority. The verifier reads the request-bound retained human Owner receipt, recomputes both
lookup digests, checks the current grant-registry pin, and requires one exact installation
selector. No grant, real principal or deployment anchor is supplied by this change. The next
critique binds T1 selection to no optional synthesis and validates result type, session, trace,
verification envelope and conclusion digest before advisory presentation. Unverified conclusions
are removed, not templated. Current evidence is local only: 13 readback checks, 7 discussion
checks, and three-file mypy passed. Console presentation and governed acceptance remain open.

### Residual Console discussion evidence

The existing Command Deck now selects ordinary chat or explicit agent discussion and forwards
the mode through the existing streaming request. Ordinary requests omit the mode. Discussion
does not carry previous incident, selected Resource or document attachment context, and pending
attachments remain intact when discussion submission is refused. The structured reply preserves
position, peer critique, evidence disclosures and every participant outcome; held conclusions
remain absent, and a conclusion is labelled verified only for a completed verified T2 envelope.

UI review scope is the production Command Deck on `/overview`, full-workspace navigation,
synthetic in-process API frames only, partial/held outcomes including one abstained participant,
and sequential 1440x900, 993x641 and 390x844 views. The rubric's core checks and overlap, wrapping,
language, authority/status, keyboard-control and responsive gates are applicable. Unexercised
human screen-reader and live authorization behavior remain unverified, not not-applicable.
Local evidence: request/render/Korean-label checks: 61 passed; Console typecheck passed; focused
discussion and existing narrow-screen E2E: 2 passed. Captures under the leased `/tmp/fdai-playwright`
slot were reviewed and contain generic synthetic records only. E2E measures topmost pointer
exposure, disjoint selector rectangles, retained mode, failed participant visibility and page
horizontal overflow. Desktop and mobile selector overlap was reproduced and repaired. This is
not Browser Entra, actual model, verifier, task-competence or operational acceptance evidence.

### Residual recurring-sample hardening

Freyr's recurring sampler previously replaced absent source observation time with the current
collection time. This could manufacture freshness before a real provider was bound. It now
rejects missing, malformed and timezone-naive observation timestamps without emitting a
capacity forecast. Existing source-attributed sampling, default advisory behavior and shadow
verdict tests remain valid: focused recurring sampling checks: 11 passed; one-file mypy passed.
This source-time repair does not bind a provider, reviewed Loki schedule, maintenance reader or
current authority source, and does not close review ids 10-15.

### Residual ordered-halt and issue identity evidence

Standard Pantheon initialization now passes its service-owned StateStore to the existing durable
ordered halt and authorized-clear framework. It does not clear a halt or grant a new authority.
Saga's StateStore issue adapter now claims a global operation binding before applying the existing
per-issue revision CAS, and rehydration backfills the exact binding for retained older histories.
A different fingerprint or content cannot reuse the same operation id after restart. The tests
exercise actual initialization, receipt ordering, local upgrade/restart identity and adjacent
Mimir close evidence: 114 passed; two-file mypy and Ruff passed. This source result does not prove
remote provider restart, remote issue adapter identity, replica publication or live handover.

### Residual handover source-grounding evidence

The model bootstrap previously accepted any nonempty citation tuple, including a quote and
person absent from the current document. It now requires the exact document, valid line,
nonempty quote on that line and a cited person, plus a canonical agent, finite confidence and
directory-only identity. Corrected positive fixtures cite real text; seven substitution cases
abstain without directory resolution. Stewardship checks: 91 passed; structural gate: 15 agents
and 2 maintainers; focused mypy and Ruff passed. No concrete adaptive model, real identities,
backup assignment, notification arrival or operational handover receipt is created by this fix.

### Residual current-inventory sampler evidence

`CapacityMetricSampler` uses only the reviewed CPU percent declaration and exact active logical
Resource/provider references. It preserves source timestamps and excludes missing, invalid,
stale, future or cross-target values. Point limits and target limits reject overflow, and start/end
inventory generations and reference sets must match. Standard Core binds it only for explicit
`FDAI_FREYR_TARGETS_JSON`, a real MetricProvider and the existing inventory source. Local routed
provider, Freyr sampling and bootstrap checks: 56 passed; seven exact-source cases and two-file
mypy passed. No actual target, metrics call, scaling, Chaos or live acceptance was performed.

### Residual recurring-window and authority-source critique

An unanchored Loki cadence previously used each tick's current time as the new start and could
generate a distinct window repeatedly. Missing or naive anchors now hold, while complete
aware anchored schedules retain existing window deduplication and always-HIL proposals.
Schedule/adversarial/sampling checks: 25 passed; one-file mypy and Ruff passed. The current
development source was separately found implemented in runtime/development_authority.py and
delivery/development_bindings.py; 26 existing composition/source tests pass. The source-absence
finding is corrected, not replaced with a false selected-profile or live-authority claim.

### Round 4 design and critique

The existing `BudgetLedger` seam receives a StateStore-backed per-correlation implementation.
Only a hash of the bounded correlation is stored. Exact policy identity, strict counters and
revision CAS prevent restart resets, parallel double admission and silent policy substitution.
There is no process-local cache or correlation eviction. Mutation retries and total I/O time are
bounded. Undeclared fleet limits remain undeclared; explicitly configured fleet totals are
rejected until a separate atomic fleet implementation is bound, never silently ignored.
This accounting controls model calls only and grants no operational authority.

### Round 2 design and critique

An independent, composition-owned synthesis verifier reads the same bounded request and
generated outcome. Its immutable receipt binds the canonical request digest, exact conclusion
digest, and complete cited evidence set. The generator cannot act as its own verifier. Missing,
timed-out, malformed, mismatched, or rejected verification retains T1 evidence and never displays
an unverified T2 conclusion. Verification is presentation-only and grants no action authority.
The verifier seam is not itself operational validation: a deployment still needs a real
V-CLAIM/independent-review binding and governed receipts. Synthetic acceptance tests establish
the fail-closed transport boundary only.

This record does not label the Pantheon or ownership handover operationally ready. Open items
remain resumable with the exact exits above. A completed local round means only its stated source
repair and focused verification succeeded.

The original 27-item scope is not fully complete: items 2, 5 and 9 have bounded source repairs;
item 1 has a fail-closed independent-verification boundary but no concrete production verifier.
Items 3, 4, 6, 7, 10-15 and 18 retain source or integration work. Item 8 remains a bounded design
rather than complete reasoning. Items 16-17 and 19-27 require separately governed operational,
deployment or human acceptance evidence; intended safety defaults are not removed to manufacture
completion. No Azure/live-model action, notification, deployment, promotion, push or PR occurred.

Round 5 also reproduced the new verifier shifting the existing positional `LlmBindings`
constructor at argument 9. Appending the optional field restores the complete original 13-field
prefix. The final focused binding/deliberation/layout/bootstrap selection passed 84 tests after
this correction; two-file mypy and Ruff passed. The earlier cumulative selection passed 966
tests before that compatibility-only correction, and the relevant changed slice was rerun.
These checks are development feedback from the shared checkout, not a clean-release or deployed
receipt. Concurrent code-security work was excluded from edits and task-owned design validation;
the 25-path task-owned design check reported no failures.
