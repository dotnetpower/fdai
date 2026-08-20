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
| T0, T1, and T2 hypothesis contracts and grounding | implemented | `services/core-control-plane/src/fdai/core/rca/`; focused RCA tests | T0 rule causes, stale-safe T1 reuse, deterministic causal chains, and grounded T2 parsing are implemented. |
| Knowledge evidence and provider binding | implemented | `core/rca/knowledge_evidence.py`; `delivery/azure/llm/rca_model.py`; composition LLM bindings | Missing knowledge or model bindings leave optional paths unavailable and never fabricate evidence. |
| Read-only operator projection | implemented | `services/operator-service/src/fdai_operator_service/rca_projection.py`; focused projection tests | Audit hypotheses, citations, structured causal chains, and linked response plans are projected without action authority. |
| Governed operational RCA accuracy | in-progress | [Observability and Detection](observability-and-detection.md#implementation-status) | No retained exact-revision cohort proves live cause accuracy, abstention, and downstream outcome closure across the tier mix. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-21 | in-progress | Moved the existing RCA tier, grounding, causal-chain, knowledge, and projection contracts into a focused owner document without changing runtime behavior or authority. | `current change`; document-size, translation, route, and link checks. | Retain a governed operational cohort with authoritative cause and outcome review. |

### Remaining work

- [ ] Retain an exact-revision operational cohort that measures supported causes, abstentions,
  stale reuse rejection, citation validity, and independently verified outcomes for T0, T1, and T2.

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

`RcaCoordinator` orchestrates T0, stale-safe T1 correlation reuse, and citation-bounded T2. The
`ControlLoop` appends a deterministic T0 `rca.hypothesis` audit entry per finding, carrying the
correlated `incident_id`. A wired T2 reasoner adds one grounded hypothesis or abstention for a novel
case. This is the "why", never a new execution path.

## Knowledge evidence

`core/rca/knowledge_evidence.py` (`KnowledgeEvidenceGatherer`) consumes the Knowledge Base seam in
`shared/providers/knowledge.py`. When bound, the coordinator searches ingested runbooks,
architecture notes, and resource plans for chunks relevant to the incident summary and adds each
as a `CitationKind.KNOWLEDGE` candidate. An unbound source, empty index, or provider outage
contributes nothing and the gate can abstain. Citation references use opaque
`knowledge:<source_ref>#<chunk_id>` handles rather than chunk bodies. The reasoner cannot cite a
chunk outside this vouched-for set.

## Deterministic T1 causal chain

`core/rca/causal_chain.py` (`CausalChainAnalyzer`) and `core/rca/t1.py` reconstruct the most probable
multi-hop chain ending at the failure: `root change -> symptom -> ... -> failure`. The root must be
a change. A window of symptoms with no antecedent change abstains.

When a resource-dependency graph is supplied, a change on a direct or bounded transitive dependency
outranks an unrelated one, and unrelated resources cannot link. Without a graph, correlated cross-
resource links remain possible. `same_resource_only` restricts every hop to the failing resource.
Confidence is a weakest-link aggregate weighted by temporal proximity, relationship strength, and
change kind. It is ambiguity-discounted and bounded to the T1 band (`0.35`-`0.85`). Strict temporal
precedence makes the event set a DAG, so the same inputs produce the same cited chain.

The `ControlLoop` obtains members through `IncidentMemberSource`, bounds them by
`causal_chain_window`, and appends one shadow T1 hypothesis per event. The hypothesis retains a
transport-safe `causal_chain` with root and failure ids, ambiguity, and ordered hop evidence.
`DeploymentHistoryMemberSource` bridges a `DeploymentHistoryProvider` and incident lookup into
antecedent change events. Without a source, the T1 causal-chain path stays unavailable.

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
