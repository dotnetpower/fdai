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

The independent Operator Service owns the authenticated conversation HTTP boundary and relays
semantic turns over Kafka. Core owns model selection and inference in the standard local and
deployed semantic path. Neither the Operator nor the Console selects a deployment from operator
text, receives execution authority, or treats model availability as verified operational evidence.

Core verifies the configured model audiences through a separate bounded readiness path. If model
identity is unavailable, semantic transport remains active and returns a typed authentication hold
before planning; it does not fall back to lexical routing or borrow the Operator HTTP identity.

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
measure again. A successful synthetic `OK` measures request duration, not time to first token
(TTFT), answer quality, or end-to-end conversation latency.

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

The Console shows `T1` plus the projected deployment in the model badge. Its tooltip distinguishes
candidate timings, sample counts, and measured, stale, unmeasured, or failed status. An open,
visible Command Deck polls health every 30 seconds; the browser never runs a model probe. This
read projection introduces no second writer, cross-service implementation import, database data
rewrite, or shared decision state.

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
narrator alongside semantic Kafka to obtain model measurements. Image turns remain unavailable
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

## Synthetic chat and prompt inspection

The [adaptive response](../../../mocks/ui/deck-sources-v2.html) and
[incident conversation](../../../mocks/ui/incident-conversation.html) mocks keep conclusions,
evidence gaps, and investigation records inside the assistant reply. Investigation completion is
distinct from incident recovery; cancellation preserves only the work already shown.
The adaptive mock's simulated LLM narration exposes
[`system-prompt.example.md`](../../../mocks/ui/assets/prompts/system-prompt.example.md) inline
beneath its file row, without a modal or blocking the composer. It supports read-only Markdown,
copy, and download. Missing captures and failed loads remain explicit, and collapsing the file
cancels its pending load. The file is a public synthetic fixture, never a captured runtime prompt.
These presentation studies do not change production prompt capture, permissions, or model routing.

## Per-user preference and TTFT

The target Settings > Models surface projects the resolved T1/T2 inventory, bootstrap state, and runtime latency
evidence without endpoints or credentials. Each authenticated principal can use `Auto` routing or
pin one deployment from the current narrator allowlist. Removed or unavailable preferences fall
back to `Auto`; the server rejects arbitrary model ids.

Target preferences use explicit revisions. Creation sends revision `0`; later writes match the current
revision. State and audit commit in one transaction, so concurrent sessions receive `409` instead
of overwriting each other.

