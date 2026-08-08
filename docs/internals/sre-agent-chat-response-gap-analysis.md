# Azure SRE Agent vs FDAI Chat Response Gap Analysis

This note compares how Azure SRE Agent and FDAI answer operator questions about incidents and
resource state. It evaluates the conversational path, evidence used, answer shape, and next-action
continuity across 56 scenarios. It complements the capability parity audit, which measures whether
an operational capability exists somewhere in the system rather than whether chat turns it into a
useful answer.

> Scope: The comparison reflects Microsoft Learn content reviewed on 2026-07-29 and executable
> FDAI source and tests on the same date. Azure SRE Agent rows marked `documented` are stated or
> demonstrated by first-party material. Rows marked `synthesized` combine documented tools into a
> representative operator question and are not product test results.

The `Basis` column describes the Azure SRE Agent baseline only. FDAI status is assessed separately
from repository code and executable tests.

## What this analysis measures

The comparison separates capability inventory from conversational completion. A provider, report
generator, or action pipeline can exist while the chat path still lacks intent routing, evidence
composition, a useful renderer, or a follow-up action.

FDAI status means:

- **Complete**: Natural-language chat selects authoritative evidence and returns a direct, grounded
  answer for the requested outcome.
- **Partial**: A provider or backend capability exists, but chat lacks one or more of routing,
  cross-source composition, rich rendering, multi-turn continuation, or deployment binding.
- **Missing**: No current chat path can produce the requested operational outcome from grounded
  evidence.

These labels do not reduce FDAI's safety guarantees. A safer typed action path can remain the right
architecture while its conversational handoff is still incomplete.

## Result at a glance

| Status | Scenarios | Share |
|--------|-----------|-------|
| Complete | 16 | 29% |
| Partial | 24 | 43% |
| Missing | 16 | 29% |

The result falsifies the stronger interpretation of the existing 51-capability parity claim: FDAI
has broad backend coverage, but only 29% of this operator-question set is conversationally complete.
The largest deficit is not basic inventory. It is the path from a broad diagnosis question to a
cross-source, evidence-ranked diagnosis with a recommended and governed next action.

## Scenario comparison

### Resource scope and direct reads

| # | Operator question | Azure SRE Agent answer pattern | Basis | FDAI | Current FDAI answer and gap |
|---|-------------------|--------------------------------|-------|------|-----------------------------|
| 1 | What resources and resource groups do you manage? | Managed scope and resource inventory | documented | Complete | Deterministic inventory count/list with source, snapshot time, freshness, and bounded records. |
| 2 | List the VMs, databases, or AKS clusters in this resource group. | Filtered resource table | documented | Complete | Type and resource-group filters return grounded names, type, location, and status. |
| 3 | Is `vm-app-01` running now? | Current state card with observation time | documented | Partial | The read tool resolves and reads state, but the generic renderer can collapse to `outcome; evidence sources=N` instead of naming the observed state and time. |
| 4 | Is this Azure subscription healthy? | Resource Health and metric summary | synthesized | Complete | Bounded subscription sweep reports findings, checked/unavailable/unsupported metrics, source, observation time, truncation, and partial coverage. |
| 5 | Is `vm-app-01` affected by a platform outage? | Resource Health event and impact context | documented | Partial | Resource Health evidence exists, but the generic per-resource renderer does not explain availability state, event window, or platform-versus-customer conclusion. |
| 6 | Who stopped or changed `vm-app-01`? | Activity Log actor, operation, and timestamp | documented | Partial | Exact attribution evidence exists, but chat does not render the actor, operation, status, occurrence time, and caveats as a structured answer. |
| 7 | What changed on this resource before the outage? | Time-ordered deployment and Activity Log changes | documented | Partial | Change history can be queried, but the direct answer lacks a bounded timeline and symptom correlation. |
| 8 | Was the VM shut down inside the guest OS? | Guest event evidence or explicit diagnostic gap | synthesized | Partial | Guest log evidence and honest `unavailable` behavior exist, but matched records are not rendered into event, host, and timestamp details. |
| 9 | Which inbound ports does this NSG allow? | NSG rule table with reachability caveat | synthesized | Complete | Structured rules include protocol, ports, source, priority, and rule name, plus the correct warning that configuration is not end-to-end proof. |
| 10 | How is this VNet peered? | Peering topology and configuration flags | documented | Complete | Structured peerings include state, sync, access, forwarded traffic, gateway flags, and one-sided-evidence caveat. |
| 11 | Can this app reach the database end to end? | Per-hop network path with blocked or unverified hops | documented | Missing | FDAI can show NSG and peering configuration, but cannot compose effective routes, reciprocal checks, DNS, firewall, and active connectivity into a path decision. |

