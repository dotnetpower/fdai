---
title: Narrator Routing and Latency
---
# Narrator Routing and Latency

This document owns deployment selection, latency measurement, operator preference, and public-web
pool behavior for conversation presentation. It separates T1 lightweight authorship and independent
review from system-governed T2 reasoning.

> **Delivery status:** Core-owned mini routing is implemented with passing focused checks. Local
> synthetic probes and authenticated Console DOM evidence are recorded below; integrated runtime,
> visual interaction, and whole-turn latency validation remain partial. Probe timings do not prove
> faster conversations.

## Narrator latency routing
Test-context lifecycle submission is deterministic Console workflow, not narrator routing. A semantic draft may open the form, but server-owned choices and Operator/Core lifecycle checks decide every accepted command.
The Outcome Assurance read panel is also outside narrator routing. It decodes an authenticated
read-only KPI projection and does not select a model deployment, submit a semantic request, or
create latency evidence.


The independent Operator Service owns the authenticated conversation HTTP boundary and relays
semantic turns over Kafka. Core owns model selection and inference in the standard local and
deployed semantic path. Neither the Operator nor the Console selects a deployment from operator
text, receives execution authority, or treats model availability as verified operational evidence.

Core verifies the configured model audiences through a separate bounded readiness path. If model
identity is unavailable, semantic transport remains active and returns a typed authentication hold
before planning; it does not fall back to lexical routing or borrow the Operator HTTP identity.

The [alert-quality API](../operations/alert-noise-governance.md) accepts explicit typed
`alert_noise.assess` and `alert_noise.propose` requests, not a conversational routing shortcut.
Its deterministic assessment adds no lexical intent branch or T2 fallback. Natural-language meaning
still requires semantic judgment; neither a typed request nor narrator text grants action authority.
Its isolated browser tests inject a test-only identity and intercepted API records, not a narrator
or provider. Their timing and screenshots establish UI mechanics only, never live model latency.

### Core-owned mini candidate selection

Core reuses the verified narrator candidate pool and admits at most four mini candidates. Exact
resolved deployment metadata establishes each candidate's identity, publisher, family, and provider
binding. Deployment names are not evidence of family or capability. Held or unverified targets are
excluded; the probe cannot discover, provision, or add a target.

Each candidate keeps a rolling window of at most eight successful probe durations. Only samples
newer than twice the configured probe interval contribute to p50 (the median) and p95. Fresh
measured candidates rank by p50; stale or unmeasured candidates retain configured fallback order
without a fastest-model claim. A failed target is excluded until a later successful probe.

Normal adaptive T1 planning and answer stages use the selected author; review and verification use
an independent eligible mini from the same pool. If no independent pair remains, the adaptive path
stays unavailable rather than using the author as its own reviewer. A model factory freezes one
immutable selection per turn, shared by every stage and deferred work. Later probes affect later
turns only. Disabling probes preserves the configured model selection and makes no measured-speed
claim.

### Billed probe limits

`FDAI_T1_MINI_PROBE_ENABLED` defaults to `0`. Set it to `1` only after explicitly authorizing billed
synthetic model requests, including in a local profile. This setting is a spending opt-in ceiling,
not approval for resource actions, T2 use, or unrestricted model calls. Selecting a local execution
venue does not enable probes automatically.

| Limit | Value |
|-------|-------|
| Probe interval | `FDAI_NARRATOR_PROBE_INTERVAL_SECONDS`: default `300` seconds, bounded to `30-3600` |
| Candidate requests per cycle | At most `4`, one per admitted mini candidate |
| Request content | Fixed synthetic request for exactly `OK`; no operator prompt, history, or tool evidence |
| Maximum output tokens | `256` per request |
| Request deadline | `8` seconds |
| Cycle deadline | `35` seconds, including projection publication |
| StateStore write deadline | `5` seconds per publication |
| Successful sample window | At most `8` per candidate; freshness is `2 * interval` |

Core runtime supervises one immediate cycle and subsequent periodic cycles without overlap.
Initial projection publication failure propagates before any probes start. Publication failure
during a cycle is logged without retry; the write also remains inside the cycle deadline.
Shutdown cancels owned work. An HTTP `429`, HTTP `503`, provider timeout, or cycle deadline ends
that cycle without retrying the same request or substituting T2. Only a later scheduled cycle can
measure again. After credential acquisition, the fixed synthetic `OK` request starts its model timer, consumes raw bytes under the response and line budgets, accepts choice-free `prompt_filter_results` or `prompt_annotations` metadata and passing content-filter annotations without a `delta`, stops reading at `[DONE]`, and records time to first non-empty token (TTFT) separately from total latency. It does not measure answer quality or end-to-end conversation latency. Operator recomputes p50 and p95 from each bounded history and rejects a projection when any paired TTFT exceeds its total latency; Console repeats the TTFT quantile and pair checks before display.

An explicit capacity benchmark requires the same billed-probe opt-in and reuses the exact same
request body and selected mini deployment. It runs 1 to 16 samples at concurrency 1 to 4, changes no
deployment, SKU, TPM, or provider state, and stops after the first wave containing `429`, `503`,
timeout, transport, identity, or malformed-output failure. Its receipt contains only bounded timings,
counts, status, deployment label, and fixed no-authority and no-capacity-change fields.

### Read-only health projection

Core is the single writer of the versioned `conversation:t1-mini-routing:v1` StateStore projection.
It contains sanitized deployment labels, selection reason, candidate timings and status, and
freshness bounds with `execution_authority=false`. It contains no endpoints, credentials, operator
content, or shared workflow authority.

Operator reads this projection only after bounded shape and freshness validation and uses only
`model` and `router` to enrich `/chat/health`. The response envelope can also carry binary documents
or no body, so the health reader accepts unknown input and rejects every non-object value. Missing,
invalid, or expired routing data cannot change semantic transport availability or manufacture a
healthy model. Health availability remains the semantic bridge's transport readiness, not a
successful inference or verified answer.

When `FDAI_SEMANTIC_AUTHENTICATION_RECEIPT_REF_ENABLED` is on, each semantic turn first performs one
bounded PostgreSQL insert of its content-free authentication receipt (10-second connect and
20-second statement limits) before the bridge accepts it. That write adds to turn acceptance latency
but does not change narrator routing, preferences, or health.

The Console keeps the persistent connection badge concise and places deployment identity and
candidate timing details in its tooltip. The tooltip distinguishes sample counts and measured,
stale, unmeasured, or failed status. An open, visible Command Deck polls health every 30 seconds;
the browser never runs a model probe. This read projection introduces no second writer,
cross-service implementation import, database data rewrite, or shared decision state.

### Unchanged boundaries and legacy narrator

