---
title: Narrator Routing and Latency
---
# Narrator Routing and Latency

This document owns deployment selection, latency measurement, operator preference, and public-web
pool behavior for the presentation narrator. It preserves the boundary between T1 narration and
system-governed T2 reasoning.

## Narrator latency routing

The console chat backend
(`fdai.delivery.operator_api.application.conversation.backend.LatencyRoutedChatBackend`) wraps the
`t1.judge` mini-stack deployments and selects the candidate with the lowest rolling p50 latency for
each turn. It is enabled when `resolved-models.json` contains two or more
`narrator_candidates`. A single text candidate uses `AzureAdChatBackend` directly unless vision
routing requires the one-candidate latency wrapper. Concrete Azure and OpenAI-compatible transports
live behind `fdai.delivery.operator_api.adapters.conversation`.

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

The Operator API refreshes text and multimodal pools independently of operator traffic. Text uses
`narrator_candidates`; image turns intersect provisioned deployments with `t1.vision` preferences
and emit `vision_candidates`. Each pool keeps separate eight-sample latency and time-to-first-token
(TTFT) windows. Startup probes text candidates twice and vision candidates with a bounded 1 px
image. Periodic checks add a sample every `FDAI_NARRATOR_PROBE_INTERVAL_SECONDS`, which defaults to
`300`. Missing vision capacity makes image turns unavailable instead of borrowing a text binding.

## Per-user preference and TTFT

Settings > Models projects the resolved T1/T2 inventory, bootstrap state, and runtime latency
evidence without endpoints or credentials. Each authenticated principal can use `Auto` routing or
pin one deployment from the current narrator allowlist. Removed or unavailable preferences fall
back to `Auto`; the server rejects arbitrary model ids.

Preferences use explicit revisions. Creation sends revision `0`; later writes match the current
revision. State and audit commit in one transaction, so concurrent sessions receive `409` instead
of overwriting each other.

The streaming router records TTFT when the first non-empty model token arrives. TTFT p50/p95 and
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

## Related docs

| To learn about | Read |
|----------------|------|
| T1/T2 capability and quality-gate policy | [LLM strategy](../architecture/llm-strategy.md) |
| Operator API runtime model and DI seams | [Operator Console runtime model](operator-console-runtime-model.md) |
| Local and deployed model resolution | [Dev and deploy parity](../deployment/dev-and-deploy-parity.md) |
