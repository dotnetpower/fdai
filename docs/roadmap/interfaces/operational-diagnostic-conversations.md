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
> **Status at 2026-09-07:** The current component slice passed 1,237 tests. Twelve focused critique
> and hardening rounds passed a 43-case matrix and prompt-bound checks after fixing four Medium
> findings: missing APIM gateway-side `429` and `503` observations, provider response-body disclosure
> in Metrics API errors, and a 32,768-character planner bound that rejected the 32,865-character
> governed frame prompt. Known operational families now use a separate 2,173-character prompt, while
> the legacy general prompt has a 33,000-character ceiling. First-turn explicit operational requests
> also bypass the 11-16 second adaptive planning stage and narrow 308 descriptors to at most five.
> A verified compact preflight can now replace the second, full semantic-judgment model call for
> F1-F4 only when current-input provenance, source spans, confidence, and family shape all pass.
> These checks do not establish an end-to-end pass. In a warm standard Browser Entra session, one
> F1 variant emitted its first answer token in 3.810 seconds and one exact F2 variant in 4.254
> seconds, each with only the compact preflight model call. F1 still produced no document artifact.
> F3 and F4 requests without exact resource identities returned clarification without provider
> reads; clarification text does not satisfy the answer-token gate. A restarted Core also started
> its semantic logical consumer about 28 seconds after `control_loop_ready`, so cold-start TTFT
> remains unqualified.

## Design at a glance

Interpret the whole request through the existing schema-validated semantic judgment. Bind its
typed goal, target, authorized scope, time, and output shape to secured `ObjectSet` reads
(permission-filtered collections), typed-path receipts (evidence for allowed property traversal),
and `MetricWindowProvider` (the existing authoritative metric-window interface). Verify evidence
before the existing conversation presentation and document exporter render it.

For the three reviewed planner shapes that cover F1-F4, compact preflight can supply the same
candidate-only judgment fields. Core accepts that shortcut only for an explicit,
context-independent request with at least 0.90 confidence, current utterance and proposal digests,
exact source spans, and a family-specific target and facet allowlist. Any mismatch uses the full
semantic judgment path. The shortcut grants no capability or execution authority.

## Scenario acceptance criteria

Every row requires the shared boundaries below. A truthful hold satisfies a safety boundary,
not the requested answer's acceptance criterion.

| Family | Required answer or artifact | Observable acceptance criteria |
|--------|-----------------------------|--------------------------------|
| F1: Scoped complete resource inventory document | A downloadable document for the resolved authorized collection, not an action draft or a previous answer's export. | The artifact binds to this turn and principal, lists every readable returned resource and supported property, discloses exclusions and observation time, and proves source and export completeness. Incomplete pagination or output limits prevent a complete-download claim. |
| F2: GPT deployment configuration change | A read-only before/after comparison for the exact deployment and requested interval. | Show readable changed paths, old/new values, source, effective/recorded times, and missing historical coverage. Keep deployment capacity units separate from tokens per minute (TPM), quota, and observed token consumption. No inferred conversion or configuration write. |
| F3: AppGW versus backend latency and changes | Aligned gateway/backend metric windows plus scoped configuration changes. | Distinguish total time, backend connection time, first-byte time, and last-byte time. Preserve native definitions, units, aggregation, dimensions, coverage, and topology evidence. Show before/after differences and contemporaneous changes without declaring a cause or inventing gateway-only latency. |
| F4: APIM versus GPT HTTP 500 and changes | Aligned APIM gateway, APIM backend, and verified GPT deployment evidence with scoped configuration changes. | Separate `GatewayResponseCode` from `BackendResponseCode` for `429`, `500`, and `503`; retain GPT-side observations separately. Preserve denominators for rates and account/deployment scope. An APIM 500 does not prove a GPT 500 or throttling. The bounded APIM profile now reads all six gateway/backend status combinations rather than omitting gateway-side `429` and `503`. |

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
  A configuration or gateway comparison without one source-grounded Resource name or id returns
  `resource_identity` clarification before frame-model or provider I/O.
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
- **Interactive latency:** The first verified answer `token` frame should arrive within 5 seconds.
  Status, acknowledgement, and unverified draft text do not satisfy time to first token (TTFT).
  A slower turn fails interactive acceptance even when its terminal answer eventually succeeds.

An accepted F2 judgment with one source-grounded Resource target and a reviewed one-hour duration
builds its configuration frame deterministically. It does not spend a second frame-model call.

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
runtime certification. The component results were rerun in the isolated working tree. Standard
interactive and provider evidence remains separate.

| Area | Current evidence | Open acceptance gap |
|------|------------------|---------------------|
| F1 document component | Implemented; included in the 1,237-test final component slice and the 43-case hardening matrix. | The observed standard interactive request still returned an action draft without an artifact, about 39.9 seconds. Retain a successful same-turn download receipt after integration. |
| Native metric components for F3/F4 | Implemented; 137 focused metric and gateway tests passed, followed by the 1,237-test final component slice. | Retain standard interactive evidence against current provider data. Do not add overlapping counts. |
| Scoped configuration comparison for F2/F3/F4 | Implemented; source isolation, bitemporal bounds, and scoped comparison cases passed in the 43-case matrix and 1,237-test final component slice. | Retain a standard interactive before/after receipt with available history. |
| Compound gateway questions for F3/F4 | Implemented at the component boundary; APIM now retains gateway and backend `429`, `500`, and `503` counts within a 74-read maximum. | The retained standard gateway question was held with `semantic_frame_unavailable`. Prove metric/configuration composition through the standard interactive path. |
| Formal critique and hardening | Implemented; 12 rounds completed, with four Medium findings fixed and no unresolved Medium-or-higher component finding. | Standard interactive and provider-evidence gaps remain separate and cannot be counted as passed. |

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