The target streaming router records TTFT when the first non-empty model token arrives. TTFT p50/p95 and
total-latency p50/p95 use separate rolling windows and include sample counts. Unmeasured TTFT stays
unavailable. The preference applies only to the T1 narrator. T1 internal judgment, embeddings, and
all T2 secondary, critic, rubric, and escalation assignments remain system-governed. The T2 primary
pool is not personalized.

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
| Core mini routing and per-turn model selection | implemented | `services/core-control-plane/src/fdai/delivery/azure/llm/t1_latency.py`; `services/core-control-plane/src/fdai/composition/wire_t1_routing.py`; `wire_adaptive_conversation.py`; [focused evidence](#local-mini-routing-evidence-2026-09-06) | Python cohort: 229 passed, two PostgreSQL cases deselected; six additional opt-in configuration checks passed. Verified mini identity, immutable author/reviewer selection, and existing T2/action quality-gate bindings remain preserved. |
| Core supervised opt-in probes | implemented | `services/core-control-plane/src/fdai/delivery/azure/llm/t1_probe.py`; `services/core-control-plane/src/fdai/runtime/bootstrap_tasks.py`; [focused and local evidence](#local-mini-routing-evidence-2026-09-06) | Focused checks passed. Four scheduled cycles observed a fastest-candidate change; publication is bounded within the cycle. Synthetic timings do not prove a whole-turn speedup. |
| Semantic health routing projection and Console badge | implemented | `services/operator-service/src/fdai_operator_service/families/conversation/t1_model_health.py`; `console/src/deck/backend-health.ts`; `console/src/deck/use-deck-backend-health.ts`; [evidence boundary](#local-mini-routing-evidence-2026-09-06) | Final Console cohort: 160 passed, overlapping earlier 147/48 cohorts; final typecheck/build passed. Isolated Operator: 152 passed. General and screen-context DOM badges/tooltips match measurements; visual and full-checkout runtime qualification remain incomplete. |
| Synthetic chat and inline prompt inspection | implemented | `mocks/ui/deck-sources-v2.html`; `mocks/ui/incident-conversation.html`; `console/tests/e2e/{adaptive-prompt-mock,deck-adaptive-mock,incident-conversation-mock}.spec.ts`; focused Playwright and type checks | Mock-only presentation. The prompt viewer reads a synthetic fixture; production capture and authorization are unchanged. |
| Local ordered narrator candidate fallback | implemented | `services/operator-service/src/fdai_operator_service/adapters/local_narrator.py`; `services/operator-service/tests/test_local_narrator.py`; focused deployment lifecycle tests | The service-local adapter loads a file or plan-sealed inline JSON, verifies the optional deployment SHA, obtains a short-lived token, tries ordered candidates, and exposes sanitized health without Core imports or execution authority. |
| Resolved narrator candidate collection | implemented | `services/core-control-plane/tests/rule_catalog/schema/test_narrator_collection.py`; model resolver and registry | Focused checks cover collection of `narrator_candidates` from reviewed model-resolution inputs. |
| Direct Key Vault resolved-model source adapter | implemented | `adapters/resolved_models_key_vault.py`; focused Operator tests | The async adapter uses an injected token provider and HTTP client, rejects untrusted origins, redirects, mismatched secret identity, disabled or expired values, excessive size or nesting, and secret-bearing representations. Startup composition and governed runtime evidence remain open. |
| Rolling text p50/TTFT, bounded refresh, and failover | implemented | `services/operator-service/src/fdai_operator_service/adapters/local_narrator.py`; `narrator_latency.py`; `narrator_payloads.py`; focused Operator tests | The independent service keeps eight-sample latency and TTFT windows, measures the first non-empty SSE token, coalesces bounded probes, ranks text candidates, preserves unanimous 429/503 status, and fails closed on malformed or oversized output. |
| Legacy periodic narrator refresh owner | implemented | `services/operator-service/src/fdai_operator_service/adapters/narrator_periodic_scheduler.py`; `environment.py`; `composition.py`; focused scheduler and composition tests | The Operator lifecycle owns one immediate-and-periodic loop only with the legacy local Azure narrator, never alongside semantic Kafka. These checks do not validate the new Core mini probe owner. |
| Vision candidate probes and image-turn routing | in-progress | `services/operator-service/src/fdai_operator_service/adapters/local_narrator.py`; focused vision-probe and image-unavailable tests | Vision candidates have an independent measured probe window. Image turns remain unavailable until a server-owned image resolver supplies validated bounded bytes; text bindings are never borrowed. |
| Per-user routing preference and runtime latency projection | in-progress | `services/operator-service/src/fdai_operator_service/adapters/narrator_preferences.py`; `services/operator-service/tests/test_narrator_preferences.py` | The service-local revisioned store keeps one `Auto` or allowlisted deployment per principal, rejects arbitrary model ids, returns a conflict for a stale revision, isolates principals, and degrades a removed deployment to `Auto` without discarding the stored choice. The sanitized projection exposes mode, revision, allowlist, and rolling timing evidence with no endpoint or credential material and declares that T2 bindings are not personalized. Durable persistence, the authenticated Settings route, and the deployment pinning contract remain open. |
| Environment T1/T2 binding drafts and protected planning | implemented | Shared `ModelBindingPolicy`; Operator IAM routes and PostgreSQL adapter; Console Models editor; protected resolver and deploy workflow; focused tests | Owner-only drafts persist with revision and idempotency fences. Assessment and plan requests remain authority-free, bind the active artifact digest, and reach activation only through the protected deployment workflow. Provider and rollback receipts remain open. |
| Answer-continuity and prompt-ablation settings | implemented | Operator runtime-settings route and PostgreSQL adapter; Core startup snapshot; Console Runtime Policies; focused Core, Operator, and Console checks | Owner changes atomically persist an inert proposal and the revision-fenced Core policy record. Both settings apply after restart, prompt ablation remains subtractive, and continuity changes only held or unsupported presentation. |
| Public-web candidate routing | in-progress | `services/operator-service/src/fdai_operator_service/application/conversation/capabilities/web_search/`; `services/operator-service/src/fdai_operator_service/adapters/conversation/web_search/`; focused Operator tests | Provider-neutral and Azure construction paths exist. Governed rolling-latency and failover evidence from local and deployed profiles remains open. |
| Five-stage qualification latency contract | implemented | [`quality_latency.py`](../../../services/core-control-plane/src/fdai/core/conversation_assurance/quality_latency.py), [`chatops_quality_latency.py`](../../../scripts/evaluation/chatops_quality_latency.py), focused checks | The versioned contract separates PR regression, live canary, and release stages, enforces sample floors and p50/p95/p99 ceilings, and emits content-free evidence. No live or release benchmark receipt is claimed. |
| Stage-owner timing receipt adapter | implemented | [`quality_latency.py`](../../../services/core-control-plane/src/fdai/core/conversation_assurance/quality_latency.py), focused Core checks | The adapter derives duration from monotonic stage-owner values and rejects an environment that differs from the installed contract. Runtime wiring remains open. |
| Eight-stage correlation trace contract | implemented | [`quality_trace.py`](../../../services/core-control-plane/src/fdai/core/conversation_assurance/quality_trace.py), [`chatops_quality_trace.py`](../../../scripts/evaluation/chatops_quality_trace.py), focused checks | The reducer requires one ordered session-to-audit chain with one correlation digest, predecessor links, authoritative timestamps, and provenance commitments. No live complete trace receipt is claimed. |
| Timing evidence binding | implemented | [`quality_timing.py`](../../../services/core-control-plane/src/fdai/core/conversation_assurance/quality_timing.py), focused checks | A complete cohort contains at least 500 unique traces and must exactly match the latency artifact's installed contract, source revision, trace count, and trace-set commitment. |
| Optional report-format parity | implemented | `fdai_operator_service.reporting.optional_pdf_report_encoder`; `IncidentRcaReportingProjectionReader`; Operator composition and route tests | Local and deployed Operator composition use the same service-local loader and authoritative audit-backed Incident report reader. Venue, environment, and identity do not change report authority. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
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
- [x] Complete the mock-only chat and inline prompt scenarios in the three focused Playwright files above; production adoption remains outside this change.
- [x] Implement and focused-test independent text and vision candidate probes, separate rolling latency and TTFT windows, bounded refresh, failover, and unavailable behavior.
- [x] Bind a periodic refresh owner with validated interval, failure isolation, duplicate-start suppression, and shutdown cleanup.
- [ ] Bind a server-owned conversation-image resolver before marking image-turn routing complete.
- [x] The revisioned per-principal `Auto` or allowlisted narrator preference store and its sanitized Settings projection exist in `services/operator-service/src/fdai_operator_service/adapters/narrator_preferences.py`, proven by `pytest services/operator-service/tests/test_narrator_preferences.py` (`14 passed`). The projection declares `personalizes_t2_bindings: false` and carries no endpoint or credential material. Durable persistence and the authenticated Settings route remain open.
- [ ] Bind the narrator preference store to durable per-principal persistence and an authenticated Settings route, and prove revision conflicts and principal scope through that route.
- [ ] Retain governed local and deployed receipts for narrator and web-search candidate selection, first-token timing, failure, recovery, and sanitized health.
- [x] Implement and focused-test the service-owned async direct Key Vault resolved-model source adapter with trusted-origin, identity, bound, expiration, timeout, and secret-redaction checks.
- [x] Bind the Key Vault source through an asynchronous Operator startup owner, and preserve Core/Operator source-revision parity while Core shares its own revision with lifecycle-hold evaluation and capability binding.
- [x] On startup failure, attempt cleanup for every acquired lifecycle service and report cleanup failures without hiding the original source-revision fence.
- [ ] Retain one governed proposal-only reconciler run and one deployed Operator startup receipt for the exact source revision.
- [ ] Retain one exact environment-policy assessment and protected PTU plan/apply/rollback campaign, including independent verification that the runtime loaded the sealed policy and model version.

## Related docs

| To learn about | Read |
|----------------|------|
| T1/T2 capability and quality-gate policy | [LLM strategy](../architecture/llm-strategy.md) |
| Operator API runtime model and DI seams | [Operator Console runtime model](operator-console-runtime-model.md) |
| Local and deployed model resolution | [Dev and deploy parity](../deployment/dev-and-deploy-parity.md) |
