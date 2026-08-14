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
owned by [LLM strategy](../architecture/llm-strategy.md#t2-primary-latency-pool-invariant-safe-opt-in).
Two constraints preserve this boundary:

- **Mixed-model invariant**: `t2.reasoner.primary.publisher` differs from
  `t2.reasoner.secondary.publisher`. Routing the whole pair by speed could collapse the required
  cross-check to one model family.
- **Judge and critic determinism**: composition binds `t1.judge`, `t2.critic`, and the debate
  orchestrator to configured deployments. A runtime routing wrapper does not silently change those
  bindings.

A fork that needs a latency-routed judge declares a separate capability with its own quality gate,
composition binding, and audit evidence.

The target independent service refreshes text and multimodal pools independently of operator
traffic. The current local adapter tries ordered `narrator_candidates`, but it does not maintain
the rolling latency and time-to-first-token (TTFT) windows described below. The target text pool
uses `narrator_candidates`; image turns intersect provisioned deployments with `t1.vision`
preferences and emit `vision_candidates`. Each pool keeps separate eight-sample latency and TTFT
windows. Startup probes text candidates twice and vision candidates with a bounded 1 px image.
Periodic checks add a sample every `FDAI_NARRATOR_PROBE_INTERVAL_SECONDS`, which defaults to `300`.
Missing vision capacity makes image turns unavailable instead of borrowing a text binding.

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
deployment multiplexes them over `aw.pantheon.objects`, both modes use the same physical marker,
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
  secret reference. A direct Key Vault loader remains deferred with the reconciler work.
- **Local model fixture**: an Ollama or LM Studio fixture is not currently included. Any such
  fixture would be an explicit model binding and would not redefine the interactive local profile.
- **Reconciler alerts**: Teams is the current assumption and remains to be confirmed when the
  reconciler is implemented.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Local ordered narrator candidate fallback | implemented | `services/operator-service/src/fdai_operator_service/adapters/local_narrator.py`; `services/operator-service/tests/test_local_narrator.py` | The service-local adapter loads the resolved artifact, obtains a short-lived token, tries ordered candidates, and exposes sanitized health without Core imports or execution authority. |
| Resolved narrator candidate collection | implemented | `services/core-control-plane/tests/rule_catalog/schema/test_narrator_collection.py`; model resolver and registry | Focused checks cover collection of `narrator_candidates` from reviewed model-resolution inputs. |
| Rolling p50/TTFT and multimodal routing | not-started | [Narrator latency routing](#narrator-latency-routing) | The retired in-process router is not composed in the independent service, and no replacement rolling-window implementation was found. |
| Per-user routing preference and runtime latency projection | not-started | [Per-user preference and TTFT](#per-user-preference-and-ttft) | The revisioned preference, TTFT projection, and deployment pinning contract remains target behavior. |
| Public-web candidate routing | in-progress | `services/operator-service/src/fdai_operator_service/application/conversation/capabilities/web_search/`; `services/operator-service/src/fdai_operator_service/adapters/conversation/web_search/`; focused Operator tests | Provider-neutral and Azure construction paths exist. Governed rolling-latency and failover evidence from local and deployed profiles remains open. |
| Optional report-format parity | implemented | `fdai_operator_service.reporting.optional_pdf_report_encoder`; Operator composition and route tests | Local and deployed Operator composition use the same service-local loader. Only package-extra availability registers `pdf`; venue, environment, and identity do not change report authority. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-14 | in-progress | Adopted the implementation ledger and clarified which latency and preference behavior remains target design; earlier provenance was not reconstructed. | `current change`; current local narrator, resolver, web-search source, and focused checks listed in the scope table. | Implement independent-service latency windows and preferences, then retain governed local and deployed evidence. |
| 2026-08-14 | implemented | Kept optional PDF report registration identical across local and deployed Operator composition. | `current change`; service-local optional loader, package-extra contract, composition binding, and focused route/composition tests. | Retain the separate authenticated Incident report receipt without treating package availability as execution authority. |

### Remaining work

- [ ] Implement and focused-test independent text and vision candidate probes, separate rolling latency and TTFT windows, bounded refresh, failover, and unavailable behavior.
- [ ] Implement revisioned per-principal `Auto` or allowlisted narrator preference storage and sanitized Settings projection without personalizing T2 bindings.
- [ ] Retain governed local and deployed receipts for narrator and web-search candidate selection, first-token timing, failure, recovery, and sanitized health.
- [ ] Implement the deferred direct Key Vault resolved-model loader and reconciler alert path only through reviewed service-owned adapter boundaries.

## Related docs

| To learn about | Read |
|----------------|------|
| T1/T2 capability and quality-gate policy | [LLM strategy](../architecture/llm-strategy.md) |
| Operator API runtime model and DI seams | [Operator Console runtime model](operator-console-runtime-model.md) |
| Local and deployed model resolution | [Dev and deploy parity](../deployment/dev-and-deploy-parity.md) |