### Diagnosis and correlation

| # | Operator question | Azure SRE Agent answer pattern | Basis | FDAI | Current FDAI answer and gap |
|---|-------------------|--------------------------------|-------|------|-----------------------------|
| 12 | Why is this service slow? | Root cause, supporting metrics/traces, fix, and verification | documented | Missing | `diagnosis` affects presentation planning, but no natural-language tool plan gathers resource-specific latency evidence. |
| 13 | Why did errors spike ten minutes ago? | Multi-source timeline, correlated change, confidence, and next step | documented | Missing | Existing incident RCA can be replayed, but chat cannot start an ad hoc metric/log/change correlation from this question. |
| 14 | Run this bounded KQL query. | Query result table with row count and execution summary | documented | Complete | Explicit `query_log query=... window=...` is bounded, deterministic, cited, and rendered as a table. |
| 15 | Find failed requests in the logs for the last 30 minutes. | Natural-language log investigation and summarized findings | documented | Missing | FDAI requires the operator to write the `query_log` command and KQL. Natural-language KQL selection and safe template choice are absent. |
| 16 | Compare CPU or memory before and after the incident. | Time-series chart, baseline, delta, and anomaly window | documented | Missing | Metric providers and anomaly code exist, but chat has no per-resource metric intent or before/after renderer. |
| 17 | Which dependency made this endpoint slow? | Application Insights request/dependency breakdown | documented | Missing | Telemetry adapters feed RCA, but Command Deck cannot initiate and render this dependency investigation directly. |
| 18 | Show the slow distributed trace. | Waterfall with spans, duration, errors, and bottleneck | documented | Missing | Trace projection exists outside the chat answer path; there is no trace-search intent and no conversational waterfall artifact. |
| 19 | Why is this AKS pod restarting or throttled? | Pod events, logs, requests/limits, restart count, and recommendation | documented | Partial | Kubernetes analyzers and governed diagnostics exist, but normal chat does not compose them into an immediate pod diagnosis. |
| 20 | Which database query caused the CPU spike? | Slow-query table correlated with CPU, connections, and I/O | documented | Missing | Metric and log providers exist, but no typed database-diagnostic chat plan or renderer connects them. |
| 21 | Does this cache have enough memory? | Capacity, eviction trend, threshold, and recommendation | synthesized | Missing | There is no resource-specific capacity intent, metric selection, or capacity answer schema. |
| 22 | Did a deployment cause this failure? | Deployment-to-symptom timeline with changed code or configuration | documented | Partial | A recorded incident can include change evidence, but ad hoc chat lacks a repository/deployment evidence provider in the same causal turn. |
| 23 | Which code change introduced the bug? | Repository search, call-chain analysis, file/line references, and fix | documented | Missing | FDAI can ingest change events and documents, but chat has no source-aware investigation path that reads code and verifies a causal claim. |
| 24 | Explain the cascade across gateway, API, database, and model service. | Cross-resource timeline, causal chain, charts, and ranked recommendations | documented | Partial | The investigation coordinator and report feed can produce cross-resource signals, but chat does not launch and render the full correlation as one diagnosis. |
| 25 | What is the impact scope if this database fails? | Dependency graph and affected services/resources | synthesized | Missing | Inventory links are listable, but chat has no impact traversal, criticality, customer/SLO impact, or bounded blast-radius answer. |

