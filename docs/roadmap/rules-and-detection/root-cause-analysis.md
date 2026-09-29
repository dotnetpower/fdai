---
title: Root-Cause Analysis
---
# Root-Cause Analysis

This document defines root-cause analysis (RCA) as a cited, bounded hypothesis produced by the
existing trust tiers. RCA explains an incident; it never grants approval or execution authority.

> **Safety boundary:** Deterministic verification, policy, what-if, risk, approval, execution, and
> effect observation remain authoritative over every RCA hypothesis.
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

## Azure Monitor telemetry evidence check

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
| Delivery status and remaining work | [Implementation ledger](../../roadmap-implementation/rules-and-detection/root-cause-analysis.md) |
| Correlation, anomaly detection, and forecasting | [Observability and Detection](observability-and-detection.md) |
| Model output and evidence boundaries | [Security and Identity](../architecture/security-and-identity.md) |
| Read-only incident presentation | [Operator Console Incident Roster](../interfaces/operator-console-incident-roster.md#1351-rca-view-root-cause-analysis) |
