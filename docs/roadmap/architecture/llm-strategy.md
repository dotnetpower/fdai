---
title: LLM Strategy
---
# LLM Strategy

The design **uses the LLM less**, not more. A model is the **T2** fallback, reached only after T0 and
T1 cannot resolve a case, and its output is never trusted for execution until deterministic verification approves it. Execution eligibility is granted by that verification, **never by the model**. This file expands the tier and quality-gate rules in
[architecture.instructions.md](../../../.github/instructions/architecture.instructions.md) and
the threat model in [security-and-identity.md](security-and-identity.md).

> Model names below are recommendations to **confirm at adoption time**. Availability, pricing,
> and preview status change; pick the concrete model by measured cost/quality on the scenario set,
> never by assumption. No specific model is fixed by this document.
## Implementation status
### Implementation scope
| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Capability registry, resolution, and provisioning assessment | implemented | `rule-catalog/llm-registry.yaml`; `rule_catalog/schema/llm_resolver.py`; `provisioning_assessment.py`; focused resolver tests | Capability-to-model mappings, explicit capacity units, mixed-publisher invariants, and fail-closed readiness are executable. |
| Environment model binding policy and PTU planning | implemented | `fdai_service_contracts/model_binding.py`; `model_binding_policy.py`; Operator IAM binding routes and PostgreSQL adapter; Console Models editor; protected deploy workflow; focused contract, resolver, Operator, Console, and Terraform checks | Owners can save revisioned `auto`, `pinned`, or `hil-only` intent for every T1/T2 capability. PTU and exact model versions are evaluated and sealed in protected planning. Console and Operator retain no provider mutation or execution authority. |
| Candidate-only semantic judgment and planning | implemented | `core/conversation/semantic_judgment.py`; `core/conversation/semantic_planning.py`; `composition/wire_semantic_query.py`; Azure semantic adapters; focused judgment and planning tests | Bounded T1 judgment retries malformed schema output on the same binding before optional T2 escalation. Accepted meaning can guide planning but grants no execution authority. |
| T2 cross-check, verifier, grounding, confidence, and rubric | implemented | `core/quality_gate/`; `delivery/azure/llm/rubric.py`; focused quality-gate and Azure adapter tests | The four required legs and optional subtractive rubric exist. Missing or invalid evidence lowers the result to denial, abstention, or human review. |
| Escalation policy and same-publisher primary latency routing | implemented | `core/quality_gate/escalation_ladder.py`; `delivery/azure/llm/latency_routed_cross_check.py`; `composition/wire_llm.py`; focused routing tests | The ladder remains never-authoritative, and latency selection cannot cross into the secondary publisher. A separate bounded proposer fallback can invoke the registered secondary proposer, but its candidate still enters the same quality gate. |
| T2 proposer failover, durable recovery evidence, and governed route selection | implemented | `core/tiers/t2_reasoning/recovery.py`; `runtime/t2_{recovery,route_registry}.py`; `ops.switch-t2-proposer-route`; focused runtime and pantheon-chain tests | Every attempted proposer reserves budget and emits sanitized durable evidence. Terminal exhaustion reaches human approval before Thor can persist a route change, and Vidar restores only the failed change. No governed deployed recovery campaign is retained here. |
| Model lifecycle expiry review mechanics | implemented | `model_lifecycle_review.py`; `model_lifecycle_reconciler.py` proposal schema v3; focused lifecycle and Key Vault source tests | Proposals bind the exact source digest and affected capabilities. Expired unmerged reviews produce authority-free holds without changing mappings. The direct Key Vault source adapter exists, but startup loading, PR lifecycle observation, decision persistence, and runtime hold application remain open. |
| Operational model evidence and enforce promotion | in-progress | `core/measurement/model_tracking.py`; [Goals and Metrics](goals-and-metrics.md#implementation-status) | Measurement and promotion contracts exist, but one retained live cohort for every active T1/T2 capability is not evidenced here. |
| Weekly model reconciler and reviewed replacement flow | in-progress | `.github/workflows/model-lifecycle-reconcile.yml`; `scripts/deployment/azure/model_lifecycle_reconciler.py`; focused lifecycle and protected-workflow tests | The proposal-only path compares family, publisher, status, SKU, capacity unit, and capacity value, emits sanitized evidence, abstains on provider failure, and can open an idempotent draft with no activation authority. It has no expired-proposal evaluator or runtime hold binding, and no governed run receipt is retained. |
### Implementation history
| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-14 | in-progress | Adopted the implementation ledger without reconstructing earlier provenance and aligned the quality-gate status with current resolver, rubric, escalation, and latency-routing code. | `current change`; registry, quality-gate, Azure adapter, composition, and measurement paths listed above. | Retain operational model evidence and implement the governed reconciler flow. |
| 2026-08-19 | implemented | Bound live model resolution to protected planning, sealed the exact full and deployment manifests into plan metadata, restored the same JSON and SHA for apply, and added a proposal-only weekly lifecycle reconciler. | `current change`; focused model lifecycle, plan verifier, Operator narrator, Terraform, and privileged-workflow checks. | Retain one governed reconciler run and separately review any draft replacement before registry or deployment change. |
| 2026-08-21 | implemented | Versioned lifecycle proposals to include SKU and effective capacity after an existing `GlobalStandard` 1K TPM embedding deployment and the reviewed `Standard` 200K TPM candidate were incorrectly classified as no change. The protected plan permits only that exact address, family, account binding, source SKU/capacity, target SKU/capacity, and replacement action. | `current change`; `model_lifecycle_reconciler.py`; `deploy-dev.yml`; focused lifecycle checks passed 5 cases and destructive-plan checks passed 2 cases. | Apply only the exact protected plan, verify the replacement and runtime binding, retain the apply receipt, and remove the bounded migration approval after convergence. |
| 2026-08-23 | implemented | Connected candidate-only semantic judgment to read-only semantic planning, added up to three same-binding schema-repair attempts before optional T2 escalation, and enforced action-posture and action-subject alignment. | `current change`; `semantic_judgment.py`; `semantic_planning.py`; `wire_semantic_query.py`; focused semantic judgment, adapter, tier-routing, and composition checks. | Add schema-repair attempt, recovery, escalation, and planning-disposition measures to the retained live-shadow cohort. |
| 2026-08-23 | implemented | Recorded the shipped T2 proposer recovery contract in this owner document. Bounded attempts persist sanitized receipts before Huginn ingress; terminal exhaustion is reduced by Heimdall and judged by Forseti; approved route changes use Thor, append-only audit, and correlation-fenced Vidar rollback. A recovered attempt remains an observation and does not open another approval. | Commits `68f0d4014` and `e96416ce1`; `recovery.py`; `t2_recovery.py`; `t2_route_registry.py`; `test_{t2_recovery,t2_route_registry}.py`; `test_t2_recovery_chain.py`. | Retain one exact-revision governed campaign proving restart recovery, exhaustion-to-approval, route switch, failed verification rollback, stale rollback rejection, and recovery without a new approval. |
| 2026-08-23 | in-progress | Corrected the lifecycle scope after source and workflow review found that proposal expiry does not lower an affected capability to human review. The scheduled workflow remains proposal-only and has no retained run. | `current change`; `.github/workflows/model-lifecycle-reconcile.yml`; `scripts/deployment/azure/model_lifecycle_reconciler.py`; focused lifecycle contract tests. | Implement the expiry-to-hold path against the authoritative runtime model source, then retain one protected scheduled run and separately review any draft replacement. |
| 2026-08-23 | implemented | Added the locally executable expiry-review slice. Lifecycle proposal v3 records the canonical source-model digest and affected capabilities. A pure evaluator holds only an expired, unmerged proposal for that exact source and rejects late merge evidence. The Operator-owned async Key Vault source validates official Azure vault origins and audiences, exact secret identity, size, JSON depth, enabled and expiration state, total deadline, and secret-safe errors and representation. | `current change`; focused lifecycle and Key Vault tests; 15 critique-and-harden rounds ended with no verified Medium-or-higher defect. | Bind asynchronous source loading and trusted PR lifecycle observations into startup, persist and verify decisions, then apply holds before capability binding without changing the model mapping. |
| 2026-08-24 | implemented | Added revisioned environment binding drafts for every T1/T2 capability, complete-candidate TPM/PTU fallback, exact GA version sealing, Owner-only assessment and plan requests, active-artifact digest fencing, and Terraform version pinning. | `current change`; shared policy, resolver, Azure query, Operator IAM, Console Models, protected workflow, and Terraform paths; focused checks recorded in the completion report. | Retain one protected PTU plan/apply/rollback receipt and one post-apply independent binding verification before classifying the path as validated. |
| 2026-08-24 | implemented | Added a model-binding-only protected deployment mode after live assessment showed that an intentionally unavailable secondary publisher made the general completeness gate stop before Terraform. Bounded `plan-model-*` and `apply-model-*` request ids require an environment policy and protected request, target only the Azure OpenAI module, accept only sealed cognitive deployment changes, and verify replacement version, SKU, and capacity against the resolved artifact. | [Issue #270](https://github.com/dotnetpower/fdai/issues/270); `deploy-dev.yml`; `test_model_resolution_lifecycle.py`; focused protected workflow checks passed 60 cases, YAML parsing passed, and Ruff passed. | Run the exact PTU plan, apply, independent runtime verification, and reverse-plan rollback before classifying the path as validated. |
### Remaining work
- [ ] Retain a pinned live-shadow cohort for every enabled T1/T2 capability with model identity, cost, latency, schema-repair attempts and recovery, escalation, planning disposition, disagreement, grounding, verifier, rubric, outcome, and guard evidence after the live KPI prerequisites in [Goals and Metrics](goals-and-metrics.md#remaining-work) and the [Agent Pantheon implementation plan](../agents/agent-pantheon-implementation.md#remaining-work) are satisfied.
- [ ] Retain a governed T2 recovery campaign proving bounded attempt budgets, durable receipt forwarding after restart, terminal exhaustion to human approval, an audited route switch, correlation-fenced rollback, and recovery without a new approval.
- [ ] Bind the implemented expired-unmerged evaluator and direct Key Vault source adapter through an asynchronous startup owner. Add trusted PR lifecycle observation, proposal and decision digest verification, persistence, and pre-binding capability holds. Prove the affected capability moves to human review without changing its model mapping, then retain a governed scheduled-run receipt showing deprecation or family drift creates only a sanitized draft PR. The startup/source contract is owned by [Narrator Routing and Latency](../interfaces/narrator-routing-and-latency.md#remaining-work).
- [ ] Promote optional rubric, escalation invocation, or primary-pool behavior only through the [authoritative ActionType registry](../decisioning/action-ontology.md#33-governance) after frozen replay and independent review; keep missing bindings fail-closed.
- [ ] Retain one protected environment policy campaign that assesses a provisioned SKU, seals the exact model version and PTU capacity, applies the approved plan, independently verifies the runtime binding, and rehearses rollback without a Console or Operator identity receiving provider mutation authority.

## Model Tiers

Coverage figures are **targets to validate against a measured baseline**
([goals-and-metrics.md](goals-and-metrics.md)), not guarantees. They partition one event
stream, so T0+T1+T2 sum to ~100%; T0 (~70-80%) is documented in
[architecture.instructions.md](../../../.github/instructions/architecture.instructions.md).

| Tier | Role | Model class | Coverage target | Cost profile |
|------|------|-------------|-----------------|--------------|
| **T0** | deterministic engine | **no model** | ~70-80% | zero tokens |
| **T1** | similarity + light judgment | **embedding model** + **small/cheap LLM** | ~15-20% | very low |
| **T2** | reasoning on novel/ambiguous cases | **frontier LLMs (2+ independent)** | ~5-10% | highest; mixed-model cross-check required |

### Tier Boundaries

- **T0 → T1** when no rule yields a deterministic verdict but the case is not novel.
- **T1 → T2** only when T1 **abstains**: no exact rule match, embedding similarity to prior
  resolved incidents falls below a configured score threshold, and no learned action applies.
- Similarity thresholds and the abstain conditions are **configuration**, not hard-coded.

## T1 - Lightweight Tier

- **Embeddings**: a small embedding model vectorizes incidents and matches past patterns. Prefer a cost-efficient hosted model, or a local sentence-transformer where residency or cost requires it (see
  [Data Privacy](#data-privacy-and-residency)). Store vectors next to state (e.g. pgvector).
- **Candidate-only semantic judgment**: a small instruction model proposes typed intent, targets, requested facts, confidence, ambiguity, and action posture from bounded context and principal-scoped capabilities.
  Invalid schema output receives only bounded, sanitized repair facts and retries the same binding up to three times before an optional T2 binding; callers can disable escalation.
- **Verified planning input**: accepted judgment is passed to semantic planning inside the untrusted input envelope. Deterministic code normalizes `advise_only` to `action_subject: none`, requires a typed
  subject for `draft_only`, and validates the resulting frame and plan. Neither model grants authorization or execution eligibility.
- Goal: absorb ~15-20% of events without a frontier round-trip.

## T2 - Reasoning Tier (Quality Gate Required)

T2 handles only novel or ambiguous cases (~5-10%). Its output must pass the quality gate
before it can execute. The model **generates a candidate**; the deterministic verifier decides
eligibility.

- **Mixed-model cross-check**: run **two or more independent models** on the same judgment.
  Independence means genuinely distinct providers/weights - do **not** count two endpoints
  serving the same base model, since correlated errors defeat the check.
  - **Agreement predicate**: agreement is on the **normalized structured action** (target
    resource, operation, parameters), not free text. Compare canonicalized action objects for
    semantic equivalence, not string identity.
  - **N models and quorum**: with N ≥ 3, require a configured quorum (e.g. majority); no quorum
    → escalate. A 2-of-2 tie (disagreement) escalates to HIL, never auto-resolves.
  - **Cost control**: prefer a **cascade** - run the cheaper reasoner first and invoke the
    second only when its self-consistency or grounding signal is weak - so the full N-model
    fan-out is spent only on genuinely hard cases.
  - **Provenance (reproducibility)**: the decision records **each model's vote**
    (`QualityDecision.model_votes`: `model_id`, proposed action type, agreed) - not just the
    agreement count - so a T2 judgment is reconstructable from the append-only audit, the
    replay property the log promises.
- **Verifier**: a **deterministic** check, independent of any model, re-validates the candidate
  action against policy-as-code and what-if/dry-run before it is execution-eligible. The
  verifier - not model text - is the authority.
- **Grounding (RAG)**: force citation of the rules/policies/docs that justify the judgment,
  and **validate that each cited item exists in the rule catalog and actually supports the
  claim** (guards against fabricated citations). **Abstain** when the answer is ungrounded.
- **Threshold gating**: schema, policy, what-if, and security-scan checks must all pass and a
  computed **confidence** must clear a threshold. Confidence is derived from verifier and
  cross-check signals (agreement, grounding validity, historical success) - **never from a
  model's self-reported confidence**, which is unreliable. Below threshold routes to HIL.

### Outcome Semantics

- **eligible** - all gates pass; hand to the risk gate.
- **abstain** - no grounded, supported answer; take no autonomous action, route to HIL.
- **disagree/escalate** - models fail quorum; route to HIL.
- **deny** - verifier or policy rejects the candidate; no-op, audited.

All four are typed, audited outcomes; only **eligible** can proceed toward execution.

![Outcome Semantics. The main stages are novel or ambiguous case, mixed-model pool: 2+ independent models, quorum agreement?, escalate to HIL, deterministic verifier: policy-as-code and what-if, deny: no-op, audited, grounded and citations valid?, abstain to HIL, confidence over threshold?, execution-eligible to risk gate.](../../diagrams/generated/fdai-roadmap-architecture-llm-strategy-01.en.svg)

### Rubric Gate (hallucination filter)

An optional fifth leg scores the candidate's reasoning against fixed criteria
(faithfulness, evidence-action alignment, completeness, coherence) and folds the
minimum score into confidence with `min()` - **subtractive only**, so a rubric can
lower eligibility but never raise it. Ships shadow-first (judge-and-log until a
promotion gate is met) and fails closed to HIL on evaluator error. The judge MUST be a
distinct publisher from the proposer (a model must not grade its own answer). Full
design: [hallucination-rubric-gate.md](../decisioning/hallucination-rubric-gate.md).

## Prompt-Injection Defense

Event payloads and tool outputs are **untrusted** and may carry direct or indirect prompt
injection ([security-and-identity.md](security-and-identity.md)).

- Treat all payload and tool-output text as **data, not instructions**; the model must not
  follow instructions embedded in it. Delimit and quarantine untrusted spans in the prompt.
- **Indirect injection**: outputs returned from tools/RAG are re-fed to the model - apply the
  same quarantine and never let retrieved text change the action contract.
- The **verifier and policy re-check are the authority**; a candidate that only "sounds"
  approved but fails deterministic checks is denied.
- Redact secrets and identifiers **before** any model call (see below), so an injection cannot
  exfiltrate them through generated output.

## Data Privacy and Residency

- **Minimize and redact**: strip secrets, connection strings, and any customer/tenant/
  subscription identifiers from prompts before a model call; send the least payload needed.
- **Residency routing**: route sensitive events to a local/in-region model (e.g. local
  embeddings) by config; do not send restricted data to an external endpoint.
- **No-train / retention**: prefer endpoints with a **no-training** guarantee and minimal
  retention for submitted prompts; record the chosen posture per capability in config.

## Provider Abstraction

- All model calls go through a **provider-neutral client** in `shared/` so models can be
  swapped without touching `core/tiers`.
- Configure models by capability, not hard-coded name: `t1.embedding`, `t1.judge`, `t1.vision`,
  `t2.reasoner.primary`, `t2.reasoner.secondary`, `t2.rca`.
- **Client contract**: enforce request timeouts, structured/JSON-schema output, token
  accounting, and reproducible settings (temperature 0 and a fixed seed where supported) so
  cross-checks and replays are comparable.
- **Versioned mapping**: the capability→concrete-model mapping is versioned; the exact model
  IDs and config version used for a decision are recorded in the audit log for replay.
- Route to Azure OpenAI, other Azure Foundry models, or third-party endpoints purely by config,
  keeping the core CSP-neutral.

### Heterogeneous Endpoint and Gateway Contract

FDAI resolves model capability, provider, route, wire protocol, authentication, and capacity as
separate fields. A deployment can therefore use Azure OpenAI directly, Azure OpenAI through Azure
API Management (APIM), or an OpenAI-compatible self-hosted GPU model through APIM without changing
the T1/T2 core contracts.

`resolved-models.json` optionally carries `endpoint_bindings`. Each verified binding declares:

- **Provider and route:** `azure-openai` or `self-hosted`, independently from `direct` or
  `apim-gateway`.
- **Wire protocol:** Azure deployment paths (`azure-openai`) or `/v1` paths with a request-body
  model id (`openai-v1`).
- **Authentication:** Entra audience or a credential reference. Runtime T1/T2 bindings currently
  require Entra; an unsupported auth kind blocks startup instead of falling back to a direct
  endpoint.
- **Capacity:** `tpm`, `ptu`, or `gpu` with one positive value. PTU and GPU values are never
  converted as if they were TPM.
- **Features and provenance:** Streaming, embeddings, structured output, tool calling, discovery
  source, a resource-reference digest, and verification time.

Endpoint URLs and credentials are not serialized in the operator projection. The binding stores an
opaque `endpoint_ref`; the composition root resolves it to an HTTPS URL from protected deployment
configuration. A binding without an injected resolver fails startup. Embedding, proposer, primary
and secondary cross-check, Critic, Judge, RCA, and narrator paths use the same request-target
builder. Legacy files without `endpoint_bindings` keep the direct Azure OpenAI path.

APIM is a route and governance boundary, not a model publisher. The mixed-model quality gate still
compares the publishers and families behind the gateway. Primary and secondary capabilities remain
separate bindings even when they share an APIM hostname, and a same-publisher pair is still invalid.

Self-hosted endpoints are never discovered by scanning a virtual network or trusting `/v1/models`
alone. They enter the candidate set through a publisher-keyed, domain-separated Ed25519 registration
(`fdai.model-endpoint-registration.v1`). Invalid signatures are rejected before parsing. Capability
probes and quality replay remain required before a registered GPU model can leave shadow mode.

Provisioned capacity discovery uses the Azure Model Capacities management API. The live resolver
first selects the latest generally available model version from the regional catalog, then queries
the subscription-scoped capacity endpoint with model format, family, and version. It filters the
response by region and provisioned SKU, follows only bounded `management.azure.com` pagination, and
uses `availableCapacity` as PTU. Missing catalog versions, malformed responses, untrusted next links,
or unavailable service capacity fail closed to `hil-only`.

An APIM route must return `x-fdai-model-backend`, `x-fdai-capacity-unit`, and
`x-fdai-spillover` response headers. T2 proposer and cross-check clients reject an otherwise
successful response when this evidence is missing or malformed. Accepted evidence appends a
redacted `selected` transition through the durable model-health sink, recording the actual backend,
TPM/PTU/GPU unit, spillover decision, and binding id. Endpoint URLs, APIM request ids, and provider
error text are not persisted.

The optional Terraform package under `infra/modules/llm/apim-ai-gateway` attaches one capability to
an existing APIM instance. It validates the FDAI caller's Entra audience, authenticates APIM to both
Azure OpenAI backends with managed identity, sends the first request to PTU, retries exactly once to
a same-family Standard deployment on HTTP 429, and emits the mandatory evidence headers. It never
creates an APIM service. Root composition keeps the module disabled by default, so the minimum-cost
day-zero inventory is unchanged.

`fdai-model-endpoint-discovery` is the protected management-plane merge command. Its strict config
lists expected Azure OpenAI accounts/deployments and APIM APIs/backends; it accepts no endpoint URL
or credential value. The Azure source verifies account kind, deployment readiness, model
family/version, SKU, and TPM/PTU capacity. The APIM source verifies the API, both backend ids,
managed-identity policy, HTTP 429 switch, and all FDAI evidence headers. Duplicate capability routes
fail before output. The command merges verified bindings into an existing `resolved-models.json`
using an atomic mode-`0600` write and refuses overwrite without `--force`.

Signed self-hosted registrations use the same source aggregation path through an injected
`Ed25519SignedRegistrationSource`. This keeps raw GPU endpoints out of the generic Azure discovery
config and requires a publisher key before the registration document is parsed.

## Model Provisioning and Lifecycle

Model availability, versions, and deprecations shift continuously. Hard-coding a model id
guarantees rot. The provisioning model below keeps the capability→concrete-model mapping
**automatic at bootstrap and reviewed at update time**, with model changes flowing through
the same shadow-before-enforce discipline as any other change.

### Capability Binding Policy

`rule-catalog/llm-registry.yaml` defines upstream defaults. An Owner can submit one revisioned
environment policy for each T1 or T2 capability when regional or provisioned-throughput (PTU)
constraints require a narrower binding. The policy is a governance draft, not a runtime switch:
the Operator API stores intent while only a reviewed protected plan can replace the active artifact.

| Selection mode | Resolver behavior | Failure behavior |
|----------------|-------------------|------------------|
| `auto` | Evaluate complete registry candidates in order. | Continue to the next candidate; use `hil-only` if none qualify. |
| `pinned` | Evaluate only the requested publisher, family, SKU, and capacity. | Hold for human review; never substitute another family. |
| `hil-only` | Bind no model for the capability. | Keep dependent decisions at human review. |

```yaml
capability: t2.reasoner.primary
selection_mode: pinned
publisher: OpenAI
family: gpt-4o
sku: GlobalProvisionedManaged
capacity: { unit: ptu, value: 30 }
```

- **Environment scope:** Policies affect one deployment environment, not one user or conversation.
- **Exact plan:** Assessment selects a compatible GA version; protected planning pins that exact
  version, SKU, capacity, policy digest, and active artifact digest for apply.
- **Candidate completeness:** `auto` evaluates complete publisher-family-version-SKU-capacity
  candidates. Missing TPM or PTU capacity advances to the next preference.
- **Capacity units:** Standard SKUs use TPM. Provisioned SKUs use PTU without conversion.
- **T2 pair atomicity:** Primary and secondary must resolve to distinct publishers unless held.
- **No Console authority:** Draft, assessment, and plan requests perform no provider mutation.
- **Independent tools:** Search, RCA, rubric, escalation, and tool calling retain separate gates.

### Bootstrap Provisioner

At `azd up` (or equivalent) the resolver combines the registry with the approved environment
policy, queries the target region's Azure OpenAI / Foundry catalog and capacity surfaces, and
provisions **one deployment per concrete capability**;
virtual `t1.vision` reuses matching narrator deployments. The resolved `{capability → deployment}`
mapping is written to Key Vault and audited.

The full **deployer-permission gate table** (what happens when the deployer identity lacks
`Cognitive Services Contributor`, when a preferred family is missing from the region, when
`capacity_tpm` quota is short, or when the mixed-model invariant cannot be satisfied) is
authored in
[dev-and-deploy-parity.md § Deployer-Scoped LLM Provisioning](../deployment/dev-and-deploy-parity.md#deployer-scoped-llm-provisioning);
this section shows the happy-path shape.

![Bootstrap Provisioner. The main stages are Terraform / Bicep: azd up, Azure OpenAI or Foundry resource, resolver, llm-registry.yaml, query catalog: / available families + versions in region, for each capability: / first preference available, mark capability hil-only / report completeness impact, create deployment / with TPM or PTU capacity, verify mixed-model invariant: / primary.publisher ≠ secondary.publisher, FAIL, write resolved-models.json to Key Vault / + audit entry.](../../diagrams/generated/fdai-roadmap-architecture-llm-strategy-02.en.svg)

**Bootstrap invariants (MUST)**
- Environmental failures such as a missing role, unavailable preferred family, or zero
  quota mark the affected capability `hil-only` and continue. The provisioning assessment
  makes that degradation visible and a deployment can choose `--assess-fail-on critical`
  to block it.
- When both T2 reasoners resolve outside explicit `hil-only` mode,
  `t2.reasoner.primary.publisher` and `t2.reasoner.secondary.publisher` MUST differ.
  A same-publisher pair is a hard resolver error.
- The resolved mapping records `{deployment, family, version, publisher}` per capability
  so the audit log can name the exact model that decided any case.

### Provisioning Completeness Gate

The resolver degrades an unprovisionable capability to `hil-only` and continues -
it never blocks the whole bootstrap on one missing family - so a **partial
deployment is silent**: `resolved-models.json` can carry only the T1 pair plus
`t2.reasoner.primary` while the registry also declares a secondary reasoner, a
critic, an RCA reasoner, and an escalation ceiling. The composition root then
quietly falls back to a forced-disagree cross-check and every T2 case routes to
HIL, with no signal at deploy time that the reasoning tier is effectively off.

[`assess_provisioning`](../../../services/core-control-plane/src/fdai/rule_catalog/schema/provisioning_assessment.py)
closes that gap. It compares the authoritative `llm-registry.yaml` (intended)
against `resolved-models.json` (actual) and returns a deterministic
`ProvisioningReport`:

- each declared capability is classified `resolved` / `capacity-reduced` /
  `hil-only` / `missing`, tagged `core` / `quorum` / `optional`, with the runtime
  impact of its absence;
- `quorum_ok` reports whether the mixed-model T2 cross-check can form (both
  reasoners available, distinct publishers) - not expected in `hil-only` mode;
- a `ProvisioningSeverity` rolls up to `ok` (all resolved), `degraded` (only
  optional capabilities missing - debate / RCA / escalation / rubric off is
  tolerable), or `critical` (a core capability missing or the quorum cannot form,
  so T2 is effectively off).

The deploy pipeline gates on the severity and writes the report to the audit log
(an A2 operational alert on `critical`), so a half-provisioned reasoning tier is
visible at `azd up` time rather than as a silent runtime HIL storm.

The bootstrap CLI exposes this directly: `fdai-llm-resolver --assess-fail-on critical`
prints the assessment to stderr (an `A2 alert:` line on `critical`) and exits non-zero,
so a CI deploy stage blocks before shipping a reasoning tier that would silently route
every T2 case to HIL. The default `--assess-fail-on none` stays report-only for backward
compatibility.

### Runtime Resolution

Core code depends only on the capability contract. `resolved-models.json` is loaded from
Key Vault at startup; a stale reference (deployment deleted or 404) **fail-closes to HIL**,
not to a different capability.

```python
# core/tiers/t2-reasoning/reasoner.py (illustrative)
primary   = client.for_capability("t2.reasoner.primary")
secondary = client.for_capability("t2.reasoner.secondary")
cand_a = primary.chat(...)
cand_b = secondary.chat(...)
if not agree(cand_a, cand_b):
    escalated = client.for_capability("t2.reasoner.escalated")   # cost-capped
    return arbitrate(cand_a, cand_b, escalated.chat(...))
return quorum_result(cand_a, cand_b)
```

- No model id appears in `core/`.
- A missing deployment is treated as an outage: the request routes to HIL and emits an
  operational alert (A2 per [channels-and-notifications.md](../interfaces/channels-and-notifications.md#3-categories-a1a4)).
  A silent switch to a different capability isn't supported.

### Escalation Ladder Policy

The `if not agree(...): escalated = ...` step above is a **policy decision**, not a
hard-coded branch. It is implemented as a pure, deterministic function in
[`core/quality_gate/escalation_ladder.py`](../../../services/core-control-plane/src/fdai/core/quality_gate/escalation_ladder.py)
(`decide_escalation`), mirroring the sibling
[`debate_router`](../../../services/core-control-plane/src/fdai/core/quality_gate/debate_router.py): a frozen
`EscalationLadderConfig` plus a stateless function that answers "climb to the
stronger model, or stop and route to HIL?". Shipping the policy on its own -
testable and auditable before any live wiring - follows the debate-router
delta-2a -> delta-2b sequence. The `QualityGate` records the decision in
**shadow** (`QualityDecision.escalation_route` / `escalation_reason`, plus the
`self_consistency` stability it read, surfaced by
`quality_decision_audit_fields`) when an `EscalationLadderConfig` is wired -
measured, never acted on; actually invoking the escalated model is the next
enforce step. The `on_self_consistency_below` trigger reads the
`action_stability` signal the composition root's self-consistency cascade
places on the candidate - the gate never samples a model itself (the sampler's
"cascade trigger is a composition concern" contract).

Before any trigger can climb, the ladder requires a trusted count of validated
ontology, rule, or deterministic-evidence improvements. The default minimum is 10. The count comes
from orchestration, never from the model candidate, and both the count and configured minimum are
recorded in `escalation_metadata`. A missing count defaults to 0 and therefore stops safely with
`ontology_improvement_budget_remaining`. This remains shadow observation until durable case-history
orchestration supplies the count and a separate promotion enables invocation.

The ladder rungs (`EscalationTier`) map one-to-one onto the registry capabilities:
`PRIMARY` -> `SECONDARY` -> `ESCALATED`. `decide_escalation` returns `ESCALATE`
(spend the next-stronger reasoner as a tiebreaker) or `STOP` (the caller routes the
unresolved case to HIL), under these hardening invariants:

- **The ladder never grants execution eligibility.** It decides only whether to
  *spend a stronger model*. The escalated model's proposal is untrusted and re-enters
  the same quality gate (verifier + grounding + quorum); a disagreement is never
  auto-resolved by climbing - the deterministic verifier stays the sole authority.
- **Fail-closed.** `escalated_available=False` (a fork that did not resolve
  `t2.reasoner.escalated`) returns `STOP`, above the deny-list in precedence.
- **Cost-bounded.** A single call climbs at most one rung and never past the
  `ESCALATED` ceiling; `enabled=False` is a killswitch for a cost spike.
- **Ontology-first.** A configured trigger still stops until the trusted validated-improvement
  count reaches `minimum_ontology_improvement_attempts`.
- **Triggers.** `cross_check_disagreement` (primary, mirrors the registry's
  `invocation: on_disagreement`) plus an optional `on_self_consistency_below`
  threshold (escalate when the self-consistency sampler reports a wavering proposer,
  even on nominal agreement). A per-ActionType `never`/`always` list tunes it, deny
  winning over allow.

Resolved model family is passed separately from the deployment alias to each T2 adapter. GPT-5
and o-series chat families send `max_completion_tokens` and omit custom `temperature`; classic
chat families retain `max_tokens` and `temperature`. This applies consistently to RCA, proposer,
and cross-check requests, including primary latency-pool members, so a friendly deployment alias
cannot select the wrong wire fields.

### Narrator routing and latency

Narrator deployment selection, multimodal probes, per-user preference, TTFT, web-search pooling,
and runtime delivery decisions are owned by
[Narrator Routing and Latency](../interfaces/narrator-routing-and-latency.md). T2 quality-gate
assignments remain system-governed; the same-publisher T2 primary exception follows below.

### T2 Primary Routing and Governed Recovery

T2 uses two separate recovery scopes. Per-call latency routing selects among deployments inside
the `t2.reasoner.primary` slot. Cross-request proposer recovery changes which registered proposer
route is preferred only through the governed action pipeline. Neither scope grants model output
authority or weakens the mixed-model quality gate.

- **Same-publisher latency pool:** Every primary-pool deployment shares one publisher, and that
  publisher remains distinct from `t2.reasoner.secondary`. Only the primary slot is latency-routed;
  the secondary cross-check, Critic, Judge, and escalation ladder keep fixed roles. The resolver
  rejects a cross-publisher pool. `llm.t2_primary_latency_routing` defaults to `true`, activates
  only for at least two emitted candidates, and leaves a single primary unchanged.
- **Bounded in-call selection:** The router records the selected deployment, classifies failures
  without provider error text, applies bounded cooldown, and tries each remaining same-publisher
  deployment at most once. It never substitutes the cross-check secondary as the latency primary.
  `ModelHealthTransitionSink` persists selected, unhealthy, and recovered deployment state; its
  failure does not turn a failed model call into success or block an already successful proposal.
- **Budgeted proposer fallback:** `BoundedFailoverT2Proposer` reserves shared T2 budget before each
  actual invocation and tries at most the registered `primary` and `secondary` proposer routes once
  each. Every candidate remains untrusted and re-enters the same verifier, grounding, cross-check,
  and risk gates. Budget exhaustion or total candidate failure returns no weaker judgment.
- **Durable evidence:** Each attempt emits a sanitized `T2AttemptReceipt` with route role, attempt,
  status, failure class, terminal state, and recovery state, but no endpoint or exception text. The
  runtime stores the receipt and audit entry before Huginn ingress, retries unforwarded receipts,
  and can materialize bounded legacy failures without replaying a provider call.
- **Governed route change:** A recovered receipt remains informational. Only terminal candidate
  exhaustion becomes a Heimdall anomaly and Forseti `hil` decision for
  `ops.switch-t2-proposer-route`. Var carries the approval, Thor performs the idempotent CAS route
  change, Saga preserves the audit chain, and Vidar restores only the failed correlation's change.
  A stale rollback cannot overwrite a newer route revision. The ActionType stays shadow-first and
  requires human approval before any enforced switch.
- **Read-only visibility:** Route state and receipts survive restart. Operator projections can show
  model health and sanitized recovery details, but cannot switch a route, clear cooldown, approve,
  or promote a deployment.

Composition binds these observers and selectors only when the configured proposer exposes the
corresponding protocols. Otherwise the existing single-route behavior remains unchanged.

### Reconciler Job

The planned weekly Job watches newer preferred families, deprecations within 60 days, and measured capacity or quality drift. It opens only a bounded issue or draft PR and an A2 alert; it never changes the live mapping.
Proposal schema v2 compares SKU and effective capacity unit/value in addition to family, publisher, and status, so an in-place scale or replacement cannot be misclassified as no change.
An expired unmerged replacement lowers the capability to human review, and any accepted registry change still needs Owner review plus frozen-scenario shadow replay.

### Mixed-Model Family Strategies

The quality gate needs two independent model families. Which pair a fork actually gets is
a bootstrap-time choice:

| Mode | Where the secondary lives | When to pick |
|------|---------------------------|--------------|
| `azure-foundry` (default) | Anthropic / Mistral / Cohere models served through Azure AI Foundry model catalog | region and compliance allow non-OpenAI Foundry models; single billing surface |
| `external` | secondary via a direct third-party endpoint (Anthropic API, etc.) | required family unavailable in Foundry for the region |
| `hil-only` | no secondary provisioned; every T2 case routes to HIL | fork cannot obtain a second family (temporarily); explicit opt-in |

The chosen mode is a config value (`llm.mixed_model_mode`); the bootstrap resolver reads
it and enforces the invariant accordingly. Switching modes later is a governance PR, not
a runtime toggle.

### Fork vs Upstream Split

Upstream owns capability names, schemas, default preferences, resolver behavior, mixed-model
invariants, and generic Azure IaC. A fork supplies region, compliance, cost, schedule, alert,
resource, and resolved-model values through the supported configuration and DI boundaries.

## Rule-to-Decision Lookup Pipeline

The tier percentages in [Model Tiers](#model-tiers) are the *outcome* of a deliberate
**layered lookup pipeline**: an incoming event traverses cheap-to-expensive layers, and a
frontier LLM (L5) is reached only when every cheaper layer abstains. The pipeline is built
on a typed **ontology**: rules, resources, signals, and actions are ontology entities, and
matching them is a deterministic graph traversal rather than a text-similarity guess.

The ontology framing borrows the object-type / link-type / action-type separation from a
prior AGI ontology design (typed objects with cardinality-aware links, functions integrated
into actions via `required_interfaces` and `submission_criteria`), applied to CSP resources
and rules. This gives every rule a deterministic dispatch path and every reuse a
canonical, hashable signature.

### Ontology Foundation

The low-level rule-dispatch foundation starts with four **ObjectTypes**; [FDAI Operating Ontology](operating-ontology.md)
owns service, objective, decision, and effect semantics. The extensible registry keeps product objects such as Process,
Conversation, and ReviewCase plus meta objects such as ResourceType, SignalType, Property, and ActionType first-class. Declarations live in `rule-catalog/vocabulary/`; runtime instances use the shared ontology store.

| ObjectType | Meaning | Backing |
|------------|---------|---------|
| `Resource` | a target under governance (Azure resource; CSP-neutral schema, populated by the provider adapter) | `shared/providers/` |
| `Rule` | a deterministic control with an intent (`applies_to`, `evaluates`, `remediates`) | `rule-catalog/` |
| `Signal` | a typed observation (Activity Log line, drift diff, cost anomaly, canary result) - the primitive that enters `event-ingest` | `shared/contracts/event` |
| `Finding` | a rule match on a resource at a point in time, with context and severity | derived at runtime; persisted in the audit store |

Meta ObjectTypes make LinkType endpoints honest. `applies_to` targets `ResourceType`,
`triggered_by` targets `SignalType`, `evaluates` targets `Property`, and `remediates` targets
`ActionType`. They may have zero runtime instances on a deployment that reads the corresponding
catalog directly; their declarations still prevent endpoint aliases such as modeling an
ActionType as a Rule.

Every shipped ObjectType, LinkType, and ActionType declaration is evidence-governed: it cites a
source URL and resolved declaration version, records license and retrieval time, and carries a
loader-verified canonical content hash. Missing or stale provenance blocks catalog composition.

Relationships are **typed LinkTypes** with cardinality metadata, so traversal is O(indexed
lookup), not scan. Each declaration also carries `is_transitive`, `is_causal`, and
`temporal_order` flags so the traversal engine knows when a recursive expansion is safe and
when a query must respect time. A temporal LinkType also declares `order_by_property`, which
MUST resolve to an ordered property on its target ObjectType. The instance store enforces
cardinality before every link write, permits a repeated same-LinkType traversal only when
`is_transitive` is true, and returns temporal links in target-property order. These are runtime
invariants, not visualization hints.

| LinkType | Cardinality | Transitive | Meaning |
|----------|-------------|:---------:|---------|
| `applies_to` | Rule → ResourceType (M:M) | - | which resource types the rule may match |
| `triggered_by` | Rule → SignalType (M:M) | - | which signals cause the rule to be evaluated |
| `evaluates` | Rule → Property (M:M) | - | which resource properties the rule reads |
| `remediates` | Rule → ActionType (M:1) | - | which ontology action the rule proposes on match |
| `resource_of` | Signal → Resource (M:1) | - | which resource the signal is about |
| `overrides` | Override → Rule (M:1) | - | the override targets this rule (see [rule-governance.md](../rules-and-detection/rule-governance.md#overrides)) |
| `causes` / `prevents` | Rule → Outcome (M:M, causal) | - | causal metadata that T2 may reason over (rare) |
| `precedes` / `follows` | Finding → Finding (M:M, temporal) | - | correlation of related findings on one incident |
| `contains` | Resource -> Resource (1:M, parent -> child) | ✓ | ownership / scope containment: subscription -> resource-group -> resource, VNet -> subnet, cluster -> node-pool. Recursive traversal follows the stored parent-to-child direction. Populated by the [inventory adapter](csp-neutrality.md#5-inventory-contract--resource-graph). |
| `attached_to` | Resource → Resource (M:1) | - | lifetime-bound attachment: NIC→VM, disk→VM, private-endpoint→target. Removing the parent breaks the child. |
| `depends_on` | Resource → Resource (M:M) | - | logical reference required for correct operation: ContainerApp→Key-Vault / ACR / Postgres, managed-identity→app. Broken edges degrade the dependent, not the target. |
| `peered_with` | Resource ↔ Resource (M:M, symmetric) | - | network peer represented by two independently supported directed records; one record never implies its reverse. |
| `routes_to` | Resource → Resource (M:1) | - | directed traffic path or reference such as a UDR next hop; absence never proves unreachable. |

Traversal is directional and cached; a `Signal` of type `T` on a `Resource` of type `R`
resolves to exactly the set of rules where `triggered_by ∋ T` and `applies_to ∋ R` via
two index intersections - no text search, no model call.

The Resource→Resource links (`contains`, `attached_to`, `depends_on`, `peered_with`, and
`routes_to`) are what let the risk-gate compute an *actual* blast radius
instead of the three-value enum in [risk-classification.md](../decisioning/risk-classification.md), and
what let T2 be prompted with a **depth-2 neighborhood subgraph** around the target
resource - grounded, cited context instead of a bare resource id. Their authoritative
source is the [inventory contract](csp-neutrality.md#5-inventory-contract--resource-graph);
`core/` never queries a cloud SDK for them. New link kinds MUST be added to
`shared/contracts/ontology/link-type.json` before an adapter can emit them - an
unrecognized link, like an unrecognized `ResourceType`, opens an issue rather than
auto-registering (self-extending ontology, see [Fork Extension](#fork-extension-self-extending-ontology)).

Runtime ObjectType properties and LinkType properties MUST be canonical JSON data. Mapping keys
are strings, numbers are finite, datetimes are timezone-aware and normalized to RFC 3339 UTC, and
unsupported Python objects are rejected at the write boundary. Both the in-memory and PostgreSQL
stores apply the same normalization so replay does not depend on the selected adapter.

### Concrete Rule semantics

Shipped Rules don't use wildcard ontology relationships. `triggered_by` references a reviewed
`SignalType`, `evaluates` references canonical `Property` identities, and
`implemented_by_policy` connects the Rule to a first-class `PolicyArtifact`. A bounded OPA AST
synchronizer verifies Rego package identity and property reads before catalog composition.

Raw events resolve through `vocabulary/signal-types.yaml`. Exact pattern matches select specialized
types; unmatched events select the single reviewed configuration baseline type. Semantic retrieval
may rank candidate Rules, but exact ids and graph links remain the authority for dispatch and
grounding.

### Rule as Ontology Artifact

Rule schema v2 in
[rule-catalog-collection.md](../rules-and-detection/rule-catalog-collection.md) carries the
ontology fields the pipeline dispatches on. It migrates the former scope-map meaning of
`applies_to` to `scope_predicates`; every dispatch field is validated by CI at load.

```yaml
# rule-catalog/rules/example.yaml (illustrative fragment; full schema in rule-catalog-collection.md)
id: object-storage.public-access.deny
version: 1.2.0
source: authored
severity: high
category: security
resource_type: object-storage
check_logic: <opa-package-ref>            # deterministic evaluator
remediation: <action-ref>                 # points to an ontology ActionType instance

# ── ontology fields (new; CI-validated) ──
applies_to:    [object-storage]
triggered_by:  [property.public_access.changed, config.public_access.enabled]
evaluates:     [object-storage.public_access]
scope_predicates: {}                         # optional labels/tags/scope filters
remediates:    remediate.disable-public-access
required_interfaces: [Evaluable, Remediable]   # submission_criteria enforced at load
submission_criteria:
  - kind: resource_type_registered
    value: object-storage
provenance: { ... }
```

`required_interfaces` and `submission_criteria` follow the same
Functions-plus-Interfaces pattern as the referenced ontology design: a rule is only
dispatchable when its interface contract is satisfied on the runtime object, and CI
rejects a rule whose `applies_to` / `triggered_by` cannot be resolved against the
schema registry.

`resource_type` remains the canonical single target used by existing policy and remediation
code; it MUST occur in `applies_to`. `scope_predicates` carries the former label/tag scope map so
it cannot be confused with the type axis. Existing and newly collected rules are backfilled with
`triggered_by: ["*"]` and `evaluates: ["*"]` only when the upstream source supplies no narrower
metadata. The wildcard is an explicit catch-all, not an inferred signal. TrustRouter and T0 use
the same `applies_to` x (`triggered_by` exact or `*`) intersection.

### Pipeline Stages and ActionTypes (distinct concepts)

Two things are called "action" in this system and MUST NOT be conflated:

- **PipelineStage** - where in the layered lookup a decision was made. This is an
  **audit vocabulary**, not a schema artifact. Every audit-log entry records the
  `pipeline_stage` field so the decision path is reconstructable end-to-end. Stages are
  read-only from the executor's perspective (no CSP mutation happens here except at
  `remediate`).
- **ActionType** - a **CSP-neutral mutation category** with a rollback contract. Declared
  in `shared/contracts/ontology/action-type.json`; instances (e.g.
  `remediate.disable-public-access`) live in the catalog and are referenced from a rule's
  `remediates` field. This is the schema artifact.

Only `remediate` couples the two: it is a PipelineStage (the executor step) whose
output is an ActionType **instance** applied to a Resource. `escalate` / `abstain` / `deny`
are terminal stages that never invoke an ActionType.

**PipelineStage vocabulary** (recorded in `audit_log.pipeline_stage`):

| PipelineStage | Layer | Cost | Preconditions | Terminal? |
|---------------|-------|------|---------------|:---------:|
| `L1_evaluate` | L1 (T0) | pure function, in-memory OPA/Rego | rule's `applies_to` matches Resource; `check_logic` compiled | - |
| `L1_simulate` (what-if) | L1 (T0) | pure function against declarative state | resource state snapshot available | - |
| `L2_reuse` | L2 | O(1) indexed SELECT | `(signature, rule_id, catalog_version)` hit in learned-action store | - |
| `L3_similarity` | L3 (T1) | 1 embedding + pgvector kNN | context compatibility check passes on the neighbor | - |
| `L4_cache_hit` | L4 | O(1) key lookup | signature match within TTL and catalog / model version | - |
| `L5_reason` | L5 (T2) | frontier LLM (primary + secondary; escalated on disagreement) | quality-gate authoritative | - |
| `remediate` | risk-gate ⇒ executor ⇒ delivery | apply an ActionType instance to a Resource | policy-as-code verifier passed; all ActionType preconditions hold | - |
| `escalate` | risk-gate ⇒ ChatOps | HIL request | no cheaper layer resolved the case | ✓ |
| `abstain` | any layer | audited no-op | grounding unavailable or verifier abstained | ✓ |
| `deny` | any layer | audited no-op | risk-classification blocked the action | ✓ |

Only `L5_reason` invokes the LLM. Every other stage is deterministic and executes in
microseconds to milliseconds.

### ActionType Contract

An **ActionType** ([schema](../../../services/core-control-plane/src/fdai/shared/contracts/ontology/action-type.json))
declares one CSP-neutral mutation category and the safety invariants for every instance
of it. All fields except `preconditions` / `stop_conditions` / `blast_radius` /
`description` are required.

- `name` - stable id (e.g. `remediate.disable-public-access`).
- `operation` - CSP-neutral verb from the enum below.
- `interfaces` - runtime contracts the executor honors; risk-gate composes its feature
  vector from this set.
- `rollback_contract` - how instances are undone. **`none` is not a valid value**; every
  ActionType MUST declare an undo path, even a best-effort one. Genuinely one-way
  mutations set `irreversible: true` (below) and are routed HIL+quorum by
  risk-classification, they do NOT silence rollback.
- `irreversible` - true only when the pre-action state cannot be fully restored (e.g.
  `purge` of a soft-deleted resource). Rollback_contract is still required and describes
  best-effort recovery.
- `default_mode` - every upstream ActionType MUST ship as `shadow`. Promotion to enforce
  is a separate governed action after its promotion gate passes.
- `promotion_gate` - measurable criteria (`min_shadow_days`, `min_samples`,
  `min_accuracy`, `max_policy_escapes`) a shadow-mode ActionType MUST clear on the
  frozen scenario set before an assignment can promote it to enforce. Rule assignments
  may tighten these values, never loosen them.
- `preconditions[]` - deterministic checks the T0 verifier evaluates BEFORE the action
  reaches the risk-gate. A failing precondition MUST abstain, never partially apply.
- `stop_conditions[]` - deterministic conditions the executor evaluates DURING or AFTER
  apply. Any true value auto-halts and triggers rollback per `rollback_contract`.
- `blast_radius` - how the risk-gate computes the blast-radius classification dimension
  for an instance. `static_enum` uses a fixed bucket; `graph_derived` walks Resource →
  Resource links (default: `contains` + reverse `depends_on`, depth 2) and counts
  affected Resources. Instances exceeding `max_affected_resources` abstain and escalate.
  Traversal implementation lands with the risk-gate (P2); P1 only records the declaration.

#### Operation Verbs

The `operation` enum is CSP-neutral. Each verb has a fixed semantic so rule authors and
provider adapters agree on intent.

| Verb | Semantic | Rollback default |
|------|----------|------------------|
| `create` | provision a new Resource | `pr_revert` (destroy in the same PR) |
| `update` | in-place property change (non-destructive) | `pr_revert` (prior property values in the diff) |
| `delete` | remove a CSP-level Resource | `snapshot_restore` (pre-delete snapshot) |
| `disable` | turn off without deleting | `state_forward_only` via `enable` |
| `enable` | inverse of `disable` | `state_forward_only` via `disable` |
| `tag` | metadata-only mutation | `pr_revert` |
| `drop` | DB-DDL removal (schema / object) | `pitr` |
| `purge` | soft-delete then hard-delete; `irreversible: true` | best-effort `snapshot_restore` |
| `scale` | count / SKU adjustment | `pr_revert` to prior spec |
| `restart` | in-place process/pod bounce | `scripted` or `state_forward_only`, depending on the provider contract |
| `failover` | trigger managed failover; `RequiresMaintenanceWindow` | `scripted` (failback) |
| `rotate` | secret / cert rotation | `snapshot_restore` (prior version retained) |
| `revert` | explicit rollback of a prior action instance | `pr_revert` on the revert PR itself |
| `attach` | create a Resource → Resource link (PE→target, MI→App, disk→VM) | `state_forward_only` via `detach` |
| `detach` | remove such a link | `state_forward_only` via `attach` |
| `quarantine` | network/policy isolation without deletion | `state_forward_only` (lift the isolation policy) |

#### Interfaces

The `interfaces` set on an ActionType names runtime contracts the executor MUST honor. A
missing interface is not "allowed anything" - the risk-gate refuses to auto-execute an
ActionType whose interface set does not cover the safety-invariant requirements for its
`operation`.

| Interface | Meaning |
|-----------|---------|
| `ControlPlane` | Touches only CSP metadata / configuration (never user data). Baseline for auto candidates. |
| `DataPlaneMutating` | Touches user data. **HIL by default** regardless of blast radius. |
| `IdempotentByKey` | Safe to retry with the same idempotency key; the executor's dedup uses this key. |
| `RateLimited` | Must respect a bucket cap (per-resource, per-tier, or global); overflow degrades to HIL. |
| `RequiresInventoryFresh` | MUST NOT fire if the target Resource's inventory record is stale beyond `freshness_ttl`. Prevents acting on ghost resources - the inventory contract ([csp-neutrality.md § 5](csp-neutrality.md#5-inventory-contract--resource-graph)) supplies the freshness cursor. |
| `GraphTraversalRequired` | Blast-radius calculation depends on Resource → Resource links (`contains` / `attached_to` / `depends_on`). If the graph is unavailable, the ActionType abstains. |
| `CrossResource` | Mutation touches multiple Resources; the executor acquires N per-resource locks in a deterministic order to stay deadlock-free. |
| `AsymmetricRollback` | Rollback path is not the exact inverse (e.g. PITR may lose Δ-data). Forces auto → HIL demotion; auto is never selected regardless of other dimensions. |
| `RequiresMaintenanceWindow` | Only executes inside an approved window (P3 chaos / DR). Missing window scheduler → abstain, never fall through to a bare execute. |


### Layered Lookup Pipeline

![Layered Lookup Pipeline. The main stages are Signal arrives, L0. event-ingest / normalize + dedup + correlate into incident, no-op, audited, L1. T0 rule match / ontology traversal: applies_to ∩ triggered_by / run each rule's evaluate action (OPA/Rego, in-memory), risk-gate, L2. Learned-action lookup / (signature, rule_id, catalog_version) → verified action, L3. Embedding similarity (T1) / 1 embedding call → pgvector kNN / reuse neighbor.action iff cos > threshold and context compatible, L4. T2 result cache / signature includes catalog_version + model_config_version + mode, L5. T2 cascade / primary → agree? → done / disagree? → escalated / quality-gate authoritative, writeback: promote verified outcome / into L2 (learned action) + L4 (result cache).](../../diagrams/generated/fdai-roadmap-architecture-llm-strategy-03.en.svg)

**Expected hit distribution** (design targets, subject to measurement per
[goals-and-metrics.md](goals-and-metrics.md)):

| Layer | Cost per hit | Design share of incoming events |
|-------|--------------|--------------------------------|
| L0 dedup / correlate | µs | folds N events → 1 incident (compression, not a coverage number) |
| L1 T0 | µs, in-memory | ~70-80% |
| L2 learned-action | ms, indexed SELECT | grows over time as L5 outcomes distill down |
| L3 embedding similarity | ~1 embedding call + kNN | remainder of the T1 ~15-20% band |
| L4 T2 cache | O(1) key | absorbs repeats of unresolved-but-recent cases |
| L5 T2 cascade | frontier LLM | **~5-10% only** - the actual token spend |

Two structural consequences:

- **LLM usage decreases over time**, not increases. Every L5 verified outcome writes back
  to L2, so a recurring case that took a full T2 cascade last week is a hash lookup this
  week. This is the concrete mechanism behind the "use the LLM less" principle.
- **A rule change invalidates the right rows automatically** (see below). No manual cache
  bust; no stale reuse survives a promotion or a demotion.

### Signature Composition

The signature that keys L2 and L4 is a canonical hash over ontology-typed fields, so
recording and reuse are semantics-aware, not string-similar.

```text
signature = sha256(
  Signal.type,
  canonical(Signal.params),                # sorted, redacted, typed
  Resource.type,
  canonical(Resource.props),               # only props referenced by evaluates
  Rule.id, Rule.version,
  Catalog.version,
  Model.config.version,                    # L4 only; L2 omits (model-independent reuse)
  Mode                                     # shadow | enforce
)
```

- **Redaction runs before hashing** so a secret can never enter a signature.
- **Only properties named in `evaluates`** participate, so unrelated resource churn does
  not invalidate reuse.
- **Catalog / model version bumps** and **shadow ↔ enforce transitions** force new
  signatures, guaranteeing the invalidation rules in [Cost Controls](#cost-controls) are
  applied without a separate cache-flush step.

### Reuse Audit (every layer, including hits)

Autonomy requires that a decision - including one produced by a reuse - is fully
attributable. Every layer writes an audit entry with:

- `layer` (L1..L5)
- `rule_id` and `rule_version` that fired
- `signature` and how it matched (exact hit / cos similarity + score / cache age)
- `reused_from`: back-reference to the audit_id whose outcome was reused (L2/L4)
- `mode` (shadow / enforce) and the resulting risk-gate decision

A reuse without a resolvable `reused_from` is a defect - the audit chain must be walkable
from any decision back to the L5 outcome that originally verified it, and forward to the
rule/model versions in effect.

### Fork Extension (self-extending ontology)

The ontology is **domain-agnostic in the core** and **extensible per fork**. A fork adds
`ObjectType` and `LinkType` catalog entries in its own package and binds a provider that emits
records conforming to those definitions; it never edits `core/` or the upstream contract
package.
- New `Resource` subtypes enter through reviewed catalog entries and inherit the pipeline
  automatically - `evaluate`, `reuse`, and `similarity` work over them with no code change
  in `core/`.
- New `LinkType`s (e.g. a fork-specific causal relation) declare their cardinality,
  transitivity, and reasoning metadata; unused links stay inert.
- New `ActionType`s (e.g. a fork-specific delivery adapter) declare their
  `required_interfaces` and `submission_criteria`; a rule that references an unregistered
  action fails at catalog load, not at runtime.
- Autoprovisioning: an unrecognized ResourceType observed in a Signal opens an issue
  (never auto-registers), so the ontology extends by review, not by drift.

### Ontology Storage Layout

The complete storage, schema, and boot/reload design now lives in
[rule-lookup-ontology-storage.md](rule-lookup-ontology-storage.md).

## Cost Controls

- **Cache** T1/T2 results keyed by a signature that includes the **normalized event
  signature + rule-catalog version + model-config version + shadow/enforce mode**. This makes
  the cache correct across change: a catalog or model-config bump invalidates stale entries.
- **Invalidation**: apply a TTL and invalidate on rule-catalog promotion; **never** serve an
  `auto` result for a case that a fresh evaluation would send to HIL, and never reuse a
  shadow-mode result to satisfy an enforce-mode decision.
- **Budget guards**: per-tier token budgets and rate limits; overflow degrades to HIL, never to
  an ungated auto-action.
- **Provider failure handling**: on timeout, rate-limit, or outage, fail **closed** - retry with bounded backoff,
  fall back to the secondary provider, then degrade to HIL through a circuit breaker. Each actual proposer candidate reserves one shared-budget call; sanitized attempt receipts retain only route role, failure class, status, and trace identity.
  Terminal exhaustion enters Huginn, Heimdall, and Forseti to create a real HIL ActionRun; recovery success remains an observation and opens no other approval. Never retry indefinitely or auto-execute an unverified candidate.
- **Outcome-Driven Token Economics**: maximize verified operational value while minimizing model calls, tokens, latency, and cost. Use provenance-linked ontology facts and T0/T1 reuse before direct source-document RAG. Give residual cases minimum grounded context and the smallest model proven sufficient; reserve direct retrieval, stronger models, cross-checks, and human approval for ambiguity or risk. Accuracy, evidence quality, and safety remain hard constraints.

## Improving T1 (Distillation)

To keep shifting load down-tier (the "use the LLM less" lever), T1 can be strengthened over
time - options to evaluate, not commitments:

- **Learned-action reuse**: promote verified T2 outcomes into learned actions T1 can match.
- **Distillation / fine-tuning**: distill accepted, verified T2 judgments into the small T1
  model to raise its coverage.
- **Constraint**: training data and fine-tuned artifacts must be **customer-agnostic** and stay
  in a downstream fork, never committed upstream
  ([generic-scope.instructions.md](../../../.github/instructions/generic-scope.instructions.md)).
  A distilled model changes nothing about the gate: its output still passes the verifier.

## Quality Measurement

- **Eval harness**: a versioned golden scenario set with expected verdicts; models are scored
  offline via replay before promotion, producing a per-model, per-tier scorecard.
- **Hallucination rate**: measured as the share of generated candidates whose citations fail
  the grounding-validity check or whose action the verifier rejects, sampled and periodically
  human-labeled - not self-reported by the model.
- Track accuracy and hallucination rate per model and per tier; **regressions auto-block
  promotion** (shadow→enforce stays in shadow) per
  [security-and-identity.md](security-and-identity.md).
- Mixed-model disagreement rate is a monitored signal; a rising rate flags drift or a bad
  model. These feed the KPIs in [goals-and-metrics.md](goals-and-metrics.md).

## Open Decisions

Decide each by **measured cost/quality on the scenario set**, not assumption.

- [ ] Fork-side registry overrides: which preferences a specific fork pins in
      `rule-catalog/llm-registry.yaml` for its region and compliance posture.
- [ ] Default **mixed-model family strategy** (`azure-foundry` vs `external` vs
      `hil-only`) - the upstream ships all three; each fork must pick one at bootstrap.
- [ ] Reconciler cadence and the concrete deprecation-feed source for Azure OpenAI /
      Foundry (weekly is the default recommendation).
- [ ] Embedding model: hosted vs local (data residency, cost).
- [ ] Quorum size / N and the disagreement-escalation policy for mixed-model.
- [ ] Confidence-threshold values per vertical (Resilience, Change Safety, Cost Governance).
- [ ] Redaction ruleset and residency routing per event class.
- [ ] Cache TTL and the catalog-version invalidation trigger.
- [ ] Whether to distill T2 outcomes into T1, and the fork-side training pipeline.
