---
title: Escalation and Standing Authority (the supervised OODA loop)
---
# Escalation and Standing Authority (the supervised OODA loop)

What happens to a **high-risk decision after the risk gate pauses it for a
human** - and nobody answers. This doc specifies the **time-bounded escalation
ladder** that walks an unanswered approval up the on-call chain by impact, and
the **standing authorization** artifact that lets an operator pre-commit a
bounded, conditional execution for the case where waiting is more dangerous
than acting. Both are framed as a **supervised OODA loop** layered on the
existing single-pass control loop.

> **Scope reminder.** Customer-agnostic. Every rung name, group, threshold, and
> channel id below is an upstream **default**; a fork tunes them via config and
> catalog-as-code ([generic-scope.instructions.md](../../../.github/instructions/generic-scope.instructions.md)).

> **Safety focus.** Nothing here weakens *fail toward safety*. Standing
> authorization is a **human approval given in advance**, bounded by an
> envelope and re-verified deterministically at execution time - it is never a
> fail-open path and never lets an LLM grant execution. Every new capability in
> this doc ships **shadow-first** ([architecture.instructions.md § Safety
> Invariants](../../../.github/instructions/architecture.instructions.md#safety-invariants)).

Human reporting source-pin refreshes remain descriptive and grant no approval or execution authority.
## What this doc covers

The control loop in
[architecture.instructions.md § Control Loop](../../../.github/instructions/architecture.instructions.md#control-loop)
is **single-pass**: an event is normalized, routed, decided, acted on, and
audited to a terminal state. That is correct for a discrete event. It does
**not** model a decision that stays *pending* while the world changes around it:

An eligible human can now answer that pending request through either a signed Teams or Slack
callback or the Entra-authenticated FDAI Console route. Both paths recheck the exact approval,
current role, expiry, and separation of duty, then atomically retain the decision and durable
outbox. This adds another safe response surface; it does not change the escalation timer,
standing-authority rules, or Thor's execution boundary.

- An actionable `hil` verdict with a registered ActionType fires an approval request with a TTL.
  Forseti also lowers an otherwise automatic verdict to human approval when the governed reversible
  ActionType semantics are absent, the action is unknown, the effective quorum is two or more, or
  the matched rule has been retired or revoked. That lowering creates the same approval lifecycle as
  any other `hil` decision and records the deterministic reason instead of treating the automatic
  path as executable.
  TTL expiry always converges to a **terminal no-op + audit**, even when no notification channel
  is configured. An actionless shadow Human-review Verdict whose exact reason is
  `no_rule_match` or `anomaly_action_unavailable` remains on the Verdict stream for Odin and Saga,
  but Thor creates no `ActionRun` or resource claim. It therefore has no approval TTL and does not
  enter this supervisor unless a new actionable proposal is judged. An available channel may add
  the A2 alert described in
  [channels-and-notifications.md § on-call, escalation, timeouts](../interfaces/channels-and-notifications.md),
  but delivery availability never controls expiry. This is fail-closed and correct, but it stops
  there.
- **Channel fallback** already exists: a failed Teams approval falls to another
  A1-capable channel, then pages the ops lane
  ([channels-and-notifications.md](../interfaces/channels-and-notifications.md)). That handles
  **delivery failure**, not **human non-response** - a different problem.
- A **forecast finding** carries a shrinking **lead time** (`actual_breach_time
  - finding_time`, the breach ETA) ([observability-and-detection.md § 3.
  Predictive / Forecasting](../rules-and-detection/observability-and-detection.md#3-predictive--forecasting)).
  While an approval sits unanswered, that ETA keeps closing - the *cost of
  inaction rises with the clock*, but the single-pass loop has already moved on.

The gap is a **temporal supervisor**: something that re-enters the loop **on a
timer** for as long as a decision is pending, re-reads the situation (approver
still silent? ETA closer? blast radius of inaction grown?), and escalates or, if
pre-authorized, acts. That is an OODA loop.

## OODA as the supervision frame

The existing pantheon control loop already maps cleanly onto OODA (see the
mapping in [architecture.instructions.md § Trust Routing](../../../.github/instructions/architecture.instructions.md#trust-routing-3-tier)).
The addition here is a **second, slower loop** that supervises *one pending
decision* and ticks until it reaches a terminal state.

![OODA as the supervision frame. The main stages are approval still pending?, forecast ETA now? / (lead time recomputed), inaction blast radius?, recompute urgency / = f(impact, ETA, rung age), which ladder rung / should hold this now?, standing authorization / matches + envelope holds / + deadline passed?, escalate to next rung, trip standing action / -> re-enter typed pipeline, terminal no-op / (ladder exhausted), audit (Saga).](../../diagrams/generated/fdai-escalation-and-standing-authority-01.en.svg)

- The supervisor **never mutates substrate directly**. Its only privileged
  outcome (`A2`) is to **re-enter the typed pipeline** so the action is
  re-judged and executed through the normal principals. A supervisor that called
  an executor directly would be a defect (same rule as the conversational port
  in [architecture.instructions.md § Agent Pantheon](../../../.github/instructions/architecture.instructions.md#agent-pantheon)).
- The loop is **bounded**: it has a maximum number of rungs and a hard overall
  deadline. It cannot tick forever.

## The escalation ladder

Runtime composition now loads the catalog and snapshots matching windows through
`CatalogEscalationTiming`. `FDAI_HIL_ESCALATION_ENVIRONMENT` explicitly selects `prod` or
`nonprod`; absence never guesses a non-production context. Private
`FDAI_HIL_ESCALATION_AUDIENCES_JSON` binds each catalog audience to one exact human. Missing,
ambiguous, or mismatched audiences preserve the conservative existing timing with a recorded
reason. The production observation path carries the actual finding class and Action blast radius;
forecast compression additionally requires explicitly verified lead-time and confidence evidence,
not raw event text. Runtime mode remains shadow and those bindings cannot promote it.

Heimdall's existing evaluator retains the computed breach ETA and configured prediction-band
confidence with the transactional forecast publication. Before parking an approval, the supervisor
reads the exact `forecast:<episode-id>` and Action target from the Core episode/outbox pair. It
checks source identity, detector/version, scope digest, cutoff, horizon, and the breached interval.
Confidence is not `R²`. Missing legacy fields, closed episodes, stale evidence, failed reads, or
expiry during I/O keep conservative timing. The five-second read bound never retries a live source.
The parked record retains the source digest and original deadlines; replay cannot extend them.

Forecast timing only shortens the response window of an approval that already exists. In the
default observation-first profile, a forecast, a Freyr capacity prediction, or a T1 match of a
learned pattern creates no approval to time: Forseti publishes an ActionType-free Verdict, and the
control loop stops T1 learned reuse before it builds an Action. Only the explicitly selected
governed execution add-on lets such input reach Var through the existing gates, as the
[learned and predicted output boundary](../agents/agent-pantheon-implementation.md#learned-and-predicted-output-boundary)
describes.

Enforce construction requires a current-role verifier. The directory adapter disables roster
caching for this check and requires an active exact person with ordinary Approver/Owner membership.
Lookup failure holds without treating outage as role loss; expiry is rechecked after the lookup.
Shadow integrity findings remain observations and cannot resolve the live approval. These local
checks do not replace measured urgency cohorts or authorization to enable rung dispatch.

An **escalation ladder** is an ordered list of **human-authority rungs**. It is
distinct from channel fallback: channel fallback answers *"the message did not
get delivered - try another pipe for the same person"*; the ladder answers
*"the message was delivered but nobody with authority acted - widen who is
asked, by impact."*

| Concept | Answers | Fails over on | Lives in |
|---------|---------|---------------|----------|
| **Channel fallback** | delivery failure | channel unreachable / send error | [channels-and-notifications.md § 6](../interfaces/channels-and-notifications.md) |
| **Escalation ladder** | human non-response | rung TTL elapsed with no decision | this doc |

For explicitly selected ActionTypes, a reviewed
[human report line](../interfaces/human-report-lines-and-approval-routing.md) can supply the
ordered people for a ladder. FDAI asks the requester for contact consent before the first
notification. It rechecks the graph revision, current role, and principal-to-ActionType policy
before each delivery and before accepting approval. A changed or incomplete route ends in a
fail-closed no-op rather than falling back to an unrelated Owner.

Each rung declares: **who** (an Entra group, resolved outside the control plane
exactly like approver groups today), a **per-rung TTL**, and the **notification
category** it may use (A1 for the decision-carrying rung, A2 paging for
awareness). The ladder is **selected by impact tier** - a `resource`-scoped
finding may only ever reach the primary on-call; a `subscription`-adjacent
impact recruits the incident commander quickly.

```yaml
# Shipped catalog-as-code artifact (shadow-first; see Rollout).
# rule-catalog/escalation-ladders/prod-forecast-breach.yaml
version: 1
kind: escalation_ladder
id: prod-forecast-breach
priority: 10                     # unique; first-match in ascending order
select_when:
  environment: prod
  finding_class: forecast.breach
  impact_at_least: resource_group
rungs:
  - rung: on_call_primary
    audience_group: aw-oncall-primary   # placeholder; fork supplies real group
    ttl_seconds: 300
    category: hil_approval
  - rung: on_call_secondary
    audience_group: aw-oncall-secondary
    ttl_seconds: 300
    category: hil_approval
    also_page: [pagerduty-primary]      # A2 awareness, non-deciding
  - rung: incident_commander
    audience_group: aw-incident-commander
    ttl_seconds: 600
    category: hil_approval
    also_page: [pagerduty-primary, sms-oncall]
overall_deadline_seconds: 1500   # hard cap; on expiry -> terminal no-op unless
                                 # a standing authorization trips first
```

Durations are integer seconds rather than `5m` strings, so a replayed schedule
never depends on a duration parser. `priority` makes first-match selection a
total order; the loader refuses a duplicate, because two ladders sharing a
priority would make selection depend on directory order. The loader also refuses
a ladder whose rung TTLs do not fit inside `overall_deadline_seconds`, so a
ladder cannot name an audience the deadline silently makes unreachable, and
refuses a rung that pages its own deciding audience, because paging is awareness
and never approval authority.

- **No self-approval survives escalation.** A later rung is a *different*
  principal; the approver-of-record is whoever actually decides, and the executor
  is still a separate principal (Var approves, Thor executes -
  [agent-pantheon.md](../agents/agent-pantheon.md)).
- **Every rung transition is audited** and, when the fingerprint repeats, feeds
  the existing `HandoffEscalation` -> GitHub issue path so chronic non-response
  becomes a tracked signal, not a silent loss
  ([agent-pantheon.md § 6.4 Handoff escalation protocol](../agents/agent-pantheon.md)).

## Time-decaying urgency

The ladder above uses *fixed* TTLs for clarity, but urgency is not fixed when a
breach is forecast. The supervisor recomputes, each tick, an **urgency** signal
and uses it to **compress** rung TTLs and to **raise the starting rung**:

- **Inputs** (all already produced upstream, no new collection): `impact` /
  blast radius from the risk gate, **breach ETA** from the forecaster
  ([observability-and-detection.md § 3](../rules-and-detection/observability-and-detection.md#3-predictive--forecasting)),
  and **rung age** (how long the current rung has been silent).
- **Rule of thumb**: `effective_ttl = min(rung.ttl, k * remaining_lead_time)`.
  As the forecast ETA closes, the window each human gets shrinks, and the loop
  climbs the ladder faster - it never *lengthens* a TTL past the declared value.
- **Confidence still gates.** A forecast only drives urgency when its
  prediction-interval band clears the configured confidence level
  ([observability-and-detection.md § 3](../rules-and-detection/observability-and-detection.md#3-predictive--forecasting));
  a noisy point-estimate breach does not get to compress deadlines.
- **A floor prevents starvation.** Compression is clamped to
  `[min_effective_ttl_seconds, rung.ttl_seconds]`, so an imminent breach cannot
  shrink a rung to a window no human could answer in.

```yaml
# rule-catalog/escalation-ladders/urgency.default.yaml
version: 1
kind: urgency_policy
id: default-forecast-urgency
lead_time_factor: 0.5            # the k above
min_forecast_confidence: 0.9     # below this, nothing compresses
min_effective_ttl_seconds: 60    # starvation floor
```

The schedule is computed by a pure function that takes the remaining lead time
and the forecast confidence as arguments rather than reading a clock, so a
recorded escalation replays to the same timeline. An absent policy, an absent
forecast, or a forecast below `min_forecast_confidence` all leave every rung at
its declared TTL: an unproven urgency signal never shortens a human's window.

Urgency changes **how fast** the ladder is walked; it never changes **whether**
an unattended approved execution is allowed. That gate is standing authorization.

## Standing authorization (pre-authorized conditional execution)

This is the mechanism behind *"the operator configured an automatic action in
advance."* A **standing authorization** is an operator-authored, policy-as-code
artifact that says:

> Under **condition** C, for actions inside **envelope** E, if the escalation
> ladder reaches its deadline **unanswered**, the pre-recorded human Approval may satisfy the
> action's `hil` requirement - and only then.

The crucial design property: a standing authorization is **not a new decision
engine and not a bypass**. It is a **deterministic input to the existing risk
gate**. When the supervisor's Decide step asks *"can this proceed unattended?"*,
the risk gate answers by checking a standing authorization the same way it checks
any other rule - and execution eligibility is still granted by that deterministic
verification, never by a model
([architecture.instructions.md § LLM Quality Gate](../../../.github/instructions/architecture.instructions.md#llm-quality-gate-required-for-t2)).
A confirmed `CausalHypothesis` closure is likewise evidence only: it never satisfies a standing
authorization condition, envelope, or `hil` requirement by itself.

```yaml
# Matches the shipped schema; shadow-only (see Rollout below).
# authority/standing-authorization.json
schema_version: "1.0.0"
id: sa-scale-out-before-quota-breach
authorization_revision: <content-digest>
status: active                  # active | revoked | expired | superseded
mode: shadow                     # judge-and-log until explicitly promoted; only value accepted today
requested_by: <normalized-human-principal>
approvals:                       # distinct normalized human principals; min 2
  - principal: <accountable-service-owner>
    role: service_owner
    approved_at: <rfc3339-timestamp>
  - principal: <owner-level-approver>
    role: owner
    approved_at: <rfc3339-timestamp>
quorum_required: 2
valid_from: <rfc3339-timestamp>
valid_until: <rfc3339-timestamp>  # expires unless renewed by the accountable owner
service_ref: <service-id>
scope:                            # MUST be resource-group-equivalent or narrower
  level: resource_group          # resource | resource_group; subscription/tenant are never eligible
  value: <rg-name>               # placeholder; fork supplies real scope
pins:                             # exact revisions the delegation was reviewed against
  policy_digest: <risk-and-approval-policy-digest>
  target_revision: <inventory-and-operating-model-revision>
  action_type_versions: [remediate.scale-out.compute@<version>]
  evidence_revisions: [<governed-evidence-ref>]
incident_classes: [forecast.breach]
responders:
  primary: <on-call-primary>
  backup: <on-call-backup>
  confirmed_at: <rfc3339-timestamp>
evidence:
  history_reviewed: true         # owner reviewed applicable logs, incidents, and audit history
  precedent_ref: <governed-evidence-ref>
  scenario_evidence_ref: <dr-chaos-or-simulation-ref>
envelope:                         # the action MUST fall entirely inside this
  action_types: [remediate.scale-out.compute]
  max_blast_radius: <bounded-resource-count>
  max_duration_seconds: <bounded-duration>
  reversible: true               # only reversible actions may be pre-authorized
  rollback_contract: scripted    # a tested undo path is mandatory
  stop_conditions: [<rollback-trigger-condition>]
```

**What makes this safe (the non-negotiables):**

- **Bounded like a human override.** Scope MUST be resource-group-equivalent or
  narrower - the same ceiling the human-override mechanism enforces
  ([architecture.instructions.md § Human Override](../../../.github/instructions/architecture.instructions.md#human-override)).
  There is no subscription-wide standing authorization.
- **Non-destructive and reversible only.** A destructive or `irreversible: true` action can never be pre-authorized;
  it always routes HIL+quorum
  ([coding-conventions.instructions.md § Safety](../../../.github/instructions/coding-conventions.instructions.md#safety)).
  A standing authorization requires a declared, tested `rollback_contract`.
- **Ladder-first, never ladder-instead.** A consumer MUST only consult a standing authorization
  after the escalation ladder's `overall_deadline_seconds` has elapsed unanswered - this is a
  calling-code invariant the schema does not encode, because nothing yet consumes the evaluator
  (see Implementation status). Channel fallback must first confirm delivery; an unreachable person
  is not recorded as silent. A standing authorization can only fire once real humans were asked and
  the deadline passed - it *shortens the tail*, it does not replace the human.
- **Distinct human quorum is the approver-of-record.** At least two normalized, distinct human
  principals approve: the accountable service owner and an Owner-level authority. The requester
  and executor are ineligible. Var carries their signed revision as the standing Approval, so
  approve-vs-execute separation holds with no model-as-approver.
- **Operational evidence is current.** The owner reviews applicable service logs, incidents, and
  audit history and records whether a precedent exists. When no adequate precedent exists, a
  current DR drill, bounded Chaos experiment, or simulation supplies scenario evidence.
- **Handover suspends until reconfirmed.** Every ownership handover requires the new accountable
  owner to confirm the service, responders, envelope, evidence, and expiry. Missing, stale, or
  declined confirmation makes the authorization ineligible.
- **Validity and revocation are monotonic.** `valid_from <= now < valid_until` and `status=active`
  are required. Revocation is immediate and blocks pending re-decisions. Renewal creates a new
  immutable revision with fresh quorum, evidence, and responder confirmation; it never extends the
  old record in place.

### Lifecycle persistence and dispatch fence

One Core lifecycle writer owns each standing-authorization family. The Operator API authenticates
the human command and publishes it through typed ingress; it does not write lifecycle tables.
PostgreSQL serializes admit, renew, and revoke commands on one family row and commits the immutable
revision, hash-chained transition, current snapshot, fencing generation, and lifecycle audit entry in one
transaction.

The revision digest covers immutable authorization terms only, including a Core-issued family id,
issuance time, and predecessor revision. Approval and independently verified evidence records are
separate immutable bindings over that digest. This avoids a circular digest while preventing an
approval or evidence bundle from being reused for another revision.

Every transition carries a contiguous family sequence, the prior transition digest, and a monotonic
fencing generation. Replay starts at admit and validates the complete chain before it can rebuild an
active snapshot. A missing projection, sequence gap, reordered transition, broken digest, stale
expected revision, or stale generation returns no active authority.

A lifecycle fence names the exact family, revision, generation, and transition digest. The
authoritative primary store can compare that fence immediately before effect dispatch. This
read-time check does not close a revoke-during-effect race, so it remains unwired with the evaluator
in the current shadow slice. Enforcement requires a separately reviewed lock or lease that spans
the side-effect commit, plus governed shadow evidence and independent promotion review.

The selected `ops.start-vm@1.0.0` development slice adds a provider-boundary shadow probe for
exactly one VM in one resource group. It compares the acquired lease through the existing
`StandingAuthorizationLeaseStore` fence and emits a content-addressed receipt, but always records
`provider_commit_attempted=false`, `effect_applied=false`, and
`provider_capability_outcome=ineligible_capability`. Azure Resource Manager cannot join its VM
start acceptance to the PostgreSQL lease transaction, so a current shadow fence is evidence about
the contract only and does not make the ActionType eligible for A3-E.

That ineligibility is now derived rather than asserted. `provider_eligibility.py` owns
`A3E_COMMIT_FENCE_ADAPTERS`, the set of ActionTypes whose adapter validates the current lease and
fencing generation atomically at provider commit. The set is empty, so `a3e_fence_capability`
returns `INELIGIBLE_CAPABILITY` for every shipped ActionType, and a promotion candidate derives its
ineligible set from that classification instead of taking it from its author. Registering an adapter
is an authority-bearing change that requires the durable provider boundary above; it still grants no
execution or promotion authority on its own.

The same slice adds a pure effect-result planner. Matched independent evidence proposes no
transition; failed, timed-out, missing, stale, conflicting, censored, or otherwise unscorable
evidence proposes `return_to_shadow`. The planner is not a registry writer, does not revoke a
standing authorization, and grants no recovery authority. A later authority-bearing consumer must
be separately reviewed and authorized.

The local acceptance-fence model orders one scripted provider submission attempt inside one
process. It persists `PREPARED` before the callback, rechecks the exact lease fence, issues at most
one permit for the target-fence digest, and records `ACCEPTED`, positive `NOT_ACCEPTED`, or
`UNKNOWN`. Every existing state blocks another submission; timeout, cancellation, exception,
or terminal-write ambiguity stays commit-equivalent and cannot be retried. The deterministic
`x-ms-client-request-id` is correlation only and is not provider-side deduplication.

This model is not distributed atomicity, does not close the revoke-during-submit race, and does
not prove the VM effect. It declares `production_eligible=false`, has only a process-local test
store, and remains unwired. The strict `StandingAuthorizationLeaseStore` provider-commit contract
and `INELIGIBLE_CAPABILITY` outcome remain unchanged.

- **Execution fits the validity window.** The risk gate requires
  `now + max_duration_seconds <= valid_until` before dispatch. It uses trusted UTC for persisted
  instants and monotonic elapsed time for the running deadline. Clock unavailability or excessive
  skew makes the authorization ineligible.
- **Responders are current.** Eligibility requires a time-aware OnCallSchedule receipt or explicit
  primary and backup identities resolved with an expiry no later than `valid_until`.
- **Version-bound and revocable.** The authorization pins its revision, policy digest, target
  revision, ActionType and workflow versions, and evidence revisions. Any mismatch, revocation,
  policy change, target drift, or catalog change requires independent re-approval.
- **Chaos injection is excluded.** A standing authorization never approves fault injection. A
  separately human-approved experiment may pre-authorize only its bounded stop and recovery path.
- **All seven autonomous-action safeguards still apply**
  ([architecture.instructions.md § Seven Autonomous-Action Safeguards](../../../.github/instructions/architecture.instructions.md#seven-autonomous-action-safeguards)).
- **Prefer safe-degradation over the risky action.** When possible, the
  pre-authorized action is a **reversible mitigation** (scale out, open a circuit
  breaker, extend a quota) that buys time, not the destructive remediation itself.
  Buying time re-arms the human loop rather than ending it.

## The re-decide path (no bypass)

When a standing authorization trips, the supervisor does **not** execute. It
**re-injects the pending action into the typed pipeline** as a fresh decision:

![The re-decide path (no bypass). The main stages are escalation supervisor / (ladder deadline + SA match), risk-gate / re-evaluates, Var / standing Approval, Thor / executes approved HIL action, delivery / remediation-PR / direct-api, audit (Saga) / reason: standing-authority sa-...id, terminal no-op / + A2 alert.](../../diagrams/generated/fdai-escalation-and-standing-authority-02.en.svg)

- **Forseti re-judges without raising risk.** The original `hil` baseline remains. The risk gate
  verifies a valid, unexpired, scope-matching standing authorization whose pinned revisions and
  envelope still hold; Var materializes its pre-recorded human Approval. Judge, approver, and
  executor remain distinct.
- **Standing authority satisfies approval; it does not raise mode.** The `ActionPromotionRegistry`
  remains an independent shadow/enforce axis and cannot represent A3-E. A3-E review uses the
  dedicated `standing-authority-promotion` change class, which requires two distinct
  phishing-resistant approvals including an Owner. The generic `enforce-promotion` class cannot
  satisfy this authority, and the review decision grants no execution authority.
- **Thor executes**, Vidar remains the rollback principal, Saga audits with an
  explicit `standing-authority` reason and the authorization id - a replayable,
  attributable record ([architecture.instructions.md § Idempotency, Ordering,
  and Replay](../../../.github/instructions/architecture.instructions.md#idempotency-ordering-and-replay)).
- **Envelope violation fails closed.** If the pending action does not fit the
  envelope (wrong action type, blast radius grew, inventory went stale), the
  standing authorization does **not** apply and the loop terminates as a no-op.

## Agent mapping (no new agents)

The pantheon is fork-locked - **no agent is added, removed, or renamed**
([agent-pantheon.instructions.md](../../../.github/instructions/agent-pantheon.instructions.md)).
The supervised loop is expressed with existing agents and their existing topics:

| OODA step | Agent(s) | Existing responsibility used |
|-----------|----------|------------------------------|
| **Observe** | Heimdall, Huginn | re-read forecast finding + pending-approval state (sensing, deterministic-first) |
| **Orient** | Odin | impact arbitration; which rung and urgency hold now |
| **Decide** | Forseti (+ risk gate) | re-judge without raising the original `hil` baseline |
| **Act (escalate)** | Var | carry the A1 request to the next rung; approver-of-record |
| **Act (execute)** | Var, Thor | Var supplies standing Approval; Thor remains sole executor |
| **Recovery** | Vidar | rollback path for the executed mitigation |
| **Audit / handoff** | Saga | append audit + `HandoffEscalation` on chronic non-response |

The supervisor itself is a **lifecycle behavior of the pending decision**, not a
sixteenth agent: it is the timer-driven re-entry of the same typed pipeline,
owned by the approval lifecycle (Var) and arbitrated by Odin.

## Terminal states

Every path ends in an audited terminal state - the loop cannot leak:

| Terminal | When | Result |
|----------|------|--------|
| **approved** | any rung decides `approve` | execute via Thor, audit |
| **rejected** | any rung decides `reject` | no-op, audit |
| **standing-authority executed** | ladder deadline passed, SA valid, envelope holds | re-decide -> standing Approval -> execute, audit with SA id |
| **terminal no-op** | ladder exhausted, no valid SA | no action, A2 alert, audit, `HandoffEscalation` if fingerprint repeats |

**Fail-closed remains the default.** Absent a valid standing authorization, an
unanswered ladder still ends in no-op - exactly today's behavior, just after a
wider, impact-tiered, time-decaying set of humans were given the chance to act.

## Rollout (shadow-first)

1. **Ladder in shadow.** Ship the escalation ladder judging-and-logging only:
   it records *which rung it would have escalated to and when*, mutating nothing.
   Promote per-ladder once the escalation timing is validated against real
   non-response incidents.
2. **Standing authorization in shadow.** Every standing authorization declares
   `mode: shadow` and a measurable promotion gate (e.g. "N shadow trips, zero
   envelope escapes, zero policy-violation escapes"). Promotion out of A3-E shadow review is a
   separate, Owner-reviewed `standing-authority-promotion` change that qualifies only the
   standing-approval lane; it never changes registry mode or bypasses `hil`, and it is never
   bundled with the authoring PR
   ([coding-conventions.instructions.md § Safety](../../../.github/instructions/coding-conventions.instructions.md#safety)).
3. **Metrics** (fold into the existing KPI stream,
   [goals-and-metrics.md](../architecture/goals-and-metrics.md)): rung-response latency,
   escalation depth distribution, ladder-exhaustion (no-op) rate, standing-
   authority trip rate, and - the guard metric - **envelope-escape count, which
   must stay zero**.

## Open questions

- **Rung membership source.** Reuse the Entra-group binding used for approver
  groups, or introduce an on-call schedule integration (PagerDuty/Opsgenie
  schedule read) so "who is primary" is time-aware? Leaning group-first for the
  upstream, schedule integration as a fork seam.
- **Urgency function shape.** The `k * remaining_lead_time` compression is a
  starting heuristic; the exact curve is a tuning parameter to backtest against
  historical forecast-to-breach series before enforce.

## Next steps

| To learn about | Read |
|----------------|------|
| The single-pass control loop this supervises | [architecture.instructions.md § Control Loop](../../../.github/instructions/architecture.instructions.md#control-loop) |
| How an action is classified auto / HIL / deny | [risk-classification.md](risk-classification.md) |
| Forecast lead time and the prediction-interval band | [observability-and-detection.md § 3](../rules-and-detection/observability-and-detection.md#3-predictive--forecasting) |
| Channel fallback vs this human-authority ladder | [channels-and-notifications.md](../interfaces/channels-and-notifications.md) |
| Which agent escalates, judges, and executes | [agent-pantheon.md](../agents/agent-pantheon.md) |
| The bounded human-override mechanism this mirrors | [architecture.instructions.md § Human Override](../../../.github/instructions/architecture.instructions.md#human-override) |

## Related docs

| To learn about | Read |
|----------------|------|
| Delivery status and remaining work | [Implementation ledger](../../roadmap-implementation/decisioning/escalation-and-standing-authority.md) |
