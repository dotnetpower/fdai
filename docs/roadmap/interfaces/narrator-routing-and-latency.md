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

The narrator's `context_selection` receipt also carries `dialogue_state_shadow`: counts, a range digest and a typed fallback reason for the history turns the request did not carry verbatim. It is shadow-only, contains no turn text, and changes neither the model request nor routing. The Operator composition binds the Postgres snapshot writer into the narrator. With `FDAI_NARRATOR_DIALOGUE_STATE_T1_ENABLED` on, a small-model proposer asks for verbatim quotes in a tracked background task, so it never delays the answer; deterministic code locates each quote and accepts a proposal only when every span reproduces its value, and any failure keeps the typed T0 fallback. The receipt reports `t1_scheduled`. When a snapshot writer is composed and the body names a `conversation_id`, the narrator retains the compacted state best-effort; a storage failure is logged and never affects the turn. See [Pantheon Conversational Deliberation](../agents/conversational-deliberation.md#structured-dialogue-state-observation-mode).

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
Its ordered fallback, text/vision probes, rolling p50/TTFT windows, failed-candidate exclusion, and
Operator-owned periodic scheduler do not implement Core mini routing. Do not enable the legacy
narrator alongside semantic Kafka to obtain model measurements. The adapter invokes its injected
HTTP stream with an explicit `POST` method. It skips answer-free Azure prompt-filter, passing
content-filter, terminal-stop, and usage metadata frames, while malformed or oversized data still
fails closed. Provider-status and malformed-frame warnings are bounded and contain no prompt,
endpoint, token, or response body. Its bounded system prompt states FDAI's product scope and treats
FDAI as a product name rather than inventing an acronym expansion. Image turns remain unavailable
without a server-owned resolver from an opaque conversation-image id to validated bounded bytes;
client-provided image fields cannot supply that authority.

The unavailable boundary now includes a provider-neutral image-token reservation contract. A
server-owned resolver may submit at most four unique image ids with validated dimensions and
reviewed `low` or `high` detail. Low detail reserves 85 tokens; high detail reserves 85 base tokens
plus 170 per 512-pixel tile, with an 8,192-token turn ceiling. The reservation grants no image
availability or execution authority and cannot be created from client-declared dimensions.

The legacy narrator now applies an 8,192-token request budget with a 1,024-token output reserve.
It serializes screen context deterministically, fits that context to 2,048 tokens, and then admits
the newest valid history turns until the complete request fits. Console sends at most 12 turns,
limits every turn to the semantic contract's 8,000-character item bound, and reports the original
turn count. The terminal event includes content-free counts for included, omitted, and shortened
history, whether screen context was shortened, and the request estimate and budget. Streaming asks
Azure for a final usage frame and retains only non-negative prompt, completion, total, and cached
token counters. A failed candidate remains excluded from operator requests until a later successful
synthetic probe restores it. These controls reduce repeated billed work but do not turn the legacy
narrator into the semantic path or verified operational evidence.

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
## Related docs

| To learn about | Read |
|----------------|------|
| Delivery status and remaining work | [Implementation ledger](../../roadmap-implementation/interfaces/narrator-routing-and-latency.md) |
| T1/T2 capability and quality-gate policy | [LLM strategy](../architecture/llm-strategy.md) |
| Operator API runtime model and DI seams | [Operator Console runtime model](operator-console-runtime-model.md) |
| Local and deployed model resolution | [Dev and deploy parity](../deployment/dev-and-deploy-parity.md) |
