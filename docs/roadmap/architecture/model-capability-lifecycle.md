---
title: Model Capability Lifecycle
---
# Model Capability Lifecycle

This document owns endpoint binding, capability preferences, model provisioning, runtime
resolution, bounded proposer recovery, and lifecycle reconciliation for system-governed T1 and T2
models. Tier eligibility and deterministic quality gates remain in [LLM Strategy](llm-strategy.md),
while presentation-only selection remains in
[Narrator Routing and Latency](../interfaces/narrator-routing-and-latency.md).

## Heterogeneous Endpoint and Gateway Contract

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

### Capability Preferences Registry

Upstream defines the *capabilities* and a **preference list per capability**; a fork
overrides preferences to match its region, compliance posture, or cost target. The registry
is catalog-as-code (path `rule-catalog/llm-registry.yaml`) reviewed like any other
governance artifact.

```yaml
# rule-catalog/llm-registry.yaml (upstream defaults; fork MAY override)
models:
  t1.embedding:
    preferences:
      - { publisher: OpenAI, family: text-embedding-3-small }
      - { publisher: OpenAI, family: text-embedding-3-large }
    sku: Standard
    capacity_tpm: 100_000
  t1.judge:                       # small/cheap default (mini tier)
    preferences:
      - { publisher: OpenAI, family: gpt-4o-mini }
    capacity_tpm: 40_000
  t2.reasoner.primary:            # first frontier reasoner
    preferences:
      - { publisher: OpenAI, family: gpt-4o }
      - { publisher: OpenAI, family: gpt-4.1 }
      - { publisher: OpenAI, family: gpt-4-turbo }
    capacity_tpm: 20_000
  t2.reasoner.secondary:          # mixed-model peer - MUST be a distinct publisher
    preferences:
      - { publisher: Anthropic, family: claude-opus-4 }
      - { publisher: MistralAI, family: mistral-large-2 }
    capacity_tpm: 10_000
  t2.reasoner.escalated:          # Opus-class ceiling, on-demand only
    preferences:
      - { publisher: OpenAI, family: o1 }
      - { publisher: Anthropic, family: claude-opus-4 }
    invocation: on_disagreement                # not on every T2 call
    capacity_tpm: 5_000
```

Rules the registry enforces (MUST, at config load):

- **Family, not version.** Preferences pin the model *family* (e.g. `gpt-4o-mini`); the
  bootstrap resolver picks the latest stable version at provisioning time and records it in
  the resolved mapping. Never pin a dated version in the registry - it hides deprecation.
- **Capacity units are explicit.** Standard and Global Standard use `capacity_tpm` as a request ceiling.
  Azure usage `Count` values are converted from 1K TPM units; batch and fine-tune quota is excluded.
  `ProvisionedManaged`, `GlobalProvisionedManaged`, and `DataZoneProvisionedManaged` use `capacity_ptu`.
  Supplying TPM for a provisioned SKU or PTU for a standard SKU is invalid; overflow degrades to HIL.
- **Escalated capability is opt-in per invocation** (`invocation: on_disagreement`); it is
  not called on every T2 request and never bypasses the quality gate.
- **RCA reasoner is opt-in per invocation** (`invocation: on_novel_case`, capability
  `t2.rca`); it fires only on a novel incident the deterministic tiers could not resolve,
  and its output is refused unless grounded on the supplied evidence (see
  [observability-and-detection.md](../rules-and-detection/observability-and-detection.md) section 4).
- **Tool capabilities resolve independently.** `tool_calling_required` gates ordinary function
  tools. Public retrieval uses the dedicated `t1.web_search` preference and serializes only its
  deployment into `web_search_candidates`. Protected apply reconciles its Foundry prompt agent
  with the exact domain allowlist, and the Operator API sends an actual managed-tool request at startup.
  Missing model, project, agent, entitlement, or tool readiness makes search unavailable without
  borrowing the narrator pool or changing conversation and execution authority.

### Bootstrap Provisioner

At `azd up` (or equivalent) the resolver reads the registry, queries the target region's Azure OpenAI / Foundry catalog, and provisions **one deployment per concrete capability**;
virtual `t1.vision` reuses matching narrator deployments. The resolved `{capability → deployment}`
mapping is written to Key Vault and audited.

The protected `deploy_core_model_quorum` mode is a bounded recovery path for a missing core pair.
Its plan permits one in-place parent-account identity update and must create exactly `t1.judge` and
`t2.reasoner.primary`; the scope gate rejects missing, extra, replacement, or unrelated resource
changes. Exact apply consumes only that sealed plan and does not promote an ActionType, Workflow,
or autonomy mode.

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

## Related docs

| To learn about | Read |
|----------------|------|
| Tier boundaries and quality gates | [LLM Strategy](llm-strategy.md) |
| Presentation-only model selection | [Narrator Routing and Latency](../interfaces/narrator-routing-and-latency.md) |
| Deployment provisioning constraints | [Development and Deployment Parity](../deployment/dev-and-deploy-parity.md) |
| Delivery status and remaining work | [Implementation ledger](../../roadmap-implementation/architecture/model-capability-lifecycle.md) |
