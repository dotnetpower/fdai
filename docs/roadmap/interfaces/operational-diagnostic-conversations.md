---
title: Operational Diagnostic Conversations
---

# Operational diagnostic conversations

This contract defines four read-only operational conversation families and their observable
acceptance criteria. It separates complete answers from safe holds, component implementation
from interactive evidence, and configuration correlation from a proven cause.

> **Scope:** Inventory documents, GPT deployment configuration comparisons, Application Gateway
> (AppGW) latency comparisons, and API Management (APIM) versus GPT error comparisons.
> This design grants no execution authority and adds no agent or state writer.
>
> **Status at 2026-09-06:** Component fixes and focused checks do not establish an end-to-end pass.
> The standard interactive document request produced an action draft without an artifact in about
> 39.9 seconds. The gateway question was held with `semantic_frame_unavailable`.
> Formal critique and hardening rounds completed: **0 of at least 10**.

## Design at a glance

Interpret the whole request through the existing schema-validated semantic judgment. Bind its
typed goal, target, authorized scope, time, and output shape to secured `ObjectSet` reads
(permission-filtered collections), typed-path receipts (evidence for allowed property traversal),
and `MetricWindowProvider` (the existing authoritative metric-window interface). Verify evidence
before the existing conversation presentation and document exporter render it.

## Scenario acceptance criteria

Every row requires the shared boundaries below. A truthful hold satisfies a safety boundary,
not the requested answer's acceptance criterion.

| Family | Required answer or artifact | Observable acceptance criteria |
|--------|-----------------------------|--------------------------------|
| F1: Scoped complete resource inventory document | A downloadable document for the resolved authorized collection, not an action draft or a previous answer's export. | The artifact binds to this turn and principal, lists every readable returned resource and supported property, discloses exclusions and observation time, and proves source and export completeness. Incomplete pagination or output limits prevent a complete-download claim. |
| F2: GPT deployment configuration change | A read-only before/after comparison for the exact deployment and requested interval. | Show readable changed paths, old/new values, source, effective/recorded times, and missing historical coverage. Keep deployment capacity units separate from tokens per minute (TPM), quota, and observed token consumption. No inferred conversion or configuration write. |
| F3: AppGW versus backend latency and changes | Aligned gateway/backend metric windows plus scoped configuration changes. | Distinguish total time, backend connection time, first-byte time, and last-byte time. Preserve native definitions, units, aggregation, dimensions, coverage, and topology evidence. Show before/after differences and contemporaneous changes without declaring a cause or inventing gateway-only latency. |
| F4: APIM versus GPT HTTP 500 and changes | Aligned APIM gateway, APIM backend, and verified GPT deployment evidence with scoped configuration changes. | Separate `GatewayResponseCode` from `BackendResponseCode` for `429`, `500`, and `503`; retain GPT-side observations separately. Preserve denominators for rates and account/deployment scope. An APIM 500 does not prove a GPT 500 or throttling. |

## Generic paraphrase set

These are acceptance inputs, not routing keywords or completed test cases. Resolve relative
times and references before reading; no example supplies a customer identifier.

| Family | Three equivalent request shapes |
|--------|--------------------------------|
| F1 | "Create a complete resource inventory document for the selected subscription."<br>"Give me a downloadable report of all resources I can read in this subscription."<br>"Document the entire authorized resource collection, including any coverage limits." |
| F2 | "What configuration changed on the selected GPT deployment during the last hour?"<br>"Compare this deployment's settings before and after the selected interval."<br>"Show the GPT deployment configuration differences, keeping capacity units separate from TPM." |
| F3 | "Compare Application Gateway and backend latency during the last hour, and list configuration changes."<br>"Did the selected gateway's total and backend timings change alongside its settings?"<br>"Show gateway versus backend timing before and after the interval, with related configuration evidence." |
| F4 | "Compare APIM and GPT 500 errors in the selected interval and show configuration changes."<br>"Separate gateway and backend 429, 500, and 503 responses, then compare the GPT deployment."<br>"When APIM returned 500, what did backend and GPT metrics show, and what settings changed?" |

## Evidence and safety boundaries

- **Exact scope:** Use the authenticated principal and server-resolved resource collection.
  Recheck scope on every read, traversal, receipt, aggregate, and export. Account-wide data cannot
  silently substitute for deployment data. Never attach global history references to scoped output.
- **Ambiguity:** Clarify an unresolved deployment, backend, collection, time zone, or meaning of
  "before" and "after"; otherwise hold with a typed reason. Never guess from a name or model keyword.
- **Exact time:** Record absolute start/end, time zone, bucket interval, and boundary semantics.
  Keep effective time, event time, observation time, and recorded time distinct. Compare aligned,
  equal-duration windows; disclose stale samples, gaps, delayed observations, and baseline selection.
- **Native metric meaning:** Preserve provider metric, status dimension, aggregation, sample
  population, and unit. Convert only documented units. An average is not a percentile or minimum;
  subtracting independently aggregated total/backend metrics does not establish gateway processing.