### Incident, knowledge, and memory

| # | Operator question | Azure SRE Agent answer pattern | Basis | FDAI | Current FDAI answer and gap |
|---|-------------------|--------------------------------|-------|------|-----------------------------|
| 26 | Summarize the latest incident. | Severity/status card, impact, outcome, and links | documented | Complete | Server read-model evidence returns bounded incident summaries and terminal verification. |
| 27 | What was the root cause of this incident? | Root cause with evidence and recommended fix | documented | Complete | Grounded recorded hypotheses with citations are preferred; unsupported RCA is withheld. |
| 28 | Show the incident timeline. | Ordered alerts, changes, symptoms, actions, and recovery | documented | Partial | Audit evidence is available, but chat lacks a first-class merged timeline renderer and visual event sequence. |
| 29 | What should we do next? | Prioritized mitigation, prevention, and verification | documented | Partial | A recorded response plan can reach narrator context, but answer completeness depends on existing RCA and lacks a deterministic recommendation schema. |
| 30 | Has this happened before, and what worked? | Similar incident card with prior resolution and pitfalls | documented | Partial | T1 reuse and case history exist, but conversational retrieval and comparison are not a dedicated, measurable answer path. |
| 31 | What does our failover runbook say? | Numbered steps with source citations | documented | Partial | Knowledge retrieval seams exist, but usefulness depends on deployment-owned indexing and ACL-aware source binding. |
| 32 | What knowledge sources are connected and fresh? | Source inventory with status and last modified time | documented | Missing | The console can expose some provider state, but chat has no authoritative knowledge-source inventory answer. |
| 33 | Turn this resolution into a runbook and save it. | Structured guide, saved document, and confirmation | documented | Missing | FDAI can propose learning artifacts, but chat cannot author, review, persist, and confirm a knowledge document end to end. |
| 34 | Remember this fact, then retrieve it in a later thread. | Explicit durable memory save/retrieve confirmation | documented | Missing | Principal-scoped memory exists, but there is no explicit chat command with consent, review, provenance, and retrieval confirmation. |

### Failure handling and investigation lifecycle

| # | Operator question | Azure SRE Agent answer pattern | Basis | FDAI | Current FDAI answer and gap |
|---|-------------------|--------------------------------|-------|------|-----------------------------|
| 35 | Which of these same-named resources do you mean? | Candidate picker and resumed investigation | synthesized | Partial | FDAI stops safely and returns bounded candidates, but typed clarification state does not resume the original plan automatically. |
| 36 | What can you conclude when one data source is unavailable? | Supported facts, missing source, uncertainty, and next check | documented | Complete | Partial and unavailable states fail closed and avoid a healthy or causal claim. |
| 37 | Why can you not inspect that resource? | Authorization/scope explanation without sensitive details | synthesized | Complete | Scope denial becomes bounded unavailable evidence and does not widen the query. |
| 38 | What are you checking now? | Live phase and tool progress | documented | Complete | SSE exposes handoff, semantic milestones, branch/tool activity, redacted execution evidence, and terminal verification. |
| 39 | Run a deep investigation. | Authorization, multi-phase detail panel, hypotheses, validation, and synthesis | documented | Partial | Durable and streamed investigation primitives exist, but Command Deck can return `handoff_required` instead of creating and following the deep investigation in-thread. |
| 40 | Cancel the investigation. | Explicit cancellation state and stopped work | documented | Partial | Disconnect cancellation and bounded worker cancellation exist; an operator-visible conversational cancel/resume contract is incomplete. |

### Actions, automation, and delivery

