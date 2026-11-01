---
title: Assurance Twin (queryable, proactive, verifiable review)
---
# Assurance Twin (queryable, proactive, verifiable review)

FDAI's answer to the "architecture review agent" request is not a chatbot
bolted onto a document index. It is an **Assurance Twin**: a queryable,
ontology-grounded digital twin of the governed subscription that answers
questions deterministically, reviews changes before anyone asks, and proposes
(never executes) remediation. A model compiles natural language into typed graph
queries and explains the results; the answer itself is produced by the
deterministic engine over the twin, so it is grounded and verifiable by
construction, not by a model's say-so.

> **Scope**: customer-agnostic. The twin's schema, rules, and thresholds are
> generic; a fork supplies its own resource population through the `Inventory`
> seam and its own rule set. No customer values, tenant ids, or resource names
> live here
> ([generic-scope.instructions.md](../../../.github/instructions/generic-scope.instructions.md)).

> **Where it sits**: the twin is a **read-only projection** over the ontology
> graph. It never holds a privileged identity. Every mutation still flows
> through `risk-gate -> executor -> delivery`, preserving the read-only surface
> rule in
> [app-shape.instructions.md](../../../.github/instructions/app-shape.instructions.md).
> Answering a question is never an action.

## What this doc covers

This document specifies the review/assurance surface that covers the
architecture-review, Q&A, and assessment-report use cases without regressing the
deterministic-first, event-driven, risk-gated design. It reuses the ontology in
[llm-strategy.md](../architecture/llm-strategy.md#ontology-foundation), the tiered router and
quality gate in
[architecture.instructions.md](../../../.github/instructions/architecture.instructions.md),
the detection findings in
[observability-and-detection.md](../rules-and-detection/observability-and-detection.md), and the
deployment analyzer in [deployment-preflight.md](../deployment/deployment-preflight.md). It
adds one new subsystem, `core/assurance_twin/`, and one delivery intent; the rest
is composition of existing parts.
## Why not a chatbot

A retrieval-augmented chatbot answers the review use cases with five structural
defects. The twin inverts each one.

| Chatbot limitation | Consequence | Assurance Twin shift |
|--------------------|-------------|----------------------|
| **Reactive** - answers only when asked | reproduces the review-queue lead time (wait for a request, then wait for a human) | **Ambient** - reviews changes proactively on the change event, before a request exists |
| **Ungrounded** - vector similarity over prose | hallucinated verdicts reach a deploy | **Ontology-grounded** - answers are deterministic graph queries with a cited rule path |
| **Stateless** - reads documents, not the live estate | no real evidence for "why is this non-compliant" | **Stateful twin** - a live projection of the subscription kept fresh by inventory delta |
| **Inert** - returns information and stops | a human still fixes it by hand | **Action-bridging** - an answer can carry a shadow remediation-PR proposal |
| **Static** - the index goes stale | wrong answers after a policy change | **Self-improving** - unanswered / abstained questions feed the rule discovery loop |

## The five shifts

### 1. Ambient (reactive to proactive)

The current implementation stops before this production flow. A stable `sha256:` Resource
revision covers the active snapshot identity and content and the bounded realtime Resource
overlay (including observation times). `load_at_revision` re-reads and rejects later content.
A trusted, injected source must re-read that revision
and provide positive rule coverage, evaluated rule ids, a rule-set digest, and a digest of the
complete finding set. An empty finding set is clear only after that independent complete rule
assessment. Pending relationship overlays, absent evidence, revision drift, stale or
conflicting sources remain unavailable. None of these read-only records grants approval,
mutation, or execution authority.

Forseti reviews FDAI's own typed change proposals, never an IaC plan. The owner decision of
2026-09-28 is that Terraform is a local deployment tool and must not be used at the governance
level, so a Terraform plan, rendered template, or pull-request diff is never a Twin review input.
One review input binds an exact ActionType id and version, exact target Resource refs, a
canonical parameter digest, and one completed what-if or dry-run result bound to the same
content-addressed proposal digest. The what-if must be passed, complete, current, non-synthetic,
from the `simulation_engine` authority class, and must name exactly the proposal's targets.
A reviewed, declared effect model for that exact ActionType version maps the parameters onto
top-level target properties. Every parameter must be consumed or declared inert.

The twin reviews typed changes as they are proposed, not on request. A typed-pipeline producer
submits the proposal and what-if to a durable, content-addressed intake. Forseti's producer
applies the declared effect to a scratch projection of the proposal's targets in the retained
Inventory revision, and the control loop T0/OPA generation evaluates the changed targets with
complete receipts. The retained and predicted values of each written property are compared leaf
by leaf, and every leaf that actually changes must be covered by a declared input of at least one
applying Rule for that target. An input on a parent path covers its children; a child input never
covers its parent or siblings, and unchanged leaves need no coverage. Otherwise the change is
`effect_unassessed`. Forseti's writer then publishes a bounded read-only review through the
exact-revision outbox. A missing effect model, an absent, stale, incomplete, failed, or
conflicting what-if, a target outside the retained revision, an undeclared parameter, or an
unassessed property settles the proposal unavailable instead of `clear`.

The review key is the proposal ref, so the ledger keeps exactly one current review per proposal.
A newer revision supersedes the older review, its outbox, and its Saga lineage in one
compare-and-set; a delayed older revision never replaces it. The Operator projection also treats
two usable reviews for one change handle as a conflict gap. An intake row stays `recorded` until
the writer confirms that exact review. When a Rule-generation or Inventory revision change blocks
the writer's fenced commit, Forseti retires the stale request so the relay stops. It re-derives
while the what-if is fresh, within at most three derivation attempts, and otherwise settles the
proposal unavailable with `rule_generation_changed` or `inventory_revision_changed`. An external
Checks publisher can later render the retained review; it is delivery, not an input.

Example: a typed proposal would set `public_access: enabled` on one storage account. With a
reviewed effect model for that exact ActionType version and a completed what-if for that exact
proposal, Forseti publishes a `blocked` review that cites the violated public-access Rule for that
target before anyone asks. The review never approves, executes, or promotes the proposal.

### 2. Ontology-grounded (retrieval to graph query)

The twin is the ontology graph, not a prose index. Every governed resource is a
`Resource` ObjectType; relationships are the existing typed LinkTypes
(`contains`, `attached_to`, `depends_on`), and rule matches are `Finding`s (see
[llm-strategy.md](../architecture/llm-strategy.md#ontology-foundation)). "Why is this resource
non-compliant" is answered by a graph traversal that returns a concrete evidence
chain, for example:

```text
Resource:storage-x --attached_to--> Resource:subnet-y
subnet-y --contains(-1)--> vnet-z
Finding: storage-x violates rule:object-storage.private-endpoint.required
  evidence: rule path + evaluated property (publicNetworkAccess=Enabled)
```

The chain is deterministic and reproducible: the same twin state yields the same
answer regardless of who asks or how the question is phrased.

### 3. Verifiable (text-to-query, not text-to-answer)

This is the core mechanism. The model is used to **compile a natural-language
question into a typed ontology query** and, at the end, to **render the result
back into prose**. It is never the source of the fact.

![3. Verifiable (text-to-query, not text-to-answer). The main stages are NL question, model: compile / NL to typed ontology query, verifier: query is / well-typed and read-only, T0: execute query / over the twin (deterministic), Assurance Twin / ontology graph, grounded result set, model: explain / result + cite rule path, answer + provenance / + confidence + what-if, abstain: 'not known'.](../../diagrams/generated/fdai-roadmap-operations-assurance-twin-01.en.svg)

- **Compilation is verified**: the compiled query MUST be well-typed against the
  ontology schema and MUST be read-only; a query that fails the check is rejected,
  not executed. This is the same fail-closed posture as the T2 verifier.
- **Compilation evidence is exact**: runtime composition requires the compiler revision, exact
  question digest, bounded result limit, and at least one evidence reference. Invalid or injected
  output becomes an explicit ambiguity result and can emit only a content-free discovery gap.
- **Answers route through the tiers**: an exact rule/graph match resolves at
  **T0**; a fuzzy question near a known pattern uses **T1** similarity; only a
  genuinely novel or ambiguous question reaches **T2**, and T2 output clears the
  [quality gate](../../../.github/instructions/architecture.instructions.md#llm-quality-gate-required-for-t2)
  (mixed-model cross-check, verifier, grounding) before it is shown.
- **Grounding or abstain**: every answer cites the rules and graph nodes that
  justify it. An answer that cannot be grounded returns "not known", never a
  guess. Hallucination is closed off by construction, not by prompt tuning.

### 4. Action-bridging (inert to proposing)

An answer may carry a proposed fix, but the twin never executes. When a question
resolves to a fixable Finding, the twin can attach a **shadow remediation-PR
proposal** built from the rule's `remediates` ActionType. Acting on it is the
existing gated path: `risk-gate -> executor -> delivery`, with HIL for anything
high risk (see [risk-classification.md](../decisioning/risk-classification.md)). Chat and the
console remain read-only surfaces; a proposal is a link to a PR, never a button
that mutates.

Example: "fix the storage accounts missing a private endpoint" resolves to a set
of Findings; the twin opens one shadow remediation-PR per resource (batched under
the blast-radius cap), each with a rollback contract, and routes to HIL. Nothing
changes until a human approves.

### 5. Self-improving (static to living)

Questions are a discovery signal. A question the twin **abstains** on, or a
recurring question with no covering rule, is emitted as a candidate to the
autonomous rule discovery loop in
[architecture.instructions.md](../../../.github/instructions/architecture.instructions.md)
(the same loop that watches HIL patterns and overrides). The candidate carries
provenance and passes the standard quality gate before it can enter the catalog;
the twin never mutates the catalog directly. The knowledge surface therefore
tracks the estate instead of going stale.

The first design considered binding a model directly and using a lexical compiler when that model
was unavailable. That fallback would invent meaning and let presentation code become semantic
authority. The revised design exposes provider-neutral compiler and discovery seams, keeps the
default explicit unavailable, verifies every injected plan deterministically, and sends only a
question digest and abstention code to discovery. No raw question, decision, or mutation authority
crosses that handoff.

## Twin as simulator (what-if over the whole graph)

The per-action what-if verifier
([architecture.instructions.md](../../../.github/instructions/architecture.instructions.md#llm-quality-gate-required-for-t2))
predicts the effect of a single change. The twin generalizes it to the whole
graph: apply a proposed change to a **scratch projection** and evaluate the
consequences before anything touches the live estate. One simulation surface
serves all three verticals, which is why the twin simplifies rather than
complicates the design.

| Vertical | Simulation question | Answered by |
|----------|---------------------|-------------|
| **Change Safety** | what is the blast radius of this change? what breaks downstream? | traverse `attached_to` / `depends_on` from the changed `Resource`; report affected set + newly-violated rules |
| **Resilience (DR)** | does the estate meet target RPO/RTO? what fails over? | replay a region/zone-loss scenario against the twin; report resources without a recovery path and the projected RPO/RTO gap |
| **Cost Governance** | what is the cost delta of this change / this optimization? | apply the SKU/scale delta on the projection; report the projected unit-cost change |

- **Read-only and deterministic**: a simulation mutates only the scratch
  projection, never the live estate or the audit store. It is a T0-flavored pass:
  static graph evaluation resolves most of it; bounded read-only probes confirm
  the rest, exactly as [deployment-preflight.md](../deployment/deployment-preflight.md) does.
- **Shadow-first**: each simulation-derived finding ships in shadow mode and is
  promoted per the shadow-to-enforce rule only after its accuracy and
  false-positive rate are measured on the frozen scenario set
  ([goals-and-metrics.md](../architecture/goals-and-metrics.md)).
- **Fidelity-measured**: `core/assurance_twin/fidelity.py`
  (`SimulationFidelityLedger`) is the mechanism behind that promotion. It joins
  each **predicted** effect (cost delta, blast-radius count, RPO/RTO gap) with
  the **actual** observed outcome by a stable prediction id and accumulates
  per-predictor MAE, MAPE, and a within-tolerance rate. `is_reliable` turns
  those into a fail-closed promotion signal: a predictor below a minimum sample
  count or above a MAPE bar is not reliable, so the caller keeps it in (or demotes
  it back to) shadow. This stops an unmeasured what-if from acting as an oracle -
  a simulation that does not come true loses its enforce eligibility automatically.
- **Adaptive but promotion-gated**: `effect_model.py` evaluates no-op and action branches with a
  versioned active model while a separate challenger learns only from post-cutoff, scorable
  `ResponseOutcome` records. The scheduled growth job persists challenger revisions through
  optimistic concurrency. It never replaces the active key. Active/challenger divergence and
  evidence below `quasi_experimental` force review. `rca/temporal_causality.py` adds differenced,
  lagged correlation with optional confounder adjustment, reverse-direction checks, and multiple-
  testing correction; this observational path can reach only `predictive_precedence`, never an
  experimental causal grade.
  `runtime.py` loads active and challenger models for at most 32 current-state branches. Missing
  active models, low evidence, or divergence require review; the T1 caller remains abstained and
  sends the learned action through normal re-verification.

### Scalar feedback reliability

Scalar learning keeps the existing `ResponseOutcome`, StateStore model key, and active/challenger
reader. Execution acceptance, independently observed effect, authorization, rollback, and evidence
sufficiency stay separate. Only scorable observations of accepted, enforced actions with an
`auto` or `hil` decision and explicit `rollback_succeeded: false` can calibrate a challenger.
Approval refusal, shadow dispatch, unknown rollback, and unavailable observation are not failures
or rewards. The original authorization decision is preserved rather than derived from effect
verification. A verified effect window does not establish sustained recovery or absence of side effects.

`ResponseOutcome` 1.1 adds predecessor-bound outcome revisions, an immutable prediction snapshot,
and observation unit and receipt references. Version 1.0 keeps its original wire shape and remains
audit-readable, but a business acceptable range is not a point prediction and cannot calibrate a
model. The snapshot records the exact action, event, target, predictor version/digest, unit,
independence key, source digest, knowledge time, point estimate, interval and nominal coverage.
Its logical action/prediction identity and content-addressed projection commit together with audit
before dispatch. A missing snapshot, wrong unit/predictor, absent observation receipt or unavailable
current-revision source makes feedback ineligible, never an inferred success or failure.

The model row carries a versioned feedback checkpoint: a fixed initial learning cutoff, at most
256 digest-only episode receipts, and an optional hold reason. Model parameters, receipt, and audit
commit in one revision-checked transaction. Exact replay after a lost response is a no-op; an
uncommitted write remains retryable. Different events with equal or out-of-order recording times
are eligible after the fixed cutoff. The model's knowledge time never moves backward and includes
the processing clock. One authoritative independence key contributes at most one sample to an
action/metric model. The learner does not invent that key from resource names or confidence.
Registered seed parameters and the applied outcome order are retained; model projections carry a
content checksum so detected corruption cannot silently become a prediction.

Changed content for an applied version, reused identity, or a correction holds the challenger
instead of adding another sample. A bounded rebuild validates complete predecessor chains and
replays latest eligible observations from the exact registered seed, preserving applied episode
representatives and order. The reviewed manifest binds every seed fact and input revision. Old
generations, replacement, and audit commit atomically. Rebuild admission, source currency and
prediction retention are required; unknown-only inputs cannot reset a model into apparent
readiness. Legacy nonempty models without attributable seeds/receipts remain held. Receipts are
never evicted to make old feedback look new. These are additive JSON projections, not a database
migration. The rebuild has a 1,024-record resource limit, not a statistical evidence threshold.

The Dynamic learner retains its own audit-source watermark, independent of pattern growth.
Unregistered challengers, contention, and unavailable checkpoints abort the batch with an attributed
audit reason before that watermark advances. Earlier committed updates are deduplicated on retry.
The CLI exposes independent `dynamic-learning`, `pattern-growth` and `graph-dynamic` consumers.
The scalar consumer and configured runtime now bind a read-only PostgreSQL revision source to
their owning audit DSN. Version 1.1 audit projections retain a recomputable outcome digest for
lookup without changing the response contract. Witness lookup and complete per-outcome history
share one repeatable-read snapshot; invalid, missing, future, superseded or incomplete chains
withhold learning and learned-model reads with explicit diagnostics.

`dynamic-rebuild` uses `FDAI_EFFECT_REBUILD_ACTION_TYPE` and `FDAI_EFFECT_REBUILD_METRIC` to preview
the exact retained seed and applied replay order. It reports the deterministic manifest for
independent review, requires an exact existing decision-evidence admission, then commits only the
challenger and retained previous generation. An absent review returns a failing status without
changing the model; a repeated completed request is a no-op. This command does not issue approval.
Review-required output is an explicit JSON subject with false authority flags. The packaged
rebuild utility is local-venue only: a deployed venue is refused before database or admission
access until its private, venue-approved admission provider is explicitly composed.

The compatible `growth` command reports known stage failures without discarding successful
independent stages. Pattern growth retains only bounded source references while holdout is pending,
revalidates source evidence after restart and reserves run budget for fresh intake.
Retry order advances durably before blocking work, even with a fixed clock. Already-owned source
rows complete their handoff without consuming fresh processing budget. Its configured
pattern-library DSN, not an unrelated state-store DSN, selects the write target. Cross-database
model/vector writes are idempotent handoffs, not one distributed transaction.
Explicit destination configuration is honored; legacy unset behavior is retained and is not a
claim that every deployment already has matched read/write configuration.

The design rejects a timestamp-only cursor as proof of processing and rejects a second database or
new reward model as unnecessary. Review identified two extra requirements: preserve a fixed seed
cutoff rather than accepting preexisting training data, and fail closed on correction or checkpoint
exhaustion rather than silently discarding deduplication evidence. Local evaluation freezes active
and challenger predictions before independent fixture outcomes, then reads the persisted challenger
through `DynamicRuntimeCoordinator`. It reports error and interval coverage separately, grants no
promotion, and is regression evidence rather than operational or cross-environment qualification.

Configured scalar simulation has one cooperative total deadline across request and model I/O.
Startup checks the complete same-revision model body and binds an evolved challenger's configured
origin to its retained immutable seed. Source outages cannot skip lineage validation; unsupported
legacy ancestry requires reviewed recovery rather than an inferred model relationship.
A missing or held challenger cannot remove a configured guard: the result stays unavailable for
review rather than silently accepting the active model alone. The default-off T1 eligibility
comparison records baseline and bounded challenger results with false authority flags; it never
changes actual selection. Prequential scoring uses frozen predictions, independent episode groups
and separate error, coverage and interval width. It does not measure a new policy's recovery rate.

> **Incomplete delivery:** authoritative current-revision/rebuild proof bindings, prediction and
> generation retention qualification, qualified Pattern-to-T1 enrollment with baseline-isolated
> shadow storage, paired operational evaluation, and target-specific runtime receipts remain open.
> Their absence is not replaced by an accepting stub. No production activation, completed
> whole-scope Low-only hardening claim, publication or merge is implied by this local checkpoint.

The installation-owned coherent retained-pattern issuer and independently measured operational
effects are tracked in #2194. They are prerequisites, not inferred from local fixtures or a merged
source change.

### Operational binding and guard

`FDAI_DYNAMIC_CONFIG_JSON` enables scalar Dynamic in a deployed core runtime. The strict object
contains ActionType-specific metric, objective, effect delta, uncertainty, divergence, and
freshness settings; exact active and challenger model records; and a causal-receipt digest
allowlist. Startup rejects partial fields, unknown fields, missing model pairs, conflicting durable
models, or a model whose receipt isn't allowlisted. Without this setting, Dynamic remains explicitly
unavailable and existing deterministic routing is unchanged.

The Azure adapter reads `operational_context.metric_values` from promoted inventory evidence and
builds one bounded action branch. The active and challenger models come from the durable StateStore
registry. A configured Dynamic simulation becomes a lower-only guard before T1 reuse enters the
safety check: unavailable requests, missing models, divergence, graph review reasons, invariant
failure, or missing Dynamic audit evidence route to human review. A prediction never approves an
action or raises its autonomy ceiling.

### Graph-wide temporal Dynamic

The existing action/metric model remains the first Dynamic layer. Graph-wide simulation extends it
with `OperationalStateTrajectory`, `GraphEffectModel`, `DynamicInvariant`, and
`TrajectoryOutcome`. A trajectory pins the ontology release, graph and inventory revisions,
evidence cutoff, horizon, normalized object/metric slices, intervention references, watermarks,
completeness, truncation, and a deterministic digest. It is not the conversation and execution
`TrajectoryEnvelope`, and neither record is evidence of provider state by itself.

Graph propagation follows only declared LinkType paths under fixed edge, depth, slice, and horizon
bounds. Deterministic topology effects run before verified active models. Interaction terms prevent
parallel action effects from being treated as a linear sum. A missing model, stale cutoff, cycle,
unavailable baseline, truncation, low causal grade, or active/challenger divergence requires review.
Challenger predictions never rank a branch.

Every graph simulation request carries a non-empty bounded invariant tuple. The simulator evaluates
each invariant over the active trajectory and returns the exact per-invariant result. A violation or
unscorable invariant adds a stable review reason and cannot raise authority. During execution, an
observed invariant violation cannot rewrite a running plan; it stops forward dispatch and re-enters
the existing typed recovery path.

The graph runtime records the predicted digest, exact trajectory, and challenger model references
in the StateStore trajectory ledger before returning simulation evidence. Heimdall's complete independent observation closes the episode
through `close_trajectory_outcome` as matched or mismatched. Identity mismatch, censoring,
incompleteness, and unscorable comparison leave it open and never update a model. Identical closure
replay is a no-op; conflicting replay fails closed. The off-path graph closure runner builds learning
observations only for complete comparable challenger slices and applies them through
`StateStoreGraphEffectModelRegistry`. Active graph models remain immutable until separate reviewed
promotion evidence applies. The scheduled growth job uses `MetricGraphTrajectoryOutcomeSource` to
observe due open episodes through the configured metric provider after the telemetry grace window.
It emits a closure command only when every predicted slice has independent finite evidence;
otherwise the episode remains open without a fabricated value.

`GET /dynamic-assurance` is a Reader-only durable projection over scalar and graph model
counts, sample and error summaries, and open or closed trajectory episodes. It exposes no model
registration, promotion, approval, or execution command.

## Assessment report (subscription posture, on demand)

The proactive per-change review composes into a full-estate report. Running every
applicable rule against the current twin produces a `PostureAssessmentReport` - a
generalization of the `DeploymentReadinessReport`
([deployment-preflight.md](../deployment/deployment-preflight.md)) from a single deploy to the
whole subscription. Each entry keeps the same three required parts - grounded
evidence (a cited rule), a severity, and a resolution mapped to a concrete lever -
so the report is actionable, not just a score. The console renders it through a
read-only `ReadPanel` route
([project-structure.md](../architecture/project-structure.md#injectable-seams)); it issues no
privileged calls.

### Deep security assessment

The security-scoped report keeps more context than a severity-only finding
list. Collectors normalize Azure Resource Graph properties, server parameters,
Defender assessments, WAF records, policy compliance, diagnostic settings, and
version/advisory matches into `SecurityControlObservation` values. Each
observation records the current and expected values, control status,
applicability, source and collection time, evidence references, remediation and
validation steps, priority and due interval, CVE applicability and patch state,
compliance mappings, and managed-service patch notes.

Applicability is a bounded enum (`applicable`, `not_applicable`, `unknown`) and
observation timestamps are timezone-aware. An `unknown` control is an evidence
gap, not an actionable recommendation. Recommendations are derived only from
failed or warning controls with grounded remediation text.

The assessment records which source supplied each fact:

| Source data | Information extracted |
|-------------|-----------------------|
| Azure Resource Graph resource properties | AKS version, private API, RBAC, network policy, Entra/local-account state, workload identity, image cleaner, add-ons, upgrade channels; MySQL network, backup, HA, encryption, and version |
| Azure Resource Graph `sku` and `kind` | AKS and MySQL service tier and resource kind |
| AKS node-pool resource properties | Node image version, secure boot, and virtual TPM |
| MySQL server parameters | Secure transport, allowed TLS versions, and audit logging |
| Azure Monitor diagnostic settings | Whether approved platform logs and metrics are routed to an evidence store |
| Defender for Cloud assessments | Runtime protection coverage and actionable unhealthy findings |
| Application Gateway WAF logs | Matched/blocked rules, attack details, resource, and event evidence |
| Security bulletins and advisory matches | CVE id, applicability, patch state, source URL, and managed-service backport note |
| Rule and compliance metadata | Expected value, rationale, remediation, validation, priority, due interval, and compliance controls |
| Report-feed timestamps and source errors | Evidence window, source availability, partial reads, and freshness gaps |

After an observed ARG or ARM inventory snapshot is promoted, the inventory job
reads only the active AKS, node-pool, and MySQL records under a bounded row cap,
runs the deterministic Azure analyzer, and writes timestamped control signals to
the durable report feed. Supplemental providers can add server parameters,
diagnostic-setting state, Defender coverage, and advisory matches. When they are
not configured, their controls and source coverage remain `unknown` or
`unavailable` instead of failing the control.

`build_security_assessment` remains a pure deterministic fold. It derives the
verdict and also reports:

- finding, rule, resource, resource-type, control, and evidence counts;
- pass, fail, warning, not-applicable, and unknown control counts;
- control pass rate, evidence coverage, and source coverage;
- category and resource-type distributions;
- positive controls and unknown controls;
- prioritized recommendations with due timestamps and validation steps;
- CVE applicability, patch status, and compliance mappings;
- available, partial, unavailable, and stale data-source counts.

A `clear` verdict describes the observed risk only. It does not imply that the
assessment is complete. `completion_status`, source coverage, stale sources,
unknown controls, and missing evidence stay visible so an unavailable provider
cannot turn into a false clean result.

The read-only `Security Assessment` catalog report renders these projections
through the existing Reports page. It uses KPI, control-status, chart, table,
group, tabs, and note widgets, so no new browser execution surface or
privileged identity is introduced.

## Module placement

The subsystem lives in `core/assurance_twin/` and imports only `shared/`
contracts and providers, like every other core subsystem
([project-structure.md](../architecture/project-structure.md#module-boundaries)). It holds no
cloud SDK and no privileged identity.

| Component | Responsibility |
|-----------|----------------|
| `projection` | Build immutable in-memory baselines and apply scratch diffs. A read-only retained Inventory snapshot and bounded realtime Resource overlay can supply one fresh projection; runtime composition and relationship-aware maintenance remain target bindings. |
| `query` | Verify and execute well-typed read-only queries with a deterministic pattern compiler. A model-backed compiler is a Protocol target. |
| `review` | Publish precomputed findings through `IacReviewPublisher`. Change-signal evaluation and a production publisher are target bindings. |
| `report` | assemble the `PostureAssessmentReport` from Findings |
| `chat` | Provide immutable grounded chat-session values and a persistence Protocol; no browser or delivery binding. |
| `graph_effect` / `graph_runtime` | Propagate bounded graph effects, evaluate required active-trajectory invariants, and return review-only simulation evidence. |
| `trajectory_ledger` | Persist predicted trajectory episodes and atomically close only complete comparable outcomes through StateStore. |
| `graph_closure` | Drain independent observations off-path, update challenger slices, and audit that active mutation and promotion did not occur. |
| `typed_proposal` | Define content-addressed typed ActionType proposals, what-if results, and the retained typed-proposal readback that Forseti's writer re-validates. |
| `proposal_effects` | Resolve an exact reviewed ActionType effect model and derive the predicted scratch change for the proposal's retained targets, or return an explicit unavailable reason. |
| `posture_activity` | Build Heimdall's existing bounded posture activity and Forseti's separate private, authority-free review activity. The delivery recorder stages each with its retained record and Saga-attributed append-only audit; two supervised relays publish revision-bound envelopes. An injected trusted source is still required to compute findings. |

`PostgresTwinInventorySource` loads the active observed, full-scope snapshot from the retained
Inventory database in a repeatable-read transaction. It rejects stale, incomplete, or superseded
coverage, limits baseline Resources and realtime deltas, and refuses pending relationship changes
that the Resource-only scratch projection cannot represent. Heimdall's production posture producer
reuses the control loop's immutable T0/OPA generation off the event-loop thread, requires every
Resource's declared Rule inputs and receipts, and holds Inventory promotion and realtime graph
locks through source persistence and writer confirmation. Forseti's review producer shares that
Inventory source and T0/OPA generation. It reviews only typed ActionType proposals from the durable
intake and only through reviewed effect models; an empty catalog keeps every proposal unavailable
rather than turning an unassessed change into a misleading `clear` verdict. An Inventory snapshot
id by itself is not the exact revision that either producer requires.

Target delivery adds one intent to the existing `chatops` adapter (question in, grounded answer
out) and reuses the `gitops-pr` adapter for proposals and Checks API reviews. The current
repository has only the `IacReviewPublisher` Protocol and test double, not a production publisher
or ChatOps binding. Adding them doesn't introduce a new privileged surface.

## Safety posture

- **Read-only twin, gated execution**: the twin and every answer are read-only;
  the only path to a mutation is a proposal that enters `risk-gate -> executor`,
  with the seven safeguards (stop-condition, rollback, blast-radius limit, dry-run, resource lock,
  idempotency, audit entry) enforced there, not in the twin.
- **Fail closed**: an ungroundable answer abstains; a mis-typed or non-read-only
  compiled query is rejected; a stale twin (`Inventory` freshness beyond
  `freshness_ttl`) refuses to answer estate-state questions rather than answer
  from ghost data, mirroring `RequiresInventoryFresh`
  ([llm-strategy.md](../architecture/llm-strategy.md)).
- **Untrusted input**: question text and change payloads are untrusted and may
  carry prompt injection; the verifier and the read-only query contract are the
  authority, never the model's free text (threat model in
  [security-and-identity.md](../architecture/security-and-identity.md)).
- **Audited**: every proposal, review, and simulation-derived finding writes an
  audit entry with its grounding; a read-only question that produces no proposal
  is logged but is not an action.

## Phasing

The twin lands incrementally on top of the existing phases; it introduces no new
tier and no new autonomy that the risk gate does not already govern.

| Phase | What lands | Gate |
|-------|------------|------|
| **P2** ([phase-2-quality-and-t1.md](../phases/phase-2-quality-and-t1.md)) | twin projection from inventory; verified text-to-query; grounded answers via the quality gate; abstain-to-discovery feedback | answers are grounded or abstain; zero ungrounded answers on the scenario set |
| **P3** ([phase-3-integrated-loop.md](../phases/phase-3-integrated-loop.md)) | ambient per-change review; whole-graph simulation for Change/DR/FinOps; shadow remediation-PR proposals; `PostureAssessmentReport` panel | each simulation finding measured shadow-first before enforce |

## Next steps

| To learn about | Read |
|----------------|------|
| the ontology the twin queries | [llm-strategy.md](../architecture/llm-strategy.md#ontology-foundation) |
| the tiers and quality gate answers route through | [architecture.instructions.md](../../../.github/instructions/architecture.instructions.md#llm-quality-gate-required-for-t2) |
| the deploy analyzer the report generalizes | [deployment-preflight.md](../deployment/deployment-preflight.md) |
| detection findings the review consumes | [observability-and-detection.md](../rules-and-detection/observability-and-detection.md) |
| where the subsystem sits in the repo | [project-structure.md](../architecture/project-structure.md#module-boundaries) |
| how proposals are risk-classified | [risk-classification.md](../decisioning/risk-classification.md) |

## Related docs

| To learn about | Read |
|----------------|------|
| Delivery status and remaining work | [Implementation ledger](../../roadmap-implementation/operations/assurance-twin.md) |