- **Capacity:** A deployment's capacity setting is not TPM. Any supported conversion needs
  authoritative model/version/deployment-type-specific evidence; otherwise report TPM as unknown.
  Token consumption is a measurement, not configured capacity.
- **Completeness:** Track source enumeration, pagination, duplicate handling, row/column/byte caps,
  historical coverage, and presentation truncation separately. All returned rows fitting in an
  export does not prove the source complete. Complete empty inventory is distinct from a failed read.
- **Missing data:** Preserve observed zero, no samples, unsupported dimensions, denied access,
  absent history, provider failure, and incomplete results as different states. Never replace
  unavailable evidence with zero or claim "no changes" without complete scoped history.
- **No causation shortcut:** Configuration differences and simultaneous metric changes establish
  association only. Keep alternative explanations visible; missing topology or request correlation
  prevents gateway/backend attribution. Similar error counts alone do not identify the same requests.
- **No mutation:** Diagnostics and document generation never change resources, quotas, policies,
  approval state, or runtime mode. A separate change request follows existing draft and approval
  boundaries. Live reads and model questions are authorized for this task; TPM reduction and chaos
  injection are not. Authorization is not proof that a validation ran.
- **Bounded execution:** Preserve existing total, stage, and no-progress deadlines and progress
  signals. An unexpected model fallback, HTTP `429`/`503`, provider timeout, or deadline expiry ends
  that attempt. Do not repeat a live request without a new hypothesis or explicit authorization.

## Design critique and revision

This design-level review does not count as one of the formal hardening rounds.

| Risk in the draft approach | Required revision |
|----------------------------|-------------------|
| Route by phrases such as "document", "GPT", or "500". | Use model-backed typed judgment and deterministic capability validation, never keyword routing or hard-coded paraphrase matches. |
| Treat every document request as a mutation or export a preceding result. | Distinguish fresh inventory reads from prior-result formatting; bind the artifact to this verified turn. |
| Attach global snapshot/history references after filtering displayed rows. | Filter readable object/path provenance before evidence aggregation and output. Scope isolation applies to references as well as values. |
| Reuse generic latency or error metrics across gateways and models. | Use reviewed native concepts through `MetricWindowProvider`, with exact dimensions, scope, time, units, and completeness. |
| Introduce a diagnostic agent, history writer, or direct agent call. | Reuse existing secured query, metric, conversation, and event boundaries; add no execution authority, agent, or state writer. |

## Current evidence and acceptance gaps

The [implementation ledger](../../roadmap-implementation/interfaces/operational-diagnostic-conversations.md)
is the authoritative delivery history. The following is its bounded status summary, not a new
runtime certification. Reported results come from the coordinating session and were not rerun by
this documentation-only change.

| Area | Current evidence | Open acceptance gap |
|------|------------------|---------------------|
| F1 document component | Fix implemented in isolation; 37 targeted tests passed. | The observed standard interactive request still returned an action draft without an artifact, about 39.9 seconds. Retain a successful same-turn download receipt after integration. |
| Native metric components for F3/F4 | 24 native metric concepts implemented. A test slice had 103 passes before two constructor-fixture fixes; five focused guard tests subsequently passed. | These results overlap: do not sum them or claim the changed slice fully passed. Retain final-snapshot checks and interactive evidence. |
| Scoped configuration comparison for F2/F3/F4 | Under revision to prevent global history references leaking into scoped output. | Prove isolation for values, object/path references, and aggregate evidence before claiming a complete comparison. |
| Compound gateway questions for F3/F4 | Wiring in progress; the observed gateway question was held with `semantic_frame_unavailable`. | Prove metric/configuration composition and semantic interpretation through the standard interactive path. |
| Formal critique and hardening | Not yet run; 0 completed rounds. | Complete at least 10 evidence-backed rounds and close accepted findings; unrelated campaigns and overlapping tests do not count. |

Addressing every listed gap in the contract is not evidence that every gap is fixed. All four
families remain short of end-to-end acceptance. The ledger records observable resumption criteria.

## Related docs

| To learn about | Read |
|----------------|------|
| Delivery evidence and remaining work | [Implementation ledger](../../roadmap-implementation/interfaces/operational-diagnostic-conversations.md) |
| Existing typed conversation planning | [Hierarchical conversation planning](hierarchical-conversation-planning.md) |
| Secured query and provider boundaries | [Ontology query coverage](ontology-query-coverage-implementation-plan.md) |
| Inventory document presentation | [Production A3 channel runtime](production-a3-channel-runtime.md) |
| Query and metric implementation | [Ontology platform source](../../../services/core-control-plane/src/fdai/core/ontology_platform/) |
| Native provider adapters | [Azure delivery source](../../../services/core-control-plane/src/fdai/delivery/azure/) |
| Document generation and delivery | [Operator conversation source](../../../services/operator-service/src/fdai_operator_service/families/conversation/) |