| # | Operator question | Azure SRE Agent answer pattern | Basis | FDAI | Current FDAI answer and gap |
|---|-------------------|--------------------------------|-------|------|-----------------------------|
| 41 | Propose a mitigation but do not execute it. | Proposal card with rationale and approval controls | documented | Partial | FDAI has the stronger typed proposal/risk/approval path, but read chat does not consistently convert diagnosis to a visible action proposal. |
| 42 | Approve and execute this mitigation. | Approval state, execution progress, result, and validation | documented | Partial | The action and human-approval routes exist separately; conversational continuity from answer to approval to post-check is incomplete. |
| 43 | Create an incident from this chat. | Draft, severity, confirmation, and incident reference | documented | Complete | Typed incident draft and explicit confirmation prevent accidental record creation and preserve idempotency. |
| 44 | Acknowledge, update, or resolve the external incident. | Incident card with updated platform state | documented | Partial | PagerDuty and ServiceNow adapters exist as external bindings, but natural-language chat continuation depends on deployment wiring and action exposure. |
| 45 | Create and pre-test an incident response plan. | Plan summary, filters, mode, test results, and activation readiness | documented | Partial | IRP authoring and pretest exist, but they are not a complete conversational workflow in Command Deck. |
| 46 | Create, pause, run now, or inspect a scheduled health task. | Schedule card, next run, state, and history | documented | Partial | Scheduler lifecycle exists in backend/console surfaces; natural-language task management is not end-to-end in chat. |
| 47 | Generate a chart or PDF investigation report. | Embedded chart or downloadable structured report | documented | Missing | Chat can render rich Markdown, but operational evidence is not transformed into typed charts or an on-demand report artifact. |
| 48 | Send these findings to Teams or email. | Delivery preview and confirmation | documented | Partial | Notification adapters exist, but ad hoc conversational delivery lacks a unified preview, recipient authorization, send result, and evidence link flow. |

### Conversational quality and institutional learning

| # | Operator question | Azure SRE Agent answer pattern | Basis | FDAI | Current FDAI answer and gap |
|---|-------------------|--------------------------------|-------|------|-----------------------------|
| 49 | How do I configure this product feature? | Current official documentation answer with links | documented | Partial | Policy-gated web/document evidence exists, but FDAI lacks a dedicated always-current product documentation specialist. |
| 50 | What can FDAI help me with? | Capability summary and suggested prompts | documented | Complete | Behavior knowledge, glossary, and capability evidence can explain FDAI without pretending to have live operational evidence. |
| 51 | What about the second one? | Follow-up resolved against prior structured scope | documented | Partial | Incident binding and session history exist, but typed multi-turn resource/time/signal slots and correction are incomplete. |
| 52 | Show the evidence for that conclusion. | Source/tool citations and drill-down links | documented | Complete | Terminal verification publishes evidence references and a bounded manifest; unsupported factual claims are corrected or held for review. |
| 53 | Answer in Korean. | Localized operational answer | documented | Complete | English/Korean routing and deterministic renderers are covered; machine evidence remains stable while Bragi localizes prose. |
| 54 | Give me a brief answer, a table, or a deep explanation. | Requested answer shape | synthesized | Complete | Deterministic answer planning supports detail, format, audience, and section preferences without changing evidence authority. |
| 55 | What did the system learn from this incident? | Session insight, reusable knowledge, and prevention | documented | Partial | Post-turn learning and case history exist, but chat does not show a durable learned-artifact lifecycle with approval and later reuse proof. |
| 56 | Open a support request with the diagnostics attached. | Ticket confirmation with attached evidence | documented | Missing | No support-request action type or conversational evidence-package workflow is exposed. |

## Systemic gaps

The scenario rows reduce to eight root gaps. Fixing these closes many rows at once.

### P0: One grounded diagnostic turn

FDAI needs one owner-selected path that translates a diagnosis question into a bounded multi-source
plan, executes only that owner's read tools, and makes those results input to the answer before
terminal verification. The minimum answer contract should contain:

1. Observed symptom and exact scope.
2. Strongest supported conclusion.
3. Ranked hypotheses with confidence and contradictory evidence.
4. Evidence timeline with source and observation time.
5. Missing or stale evidence.
6. Recommended next check or governed action.
7. Recovery verification criteria.

