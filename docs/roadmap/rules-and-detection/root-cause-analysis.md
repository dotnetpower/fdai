---
title: Root-Cause Analysis
---
# Root-Cause Analysis

This document defines root-cause analysis (RCA) as a cited, bounded hypothesis produced by the
existing trust tiers. RCA explains an incident; it never grants approval or execution authority.

> **Safety boundary:** Deterministic verification, policy, what-if, risk, approval, execution, and
> effect observation remain authoritative over every RCA hypothesis.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| T0, T1, and T2 hypothesis contracts and grounding | implemented | `services/core-control-plane/src/fdai/core/rca/`; focused RCA tests | T0 rule causes, stale-safe T1 reuse, deterministic causal chains, typed cause domains, and grounded T2 parsing are implemented. |
| Knowledge evidence and provider binding | implemented | `core/rca/knowledge_evidence.py`; `shared/providers/knowledge.py`; `delivery/pgvector/knowledge.py`; `service-migrations/branches/core-control-plane/versions/20260917_core_knowledge_read.py`; `delivery/azure/llm/rca_model.py`; `runtime/bootstrap.py`; focused provider, migration, adapter, and runtime tests | The runtime attaches the configured pgvector source after Azure LLM finalization as well as in telemetry-only mode. Core searches the default table only through a bounded `SECURITY DEFINER` function that excludes governed documents; `fdai_core` receives function execution and no raw `knowledge_chunk` table read. Re-ingestion atomically replaces a document's chunks and an empty replacement deletes them, so stale revisions do not remain searchable. Missing bindings never fabricate evidence. |
| Governed automated Incident RCA context | implemented | `delivery/persistence/postgres_governed_document_read.py`; `delivery/governed_rca_context.py`; `runtime/governed_rca.py`; automated T2 and context tests | A complete deployment binding supplies a separate read-only DSN, collection, access references, and reader groups. Automated Incident T2 uses the fixed Forseti principal and `incident-review` purpose, binds incident, resource, cutoff, ontology, and catalog identity, and holds when authorized document evidence is absent. |
| Azure deployment history and dependency context | implemented | `delivery/azure/deployment_history.py`; `delivery/persistence/postgres_provider_identity.py`; `runtime/rca_bindings.py`; topology-history, provider, runtime, and control-loop tests | A dedicated Monitoring Reader resolves provider identity from the inventory generation at the event cutoff. Runtime materializes the bitemporal topology at the same cutoff, admits only successful exact-scope mutations with matching generation, supports lifecycle reopen intervals, and bounds context, analysis, and audit in one side-path deadline. |
| Azure Monitor telemetry routing and model-safe facts | validated | `delivery/azure/telemetry_workspace.py`; `delivery/azure/telemetry_query.py`; `core/rca/evidence.py`; `delivery/azure/llm/rca_model.py`; focused workspace, KQL, RCA, control-loop, and runtime tests; bounded local source probe | Event-time inventory identity selects exact Diagnostic Settings and workspace-based Application Insights routes under the dedicated reader. Up to three discovered workspaces plus one explicit fallback are queried. Automatic log and trace reads run concurrently with independent four-second source budgets; one timeout cannot suppress the other source, and unavailable evidence still holds T2. The query adapter uses the current `api.loganalytics.azure.com` endpoint while retaining the documented `api.loganalytics.io/.default` token scope. T2 receives bounded fact tokens and opaque citations, never raw log bodies from this telemetry leg. |
| Adaptive telemetry recipe investigation | implemented | `core/rca/telemetry_evidence.py`; `core/rca/telemetry_recipes.py`; `core/read_investigation/telemetry_adaptive.py`; `delivery/azure/telemetry_recipe_query.py`; `runtime/adaptive_telemetry.py`; focused Core, Azure, Process, Operator, Pantheon, and Console tests | Forseti selects only reviewed recipe ids through the existing bounded adaptive Process. Heimdall supplies typed completeness receipts, Saga retains replay evidence, and complete positive receipts alone can ground T2. Raw KQL remains operator-only. |
| Distributed trace cause discrimination | implemented | `core/rca/trace_continuity.py`; `tests/core/rca/test_trace_continuity.py` | One independently cited signal can distinguish instrumentation, collector, or header-propagation causes. Missing, conflicting, or scope-mismatched evidence holds for review, and the result carries no remediation reference. |
| Read-only operator projection | implemented | `services/operator-service/src/fdai_operator_service/rca_projection.py`; focused projection tests | Audit hypotheses, citations, structured causal chains, and linked response plans are projected without action authority. |
| Governed operational RCA accuracy | in-progress | [Observability and Detection](observability-and-detection.md#implementation-status) | No retained exact-revision cohort proves live cause accuracy, abstention, and downstream outcome closure across the tier mix. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-09-20 | validated | Made automatic log and trace evidence reads concurrent and independently bounded, and moved the default query host to the current Azure Monitor Logs endpoint without changing its token audience. A slow source now closes as typed unavailable while evidence from the other source remains eligible. | `current change`; focused RCA and Azure query tests passed 51 cases; the configured local workspace accepted a content-free query, and the real log plus trace gatherer completed in 1.793 seconds under the production five-second side-path bound with zero citations for the probe scope. | Retain a governed live multi-workspace receipt containing actual error rows and include it in the exact-revision cause-accuracy cohort. |
| 2026-09-16 | implemented | Bound the reviewed telemetry recipe catalog to the existing adaptive investigation Process, exact event-time Azure workspace routing, completeness-aware Forseti revision, Saga Process evidence, Operator projection, and bilingual Console Investigation Room. Raw KQL is excluded from narrator and Pantheon model-visible tools. Completed 10 focused critique rounds; fixed raw-query authority exposure, unversioned policy identity, metadata substitution, cancellation leakage, no-data grounding, replay-unstable deadlines and citations, disabled production binding, module ownership, and projection/localization gaps. No finding above Low remains in this bounded slice. | `current change`; focused Core, Azure, Process replay, control-loop, Pantheon, Operator, Console model/i18n/typecheck, and 1440/993/390 Playwright checks passed. | Retain a governed live multi-workspace receipt and exact-revision cause-accuracy cohort before claiming operational validation. |
| 2026-09-16 | implemented | Registered the bounded log fact reducer as a reviewed typed-evidence path after exact-head CI correctly flagged its regular expressions as an unreviewed lexical classifier. The reducer accepts one `LogRecord`, never operator utterance, and cannot select intent or authority. The semantic-routing detector remains unchanged. | PR #1145 CI run `35054516295`, attempt 1, regression shard 3/4 job `104662007669`; exact semantic-routing and typed-input regressions. | Require fresh exact-head CI before merge. Live multi-workspace evidence remains separate. |
| 2026-09-16 | implemented | Connected event-time Azure resource identity to Diagnostic Settings and workspace-based Application Insights discovery, queried a capped workspace set with exact resource and time filters, and supplied model-safe telemetry fact tokens independently from governed document configuration. Completed 12 critique and hardening rounds over identity, ARM response integrity, route bounds, KQL semantics, event time, partial evidence, disclosure, determinism, cancellation, sovereign clouds, runtime parity, and typing. The rounds fixed strict ARM and Diagnostic Settings identity checks, case-equivalent route deduplication, fallback-inclusive limits, escaped KQL bounds, marker false positives, and citation identity collisions. Two reported higher-severity hypotheses were rejected because non-mapping payloads already fail before member access and KQL `=~` is case-insensitive equality rather than a regular-expression operator. No finding above Low remains in this bounded slice. | `current change`; focused RCA, Azure KQL, composition, control-loop, and runtime tests passed 483 cases; the new resolver reached 99.16% branch coverage; task-scoped Ruff and strict mypy passed. | Retain a governed live multi-workspace RCA receipt and include its cause accuracy and abstention outcomes in the exact-revision operational cohort. |
| 2026-09-09 | implemented | Added deterministic T1 discrimination for distributed trace discontinuities. The classifier accepts exactly one bounded telemetry signal, requires its affected hop or boundary to match the detector result, cites both continuity and cause evidence, and returns no remediation reference. | `current change`; focused trace RCA checks passed 9 cases; Ruff and strict mypy passed the new Core slice. | Bind authoritative instrumentation, collector, and header-propagation evidence producers, then retain the governed live cohort tracked by issue #142. |
| 2026-09-09 | implemented | Canonicalized bounded trace cause items and citations while rejecting whitespace, duplicates, and aggregate text overflow. | `current change`; focused trace RCA normalization checks. | Continue the bounded trace RCA critique campaign. |
| 2026-09-09 | implemented | Bound trace cause evidence to the exact topology, scenario, window, and observed time so citations cannot replay across incidents or later evidence. | `current change`; focused scope and time replay checks. | Continue the bounded trace RCA critique campaign. |
| 2026-09-09 | implemented | Moved trace RCA confidence-floor validation ahead of every early hold so invalid configuration always fails explicitly. | `current change`; focused invalid-confidence regression test. | Continue the bounded trace RCA critique campaign. |
| 2026-09-09 | implemented | Applied one 100-reference ceiling to the combined continuity and cause citation set, holding instead of truncating overflow. | `current change`; focused combined-citation overflow test. | Continue the bounded trace RCA critique campaign. |
| 2026-09-09 | implemented | Removed unsupported instrumentation attribution for hop-order findings because the detector does not identify an offending hop. | `current change`; focused invalid-hop-order hold test. | Continue the bounded trace RCA critique campaign. |
| 2026-09-09 | implemented | Lowered header-propagation cause domain from application to unknown because a disconnected boundary does not prove ownership. | `current change`; focused header-domain regression test. | Continue the bounded trace RCA critique campaign. |
| 2026-09-09 | implemented | Replaced fixed trace-cause confidence with a finite evidence score capped at the T1 ceiling before the grounding floor. | `current change`; focused confidence cap and hold tests. | Continue the bounded trace RCA critique campaign. |
| 2026-09-09 | implemented | Added a positive five-minute default cause-evidence age so a matching window label cannot admit stale telemetry. | `current change`; focused stale-evidence and invalid-age tests. | Continue the bounded trace RCA critique campaign. |
| 2026-09-09 | implemented | Capped configured trace cause evidence age at 24 hours so a large positive value cannot disable stale-evidence protection. | `current change`; focused evidence-age ceiling test. | Continue the bounded trace RCA critique campaign. |
| 2026-09-09 | implemented | Raised the trace-specific default confidence floor from zero to `0.5` so zero-confidence evidence cannot produce a grounded cause. | `current change`; focused zero-confidence hold test. | Continue the bounded trace RCA critique campaign. |
| 2026-09-09 | implemented | Completed 12 trace RCA critique rounds. Ten material fixes canonicalized and bounded cause evidence, prevented cross-scope and stale replay, validated confidence before holds, bounded combined citations, refused unsupported hop-order attribution, removed boundary ownership claims, capped evidence confidence and age, and required a non-zero default confidence floor. Two additional hypotheses were rejected after tracing the typed detector producer and the intentionally absent remediation reference. No finding above Low remains in this bounded slice. | `current change`; full RCA, detector, and Incident-chain slice passed 294 cases; strict mypy passed 26 RCA source files; Ruff passed. | Bind authoritative cause-evidence producers and retain the governed live cohort under issue #142. |
| 2026-09-04 | implemented | Hardened T1 into one event-time context over historical inventory identity, append-only topology history, canonical lifecycle Incident matching, dedicated reader RBAC, sovereign endpoint/audience binding, and a complete side-path timeout. Split deployment hydrates and guards the exact platform reader identity. | `current change`; focused RCA provider, member, topology, timeout, hydration, plan-guard, Terraform, Ruff, and strict mypy checks; residual hardening rounds 1-4, 11-12, 15-16, 22-29, and 32-42. | Retain the governed exact-revision operational cohort. |
| 2026-09-04 | implemented | Bound automated Incident T2 to a server-owned governed document context. A separate read-only PostgreSQL adapter filters by collection and access reference before lexical ranking, rechecks immutable metadata and exact reader groups, and passes an incident-, resource-, purpose-, cutoff-, release-, and principal-bound context into the existing document evidence verifier. Missing documents or access now holds T2 instead of continuing with other citations. | `current change`; focused governed context, automated T2, document evidence, Ruff, strict mypy, and Core service Terraform checks. | Retain the governed operational RCA cohort and deployed document-read receipt. |
| 2026-09-04 | implemented | Bound T1 RCA to exact Azure Activity Log mutations and a complete current dependency graph. The adapter resolves neutral ids through the server-owned inventory, hashes caller identity, rejects reads, failures, scope escapes, pagination overflow, stale identity, and graph-generation drift, and keeps every result in shadow. | `current change`; focused Azure deployment-history, dependency-generation, member-source, and control-loop tests (`28 passed`), Ruff, and strict mypy. | Retain an exact-revision operational cohort and independently verified outcomes. |
| 2026-09-04 | implemented | Added an additive cause-domain classification to every RCA hypothesis. T0 defaults reviewed configuration violations to infrastructure, T1 preserves the domain of its root change, T2 can propose only one supported enum value, and old rows remain `unknown`. Audit, reporting, Operator, and Console projections preserve the value without granting action authority. | `current change`; focused Core RCA, Azure adapter, Operator projection, Console decoder, and type checks. | Bind deployment history and current graph evidence that can supply non-default domains, then retain the governed operational cohort. |
| 2026-08-29 | implemented | Hardening round 6 reviewed 26 KnowledgeSource lenses and rejected non-finite embedding values before pgvector serialization while mapping non-finite similarity to zero in the reference index. Invalid vectors can no longer create non-deterministic retrieval order. | `current change`; focused KnowledgeSource and pgvector tests. | Retain a governed RCA cohort over deployment-owned indexed documents. |
| 2026-08-28 | implemented | Moved durable KnowledgeSource attachment after model finalization so Azure LLM mode no longer leaves RCA on the default empty source when a knowledge DSN is configured. The same guarded call preserves telemetry-only and local model behavior. Both in-memory and pgvector sources now treat re-ingestion as complete replacement, preserve the prior revision when embedding fails, remove obsolete chunks, and accept an empty replacement as deletion under a per-document transaction lock. | `current change`; `runtime/bootstrap.py`; `shared/providers/knowledge.py`; `delivery/pgvector/knowledge.py`; focused bootstrap and runtime configuration checks passed 42 cases; focused KnowledgeSource and SQL lifecycle checks passed 21 cases with one live-database parity case environment-gated; Ruff and strict mypy passed. | Retain a governed RCA cohort over deployment-owned indexed documents and bind source connectors to the replacement contract. |
| 2026-08-21 | in-progress | Moved the existing RCA tier, grounding, causal-chain, knowledge, and projection contracts into a focused owner document without changing runtime behavior or authority. | `current change`; document-size, translation, route, and link checks. | Retain a governed operational cohort with authoritative cause and outcome review. |

### Remaining work

- [ ] Retain an exact-revision operational cohort that includes a governed live multi-workspace
  telemetry receipt and measures supported causes, abstentions, stale reuse rejection, citation
  validity, and independently verified outcomes for T0, T1, and T2.

## Tier contract

Make RCA a first-class output of the tiers instead of an implicit side effect.

| Tier | RCA role |
|------|----------|
| **T0** | Direct cause: the matched rule or policy names the violated control and its remediation. |
| **T1** | Correlation cause: reuse a reverified resolved incident, or reconstruct a deterministic causal chain from bounded correlated events. |
| **T2** | Reasoning cause: produce a grounded hypothesis for novel or ambiguous incidents that cites supplied evidence and passes the quality gate. |

- RCA output is a **hypothesis with citations**, not an authoritative decision. Deterministic
  verification grants execution eligibility, never the RCA text or a forecast alone.
- Telemetry and correlated events feeding T2 are untrusted input. The verifier and policy re-check
  remain authoritative over any model text.
- T1 reuse re-verifies that the prior cause and learned action still apply. Any resulting action
  runs what-if before the risk gate; a stale learned action is never replayed blindly.
- An RCA that cannot be grounded holds for human review.
- The [correlated incident](observability-and-detection.md#1-event-correlation) is the RCA input, so
  analysis reasons over one incident rather than a storm of duplicates.

## Azure Monitor telemetry grounding

The initial design would let T2 query one configured Log Analytics workspace and pass matching raw
rows to the model. That approach is not accepted. A resource can send diagnostics to another
workspace, several destinations can be configured, and raw log text can contain credentials or
personal data. A successful query against the wrong workspace would also look like complete empty
evidence.

The revised design keeps source selection and disclosure deterministic:

1. The Azure delivery adapter resolves an exact ARM resource only through its read-only Diagnostic
  Settings and workspace-based Application Insights relationship. The server-configured workspace
  remains an explicit fallback route. The model cannot select a workspace, resource, endpoint, or
  cross-scope function.
2. A route set is deduplicated and capped before provider I/O. Malformed identities, ambiguous
  destination metadata, route overflow, partial responses, or unavailable authorization produce
  incomplete evidence rather than a wider query.
3. Reviewed KQL projections retain the exact resource and time bounds. Provider-specific tables and
  columns stay in Azure delivery code; the core receives cloud-provider-neutral log and trace
  records.
4. Telemetry candidates carry an opaque citation plus bounded semantic fact tokens. The tokens use
  a fixed machine grammar for signal, severity, source, duration, protocol, and deterministic cause
  markers. Raw log bodies, resource IDs, workspace IDs, URLs, addresses, and credential-shaped
  values do not enter the model request through this telemetry leg or enter the audit row.
5. Telemetry gathering is independent from governed document availability. A required governed
  document can still hold the final RCA, but its configuration does not decide whether exact,
  bounded telemetry is collected.
6. Automatic log and trace projections run concurrently under separate four-second source budgets
  inside the five-second RCA side-path deadline. A timeout becomes source-specific unavailable
  evidence, so one delayed source cannot cancel a completed citation from the other source.

This path remains read-only and shadow-only. It can improve a hypothesis and its citations, but it
does not grant action, approval, or execution authority.

### Deciding when to query logs

The initial automatic path queries both the default log and trace projections whenever T0 or T1
cannot close a resource-bound case. The conversational `query_log` surface separately accepts raw
KQL from an operator. Neither behavior lets an agent decide which missing evidence would distinguish
the active hypotheses, and exposing raw KQL to a model would turn untrusted text into provider work.

The revised path uses a typed `TelemetryEvidenceNeed`. Forseti may select only a catalogued recipe
identifier after the current evidence declares one of `missing`, `partial`, `no_data`, `timed_out`,
`unauthorized`, or `unavailable`. Heimdall supplies the source completeness record. The request pins
the incident, exact resource, evidence cutoff, lookback profile, expected output schema, query and
cost budgets, and idempotency key. It contains no KQL, workspace identifier, endpoint, table name,
or caller-provided filter text.

The Azure delivery adapter compiles the recipe identifier into reviewed KQL after exact workspace
resolution. Results return bounded fact tokens and one source receipt with route count, rows,
latency, truncation, freshness, completeness, and estimated cost units. A missing or failed source
does not become an empty healthy observation. The existing raw `query_log` command remains an
operator diagnostic surface and is not registered as a Pantheon autonomous tool.

The runtime binds this shadow read path automatically when exact Azure telemetry routing is
available. `FDAI_RCA_ADAPTIVE_TELEMETRY_ENABLED=false` is a deployment ceiling that disables it.
The optional `MAX_ROUNDS`, `MAX_QUERIES`, `MAX_COST_UNITS`, and `DEADLINE_SECONDS` suffix settings
narrow server-owned bounds; malformed or excessive values fail startup. Configuration version,
recipe catalog digest, bounds, evidence cutoff, and terminal usage remain replay-stable Process
evidence.

## Cause domains

Every hypothesis carries one typed operational layer: `infrastructure`, `application`,
`shared_dependency`, `external_provider`, `mixed`, or `unknown`. The field classifies the cited
hypothesis; it is not a final incident verdict and cannot grant action authority.

T0 configuration-rule causes default to `infrastructure`, while a caller with stronger reviewed
evidence can supply a narrower domain. T1 takes the domain from the root change event and preserves
it through resolved-case reuse. T2 can return only a declared enum value; an absent value remains
`unknown`, and an unsupported value causes the parser to hold the hypothesis for review. Historical
audit rows without this field project as `unknown`.

## Distributed trace cause discrimination

The continuity detector reports the observed shape and never guesses a cause. The deterministic T1
classifier in `core/rca/trace_continuity.py` accepts the detector result plus exactly one independent
`TraceCauseEvidence` signal:

| Cause | Required match |
|-------|----------------|
| `instrumentation` | The cited affected hop is missing from a dropped-context result. |
| `collector` | The cited collector evidence names only hops missing from a dropped-context result. |
| `header_propagation` | The cited boundary is disconnected in a regenerated-context result or is adjacent to a missing hop in a dropped-context result. |

The signal and detector citations are all `telemetry` references. No signal, more than one signal, a
scope mismatch, or a non-discontinuous result produces an explicit held outcome. A grounded result
uses the T1 tier with bounded confidence and `remediation_ref=None`; it explains the observed cause
but cannot select or authorize a recovery action. Affected items and evidence references reject
surrounding whitespace, duplicates, and aggregate text overflow, then use canonical sorted order so
equivalent evidence produces one replay-stable hypothesis.
An invalid-hop-order result does not identify an offending hop, so this classifier holds it rather
than assigning an instrumentation cause from an arbitrary observed hop.
Instrumentation maps to the application cause domain and collector loss maps to shared dependency.
Header propagation remains `unknown` because a boundary alone does not prove which side owns the
fault.
Each cause signal also binds the exact topology, scenario, observation window, and timezone-aware
observation time. A signal from another scope or later than the continuity result cannot be reused.
The cause observation must also fall within a positive configured evidence age, five minutes by
default and at most 24 hours, so a copied window label or unbounded configuration cannot revive
stale telemetry.
The confidence floor is validated before any held outcome, so invalid configuration cannot hide
behind missing or conflicting evidence.
Cause evidence carries a finite confidence in `[0, 1]`. The hypothesis uses the lower of that value
and the T1 ceiling `0.85`, then applies a confidence floor that defaults to `0.5`.
After deduplication, continuity and cause citations share one 100-reference ceiling. Overflow holds
instead of truncating the evidence set used to ground the hypothesis.

## Upstream implementation

`core/rca/` ships the RCA contract (`RootCauseHypothesis` and `Citation`), the deterministic T0
cause (`t0_root_cause`), and the grounding gate (`enforce_grounding`). An ungrounded or below-
confidence hypothesis holds for human review. The `RcaReasoner` Protocol is the optional T2 seam.
Upstream `core/rca/llm.py` supplies `LlmRcaReasoner` and the `RcaModel` seam. Its deterministic
parser refuses malformed answers, fabricated citations, and ungrounded answers.

The Azure binding is `delivery/azure/llm/rca_model.py` (`AzureOpenAIRcaModel`). It calls Azure
OpenAI with a managed-identity token and returns raw JSON for the upstream parser. The composition
root binds it from the `t2.rca` capability in `resolved-models.json`. A missing capability or prompt
leaves `LlmBindings.rca_reasoner = None`, so T2 RCA stays unavailable and T0 continues.
After model finalization, runtime bootstrap attaches the configured pgvector KnowledgeSource when
`FDAI_KNOWLEDGE_DSN` or `FDAI_STATE_STORE_DSN` is available. This ordering applies in Azure LLM,
telemetry-only, and local model modes and preserves the empty-source fallback when no DSN exists.

`RcaCoordinator` orchestrates T0, stale-safe T1 correlation reuse, and citation-bounded T2. The
`ControlLoop` appends a deterministic T0 `rca.hypothesis` audit entry per finding, carrying the
correlated `incident_id`. A wired T2 reasoner adds one grounded hypothesis or abstention for a novel
case. This is the "why", never a new execution path.

When Azure Monitor is configured, the same provider binding is available in Azure LLM and
telemetry-only modes. Standard runtime composition reuses the event-time inventory identity resolver
and the dedicated Monitoring Reader to discover Diagnostic Settings with API version
`2021-05-01-preview`, resolve workspace-based Application Insights, and obtain each Log Analytics
workspace customer ID. The outer RCA side-path deadline bounds the complete discovery and KQL
sequence. Missing inventory identity, reader authority, complete ARM responses, or a bounded route
set makes telemetry unavailable. The static `FDAI_MONITOR_WORKSPACE_ID` route remains the final
explicit fallback and never authorizes a cross-workspace KQL function.

## Knowledge evidence

`core/rca/knowledge_evidence.py` (`KnowledgeEvidenceGatherer`) consumes the Knowledge Base seam in
`shared/providers/knowledge.py`. When bound, the coordinator searches ingested runbooks,
architecture notes, and resource plans for chunks relevant to the incident summary and adds each
as a `CitationKind.KNOWLEDGE` candidate. An unbound source, empty index, or provider outage
contributes nothing and the gate can abstain. Citation references use opaque
`knowledge:<source_ref>#<chunk_id>` handles rather than chunk bodies. The reasoner cannot cite a
chunk outside this vouched-for set.

Knowledge ingestion uses complete replacement semantics per `doc_id`. A newer revision removes
obsolete chunks in the same transaction, and an empty replacement deletes every chunk for that
document. The in-memory and pgvector implementations share this behavior so connector deletion and
revision propagation do not leave stale text searchable.

Governed uploaded documents use a separate path. `GovernedDocumentEvidenceReadAdapter` applies the
document access provider and collection-scoped search before it creates a document-only
`OperationalEvidenceBundle`. `GovernedKnowledgeEvidenceGatherer` then verifies the principal,
purpose, scope, cutoff, document revision, access context, redaction state, and citation manifest
before it emits opaque `CitationKind.KNOWLEDGE` refs. A missing or rejected governed context holds
the RCA result and never falls back to the unscoped `KnowledgeSource`. The gatherer also requires
the document evidence-ref set to equal the document-lane citation manifest exactly; extra,
duplicate, or missing entries hold the result.
When a caller requests governed document context, an empty gatherer result is also a hold. The
coordinator cannot silently continue with telemetry or other citations after the required governed
evidence path returned neither evidence nor an explicit reason.

Automated Incident T2 now enters that path through a fixed `principal:fdai-rca` Forseti read
context with purpose `incident-review`. The deployment supplies a separate read-only PostgreSQL
secret, one collection, exact access-descriptor references, and exact document reader groups.
Search applies collection and access-reference predicates before deterministic lexical ranking;
metadata and group authorization are checked again afterward. The request binds the incident,
resource, evidence cutoff, ontology release, and catalog revision. A partial configuration fails
startup, while a missing complete configuration leaves governed document evidence unavailable.

## Deterministic T1 causal chain

`core/rca/causal_chain.py` (`CausalChainAnalyzer`) and `core/rca/t1.py` reconstruct the most probable
multi-hop chain ending at the failure: `root change -> symptom -> ... -> failure`. The root must be
a change. A window of symptoms with no antecedent change abstains.

The reusable analyzer can score unscoped correlated input for isolated analysis, but the production
ControlLoop requires a non-empty resource-dependency graph. A change on a direct or bounded
transitive dependency outranks an unrelated one, and unrelated resources cannot link.
`same_resource_only` restricts every hop to the failing resource.
Confidence is a weakest-link aggregate weighted by temporal proximity, relationship strength, and
change kind. It is ambiguity-discounted and bounded to the T1 band (`0.35`-`0.85`). Strict temporal
precedence makes the event set a DAG, so the same inputs produce the same cited chain.

The `ControlLoop` obtains one `IncidentRcaContext` containing members and a dependency graph for the
current event cutoff. It maps the EventCorrelator id to exactly one lifecycle Incident using exact
resource, signal, and optional correlation keys, including reopen intervals. The Azure reader uses
a dedicated Monitoring Reader identity, resolves the provider id from the matching historical
inventory generation, and retains only successful exact-resource mutations. Append-only topology
history materializes the complete `depends_on` graph at the same event time and known-at cutoff.
Generation mismatch, ambiguity, stale scope, incomplete topology, timeout, or audit delay ends the
side path without unscoped fallback or authority.

## Read-only operator surface

Shadow `rca.hypothesis` audit entries are projected into the **History > RCA** panel through
`GET /rca?correlation=<id>` in
`services/operator-service/src/fdai_operator_service/rca_projection.py`. The projection renders
tiered hypotheses, citations, a structured T1 chain, grounding state, and the linked response plan
from the same audit stream. An abstained hypothesis appears as insufficient grounding rather than a
confident cause. The surface is read-only and adds no source of truth. See
[Operator Console Incident Roster](../interfaces/operator-console-incident-roster.md#1351-rca-view-root-cause-analysis).

## Related docs

| To learn about | Read |
|----------------|------|
| Correlation, anomaly detection, and forecasting | [Observability and Detection](observability-and-detection.md) |
| Model output and evidence boundaries | [Security and Identity](../architecture/security-and-identity.md) |
| Read-only incident presentation | [Operator Console Incident Roster](../interfaces/operator-console-incident-roster.md#1351-rca-view-root-cause-analysis) |
