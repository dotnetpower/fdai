---
title: Narrator Routing and Latency
---
# Narrator Routing and Latency

This document owns deployment selection, latency measurement, operator preference, and public-web
pool behavior for the presentation narrator. It preserves the boundary between T1 narration and
system-governed T2 reasoning.

## Narrator latency routing

The independent Operator Service owns the authenticated conversation HTTP boundary. In the
standard local profile, its service-local `LocalAzureNarratorAdapters` reads the prepared resolved
model artifact, obtains a short-lived Cognitive Services token from Azure CLI, and tries the
ordered `narrator_candidates` without importing Core or receiving execution authority. Health is
available only when the resolved artifact and token are usable. Model-only answers remain
explicitly unverified until an authoritative evidence and claim-verification path supplies receipts.

Production conversation delivery still requires an injected projection and stream adapter. The
prior in-process `LatencyRoutedChatBackend` was retired with the top-level Operator implementation;
rolling p50/TTFT selection and multimodal routing remain target behavior for the independent
service rather than a currently composed production capability.

The router is scoped to T1 narrator traffic. Extending latency routing to a T2 capability requires
separate design review. The reviewed same-publisher exception for the `t2.reasoner.primary` slot is
owned by [LLM strategy](../architecture/llm-strategy.md#t2-primary-routing-and-governed-recovery).
Two constraints preserve this boundary:

- **Mixed-model invariant**: `t2.reasoner.primary.publisher` differs from
  `t2.reasoner.secondary.publisher`. Routing the whole pair by speed could collapse the required
  cross-check to one model family.
- **Judge and critic determinism**: composition binds `t1.judge`, `t2.critic`, and the debate
  orchestrator to configured deployments. A runtime routing wrapper does not silently change those
  bindings.

A fork that needs a latency-routed judge declares a separate capability with its own quality gate,
composition binding, and audit evidence.

The independent local service now refreshes text and vision pools through one coalesced, bounded
on-demand cycle. It probes each text candidate twice and each vision candidate once with a bounded
1 px image, keeps separate eight-sample latency and time-to-first-token (TTFT) windows, and ranks
text turns by measured p50 with bounded failover. Unmeasured candidates receive one warm-up chance.
Failures receive a bounded penalty rather than disappearing from the pool.

Image turns remain unavailable because the Operator Service has no server-owned resolver from an
opaque conversation-image id to validated bounded bytes. Client-provided image fields cannot become
that authority. A process-owned scheduler now runs one immediate refresh and later cycles at the
validated `FDAI_NARRATOR_PROBE_INTERVAL_SECONDS` interval, which defaults to `300` and is bounded to
`30-3600`. Provider failures wait for the next interval, and shutdown cancels the loop plus its
coalesced probe task.

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

The web-search pool uses the same warm-up and periodic measurement pattern. Its periodic probe asks
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
  state, and a total deadline without exposing the value. Startup binding remains deferred until an
  asynchronous owner can publish one immutable source revision to both capability binding and
  lifecycle-hold evaluation.
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

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Local ordered narrator candidate fallback | implemented | `services/operator-service/src/fdai_operator_service/adapters/local_narrator.py`; `services/operator-service/tests/test_local_narrator.py`; focused deployment lifecycle tests | The service-local adapter loads a file or plan-sealed inline JSON, verifies the optional deployment SHA, obtains a short-lived token, tries ordered candidates, and exposes sanitized health without Core imports or execution authority. |
| Resolved narrator candidate collection | implemented | `services/core-control-plane/tests/rule_catalog/schema/test_narrator_collection.py`; model resolver and registry | Focused checks cover collection of `narrator_candidates` from reviewed model-resolution inputs. |
| Direct Key Vault resolved-model source adapter | implemented | `adapters/resolved_models_key_vault.py`; focused Operator tests | The async adapter uses an injected token provider and HTTP client, rejects untrusted origins, redirects, mismatched secret identity, disabled or expired values, excessive size or nesting, and secret-bearing representations. Startup composition and governed runtime evidence remain open. |
| Rolling text p50/TTFT, bounded refresh, and failover | implemented | `services/operator-service/src/fdai_operator_service/adapters/local_narrator.py`; `narrator_latency.py`; `narrator_payloads.py`; focused Operator tests | The independent service keeps eight-sample latency and TTFT windows, measures the first non-empty SSE token, coalesces bounded probes, ranks text candidates, preserves unanimous 429/503 status, and fails closed on malformed or oversized output. |
| Periodic narrator refresh owner | implemented | `services/operator-service/src/fdai_operator_service/adapters/narrator_periodic_scheduler.py`; `environment.py`; `composition.py`; focused scheduler and composition tests | The Operator lifecycle owns exactly one immediate-and-periodic loop, validates a 30-3600 second interval, isolates provider failures until the next cycle, and cancels in-flight probes during shutdown. It is bound only with the local Azure narrator. |
| Vision candidate probes and image-turn routing | in-progress | `services/operator-service/src/fdai_operator_service/adapters/local_narrator.py`; focused vision-probe and image-unavailable tests | Vision candidates have an independent measured probe window. Image turns remain unavailable until a server-owned image resolver supplies validated bounded bytes; text bindings are never borrowed. |
| Per-user routing preference and runtime latency projection | in-progress | `services/operator-service/src/fdai_operator_service/adapters/narrator_preferences.py`; `services/operator-service/tests/test_narrator_preferences.py` | The service-local revisioned store keeps one `Auto` or allowlisted deployment per principal, rejects arbitrary model ids, returns a conflict for a stale revision, isolates principals, and degrades a removed deployment to `Auto` without discarding the stored choice. The sanitized projection exposes mode, revision, allowlist, and rolling timing evidence with no endpoint or credential material and declares that T2 bindings are not personalized. Durable persistence, the authenticated Settings route, and the deployment pinning contract remain open. |
| Environment T1/T2 binding drafts and protected planning | implemented | Shared `ModelBindingPolicy`; Operator IAM routes and PostgreSQL adapter; Console Models editor; protected resolver and deploy workflow; focused tests | Owner-only drafts persist with revision and idempotency fences. Assessment and plan requests remain authority-free, bind the active artifact digest, and reach activation only through the protected deployment workflow. Provider and rollback receipts remain open. |
| Public-web candidate routing | in-progress | `services/operator-service/src/fdai_operator_service/application/conversation/capabilities/web_search/`; `services/operator-service/src/fdai_operator_service/adapters/conversation/web_search/`; focused Operator tests | Provider-neutral and Azure construction paths exist. Governed rolling-latency and failover evidence from local and deployed profiles remains open. |
| Five-stage qualification latency contract | implemented | [`quality_latency.py`](../../../services/core-control-plane/src/fdai/core/conversation_assurance/quality_latency.py), [`chatops_quality_latency.py`](../../../scripts/evaluation/chatops_quality_latency.py), focused checks | The versioned contract separates PR regression, live canary, and release stages, enforces sample floors and p50/p95/p99 ceilings, and emits content-free evidence. No live or release benchmark receipt is claimed. |
| Eight-stage correlation trace contract | implemented | [`quality_trace.py`](../../../services/core-control-plane/src/fdai/core/conversation_assurance/quality_trace.py), [`chatops_quality_trace.py`](../../../scripts/evaluation/chatops_quality_trace.py), focused checks | The reducer requires one ordered session-to-audit chain with one correlation digest, predecessor links, authoritative timestamps, and provenance commitments. No live complete trace receipt is claimed. |
| Optional report-format parity | implemented | `fdai_operator_service.reporting.optional_pdf_report_encoder`; `IncidentRcaReportingProjectionReader`; Operator composition and route tests | Local and deployed Operator composition use the same service-local loader and authoritative audit-backed Incident report reader. Venue, environment, and identity do not change report authority. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
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

### Remaining work

- [x] Implement and focused-test independent text and vision candidate probes, separate rolling latency and TTFT windows, bounded refresh, failover, and unavailable behavior.
- [x] Bind a periodic refresh owner with validated interval, failure isolation, duplicate-start suppression, and shutdown cleanup.
- [ ] Bind a server-owned conversation-image resolver before marking image-turn routing complete.
- [x] The revisioned per-principal `Auto` or allowlisted narrator preference store and its sanitized Settings projection exist in `services/operator-service/src/fdai_operator_service/adapters/narrator_preferences.py`, proven by `pytest services/operator-service/tests/test_narrator_preferences.py` (`14 passed`). The projection declares `personalizes_t2_bindings: false` and carries no endpoint or credential material. Durable persistence and the authenticated Settings route remain open.
- [ ] Bind the narrator preference store to durable per-principal persistence and an authenticated Settings route, and prove revision conflicts and principal scope through that route.
- [ ] Retain governed local and deployed receipts for narrator and web-search candidate selection, first-token timing, failure, recovery, and sanitized health.
- [x] Implement and focused-test the service-owned async direct Key Vault resolved-model source adapter with trusted-origin, identity, bound, expiration, timeout, and secret-redaction checks.
- [ ] Bind the Key Vault source through an asynchronous startup owner shared by capability binding and lifecycle-hold evaluation, preserve Core/Operator source-revision parity, and retain one governed proposal-only reconciler run.
- [ ] Retain one exact environment-policy assessment and protected PTU plan/apply/rollback campaign, including independent verification that the runtime loaded the sealed policy and model version.

## Related docs

| To learn about | Read |
|----------------|------|
| T1/T2 capability and quality-gate policy | [LLM strategy](../architecture/llm-strategy.md) |
| Operator API runtime model and DI seams | [Operator Console runtime model](operator-console-runtime-model.md) |
| Local and deployed model resolution | [Dev and deploy parity](../deployment/dev-and-deploy-parity.md) |