This closes scenarios 12, 13, 15-24, and 29 more effectively than adding isolated intent regexes.

### P0: Resource-specific response renderers

`HeimdallReadInvestigationResponder._render_answer()` provides useful NSG and peering output, but
other intents can end as `Read investigation for X: matched; evidence sources=N`. Add typed
renderers for resource state, Activity Log attribution/history, Resource Health, and guest events.
Each renderer should expose the normalized record fields, freshness, truncation, caveat, and next
check without sending raw provider output to the narrator. This closes scenarios 3 and 5-8.

### P0: Typed clarification and multi-turn scope

Persist bounded conversation slots for resource, resource group, incident, time window, signal,
and requested depth. An ambiguous result should create a typed clarification turn; the selection
should resume the same immutable plan rather than asking the model to reconstruct it. This closes
scenarios 35 and 51 and prevents silent scope drift.

### P1: Repository, deployment, and knowledge evidence

The change feed and knowledge seams need a conversational evidence provider with explicit states:
connected, stale, disconnected, unauthorized, and degraded. A causal code claim should require a
deployment/change match plus file/line evidence. Knowledge answers should show source freshness and
ACL-filtered citations. This closes scenarios 22, 23, 30-34, 49, and 55.

### P1: Impact and topology reasoning

Add a bounded impact traversal over inventory relationships with service criticality and evidence
coverage. Keep configured NSG/peering evidence distinct from effective reachability. Active network
tests, effective routes, DNS, and reciprocal checks should be separate typed tools. This closes
scenarios 11 and 25 without overstating connectivity.

### P1: Diagnosis-to-action continuity

Preserve FDAI's typed ActionType, risk, approval, rollback, lock, idempotency, and audit path, but
make the handoff visible in the same conversation. A diagnosis should create an inert proposal,
show impact scope and rollback, wait for an authorized approval, stream execution, and run a
post-check. This closes scenarios 41, 42, 44-46, 48, and 56.

### P1: Rich operational answer artifacts

Define typed chat artifacts for timeline, metric series, dependency graph, trace waterfall,
proposal, schedule, incident, and report link. The Markdown renderer can remain a fallback, but
critical operational structures should not depend on prose formatting. This closes scenarios 18,
24, 28, 39, 47, and 48.

### P1: Executable comparison benchmark

The current parity catalog proves path existence, and claim fixtures prove selected grounding
properties. Neither measures full operator outcomes. Freeze this 56-scenario set as a benchmark
with synthetic evidence for both English and Korean prompts.

## Acceptance gates

The next implementation should not claim conversational parity until the benchmark demonstrates:

- **Routing**: At least 95% of supported prompts choose the intended owner, scope, and read plan.
- **Grounding**: Zero unsupported causal, numeric, identity, time, or execution claims.
- **Completeness**: At least 90% of diagnosis answers include conclusion, evidence, uncertainty,
  next step, and verification criteria when those fields are available.
- **Failure honesty**: 100% of unavailable, partial, stale, ambiguous, unauthorized, and truncated
  fixtures preserve their limitation in the terminal answer.
- **Citation integrity**: Every terminal citation resolves to a consumed evidence-manifest entry;
  no unused source is presented as support.
- **Multi-turn stability**: Clarification, correction, follow-up, cancellation, and replay preserve
  immutable scope and idempotency.
- **Locale parity**: English and Korean variants select the same plan and evidence while rendering
  natural localized prose.
- **Transport parity**: JSON, SSE terminal, replayed transcript, Teams, and Slack retain the same
  canonical facts and trust state.
- **Latency**: Time to first honest progress and terminal p95 are measured separately for direct,
  streamed, and detached modes; no timeout or retry increases the original budget.
- **Safety**: Every action continuation retains stop condition, rollback, impact limit, dry run,
  resource lock, idempotency key, approval separation, and audit evidence.

## FDAI advantages to preserve

FDAI should close conversational gaps without copying unsafe mechanisms:

- Typed actions replace arbitrary write commands.
- Per-action promotion and risk ceilings replace a global autonomous mode.
- Human approval identity remains distinct from executor identity.
- Unsupported evidence produces correction, review, or an explicit limitation.
- Provider output is normalized, bounded, and treated as untrusted data.
- Replays, locks, timeouts, and idempotency are explicit contracts rather than prose promises.

These are design advantages. The target is Azure SRE Agent's diagnostic coherence and operator
experience with FDAI's stronger evidence and execution boundaries.

## Sources and implementation evidence

First-party comparison sources:

- [Azure SRE Agent overview](https://learn.microsoft.com/azure/sre-agent/overview)
- [Run your first investigation](https://learn.microsoft.com/azure/sre-agent/first-investigation)
- [Deep investigation tutorial](https://learn.microsoft.com/azure/sre-agent/tutorial-deep-investigation)
- [Diagnose with Azure observability](https://learn.microsoft.com/azure/sre-agent/diagnose-azure-observability)
- [Tools in Azure SRE Agent](https://learn.microsoft.com/azure/sre-agent/tools)
- [Connect knowledge](https://learn.microsoft.com/azure/sre-agent/connect-knowledge)
- [Memory and knowledge](https://learn.microsoft.com/azure/sre-agent/memory)
- [Incident platforms](https://learn.microsoft.com/azure/sre-agent/incident-platforms)
- [Incident response plans](https://learn.microsoft.com/azure/sre-agent/incident-response-plans)
- [Scheduled tasks](https://learn.microsoft.com/azure/sre-agent/scheduled-tasks)
- [Workflow automation](https://learn.microsoft.com/azure/sre-agent/workflow-automation)
- [Learn via chat](https://learn.microsoft.com/azure/sre-agent/docsguide)

FDAI implementation evidence:

- [SRE Agent parity audit](sre-agent-parity-audit.md)
- [Azure read investigations](../roadmap/interfaces/azure-read-investigations.md)
- [Operator console](../roadmap/interfaces/operator-console.md)
- `services/core-control-plane/src/fdai/core/read_investigation/routing.py`
- `services/core-control-plane/src/fdai/core/conversation/answer_plan.py`
- `services/operator-service/src/fdai_operator_service/`
- `services/operator-service/src/fdai_operator_service/`
- `services/operator-service/src/fdai_operator_service/`
- `services/operator-service/src/fdai_operator_service/`
- `services/operator-service/src/fdai_operator_service/`
- `services/operator-service/src/fdai_operator_service/`
- `services/operator-service/tests/`
- `services/operator-service/tests/`
- `services/operator-service/tests/`
- `services/operator-service/tests/`
- `services/operator-service/tests/`

Executable validation map:

| Scenario rows | Focused evidence |
|---------------|------------------|
| 1-2 | [Inventory chat tests](../../services/operator-service/tests/) |
| 3-10, 35, 37-40 | [Read investigation tests](../../services/operator-service/tests/) and [progress tests](../../services/operator-service/tests/) |
| 4, 36 | [Subscription health tests](../../services/operator-service/tests/) |
| 14 | [Bounded KQL chat tests](../../services/operator-service/tests/) |
| 26-29, 43 | [Operational evidence tests](../../services/operator-service/tests/) and [chat route tests](../../services/operator-service/tests/) |
| 38, 52 | [Terminal verification tests](../../services/operator-service/tests/) |
| 53-54 | [Answer-plan tests](../../services/operator-service/tests/) and [chat route tests](../../services/operator-service/tests/) |

## Related docs

| To learn about | Read |
|----------------|------|
| Atomic capability parity | [Azure SRE Agent parity audit](sre-agent-parity-audit.md) |
| Earlier connector-focused gaps | [FDAI vs Azure SRE Agent capability gaps](sre-agent-gap-analysis.md) |
| Read-only Azure investigation contract | [Azure read investigations](../roadmap/interfaces/azure-read-investigations.md) |
| Command Deck and evidence rendering | [Operator console](../roadmap/interfaces/operator-console.md) |