The configured T2 primary (Sol where bound) remains an optional refinement stage and is neither
probed nor selected by mini latency. Its output still re-enters independent review. The operational
mixed-publisher T2 invariant and the configured `t1.judge`, `t2.critic`, and debate bindings remain
unchanged. Extending latency routing to those roles requires separate design review; the reviewed
T2 primary exception remains owned by
[LLM strategy](../architecture/llm-strategy.md#t2-primary-routing-and-governed-recovery).

`LocalAzureNarratorAdapters` is the separate legacy local narrator, not the semantic Kafka path.
Its ordered fallback, text/vision probes, rolling p50/TTFT windows, failure penalties, and
Operator-owned periodic scheduler do not implement Core mini routing. Do not enable the legacy
narrator alongside semantic Kafka to obtain model measurements. The adapter invokes its injected
HTTP stream with an explicit `POST` method. It skips answer-free Azure prompt-filter, passing
content-filter, terminal-stop, and usage metadata frames, while malformed or oversized data still
fails closed. Provider-status and malformed-frame warnings are bounded and contain no prompt,
endpoint, token, or response body. Its bounded system prompt states FDAI's product scope and treats
FDAI as a product name rather than inventing an acronym expansion. Image turns remain unavailable
without a server-owned resolver from an opaque conversation-image id to validated bounded bytes;
client-provided image fields cannot supply that authority.

## Interactive semantic-planning latency

Interactive questions still require schema-validated model meaning before Core selects a
capability. A provenance-bound compact preflight can provide candidate meaning only for three
reviewed F1-F4 shapes; every other request retains full semantic judgment. When accepted meaning
contains an unambiguous read intent for a
bound Resource state, Resource Health, or Service Health function, Core builds the typed frame
deterministically and skips the second frame-model call. The exact function must exist in the
principal-scoped manifest, and the normal verifier, evidence execution, and answer checks still run.
Novel, ambiguous, action-related, or unbound questions keep the general frame-planning path.
Provider calls use strict structured output instead of a free-form JSON object plus a repeated
textual schema. Compact preflight now runs on the first turn before adaptive planning. Explicit and
contextual operational signals enter verified semantic planning directly, while mixed signals retain
adaptive goal separation. Accepted operational diagnostic intents use at most five reviewed
descriptors and a 544-token operational frame prompt; their schema-inclusive request cannot exceed
64 KiB. Direct-response candidates still require the independent preflight before any social answer
is rendered.

Resource-state inventory meaning has one mandatory independent T2 review after T1 judgment. It
adds one bounded model call only for that read family and requires a distinct model instance and
configuration digest. It is not aggressive recovery: disagreement or reviewer unavailability holds
the request instead of producing a new plan, and the T1 proposal remains the accepted identity when
both judgments match.

The standard local stack multiplexes logical semantic and agent topics over one physical Kafka
topic. Its PLAINTEXT consumer applies the same bounded record-count and elapsed-time commit policy
as the cloud SASL consumer. It never pays one broker commit for every unrelated physical event, and
it still commits only after the caller resumes from a successfully processed envelope. Closing or
failing mid-processing preserves at-least-once redelivery.

Warm standard Browser Entra measurements reached 3.810 seconds for one F1 answer token and 4.254
seconds for one exact F2 answer token. Both used one preflight model call. These samples do not
qualify the SLO distribution. F1 still lacked its requested document, and targetless F3/F4
clarifications emitted no answer token. Core restart readiness now waits for both a post-launch
semantic logical consumer and a fresh Pantheon heartbeat. A retained restart emitted `ready` after
both markers, and its first exact F2 request emitted an answer token in 3.948 seconds.

Console starter questions expose only this contract-covered function-backed set. They ask for
current server-owned evidence instead of browser-authored screen summaries, tier estimates, pending
decisions, or cost opportunities that the semantic runtime cannot yet prove. The question-bank
inventory records the bilingual wording, typed intent, retained evidence source, and focused
contract validation for each visible starter.

Aggressive T2 recovery defaults off in every environment. Owners can enable one audited bounded
recovery experiment, but an interactive request never receives T2 merely because it runs in a
development process. Model transparency records every completed semantic judgment, frame, and plan
model call with its measured duration and token usage when available. The end-to-end turn timing
continues to include deterministic and provider work that is not a model call.

### Single-meaning read admission

In the existing typed-only development path, a released read compilation may replace the
parallel capability-named judgment only when the form proposer and its blind independent
constraint reader both explicitly classify the request as a direct read. Missing, quoted,
hypothetical, action-related, or disagreeing classifications retain the existing judgment
path. Bound investigations, resource contexts, and required-document turns are excluded.
Principal and purpose checks run before either path; fresh plan verification and all
constraint, catalog, reference, and evidence checks remain mandatory. Critique rejected using
preflight confidence as authority or simply consuming a compiled ticket earlier: neither proves
discourse or preserves action-draft handling.

### Turn-local semantic work optimization

Typed-only planning skips legacy subtype grounding because that mode never consumes a legacy
plan. The released question-form path still performs complete-catalog grounding, independent
review, and fresh plan verification; an unavailable compiled path remains held.

Within one question-form run, a schema-valid concept choice may be reused only for the exact
utterance, mention payload, original shard digest, and reader identity. Primary and independent
readers have separate entries. Failures and malformed choices are not cached, returned values
are copied, and the cache ends with the run. It stores no provider observations, resource state,
authorization decisions, or cross-turn meaning. Call accounting counts provider invocations,
not cache reads.

Concept prompts represent every candidate as a row under explicit `id`, `values`, and `labels`
columns. This lossless encoding removes repeated field names, not candidates or context. Safety
scanning, shard hashes, exhaustive presentation receipts, and closed output schemas still use
the original complete catalog. Local reconstruction and call-count tests prove these mechanics;
they do not establish a live latency or billed-token reduction.

Candidate references in model input are shard-local opaque positions. The adapter converts only
presented references back to canonical candidate ids under the original shard digest and refuses
foreign references. Shards account for their complete transmitted representation, including
headers; every candidate remains represented once, and an oversized candidate holds the stage.

Each blind reader executes complete shards in waves of at most two concurrent calls, preserving
ordered receipt accounting and the existing call budget. A failed or cancelled wave cancels and
drains its other calls before the stage ends; finalists and bounded repairs retain their gates.
Independent finalist runoffs use the same two-call waves only after their total fits the
remaining reader budget. Answers retain request order and each mention's exact candidate
boundary. This removes serial finalist waits without claiming measured end-to-end savings.

### Operator timing and token accounting

The Command Deck work record separates server elapsed time from cumulative model-call duration.
Parallel call durations are summed in the latter, so it may exceed server elapsed time. An
observed transcript interval remains labeled separately when server timing is unavailable.
Input, output, and total tokens are displayed independently. A missing split stays unrecorded,
never zero. Exact call counts use a captured trace, including omitted calls, or complete
server-owned turn-budget accounting; an incomplete budget never becomes an exact count.
These displays require no prompt-content capture, new model request, or execution authority.
The existing numeric usage map also carries recorded model-call count without detailed trace
capture. Local development diagnostics retain bounded per-call durations and input/output token
counts for grounding as well as their grouped summary; omitted call details are counted explicitly.
Neither diagnostic capture nor a missing usage field manufactures token or billing evidence.

### Bounded optimization evidence (2026-10-02)

The first exact-source reevaluation on `e5c82e7e4f` made four fresh first-turn database list/count
requests in English and Korean. Three answered with consistent verified claims and incomplete
source evidence; the English count held on independent `resource_class` concept disagreement.
No failed case was counted as success. The identical Korean list used 26,428 total tokens and
10,535 ms server time versus the retained 49,105-token, 10,807 ms baseline.

After bounded two-shard concurrency, the final source `66a49cb735` answered one additional list
pair with 5/5 supported claims. Korean used 25,673 total tokens and 13,374 ms; English used
26,405 tokens and 8,367 ms. The preceding serial English list took 14,141 ms. Input token
reduction is supported by turn metadata, and content-free decision traces confirmed zero
duplicate capability judgments. Korean wall time regressed, so no uniform speedup, monetary
saving, latency distribution, or SLO qualification is claimed. Evidence snapshots changed over
time and provider latency was not controlled. Final focused runtime checks passed 918 cases;
Console accounting checks passed 66 cases. No provider failure was retried.

### Speculative form start and single-shard concept catalogs (2026-10-06)

A content-free trace of one Korean resource-group list showed that semantic planning took
8.82 s of 9.06 s, while the ontology read took 180 ms. The preflight, question form, concept
selection, and finalist runoff ran as four serial model stages of about 1.6 to 2.7 s each. The
runoff exists only because the resource-type catalog spanned two 12 KiB shards that were judged
independently, and a third shard, such as a region catalog, added a second chooser wave.
Repeated identical prompts already reported 2,304 to 5,760 cached prompt tokens without shorter
calls, so prompt-cache ordering wasn't pursued.

Two local settings change the form path's timing without changing what it reads or verifies.
Both apply only where compiled answers are enabled in the local venue, and the local launcher
enables both:

- `FDAI_SEMANTIC_CONCEPT_SHARD_BYTES` bounds a concept shard between 4 KiB and 64 KiB, with
  12 KiB as the default. At 32 KiB, the resource-type catalog fits one shard. Every candidate is
  still presented once with a presentation receipt, and both blind choosers still run.
- `FDAI_SEMANTIC_SPECULATIVE_FORM_START=1` starts the form path in a worker thread when the turn
  begins, beside the preflight, for a turn without a bound incident, investigation, resource
  context, or document evidence. The preflight keeps its routing authority. The planner adopts the
  ticket only for the first verified read of the same question and consumes it at the same point
  as before. Every other route cancels it when the turn ends.

Core diagnostics now record each call's start offset and provider-reported cached prompt tokens.
The cached count stays out of the model trace and wire usage.

The authenticated local Console sent the same two Korean questions through new conversations on
the same source, five list turns and three count turns per variant. Server processing time:

| Variant | List, answered | List, held | Count, answered |
|---------|----------------|------------|-----------------|
| Baseline | 10.0, 10.2 s | 15.3, 16.4, 18.2 s | 11.7, 15.4, 27.4 s |
| 32 KiB shards | 7.7, 10.9 s | 11.7, 12.4, 12.8 s | 7.2, 8.1, 9.2 s |
| 32 KiB shards and speculative start | 5.0, 5.3, 11.9 s | 7.7, 10.4 s | 5.4, 6.3, 9.9 s |

With both settings, the form and constraint reader started 26 to 31 ms after the preflight
instead of after it. The concept stage ran as one wave without a runoff. A direct answered list
fell from 8 model calls and about 22,300 tokens to 5 calls and about 20,500 tokens. Answers
matched the baseline: 19 rows for the list and a count of 49. The longer answered turns in each
variant came from a second form pass.

The held list turns came from the question form reading the name fragment as a value
(`anchor_form_unsupported:value`), plus one `anchor_not_found:m1` clarification. Neither setting
changes that reading. The samples are small, provider latency was uncontrolled, and cached
identical prompts favor every variant equally. No latency distribution, SLO qualification, or
monetary saving is claimed.

## Synthetic chat and prompt inspection

The [Command deck](../../../mocks/ui/deck.html) mock keeps conclusions, evidence gaps, and
investigation records inside the assistant reply for every response form, including its incident
and change forms. Investigation completion is distinct from incident recovery; cancellation
preserves only the work already shown. When trace capture is on for a turn, each model call in the
run record exposes
[`system-prompt.example.md`](../../../mocks/ui/assets/prompts/system-prompt.example.md) inline
under its dynamic system prompt, without a modal or blocking the composer. It supports read-only
Markdown, copy, and download. Missing captures and failed loads remain explicit, and closing the
file cancels its pending load. The file is a public synthetic fixture, never a captured runtime
prompt. These presentation studies do not change production prompt capture, permissions, or model
routing.

## Per-user preference and TTFT

The target Settings > Models surface projects the resolved T1/T2 inventory, bootstrap state, and
runtime latency evidence without endpoints or credentials. Each authenticated principal can use
`Auto` routing or pin one deployment from the current narrator allowlist. Removed or unavailable
preferences fall back to `Auto`; the server rejects arbitrary model ids.

The Settings navigation prefetches this projection when the Models link receives pointer or keyboard focus. One authenticated API client coalesces overlapping reads and keeps only a successful projection in memory for 60 seconds. Explicit catalog refresh, conflict recovery, and reads after a settings mutation bypass or invalidate that cache. Browser storage and shared HTTP caches remain unused, and every server request still authenticates and authorizes the current principal.

Target preferences use explicit revisions. Creation sends revision `0`; later writes match the current
revision. State and audit commit in one transaction, so concurrent sessions receive `409` instead
of overwriting each other.

The target streaming router records TTFT when the first non-empty model token arrives. TTFT p50/p95 and
total-latency p50/p95 use separate rolling windows and include sample counts. Unmeasured TTFT stays unavailable. The account preference applies only to the T1 narrator. T1
internal judgment, embeddings, and all T2 secondary, critic, rubric, and escalation assignments
remain system-governed.

The Command Deck also provides a separate per-conversation model selector. `Auto` preserves the
normal deterministic-first route, `T1` prevents optional T2 refinement for that conversation, and
`T2` uses the active `t2.reasoner.primary` binding. A pure general-knowledge turn uses that T2
binding for one compact preflight that classifies and authors the bounded answer together. It does
not run adaptive plan, review, refine, or verify stages. Operational turns retain the verified T2
planning and evidence path.
The selected tier applies to new turns, is cached under the principal-scoped conversation key, and
is included in the no-authority semantic request. T2 is offered when the sanitized model settings
projection reports an active primary. The action-quality `quorum_ready` flag does not control this
conversation choice. Pure general advice has no action authority and does not invoke the operational
T2 quality pair. Operational T2 still preserves its separately configured independent reviewer.
The browser cannot submit an arbitrary deployment id, choose that reviewer, or change an in-flight
turn. An unavailable selected T2 produces an explicit held result instead of silently falling back
to T1.

Settings > Models also provides a T2 model-policy draft builder. The Operator API projects only
publisher and family preferences from `rule-catalog/llm-registry.yaml`. Operators can select
primary and secondary candidates only when publishers differ, then copy a validated YAML fragment
for a governance PR. The browser does not write the selection to runtime state. The active pair
changes only after catalog review, resolver regeneration, and deployment reload.

Local operator mode can combine the regional GPT catalog, subscription quota, and existing
deployments from the Azure CLI session. The asynchronous reader caches for five minutes and exposes
an explicit read-only refresh. It returns family, version, lifecycle, supported SKU, available
quota, and deployment names only. Deprecated chat, codex, and realtime families are not offered as
new T2 role choices. Selecting a model creates a governance draft; it does not mutate Azure.

The same page projects a sanitized endpoint inventory with capability, provider, direct or APIM
route, API style, deployment, family, capacity, features, discovery source, and verification time.
It omits endpoint references, auth audiences, resource digests, URLs, and credentials. Endpoint
registration, APIM changes, resizing, image changes, and T2 role assignment remain deployment or
catalog workflows.

## Conversational web-search latency pool

Public-web lookup is a separate Chat T2 tool invocation, not T1 judgment and not part of the action
quality-gate pair. When enabled, the Azure Responses `WebSearchProvider` uses the separate
`web_search_candidates` function-calling pool, selects the lowest rolling p50, and fails over
across the remaining candidates. The deterministic web-search policy promotes the turn before the
provider is called.

Local and deployed Operator API composition use the same provider-neutral resolver in
`application.conversation.capabilities.web_search`. Environment loading, resolved-model candidate
selection, and Azure construction remain in `adapters.conversation.web_search`. The resolver
receives only the server-owned allowlist and injected provider; operator text cannot choose an
endpoint, deployment, credential, or provider scope.

Local and deployed semantic turns also use the same logical request and projection names. When the
deployment multiplexes them over `fdai.pantheon.objects`, both modes use the same physical marker,
hashed consumer-group derivation, managed-identity transport, and shared physical DLQ behavior.

Local and deployed Operator API composition also exposes the same service-owned, authenticated,
read-only `/agents/activity` route from the frozen parity manifest. The route reads the durable
activity projection and carries no decision, approval, or execution authority.

The separate web-search pool retains its own warm-up and periodic measurement pattern. Its periodic probe asks
for a minimal model response without the `web_search` tool; actual searches add end-to-end latency
to the same window. `FDAI_WEB_SEARCH_PROBE_INTERVAL_SECONDS` defaults to `300` and cannot be below
`30`.

Settings > Models exposes deployment-wide web-search enablement and exact-host allowlists to
Owners. Writes use the same revisioned state-and-audit transaction and update the live resolver
after commit. Without a registered resolver, the projection reports unavailable and writes return
`503` before persistence. Configuration defaults alone do not prove provider availability.

The page also reports the generated resolved-model snapshot's sanitized filename,
`kind=generated-file`, and UTC modification time as `as_of`. It never returns the full local path.
Discovery and provisioning labels describe configured behavior; they do not replace freshness
evidence.

## Runtime delivery decisions

- **Resolved model delivery**: day zero supports a filesystem path or inline JSON environment or
  secret reference. The service-owned async Key Vault source adapter now validates official Azure
  vault origins and audiences, exact secret identity, size, JSON structure, enabled and expiration
  state, and a total deadline without exposing the value. Focused lifecycle composition constructs
  that source, and the application lifespan invokes one asynchronous owner to publish an immutable
  source revision to capability binding and lifecycle-hold evaluation before later services start.
  The local Azure narrator defers target construction until that owner publishes the revision;
  synchronous composition does not reread the file or inline source.
- **Local model fixture**: an Ollama or LM Studio fixture is not currently included. Any such
  fixture would be an explicit model binding and would not redefine the interactive local profile.
- **Reconciler delivery**: the weekly workflow retains sanitized evidence and opens an idempotent
  draft PR when review is required. It sends no Teams alert and has no activation authority.

## Qualification latency SLOs

The versioned `chatops-latency-v1` contract separates pull-request regression checks from live
canary and release evidence. Each stage has one owning environment, a minimum sample count, and
ordered p50, p95, and p99 ceilings:

| Stage | Environment | Minimum samples | p50 | p95 | p99 |
|------|-------------|----------------:|----:|----:|----:|
| Time to first token | `live_canary` | 30 | 1000 ms | 2500 ms | 5000 ms |
| Terminal answer | `release` | 500 | 8000 ms | 20000 ms | 30000 ms |
| Deterministic verification | `pr_regression` | 100 | 250 ms | 750 ms | 1500 ms |
| Channel acknowledgement | `live_canary` | 30 | 1000 ms | 5000 ms | 9000 ms |
| Complete delivery | `release` | 500 | 10000 ms | 25000 ms | 40000 ms |

Stage owners provide premeasured duration, timestamp-authority, trace, and provenance commitments.
The pure Core reducer computes percentiles and outcome counts for completed, corrected, held,
unsupported, fallback, truncated, and timed-out samples. A timeout, insufficient sample count, or
percentile above its ceiling fails that stage.
`LatencyStageReceipt` prevents a caller from submitting duration directly: the stage owner supplies
monotonic start and completion values, and the adapter derives milliseconds only after the
receipt's environment matches the installed stage contract.
Reduced latency and trace evidence revalidates stage order, contract floors and ceilings, pass and
gap consistency, and timestamp-authority presence. Qualification input `1.0.0` remains readable but
cannot clear the timing hard cap. Input `1.1.0` binds paired latency and trace-cohort content digests,
and scorecard `1.1.0` exposes the same pair for independent replay.

Run the repository benchmark adapter after collecting content-free samples:

```bash
uv run python scripts/evaluation/chatops_quality_latency.py \
  --input <latency-samples.json> \
  --output <latency-evidence.json> \
  --require-slo
```

The output hashes the run identity and the canonical sample manifest. It retains stage,
environment, percentile, sample-count, timestamp-authority, outcome-count, source-revision, and
contract evidence without exposing trace ids, provenance records, answer text, principals,
endpoints, or customer identifiers. This reducer never claims a complete correlation trace;
trace completeness remains an independent requirement.

The sibling `chatops_quality_trace.py` command validates the independent trace requirement. A
complete trace contains exactly one ordered commitment for session, request, turn, tool or agent
evidence, proposal, decision, delivery, and audit. Every event uses the same correlation digest,
links to its predecessor record, carries an authoritative timestamp and provenance commitment, and
falls inside the trace window. Missing, duplicate, reordered, cross-correlation, or broken-link
events keep `complete_trace=false`.

```bash
uv run python scripts/evaluation/chatops_quality_trace.py \
  --input <trace-commitments.json> \
  --output <trace-evidence.json> \
  --require-complete
```

## Local mini-routing evidence (2026-09-06)

The implementation session reported the following bounded evidence for the current change:

- **Focused checks:** Python: `229 passed`, two PostgreSQL cases deselected; six additional opt-in
  configuration checks passed. Console cohorts passed `147`, then `48`, then a final `160` cases.
  These cohorts overlap and are not additive. Final Console typecheck and production build passed.
- **Live synthetic probes:** The first two scheduled Core cycles completed eight mini probes without
  T2. The first selected `narrator-gpt-5-mini` at `843 ms` against `1288`, `1517`, and `2086 ms`.
  Cycles three and four switched the fastest selection to `gpt-4.1-mini`, with its latest observed
  p50 approximately `1068 ms`. These are synthetic probe timings, not whole-turn speed or quality.
- **Authenticated presentation:** General and screen-context Console DOM badges and tooltips matched
  the changed selection and measurements. Electron's hidden visibility still limits raster and
  pointer qualification; no visual pass is claimed.
- **Runtime provenance:** Operator ran from an isolated worktree based on committed `9ed204592`
  plus only five task-owned health files; `152` focused checks passed there. Its `auth.py` matched
  that baseline. Unrelated `auth.py` edits in the shared checkout reject the existing token without
  `idtyp`; this task left that source untouched. The isolated result does not validate the full
  dirty checkout. This task created no commit or push.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Speculative form start and single-shard concept catalogs | implemented | `semantic_runtime_speculation.py`; `semantic_planning_speculation.py`; `semantic_query_type_grounding.py`; `scripts/deployment/local/run-console-service.sh`; `test_semantic_runtime_speculation.py`, `test_semantic_compiled_planning.py`, and `test_semantic_query_second_reader.py` | Local compiled-answer turns start the form path beside the preflight and present a catalog up to 32 KiB in one shard. The preflight keeps routing authority, and every candidate is still presented once. See [the 2026-10-06 evidence](#speculative-form-start-and-single-shard-concept-catalogs-2026-10-06). |
| Turn-local grounding reuse and lossless catalog prompts | implemented | `semantic_planning.py`; `semantic_reasoning_shadow.py`; `semantic_question_form.py`; focused grounding, compiler, catalog, and masking tests | Typed-only planning avoids unused legacy grounding. Only exact, schema-valid same-reader concept choices are reused within one run; every catalog candidate and independent review remain required. No live speedup or billing claim. |
| Conversation time and usage presentation | implemented | `console/src/deck/conversation-trajectory-{presentation,view}.ts*`; `conversation-trajectory-presentation.test.ts`; bilingual performance cases in `conversation-entry.spec.ts` | Server elapsed and cumulative model time, input/output/total tokens, and recorded call counts remain distinct. Missing measurements stay unrecorded. Desktop, constrained desktop, and mobile synthetic checks pass. |
| Core mini routing and per-turn model selection | implemented | `services/core-control-plane/src/fdai/delivery/azure/llm/t1_latency.py`; `services/core-control-plane/src/fdai/composition/wire_t1_routing.py`; `wire_adaptive_conversation.py`; [focused evidence](#local-mini-routing-evidence-2026-09-06) | Python cohort: 229 passed, two PostgreSQL cases deselected; six additional opt-in configuration checks passed. Verified mini identity, immutable author/reviewer selection, and existing T2/action quality-gate bindings remain preserved. |
| Core supervised opt-in probes | implemented | `services/core-control-plane/src/fdai/delivery/azure/llm/t1_probe.py`; `services/core-control-plane/src/fdai/runtime/bootstrap_tasks.py`; focused TTFT and benchmark checks | The fixed request records first non-empty token and total latency separately. The explicit benchmark reuses that request under fixed sample and concurrency bounds without changing capacity and stops without retry on pressure or provider failure. |
| Semantic health routing projection and Console badge | implemented | `services/operator-service/src/fdai_operator_service/families/conversation/t1_model_health.py`; `console/src/deck/backend-health.ts`; `console/src/deck/backend-health-presentation.ts`; focused Operator and Console checks | Operator validates bounded TTFT fields independently from total latency. Console labels both p50/p95 windows and sample counts; absent or stale TTFT remains unavailable instead of borrowing total latency. Runtime visual qualification remains incomplete. |
| Synthetic chat and inline prompt inspection | implemented | `mocks/ui/deck.html`; `mocks/ui/assets/deck-sources.js`; `mocks/ui/assets/deck-forms.js`; `console/tests/e2e/{deck-forms-mock,deck-prompt-mock,neutral-chat-mock}.spec.ts`; focused Playwright checks | Mock-only presentation. The run record opens a synthetic prompt fixture; production capture and authorization are unchanged. |
| Local ordered narrator candidate fallback | implemented | `services/operator-service/src/fdai_operator_service/adapters/local_narrator.py`; `services/operator-service/tests/test_local_narrator.py`; focused deployment lifecycle tests | The service-local adapter loads a file or plan-sealed inline JSON, verifies the optional deployment SHA, obtains a short-lived token, tries ordered candidates, and exposes sanitized health without Core imports or execution authority. |
| Resolved narrator candidate collection | implemented | `services/core-control-plane/tests/rule_catalog/schema/test_narrator_collection.py`; model resolver and registry | Focused checks cover collection of `narrator_candidates` from reviewed model-resolution inputs. |
| Direct Key Vault resolved-model source adapter | implemented | `adapters/resolved_models_key_vault.py`; focused Operator tests | The async adapter uses an injected token provider and HTTP client, rejects untrusted origins, redirects, mismatched secret identity, disabled or expired values, excessive size or nesting, and secret-bearing representations. Startup composition and governed runtime evidence remain open. |
| Rolling text p50/TTFT, bounded refresh, and failover | implemented | `services/operator-service/src/fdai_operator_service/adapters/local_narrator.py`; `narrator_latency.py`; `narrator_payloads.py`; focused Operator tests | The independent service keeps eight-sample latency and TTFT windows, measures the first non-empty SSE token, coalesces bounded probes, ranks text candidates, preserves unanimous 429/503 status, and fails closed on malformed or oversized output. |
| Legacy periodic narrator refresh owner | implemented | `services/operator-service/src/fdai_operator_service/adapters/narrator_periodic_scheduler.py`; `environment.py`; `composition.py`; focused scheduler and composition tests | The Operator lifecycle owns one immediate-and-periodic loop only with the legacy local Azure narrator, never alongside semantic Kafka. These checks do not validate the new Core mini probe owner. |
| Vision candidate probes and image-turn routing | in-progress | `services/operator-service/src/fdai_operator_service/adapters/local_narrator.py`; focused vision-probe and image-unavailable tests | Vision candidates have an independent measured probe window. Image turns remain unavailable until a server-owned image resolver supplies validated bounded bytes; text bindings are never borrowed. |
| Per-user routing preference and runtime latency projection | implemented | `services/operator-service/src/fdai_operator_service/{postgres_iam_configuration,model_lifecycle_startup}.py`; `services/operator-service/tests/test_narrator_preference_persistence.py`; `tests/integration/services/test_narrator_preference_postgres.py`; `scripts/lib/design-routes.json`; local PostgreSQL restart/CAS check | The authenticated Settings route validates choices against the startup digest-pinned resolved-model narrator candidates, writes principal-scoped state and an inert proposal through one revision-fenced PostgreSQL transaction, reads stored preferences after adapter reconstruction, and falls back to `Auto` when a selected deployment disappears without erasing the choice. Focused route and atomic-state checks pass, and the service-owned loopback PostgreSQL fixture verified audit persistence and restart readback through a new connection. T2 bindings remain system-governed; deployed and timing evidence remain open. |
| Per-conversation T1/T2 selection | validated | `packages/service-contracts/src/fdai_service_contracts/semantic_turn.py`; `services/operator-service/src/fdai_operator_service/families/conversation/semantic_turn.py`; `services/core-control-plane/src/fdai/core/conversation/{conversation_preflight,semantic_runtime}.py`; `console/src/deck/conversation-model-selection.ts`; focused contract, Core, Operator, and Console tests; one bounded local live diagnostic | The Command Deck stores `Auto`, `T1`, or `T2` per conversation. Schema 1.7 carries only an allowed tier with `execution_authority=false`. A general T2 turn uses the configured primary for one low-reasoning preflight and returns its bounded answer without adaptive plan/review/refine/verify. The measured local diagnostic completed in 4.286 seconds with `gpt-5.6-sol`; one sample is not an SLA claim. Cross-device server persistence and authenticated visible-browser evidence remain open. |
| Environment T1/T2 binding drafts and protected planning | implemented | Shared `ModelBindingPolicy`; Operator IAM routes and PostgreSQL adapter; Console Models editor; protected resolver and deploy workflow; focused tests | Owner-only drafts persist with revision and idempotency fences. Assessment and plan requests remain authority-free, bind the active artifact digest, and reach activation only through the protected deployment workflow. Provider and rollback receipts remain open. |
| Answer-continuity and prompt-ablation settings | implemented | Operator runtime-settings route and PostgreSQL adapter; Core startup snapshot; Console Runtime Policies; focused Core, Operator, and Console checks | Owner changes atomically persist an inert proposal and the revision-fenced Core policy record. Both settings apply after restart, prompt ablation remains subtractive, and continuity changes only held or unsupported presentation. |
| Public-web candidate routing | in-progress | `services/operator-service/src/fdai_operator_service/application/conversation/capabilities/web_search/`; `services/operator-service/src/fdai_operator_service/adapters/conversation/web_search/`; focused Operator tests | Provider-neutral and Azure construction paths exist. Governed rolling-latency and failover evidence from local and deployed profiles remains open. |
| Five-stage qualification latency contract | implemented | [`quality_latency.py`](../../../services/core-control-plane/src/fdai/core/conversation_assurance/quality_latency.py), [`chatops_quality_latency.py`](../../../scripts/evaluation/chatops_quality_latency.py), focused checks | The versioned contract separates PR regression, live canary, and release stages. Reduced results revalidate every stage, floor, ceiling, pass, gap, and timestamp-authority invariant. No live or release benchmark receipt is claimed. |
| Stage-owner timing receipt adapter | implemented | [`quality_latency.py`](../../../services/core-control-plane/src/fdai/core/conversation_assurance/quality_latency.py), focused Core checks | The adapter derives duration from monotonic stage-owner values and rejects an environment that differs from the installed contract. Runtime wiring remains open. |
| Eight-stage correlation trace contract | implemented | [`quality_trace.py`](../../../services/core-control-plane/src/fdai/core/conversation_assurance/quality_trace.py), [`chatops_quality_trace.py`](../../../scripts/evaluation/chatops_quality_trace.py), focused checks | The reducer requires one ordered session-to-audit chain with one correlation digest, predecessor links, authoritative timestamps, and provenance commitments. Constructed evidence cannot contradict its completeness or authority state. No live complete trace receipt is claimed. |
| Timing evidence binding | implemented | [`quality_timing.py`](../../../services/core-control-plane/src/fdai/core/conversation_assurance/quality_timing.py), focused checks | A complete cohort contains at least 500 unique traces and must match the latency artifact's installed contract, source revision, trace count, trace-set commitment, and paired artifact content digests. Legacy input remains timing-capped. |
| Optional report-format parity | implemented | `fdai_operator_service.reporting.optional_pdf_report_encoder`; `IncidentRcaReportingProjectionReader`; Operator composition and route tests | Local and deployed Operator composition use the same service-local loader and authoritative audit-backed Incident report reader. Venue, environment, and identity do not change report authority. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-10-06 | implemented | Added call start offsets and cached prompt tokens to Core diagnostics, a bounded concept shard setting, and a speculative form-path start beside the preflight. The local launcher enables 32 KiB shards and the speculative start. A bounded authenticated local comparison of eight Korean turns per variant cut answered list turns from about 10 s to about 5 s and answered count turns from 11.7 to 27.4 s to 5.4 to 9.9 s, with identical answers. | `current change`; focused Core suites (`4920 passed`); mypy and ruff on changed modules; [measured evidence](#speculative-form-start-and-single-shard-concept-catalogs-2026-10-06) | The question form's value reading of a name fragment still holds two or three of five list turns per variant. |
| 2026-10-02 | implemented | Completed certified typed-only read reuse, opaque complete catalog packing, recorded call metrics and bounded two-shard waves, then reevaluated four fixed cases and one final bilingual list pair. | `0cd7ab82c1`, `32833c7dea`; final measured source `66a49cb735`; [bounded results](#bounded-optimization-evidence-2026-10-02); 918 focused runtime and 66 Console accounting checks passed. | Korean end-to-end latency remains variable and the English count concept disagreement remains held. Retain a controlled paired cohort before claiming uniform speed, money or SLO improvement. |
| 2026-10-02 | implemented | Removed unused typed-only legacy grounding, reused exact closed concept choices within one run, losslessly compacted complete catalog prompts, and separated elapsed/cumulative timing and input/output tokens in the work record. | `current change`; grounding, shadow, concept, masking, and compiled-answer cohort: 380 passed; Console performance projection: 11 passed; bilingual focused Playwright: 2 passed across 1440, 993, and 390 CSS pixel widths. | Retain an explicitly authorized same-source live comparison before claiming measured latency, billed-token, or cost improvement; no live model request or model setting change was made. |
| 2026-10-01 | implemented | Kept narrator preference route assembly in the preference owner while Operator composition adds service-owned routes. The Settings projection remains sanitized and `personalizes_t2_bindings` stays false. | `current change`; `fdai_operator_service/composition_routes.py`; focused Operator route-count evidence. | Retain deployed startup-source and runtime timing receipts before raising this area to `validated`. |
| 2026-09-29 | implemented | Moved synthetic chat and prompt inspection into the one Command deck mock. The adaptive response and incident conversation addresses now open its change and incident forms, and the inline prompt file opens from each captured model call in the run record instead of a separate narration row. | `current change`; `mocks/ui/deck.html`; `mocks/ui/assets/deck-sources.js`; `mocks/ui/assets/deck-forms.js`; `npm --prefix console run test:e2e:quick -- tests/e2e/deck-forms-mock.spec.ts tests/e2e/deck-prompt-mock.spec.ts tests/e2e/neutral-chat-mock.spec.ts` (`12 passed`) | None for the mock. Production prompt capture and authorization are unchanged. |
| 2026-09-27 | implemented | Verified the revision-fenced narrator preference write, audit record, and restart readback against the service-owned loopback PostgreSQL validation database after normalizing its private SQLAlchemy DSN for the psycopg fixture. | `current change`; `test_narrator_preference_commits_with_audit_and_survives_new_connection` passed against the prepared local validation database; PR #1458 source and required CI evidence remain unchanged. | Retain separate deployed startup-source and runtime timing receipts before raising this area to `validated`. |
| 2026-09-27 | in-progress | Routed only the narrator preference implementation paths through their own design owner while retaining every existing shared-file route and owner requirement. The preference behavior and no-authority boundary are unchanged. | `current change`; `scripts/lib/design-routes.json`; focused Operator, route, and persistence cohort (305 passed; the optional PDF case and real PostgreSQL case skipped); `check-design-routes.py`, staged `check-design-doc-impact.py`, and roadmap/localization checks passed. The approved loopback PostgreSQL DSN is masked from this session. | Run the real PostgreSQL restart and concurrent-CAS test when the approved loopback DSN becomes available, then retain separate deployed startup and timing receipts. |
| 2026-09-26 | in-progress | Bound the authenticated per-principal narrator preference route to startup digest-pinned choices and atomic proposal/state CAS. A removed deployment retains its stored choice while effective selection returns to `Auto`; the public Settings response stays sanitized and T2 bindings are not personalized. | `current change`; `postgres_iam_configuration.py`, `model_lifecycle_startup.py`, IAM composition and focused preference tests; `uv run pytest -q --no-cov services/operator-service/tests/test_operator_service_composition.py services/operator-service/tests/test_narrator_preference_persistence.py services/operator-service/tests/test_narrator_preferences.py services/operator-service/tests/test_operator_service_postgres.py services/operator-service/tests/test_operator_iam_family.py tests/integration/services/test_narrator_preference_postgres.py` (305 passed, one optional PDF and one PostgreSQL test skipped because `FDAI_ASSIGNMENT_TEST_DSN` was unset); Ruff and strict mypy passed. | Run the supported loopback PostgreSQL fixture for actual restart readback and concurrent CAS, then retain exact deployed startup-source and runtime timing evidence. |
| 2026-09-17 | implemented | Added pointer and keyboard prefetch plus a 60-second authenticated-client memory cache for the complete Models projection. Overlapping reads coalesce; failures are evicted; explicit catalog refresh, conflict recovery, and post-mutation reloads remain fresh. | `current change`; `console/src/api.ts`; `console/src/components/settings-overlay.tsx`; `console/src/routes/settings-models.tsx`; focused cache and Playwright checks. | Retain an authenticated cold- and warm-load timing distribution before claiming a measured latency improvement. |
| 2026-09-14 | implemented | Required content-addressed latency and trace-cohort bindings before qualification timing can clear its hard cap and revalidated reduced result invariants at construction. | `current change`; focused scorecard, timing, and CLI checks (`69 passed`); Ruff passed. | Bind authoritative stage owners and retain one matching controlled cohort of at least 500 traces. |
| 2026-09-08 | implemented | Added true first-nonempty-token TTFT measurement to the Core mini probe, projected separate TTFT and total windows through Operator and Console, and added a bounded exact-request capacity benchmark that cannot change TPM or retry pressure failures. | `current change`; focused Core/Operator TTFT and benchmark checks passed 41 cases, Console routing and tooltip checks passed 66 cases, Ruff and strict mypy passed. | Run the live benchmark only from a clean coherent committed snapshot. Retain authenticated visible-browser timing before raising runtime validation. |
| 2026-09-07 | validated | Routed a selected T2 general-knowledge turn through one T2 preflight that classifies and authors the bounded answer together. GPT-5 preflight requests use low reasoning effort; adaptive plan/review/refine/verify remain absent from this advisory path. | `current change`; 162 focused preflight/composition checks, Ruff, strict mypy, service-boundary checks, and one local live diagnostic completed as `advisory_response` with `model=gpt-5.6-sol` in 4.286 seconds. | Retain authenticated visible-browser streaming evidence and a measured distribution before making a latency target claim. |
| 2026-09-07 | implemented | Added a per-conversation `Auto`/`T1`/`T2` selector. T2 uses the configured primary for model-authored conversation stages while preserving the independent reviewer and no-authority request boundary. | `current change`; focused service-contract, Operator, Core routing, Console payload, persistence, localization, typecheck, and build checks. | Retain authenticated visible-browser evidence and add server-side preference persistence if cross-device continuity becomes required. |
| 2026-09-07 | implemented | Made bounded Core readiness span `core-runtime.log.1` and the current log so rotation between semantic-consumer and heartbeat markers cannot create a false timeout. | `current change`; focused rotation-boundary regression passed. | More than one full 1 MiB rotation remains a bounded unavailable outcome. |
| 2026-09-07 | implemented | Increased the bounded Core readiness log window to 1 MiB after verbose startup output pushed the semantic-consumer marker outside the former 64 KiB tail. | `current change`; a regression preserves marker ordering across more than 64 KiB of intervening output. | Prefer a structured readiness projection if startup output approaches the new bound. |
| 2026-09-07 | implemented | Ordered restart readiness so the accepted fresh Pantheon heartbeat must follow the post-launch semantic consumer marker. | `current change`; focused developer-workflow test covers an earlier post-launch heartbeat and a later valid heartbeat. | Retain a bilingual latency distribution. |
| 2026-09-07 | implemented | Made Core restart readiness require a post-launch semantic consumer and fresh Pantheon heartbeat rather than accepting a previous process's heartbeat. | `current change`; 46 focused launcher/workflow tests passed. A retained restart emitted `ready` after both markers and its first F2 answer token at 3.948 seconds. | Retain a bilingual latency distribution; one sample is not SLO qualification. |
| 2026-09-07 | in-progress | Reduced the preflight body to about 654 estimated tokens while retaining exact schema names. Warm F1/F2 variants used one preflight call and met the 5-second answer-token gate. | Standard Browser Entra F1/F2 timings were 3.810/4.254 seconds. | Retain a bilingual distribution and make Core readiness include the semantic consumer, which started about 28 seconds after `control_loop_ready`. |
| 2026-09-07 | implemented | Batched local PLAINTEXT Kafka consumer commits by the existing record and time bounds instead of committing every multiplexed physical event. Preserved commit-after-processing and redelivery on mid-processing close. | `current change`; focused Event Bus and multiplex tests passed. | Restart the standard Core and retain F1-F4 answer-token TTFT after the logical consumer catches up. |
| 2026-09-07 | implemented | Added a live operational-conversation qualification gate that measures the first `onToken` callback independently from status and terminal timing and fails above 5 seconds. | `current change`; Console typecheck passed. | Run the gate after the complete standard stack starts from one exact source revision. |
| 2026-09-07 | implemented | Moved compact preflight ahead of adaptive planning for first-turn explicit/contextual operational signals and selected a dedicated bounded frame prompt plus intent-scoped descriptors after semantic judgment. | `current change`; 1,237 focused component tests, targeted Ruff, and strict mypy passed. | Measure verified first-answer-token latency on one coherent standard-stack SHA; status frames do not satisfy the 5-second TTFT target. |
| 2026-09-06 | implemented | Corrected the T1 health boundary after the conversation response envelope gained binary and absent bodies. The health parser now accepts unknown input and rejects non-object values, while the semantic runtime facade explicitly exports the reader that Operator composition already consumes. | `current change`; `t1_model_health.py`, `semantic_turn_runtime.py`, `test_t1_model_health.py`, and focused strict mypy, Operator, and service-suite checks. | Retain visible-browser and governed deployed runtime evidence before reporting end-to-end latency validation. |
| 2026-09-06 | implemented | Routed the T1 health reader through the existing semantic runtime facade so local and deployed Operator composition keep the same binding while the root remains below its reviewed fanout ceiling. | `current change`; Operator boundary check reports 39 unique imports; 92 focused composition and T1 health checks passed; Ruff passed. | Retain visible-browser and governed deployed runtime evidence before reporting end-to-end latency validation. |
| 2026-09-05 | implemented | Refined incident and adaptive replies, retained investigation records across completion, and added inline synthetic Markdown prompt inspection without blocking chat. | `current change`; the three mock Playwright files listed above passed their focused scenarios; shared style checks and Console typecheck passed. | Production adoption requires separate review and authenticated, permission-scoped evidence; no runtime prompt capture is claimed. |
| 2026-09-02 | implemented | Added revision-fenced answer-continuity and prompt-ablation settings, one startup-consistent Core snapshot, and localized Console controls without personalizing T2 or granting action authority. | `current change`; focused Core, Operator, and Console checks in the prompt-composition implementation record. | Retain a governed shadow campaign before claiming runtime validation. |
| 2026-08-28 | implemented | Added the stage-owner receipt adapter so benchmark duration cannot be caller-authored and PR/canary/release environment mismatches fail closed. | `current change`; focused Core latency checks (`8 passed`); Ruff and strict mypy. | Wire receipts at authoritative stage owners and retain controlled evidence. |
| 2026-08-28 | implemented | Bound the latency artifact and complete trace cohort before deriving qualification timing state. | `current change`; focused binding checks (`4 passed`); combined latency/trace/timing checks (`23 passed`). | Bind runtime producers and retain one matching controlled evidence set. |
| 2026-08-28 | implemented | Added the eight-stage content-free correlation trace reducer and `--require-complete` CLI. | `current change`; focused Core and CLI checks (`8 passed`); Ruff and strict mypy. | Bind authoritative record producers and retain one complete PR/canary/release trace receipt. |
| 2026-08-28 | implemented | Added the five-stage `chatops-latency-v1` SLO contract, deterministic percentile reducer, and content-free benchmark CLI. | `current change`; focused Core and CLI checks (`11 passed`); Ruff and strict mypy. | Bind authoritative stage producers, retain PR/canary/release receipts, and validate complete correlation traces before claiming latency qualification. |
| 2026-08-14 | in-progress | Adopted the implementation ledger and clarified which latency and preference behavior remains target design; earlier provenance was not reconstructed. | `current change`; current local narrator, resolver, web-search source, and focused checks listed in the scope table. | Implement independent-service latency windows and preferences, then retain governed local and deployed evidence. |
| 2026-08-14 | implemented | Kept optional PDF report registration identical across local and deployed Operator composition. | `current change`; service-local optional loader, package-extra contract, composition binding, and focused route/composition tests. | Retain the separate authenticated Incident report receipt without treating package availability as execution authority. |
| 2026-08-14 | implemented | Kept authoritative Incident RCA report materialization identical across local and deployed Operator composition. | `current change`; service-local audit-backed report reader, composition binding, and focused reader/family tests. | Retain the separate authenticated Incident report receipt. |
| 2026-08-14 | implemented | Added service-local rolling text latency and TTFT routing with bounded coalesced text and vision probes, measured failover, strict SSE and output limits, and bounded Azure CLI credential acquisition. | `current change`; narrator adapter modules; focused local narrator and credential tests `21 passed`; integrated Operator and Core narrator checks passed. | Bind periodic refresh and a server-owned image resolver, then retain governed local and deployed timing evidence. |
| 2026-08-14 | implemented | Bound one immediate-and-periodic narrator refresh loop to the Operator lifecycle with validated interval configuration, failure isolation, duplicate-start suppression, and shutdown cleanup. | `current change`; scheduler, environment, composition, local narrator cleanup, and focused tests `66 passed`. | Bind a server-owned image resolver and retain governed local and deployed timing evidence. |
| 2026-08-16 | in-progress | Added the revisioned per-principal narrator preference store and its sanitized Settings projection. `Auto` and allowlisted deployments are the only accepted values, a stale revision conflicts, principals stay isolated, and a removed deployment degrades to `Auto` while preserving the stored choice. T2 bindings are not personalized. | `current change`; `services/operator-service/src/fdai_operator_service/adapters/narrator_preferences.py`; `pytest services/operator-service/tests/test_narrator_preferences.py` (14 passed). | Bind durable persistence and the authenticated Settings route, then retain governed timing receipts. |
| 2026-08-19 | implemented | Bound the protected resolver's exact inline JSON and SHA to Operator startup and added proposal-only weekly reconciliation. Digest mismatch blocks narrator composition; provider failure produces sanitized abstention and no PR. | `current change`; focused narrator, lifecycle, plan verifier, Terraform, and privileged-workflow tests. | Retain governed local/deployed timing and reconciler-run evidence; direct Key Vault loading remains deferred. |
| 2026-08-23 | implemented | Added the service-owned asynchronous Key Vault source adapter for resolved-model JSON. The adapter keeps token and HTTP providers injected, accepts only current Azure Key Vault DNS suffixes with the matching cloud audience, binds response identity to the requested secret and version, and fails closed within one total deadline. | `current change`; focused Key Vault source tests and 15 critique-and-harden rounds. | Add an asynchronous startup owner, immutable source revision publication, Core/Operator parity binding, and governed local/deployed evidence before replacing the current file or inline source. |
| 2026-08-24 | implemented | Added one environment-wide policy editor for T1/T2 `auto`, `pinned`, and `hil-only` modes, including provisioned SKU and PTU capacity, exact active-digest fencing, and separate draft, assessment, and protected-plan requests. | `current change`; shared contract, Operator route/store, Console policy editor, resolver, workflow, and Terraform checks. | Retain protected provider assessment, apply, independent verification, and rollback receipts. |
| 2026-09-05 | implemented | Bound the service-owned source to the first Operator application lifecycle position. It loads once, validates JSON, and rejects a mismatch with `LLM_RESOLVED_MODELS_SHA256` before later services start; direct Key Vault remains the deployed source seam and configured file or inline content preserves local compatibility. | `current change`; focused Operator production composition and Key Vault source tests. | Retain one governed deployed startup receipt for the exact source revision. |
| 2026-09-06 | in-progress | Defined Core-owned, explicitly opted-in mini probes, freshness-aware routing, immutable per-turn independent review, and a read-only Operator/Console health projection separately from the legacy narrator. | `current change`; source paths in the three new scope rows and this paired design update. Focused implementation and documentation validation are pending; no commit or runtime receipt is claimed. | Prove bounds, failures, per-turn isolation, projection validation, and visible health refresh; retain authorized measurements before claiming faster conversations. |
| 2026-09-06 | implemented | Completed mini routing, bounded probes, health projection, and badge freshness/hidden-browser fixes while preserving T2 and independent review. | `current change`; [bounded evidence](#local-mini-routing-evidence-2026-09-06): 229 Python cases passed, two PostgreSQL cases deselected; overlapping Console cohorts passed 147 and 48; typecheck/build passed; isolated Operator cohort passed 152; eight scheduled mini probes and authenticated DOM label observed. | Complete PostgreSQL, integrated runtime, and visible-browser evidence. No whole-turn speedup, visual pass, new commit, or pushed revision is claimed. |
| 2026-09-06 | implemented | Included projection publication in the 35-second cycle with a separate five-second write deadline and no publication retry. | `current change`; six opt-in configuration checks and final Console 160-case cohort/typecheck/build passed; third/fourth scheduled cycles changed the fastest mini, and authenticated general/screen-context DOM badges and tooltips matched. Console cohorts overlap. | PostgreSQL, integrated runtime, raster/pointer qualification, and whole-turn comparison remain open; synthetic p50 near 1068 ms is not a conversation speedup claim. |

### Remaining work

- [x] Record the focused Python routing/probe cohort: 229 passed, two PostgreSQL cases deselected,
  as detailed in [local evidence](#local-mini-routing-evidence-2026-09-06).
- [x] Record six additional opt-in configuration checks and final Console 160-case/typecheck/build
  passes, overlapping prior 147/48 cohorts; isolated Operator checks passed 152.
- [x] Observe four scheduled Core cycles and a fastest-mini change, with authenticated general and
  screen-context DOM badges/tooltips matching synthetic measurements, without T2.
- [ ] Complete the two deselected PostgreSQL cases and retain integrated runtime evidence on one
  reconciled source snapshot; the isolated Operator result does not validate unrelated auth edits.
- [ ] Verify the model badge and tooltip through raster and pointer checks in a visible browser;
  hidden Electron DOM evidence alone does not satisfy visual acceptance.
- [ ] Retain an explicitly authorized bounded conversation comparison before claiming a live
  latency improvement; synthetic `OK` timings alone are insufficient.
- [ ] Fix the question-form reading that types a name fragment as a value
  (`anchor_form_unsupported:value`), which held two or three of five Korean list turns in each
  2026-10-06 variant, through the typed form contract rather than a lexical rule.
- [ ] Record the provider calls of a speculative ticket that a direct response cancels in the turn's
  call accounting; today only adopted tickets contribute observations.
- [x] Complete the mock-only chat and inline prompt scenarios in the three focused Playwright files above; production adoption remains outside this change.
- [x] Implement and focused-test independent text and vision candidate probes, separate rolling latency and TTFT windows, bounded refresh, failover, and unavailable behavior.
- [x] Bind a periodic refresh owner with validated interval, failure isolation, duplicate-start suppression, and shutdown cleanup.
- [ ] Bind a server-owned conversation-image resolver before marking image-turn routing complete.
- [x] The revisioned per-principal `Auto` or allowlisted narrator preference validation and sanitized projection exist in `services/operator-service/src/fdai_operator_service/adapters/narrator_preferences.py`, proven by the focused preference tests. The projection declares `personalizes_t2_bindings: false` and carries no endpoint or credential material.
- [ ] Run `uv run pytest -q --no-cov tests/integration/services/test_narrator_preference_postgres.py` with the supported loopback-only `FDAI_ASSIGNMENT_TEST_DSN`, and record a passing real PostgreSQL restart-readback, atomic audit/state commit, and concurrent revision-CAS result against the exact startup-pinned source before closing durable per-principal preference delivery.
- [ ] Retain governed local and deployed receipts for narrator and web-search candidate selection, first-token timing, failure, recovery, and sanitized health.
- [x] Implement and focused-test the service-owned async direct Key Vault resolved-model source adapter with trusted-origin, identity, bound, expiration, timeout, and secret-redaction checks.
- [x] Bind the Key Vault source through an asynchronous Operator startup owner, and preserve Core/Operator source-revision parity while Core shares its own revision with lifecycle-hold evaluation and capability binding.
- [x] On startup failure, attempt cleanup for every acquired lifecycle service and report cleanup failures without hiding the original source-revision fence.
- [ ] Retain one governed proposal-only reconciler run and one deployed Operator startup receipt for the exact source revision.
- [ ] Retain one exact environment-policy assessment and protected PTU plan/apply/rollback campaign, including independent verification that the runtime loaded the sealed policy and model version.
- [x] Add a per-conversation `Auto`/`T1`/`T2` selector that sends an allowlisted tier on schema 1.7, uses the configured T2 primary for model-authored stages, and preserves the independent reviewer and `execution_authority=false`.
- [ ] Retain authenticated visible-browser evidence for T1 to T2 switching, persistence after reload, disabled unavailable state, and explicit T2 provider failure without silent T1 fallback.

## Related docs

| To learn about | Read |
|----------------|------|
| T1/T2 capability and quality-gate policy | [LLM strategy](../architecture/llm-strategy.md) |
| Operator API runtime model and DI seams | [Operator Console runtime model](operator-console-runtime-model.md) |
| Local and deployed model resolution | [Dev and deploy parity](../deployment/dev-and-deploy-parity.md) |
