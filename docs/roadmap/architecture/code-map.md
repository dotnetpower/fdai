---
title: Code Map
---
# Code Map

This page maps each FDAI runtime service and shared package to its physical source, tests, and
owning design. Use it to find the current service-owned implementation without relying on the
retired top-level application tree.

> **Scope:** This map describes the validated local IS-08 repository ownership and IS-07 local
> upgrade and rollback proof. IS-09 owns the deferred remote verification.

## Design at a glance

- **Five service distributions:** Every runtime process owns one package under `services/`.
- **Two shared packages:** `packages/service-contracts/` owns implementation-free wire contracts;
  `packages/github-app-auth/` owns refreshable provider credentials used by Core and ingestion.
- **Service-owned tests:** Unit and component tests live beside their owning service or package.
- **Virtual root:** The root `pyproject.toml` has `package = false` and coordinates the uv workspace. `pytest-timeout` enforces a 120 s per-test ceiling so a hanging test cannot block an xdist shard indefinitely; `faulthandler_timeout` (90 s) dumps all thread stacks before the hard kill to preserve diagnostic evidence.
- **Integration-only root tests:** `tests/integration/` owns cross-service compatibility, topology,
  and repository checks.
- **Operator startup revision fence:** Production Operator composition delegates resolved-model
  source construction to a focused lifecycle module and verifies the immutable digest before Cost
  Governance projections or any other lifecycle bridge starts.
  The fence grants no mapping, assessment, or execution authority. If startup fails, composition
  attempts every acquired service cleanup and reports cleanup errors with the original failure.
- **Platform-to-service bindings:** Root Terraform exports reviewed non-secret targets and Key Vault
  secret references. Protected service deployment validates those objects before delivery, and the
  bot-owned wrapper accepts only an exact Core or Document Ingestion API plan. Transition flags come
  from its sealed mode, including combined Core bindings; service tfvars cannot replace ownership or approval.
- **Model network policy:** `infra/modules/llm/azure-openai/` keeps public access and key authentication disabled by default. The root module and protected dev workflow expose one explicit public-access opt-in only for environments that independently retain deny-by-default trusted-source ACLs.

> **Index contract:** This page is navigation-only. Linked owner documents contain current
> implementation status and history. The retired mixed-purpose ledger is preserved in the
> [archived Code Map implementation ledger](../../roadmap-implementation/architecture/code-map.md).

## Physical service ownership

| Owner | Source | Tests | Distribution |
|-------|--------|-------|--------------|
| Core Control Plane | [fdai](../../../services/core-control-plane/src/fdai/) and [fdai_core_service](../../../services/core-control-plane/src/fdai_core_service/) | [Core tests](../../../services/core-control-plane/tests/) | `fdai-core-control-plane` |
| Operator Service | [fdai_operator_service](../../../services/operator-service/src/fdai_operator_service/) | [Operator tests](../../../services/operator-service/tests/) | `fdai-operator-service` |
| Document Ingestion API | [fdai_ingestion_api_service](../../../services/document-ingestion-api/src/fdai_ingestion_api_service/) | [Ingestion API tests](../../../services/document-ingestion-api/tests/) | `fdai-document-ingestion-api` |
| Document Processing Worker | [fdai_document_worker_service](../../../services/document-processing-worker/src/fdai_document_worker_service/) | [Worker tests](../../../services/document-processing-worker/tests/) | `fdai-document-processing-worker` |
| Isolated Executor | [fdai_executor_service](../../../services/isolated-executor/src/fdai_executor_service/) | [Executor tests](../../../services/isolated-executor/tests/) | `fdai-isolated-executor-service` |
| Service contracts | [fdai_service_contracts](../../../packages/service-contracts/src/fdai_service_contracts/) | [Contract tests](../../../packages/service-contracts/tests/) | `fdai-service-contracts` |
| Optional Cost Governance package | [fdai_cost_governance](../../../extensions/cost-governance/src/fdai_cost_governance/) | [Package tests](../../../extensions/cost-governance/tests/) and [legacy advisory guard coverage](../../../extensions/cost-governance/tests/test_legacy_advisory_guards.py) | `fdai-cost-governance` |
| Cross-service integration | Not applicable | [Root integration tests](../../../tests/integration/) | Virtual root only |

Shared handover artifacts exclude computed convenience fields from their serialized API and storage
projection, so service-local derived properties cannot change the cross-service wire contract.

The Document Ingestion API also owns the FDAI-native cross-tenant SharePoint connector. Its
federated managed identity obtains Microsoft Graph tokens in the target tenant, while its durable
delta and intake adapters map changed files to server-owned document policy. Power Platform is not
a runtime dependency. Root Terraform forwards connector settings only through the document
ingestion module; neither service composition nor root composition imports the optional Cost
Governance package or changes cost authority.

## Core Control Plane map

The Core distribution retains the complete `fdai` namespace. Internal module boundaries remain
unchanged by the physical move.

Service migration inventory tests verify that renamed partitions retain their creation lineage,
use the effective table name at the current migration head, and that the legacy schema contract
fingerprint reflects the post-rename table set and counts. CI runs root rollback checks before
service-owned migrations in the isolated service database, then runs service-dependent tests at
that service head. Cross-service database grants, such as Operator read access to Core-owned Cost
Governance objects, live in downstream Operator-owned migrations rather than the Core branch, so
bootstrap ordering never requires a role created later in the sequence.
The migration ownership inventory also pins the durable conversation-channel message claim and the
Cost Governance lifecycle, settlement, and retention tables before either package can ship. The
single required CI graph owns Terraform validation and security scanning, while the path-scoped
container supply-chain workflow owns image build, vulnerability scanning, and attestation.
Core image materialization writes canonical resolved-model JSON bytes, so the attested digest is
the same byte-level fence enforced at startup.
External actions remain pinned to full commit SHAs; repository-local composite actions are accepted
only by their checked-out relative path and are covered by the protected-workflow source verifier.
The Terraform security scan requires either an expiry or an explicit coordinated-rotation rationale
for each Key Vault secret.
The root integration suite also contract-pins the Document Processing Worker outbox rule that
routes logical `object.*` events before marking durable publication complete.
Control-loop end-to-end tests count published actions and unresolved graph-derived blast-radius
abstentions separately.
Azure semantic query construction lives in `semantic_query_azure_composition.py`.
`wire_semantic_query.py` directly re-exports that constructor while retaining the established
public import, and the general wiring module stays below the enforced 800-line ceiling.

Semantic resource-health planning now keeps collection health, exact resource identity, explicit
name-or-tag filtering, and time-bounded evidence requests distinct. The Core query path preserves
provider completeness and reason codes, while the Operator presentation and Console dashboard keep
partial or unavailable observations visible instead of substituting generic inventory rows.
Inventory change ingestion now uses the typed `inventory_observation.py` contract and dual-writes
the Core-owned append-only PostgreSQL observation journal while the existing overlay remains the
current read path. Journal replay applies explicit property masks, keeps operation status separate
from resource state, and exposes journal and ontology projection watermarks to source-completeness
checks.
`operational_history_lifecycle.py` and `operational_history_certification.py` own incarnation,
partition, correction, checkpoint, pin, retention, pressure, recovery, and pinned-revision
certification semantics. Delivery adapters bind those records to PostgreSQL, verified private Blob
artifacts, principal-scoped reads, a database-owned purge gate, and a fixed shadow schedule.
The OI-16 protected certification campaign lives in
`delivery/operational_history_certification_campaign*.py`, with its exact synthetic retention and
append-only recovery schema in `20260907_core_oi16_certification_support.py`. The shared journal
keeps synthetic purge retention disabled by default; only a validated dev campaign enables it.
The protected workflow binds all 13 scenario results to exact CI, runtime-image attestation,
deployment evidence, and separate human approval before the certification writer can append a
receipt.

Prompt composition keeps role and safety layers in `core/prompts/` and moves Azure startup assembly
into `composition/wire_azure_prompts.py`. Revisioned conversation settings are written by the
Operator Service to the shared `runtime-settings:policy` record and consumed once by Core at
startup. Prompt ablation removes only optional context and records every exclusion for replay.
Question campaign wording uses `core/conversation/question_candidates.py` as the server-owned
semantic boundary. Azure and explicit Copilot generators receive the complete immutable case but
can return only a `question` field. Core binds the case before independent semantic review, so
generated prose cannot replace scope, authority, capability, evidence posture, or result shape.
Generated question-bank artifacts record the current Console catalog digests, so a reviewed
presentation-contract change regenerates the JSON bank and review catalog together.
The generated question bank binds both Console message catalogs by digest and is regenerated
whenever those reviewed source catalogs change.
The Console static catalog inventory resolves shared, route-local, and optional package catalogs,
including the Dashboard v2 catalog, so a new route cannot hide a missing English fallback key.

Semantic conversation planning keeps `semantic_planning.py`, `semantic_planning_cascade.py`, and
`semantic_planning_frame.py` as compatibility facades. `semantic_planning_fallbacks.py` owns
deterministic clarification and candidate recovery. Focused sibling modules own frame checks,
plan dispatch, anchored-incident and stated-value-filter plan construction, judgment, validation,
frame construction, facets, evidence-specific investigation normalization, typed multi-pair
relationship planning, and queries while preserving public imports, deterministic gate order, and
read-only authority. Typed Rule traces bind the exact Rule declaration and all required LinkType
receipts before answering. Service-to-Agent ownership uses one exact-release, principal-scoped
composite read receipt and preserves each concrete BusinessService-to-Agent instance path without
granting execution permission. A missing concrete path remains held instead of becoming an answered
identity claim.
Validated `Document` judgments and exact named resource-group membership bypass the residual frame
model through deterministic builders. The document path remains draft-only and binds its source to
the authenticated principal's preceding verified result.
The Core package pins the Snappy codec used by Kafka consumers so compressed EventBus records do
not pass readiness and then terminate a required runtime task.
Resource-state collection plans explicitly request object-only ObjectSets. Other ObjectSets retain
relationship inclusion by default, and the default remains absent from legacy serialized
definitions so replay digests do not change.
Semantic judgment uses strict structured output, and a first-turn operational read avoids the
social preflight while direct social candidates and context-bearing turns remain independently
confirmed.
For a
validated `query.ontology_declaration` count judgment, a unique canonical declaration `*Type` target
takes precedence over a conflicting frame subject. Non-declaration domain targets do not participate
in declaration selection. An exact declaration-kind or canonical `*Type` frame subject is used only
when the judgment has no canonical declaration target. Conflicting canonical declaration targets
remain unresolved. The resulting declaration-count frame uses the focused manifest planner to compile
`query.manifest` and `count` without a model-authored plan.
The Core semantic-turn processor renders complete grouped values as typed declaration counts and
names the read-only manifest source instead of reporting only the aggregate row count. It binds the
display type to the verified frame subject, not to a model-authored node id. These modules preserve
public imports, deterministic gate order, and read-only authority.
Resource Health state-group derivation lives in `semantic_query_health_values.py`, which keeps the
public semantic composition facade below the enforced 800-line ceiling without changing registration
order.
Topology endpoint clarification normalization lives in
`semantic_planning_topology_normalization.py`; the compatibility facade preserves public imports,
deterministic gate order, and read-only authority.
Historical and activity frame construction lives in
`semantic_planning_temporal_frames.py`; inventory collection-health assembly lives in
`inventory_collection_health_reporting.py`; and PostgreSQL inventory-source completeness reduction
lives in `postgres_ontology_source_coverage.py`. The established owner modules keep their import
surfaces while these cohesive helpers stay below structural size ratchets. Service image builds also
assert the resolved security-fixed OPA transitive module versions, and each Python distribution pins
the shared `pypdf` security floor through the frozen workspace lock.
The semantic-routing baseline records each lexical owner and classifies deterministic model-output
validation separately from semantic inference. Content-free judgment telemetry exposes profile and
model-configuration revisions, tier, confidence, latency, outcome, and abstention rate without
retaining utterance, context, or proposal digests. The competency fixture pins the current
structural release and Reader manifest as one coupled identity without claiming production
readiness. ARB evidence fixtures use the authenticated principal context required by runtime reads,
and Cost Governance refreshes its exact-release profile and fixture digests after additive declarations.
Interactive semantic turns can read the audited
`conversation.t2_escalation.aggressive_enabled` runtime setting for each request. Development
defaults it on while staging and production default it off. Eligible read-only T1 clarification,
unavailability, and rejected proposal outcomes can receive one same-stage T2 retry with compact
typed recovery context. Golden campaign, action-draft, server-bound scope, authorization,
deterministic verification, and execution-authority boundaries remain unchanged. The Operator
settings store advances existing revisioned state through one atomic proposal transaction, and
local preparation includes the runtime-setting definition source when deciding whether to refresh
the Settings projection.
Kubernetes Resource Event projections retain optional object UID, cluster, recorded time, and source
revision fields so downstream recovery evidence can preserve identity and provenance without raw
provider payloads.
Semantic answer authority starts in the Core `OntologyFunctionRegistry` invocation receipt. Query
execution carries that typed authority with the same evidence references through `QueryNodeResult`,
`GoalTaskReceipt`, and intent-graph evidence v2. The Operator semantic presentation reads only those
receipts. It preserves distinct subscription health, inventory graph, metering, and ontology
manifest sources, ignores model or client authority text, and leaves missing or conflicting
authority held and unverified.
Mixed resource-condition answers use separate inventory and Resource Health output receipts.
Service Health uses its own subscription-scoped summary, and the Operator retains each source's
authority, completeness, and limitation instead of creating a synthetic combined authority.
An unfiltered Service Health answer derives outage status only from complete `service_issue`
event rows. Health advisories and planned maintenance remain separate active-event categories, and
truncated category coverage produces an unknown outage conclusion rather than an affirmative one.
A configured, managed, or referenced subscription belongs to the server-owned query scope and does
not become an exact server Resource identity or a resource-name clarification.
Inventory promotion also writes verified state changes to the Core-owned append-only operational
state-transition ledger. The ontology remains the rebuildable current-state projection, while the
ledger preserves effective time, recorded time, evidence, and positive coverage for replay.
Collection questions that carry multiple typed resource-state targets bypass exact-target
clarification and retain their grouped read plan. Dependent FunctionType reads still require an
admitted secured ObjectSet receipt. Missing decision-evidence admission produces a bounded
source-unavailable result, and query execution records the non-sensitive denial reason for
diagnosis without weakening the gate.
RCA hypotheses now carry an additive cause domain through T0, T1, and T2. T0 configuration
violations default to infrastructure, T1 preserves the root change domain, and the T2 parser accepts
only the reviewed domain enum. Audit and read projections map historical or unsupported values to
`unknown`; the classification remains evidence-only and cannot authorize an action.
Secured operational-context presentation now requires every named semantic identity to be present
in the receipt-bound ObjectSet before it exposes service, workload, objective, constraint,
ownership, dependency, and per-kind coverage metadata. This closes a projection gap without making
the Console a graph source.
Each verified Context identity list also enforces its expected ObjectType set, preventing a
receipt-bound but type-confused object from being presented as ownership, service, workload,
objective, constraint, or dependency evidence.
Governed RCA document evidence uses a separate adapter and gatherer over the existing
OperationalEvidenceBundle contract. It rechecks current document authorization and revision after
collection-scoped search, emits only opaque citations, and cannot fall back to the unscoped
KnowledgeSource when governed evidence is unavailable.
The governed gatherer independently requires exact set equality between document excerpts and the
document-lane citation manifest, so an extra, duplicate, or missing manifest entry cannot become an
RCA citation.
When governed context is explicitly requested, a gatherer that returns neither citations nor a
hold is normalized to `document_evidence_missing`; unrelated telemetry cannot silently satisfy the
missing governed-evidence requirement.
WARA assessment now layers an exact evaluator-binding catalog over the immutable generated
crosswalk. The Azure delivery adapter accepts only approved management token targets and exact ARM
resource scopes, and carries the overlay digest through read-plan, observation, evidence, result,
and replay identities.
The WARA assessment service can now compose an optional observation runner that executes every
eligible exact-bound read before evaluation, preserves manual receipts, and records provider
unavailability as bounded audit evidence instead of a satisfaction result.
After collection, the runner advances the request evaluation and recorded cutoffs to the latest
collected receipt, preventing a valid fresh observation from being classified as future evidence.
Only evidence collected from the provider in that run participates in cutoff advancement;
caller-supplied evidence remains gated by the request's independent original cutoff.
Caller receipts beyond that original cutoff are marked inadmissible before provider collection, so
an unrelated later observation cannot retroactively admit them.
Before a matching-row WARA evaluator can treat zero violations as satisfied, the Azure adapter
requires a companion exact-id coverage query to observe every target under the same identity and
deadline.
Immutable WARA request, evidence, status, control, and result contracts live in
`core/wara/models.py`. `core/wara/runtime.py` retains deterministic evaluation, observation
collection, audit, and publication while re-exporting the established public contracts.
Default ControlLoop assembly now binds one event-time `IncidentRcaContextSource`. It resolves exact
provider identity from the event's inventory generation, materializes bitemporal topology history,
matches one lifecycle Incident, and admits deployment members only when all generations agree.
Dedicated read identity, sovereign endpoint, split-service hydration, and one complete timeout keep
the path fail closed without unscoped production correlation.
`runtime/control_loop_auxiliary.py` owns deterministic RCA catalog identity and IRP handler assembly.
`runtime/control_loop.py` retains authoritative loop composition and re-exports the existing private bootstrap hook through an explicit `__all__` entry for package-wide strict type checking.
Automated Incident T2 also has a paired governed-document binding. Core receives a separate read-only DSN plus exact collection, access-reference, and reader-group configuration; it creates a fixed Forseti principal context and holds the RCA when authorized document evidence is unavailable.

| Area | Responsibility | Source | Tests |
|------|----------------|--------|-------|
| Human approval callback and decision delivery | Teams Bot service and OBO actor verification, mapped Slack reauthentication, exact callback context, sanitized two-phase audit, lease-fenced Operator outbox, workflow quorum routing, and action-only resume with no BreakGlass or executor authority | [Operator callback family](../../../services/operator-service/src/fdai_operator_service/families/iam/), [Operator outbox](../../../services/operator-service/src/fdai_operator_service/families/iam/hil_decision_outbox.py), [Core decision consumer](../../../services/core-control-plane/src/fdai/runtime/consumers.py), and [HIL registry](../../../services/core-control-plane/src/fdai/shared/providers/hil_registry.py) | [Operator IAM tests](../../../services/operator-service/tests/test_operator_iam_family.py), [Teams callback tests](../../../services/operator-service/tests/test_hil_teams_callback.py), [outbox replay tests](../../../services/operator-service/tests/test_hil_decision_outbox_replay.py), and [cross-service routing tests](../../../tests/integration/test_hil_decision_routing.py) |
| Human assignment ownership coordination | Idempotent shadow ownership draft publication, exact case, PR, and content-digest merge correlation, ownership effect recording, and typed shadow IAM apply requests | [Human assignment core](../../../services/core-control-plane/src/fdai/core/human_assignment/) and [ownership coordinator](../../../services/core-control-plane/src/fdai/core/human_assignment/ownership_coordination.py) | [Human assignment tests](../../../services/core-control-plane/tests/core/human_assignment/) |
| Deployed model inventory discovery | Read-only collection, readable model/SKU/status projection, bilingual semantic lookup, and ontology projection of existing Azure AI model deployments under their parent accounts, with normal scope, freshness, completeness, and no-execution constraints. Conversational deployment requests produce no ActionType. | [resource type](../../../rule-catalog/vocabulary/resource-types.yaml), [Azure ARG projection](../../../services/core-control-plane/src/fdai/delivery/azure/arg_query.py), [provider relationship mapping](../../../rule-catalog/vocabulary/provider-relationship-mappings/azure-arg-v1.yaml), and [Operator rows](../../../services/operator-service/src/fdai_operator_service/families/conversation/presentation_rows.py) | [semantic planning tests](../../../services/core-control-plane/tests/conversation/test_semantic_planning.py), [Azure projection tests](../../../services/core-control-plane/tests/delivery/azure/test_arg_query.py), [ontology projection tests](../../../services/core-control-plane/tests/core/ontology_platform/test_inventory_projection.py), and [Operator row tests](../../../services/operator-service/tests/test_presentation_rows.py) |
| Azure Resource Health exact-denominator evidence | Exact secured Resource denominator, fixed bracket-only provider queries, canonical availability states, per-target coverage, separate collection and provider times, deterministic claim projection, limitation-visible Operator presentation, and no execution authority | [evidence contract](../../../services/core-control-plane/src/fdai/core/ontology_platform/resource_health_evidence.py), [FunctionType](../../../services/core-control-plane/src/fdai/core/ontology_platform/resource_health_queries.py), [Azure reader](../../../services/core-control-plane/src/fdai/delivery/azure/resource_health_collection.py), [claim projection](../../../services/core-control-plane/src/fdai_core_service/semantic_assurance_claims.py), and [Operator presentation](../../../services/operator-service/src/fdai_operator_service/families/conversation/presentation_artifact_v2.py) | [contract and FunctionType tests](../../../services/core-control-plane/tests/core/ontology_platform/test_resource_health_queries.py), [Azure reader tests](../../../services/core-control-plane/tests/delivery/azure/test_resource_health_collection.py), [claim tests](../../../services/core-control-plane/tests/test_semantic_assurance_projection.py), and [presentation tests](../../../services/operator-service/tests/test_presentation_artifact_v2.py) |
| Conversation assurance policy lifecycle | Scoped shadow-to-active progression with an enforced no-skip stage graph, mandatory audit reasons, PostgreSQL-persisted paired decision-evidence digests, legacy-stable keys and no-op replay, bounded trial metrics, non-negative absolute costs, immutable rollback, and no execution authority | [promotion contract](../../../services/core-control-plane/src/fdai/core/conversation_assurance/promotion.py), [lifecycle coordinator](../../../services/core-control-plane/src/fdai/core/conversation_assurance/lifecycle.py), and [PostgreSQL store](../../../services/core-control-plane/src/fdai/delivery/persistence/postgres_conversation_assurance_policy.py) | [promotion tests](../../../services/core-control-plane/tests/core/conversation_assurance/test_learning.py), [lifecycle tests](../../../services/core-control-plane/tests/core/conversation_assurance/test_lifecycle.py), and [persistence tests](../../../services/core-control-plane/tests/persistence/test_postgres_conversation_assurance_policy.py) |
| Pantheon conversation diagnostics | Content-free 30-point turn reduction with validated case expectations, strict independent-review identities and booleans, exact complete atomic-rubric ordering, lowercase SHA-256 trace binding, aggregate-decision and hard-zero consistency, and fail-closed schema-v1 empty-result compatibility at replay boundaries | [diagnostic scorecard](../../../services/core-control-plane/src/fdai/core/conversation_assurance/pantheon_scorecard.py) | [diagnostic tests](../../../services/core-control-plane/tests/core/conversation_assurance/test_pantheon_diagnostics.py) and [hardening classification tests](../../../services/core-control-plane/tests/core/conversation_assurance/test_pantheon_hardening.py) |
| Typed relationship conversation assurance | Deterministic semantic-facet recovery, exact Rule declaration plus multi-pair LinkType planning, merged receipt lineage, bounded verified ontology paths, and schema claims that never masquerade as current instance identity. Service ownership uses a complete, non-redacted, generation-bound instance path under one composite read authority; unsupported or empty mappings remain held. An unbound change-correlation request retains its reviewed `compare/windowed` frame and returns a hold without relationship or causal evidence only for the already reviewed relationship or change-activity intent, the exact `approved_windows`, `target_resources`, and `service_paths` facets, a reviewed non-causal facet, and a `change`, `changes`, `change_records`, or `incident` anchor. The hold cannot assert causation, so a model-omitted non-causal facet does not turn it into an unsupported generic relationship response. Reviewed schema-level object-type and link-type targets may preserve that frame but never establish instance identity; any concrete target or extra facet bypasses the hold. | [relationship planner](../../../services/core-control-plane/src/fdai/core/conversation/semantic_relationship_planning.py), [instance path handler](../../../services/core-control-plane/src/fdai/core/ontology_platform/query_source_handlers.py), [frame checks](../../../services/core-control-plane/src/fdai/core/conversation/semantic_planning_frame_checks.py), [assurance projection](../../../services/core-control-plane/src/fdai_core_service/semantic_assurance_projection.py), and [answer projection](../../../services/core-control-plane/src/fdai_core_service/semantic_relationship_projection.py) | [semantic planning tests](../../../services/core-control-plane/tests/conversation/test_semantic_planning_tier_routing.py), [instance path tests](../../../services/core-control-plane/tests/core/ontology_platform/test_investigation_query_nodes.py), [assurance tests](../../../services/core-control-plane/tests/test_semantic_assurance_projection.py), and [answer tests](../../../services/core-control-plane/tests/test_semantic_turn_processor.py) |
| Kubernetes Resource event history | Source-grounded exact-target planning, fail-closed exact identity cardinality, receipt-bound exact-child UID filtering or explicit exact-cluster bounded Kubernetes Event reads, leased opaque-cursor collection, indexed append-only retention, normalized event time, content-addressed evidence, limitation-aware bilingual answers, independent Azure/Kubernetes family routing, explicit incomplete results, and no raw message, cause, mutation, or execution authority | [semantic planner](../../../services/core-control-plane/src/fdai/core/conversation/semantic_resource_event_planning.py), [FunctionType](../../../services/core-control-plane/src/fdai/core/ontology_platform/resource_event_queries.py), [Kubernetes reader](../../../services/core-control-plane/src/fdai/delivery/kubernetes_resource_event_history.py), [family router](../../../services/core-control-plane/src/fdai/delivery/resource_event_history.py), [runtime binding](../../../services/core-control-plane/src/fdai/runtime/resource_event_providers.py), and [answer projection](../../../services/core-control-plane/src/fdai_core_service/semantic_turn_processor.py) | [semantic planning tests](../../../services/core-control-plane/tests/conversation/test_semantic_planning.py), [Kubernetes adapter tests](../../../services/core-control-plane/tests/delivery/test_kubernetes_resource_event_history.py), [router tests](../../../services/core-control-plane/tests/delivery/test_resource_event_history.py), [FunctionType tests](../../../services/core-control-plane/tests/core/ontology_platform/test_resource_event_queries.py), [answer tests](../../../services/core-control-plane/tests/test_semantic_turn_processor.py), and [runtime tests](../../../services/core-control-plane/tests/runtime/test_resource_health_provider.py) |
| Exact-Pod diagnosis | Exact secured Pod UID, bounded termination lookback, fresh complete conflict-free provider state metadata, UID-filtered lifecycle reasons, content-free log evidence, and no cause or execution authority | [diagnosis FunctionType](../../../services/core-control-plane/src/fdai/core/ontology_platform/kubernetes_pod_diagnosis_queries.py) and [diagnosis reducer](../../../services/core-control-plane/src/fdai/core/ontology_platform/kubernetes_pod_diagnosis_evidence.py) | [diagnosis query tests](../../../services/core-control-plane/tests/core/ontology_platform/test_kubernetes_pod_diagnosis_queries.py) and [diagnosis reducer tests](../../../services/core-control-plane/tests/core/ontology_platform/test_kubernetes_pod_diagnosis_evidence.py) |
| Control loop and decisioning | Event normalization, tier routing, exact Rego allow/deny evaluation receipts, quality, risk, approval, execution coordination, recovery, and audit | [core](../../../services/core-control-plane/src/fdai/core/) | [core tests](../../../services/core-control-plane/tests/core/) |
| CAF/WAF/WARA framework catalog and readiness | Pinned advisory framework definitions, complete 59-control WAF checklist, all 456 WARA/APRL lifecycle records, typed scope-bound evidence, manifest-derived completeness, non-authoritative ontology projection, and bounded source-visible Operator reads | [framework loader](../../../services/core-control-plane/src/fdai/rule_catalog/schema/framework_catalog.py), [WARA importer](../../../scripts/catalog/import_wara_aprl.py), [readiness composition](../../../services/core-control-plane/src/fdai/composition/readiness_catalog.py), [framework projection](../../../services/core-control-plane/src/fdai/core/ontology_platform/framework_projection.py), and [Operator projection](../../../services/operator-service/src/fdai_operator_service/family_adapters.py) | [framework catalog](../../../services/core-control-plane/tests/rule_catalog/test_framework_catalog.py), [WARA importer](../../../services/core-control-plane/tests/rule_catalog/test_wara_import.py), [readiness](../../../services/core-control-plane/tests/composition/test_readiness_catalog.py), [ontology projection](../../../services/core-control-plane/tests/core/ontology_platform/test_framework_projection.py), and [Operator workflow](../../../services/operator-service/tests/test_operator_workflow_family.py) tests |
| Planned-change graph evidence | Exact-cutoff graph receipts that independently re-derive authentication, release alignment, freshness, completeness, conflict, synthetic, future-time, and truncation state before Forseti can preserve an existing authority ceiling | [impact assessment](../../../services/core-control-plane/src/fdai/core/impact_analysis/change_assessment.py) and [Forseti](../../../services/core-control-plane/src/fdai/agents/forseti.py) | [impact tests](../../../services/core-control-plane/tests/core/impact_analysis/test_change_assessment.py) and [agent-chain tests](../../../services/core-control-plane/tests/agents/test_change_management_chain.py) |
| Phase 4 measurement Jobs | Three default-off bounded Container Apps Jobs with a dedicated non-executor identity, secret references, and nullable root outputs | [measurement module](../../../infra/modules/measurement-runners/) and [root composition](../../../infra/main.tf) | [Terraform plan tests](../../../infra/modules/measurement-runners/tests/jobs.tftest.hcl) and [root contract tests](../../../tests/integration/infra/test_measurement_runner_jobs.py) |
| Phase 4 measured policy runners | Complete temporal holdout before inert pattern write, paired model cost/quality review recommendations, T0/T1/T2 budget-volume-percentile audit, explicit unavailable state, and durable duplicate/restart convergence without promotion or execution authority | [Core reducers](../../../services/core-control-plane/src/fdai/core/measurement/), [holdout gate](../../../services/core-control-plane/src/fdai/delivery/measurement/holdout.py), [measured policy runner](../../../services/core-control-plane/src/fdai/delivery/measurement/measured_policy.py), and [CLI composition](../../../services/core-control-plane/src/fdai/delivery/measurement_runner_cli.py) | [Core measurement tests](../../../services/core-control-plane/tests/core/measurement/), [delivery tests](../../../services/core-control-plane/tests/delivery/measurement/), and [runner tests](../../../services/core-control-plane/tests/measurement/test_runners.py) |
| Provider relationship D2-D4 lifecycle | Pinned schema inputs, inert explicit-orientation candidates, complete-endpoint canonical projection, transitive-only rebuild invalidation, replayable edge/traversal/impact comparison, exact rollback pointer, and immutable distinct-reviewer proposal history | [candidate generation](../../../services/core-control-plane/src/fdai/delivery/provider_schema_relationship_generation.py), [review ledger](../../../services/core-control-plane/src/fdai/delivery/provider_schema_relationship_ledger.py), [complete-generation projection](../../../services/core-control-plane/src/fdai/delivery/azure/generation_relationships.py), and [D4 comparison](../../../services/core-control-plane/src/fdai/core/ontology_platform/direction_shadow/) | [generation and ledger tests](../../../services/core-control-plane/tests/delivery/), [canonical fixture tests](../../../services/core-control-plane/tests/delivery/test_inventory_relationship_verifier.py), and [D4 tests](../../../services/core-control-plane/tests/core/ontology_platform/direction_shadow/) |
| Decision-evidence verification | Versioned authentication, evidence, completeness, conflict, and freshness-policy proofs; content-addressed bundles; validity and revocation-aware verifier selection; fail-closed readiness checks that convert expected verifier, validation, timeout, lookup, and transport failures into bounded rejection while preserving task cancellation; a short-lived no-authority admission that binds verified evidence to an exact downstream decision input; every registered positive decision boundary in `config/decision-boundary-inventory.json`, covering ChatOps qualification, chat-policy stage promotion, rubric mode promotion, current-case T1 reuse, operational promotion, secured ontology query consumption, operational-context state evidence and snapshots (bypass closure forces SHADOW_ONLY only when a provider is bound but not required; without a provider the graph-based ceiling applies), analyzer identity and state target selection, startup readiness, operational readiness, causal closure, effect-model activation and idempotent replay, workflow gates, durable workflow approval, and workflow outcome acceptance, each of which accepts a positive outcome only for a current admission matching its complete input digest, scope, purpose, and source revision; a complete-inventory coverage guard that pins the exact reviewed decision surface and fails for an uncovered boundary, a dead or discarded admission check, a wrong-module assessor, or a source boundary missing from the inventory; legacy promotion receipts that remain readable but cannot authorize enforcement without the shared receipt and bundle digests; and Managed Identity-authenticated Azure readback without credential retention or execution authority | [verification contract](../../../packages/service-contracts/src/fdai_service_contracts/decision_evidence_verification.py), [verifier provider seam](../../../services/core-control-plane/src/fdai/shared/providers/decision_evidence_verifier.py), [readiness gate](../../../services/core-control-plane/src/fdai/core/readiness/decision_evidence.py), [startup coordinator](../../../services/core-control-plane/src/fdai/core/readiness/coordinator.py), [operational readiness service](../../../services/core-control-plane/src/fdai/composition/readiness.py), [qualification reducer](../../../services/core-control-plane/src/fdai/core/conversation_assurance/quality_qualification.py), [chat-policy promotion](../../../services/core-control-plane/src/fdai/core/conversation_assurance/promotion.py), [promotion evaluator](../../../services/core-control-plane/src/fdai/core/measurement/operational_promotion.py), [query authority](../../../services/core-control-plane/src/fdai/core/ontology_platform/query_receipt_authority.py), [state bundle](../../../services/core-control-plane/src/fdai/core/operational_context/evidence_bundle.py), [context snapshot materializer](../../../services/core-control-plane/src/fdai/core/operational_context/materializer.py), [analyzer target resolver](../../../services/core-control-plane/src/fdai/delivery/analyzer_targets.py), [causal closure](../../../services/core-control-plane/src/fdai/core/rca/hypothesis.py), [effect-model activation](../../../services/core-control-plane/src/fdai/core/assurance_twin/model_promotion.py), [workflow gate resolver](../../../services/core-control-plane/src/fdai/core/workflow/gate_resolver.py), [workflow approval admission](../../../services/core-control-plane/src/fdai/core/workflow/approval_admission.py), [workflow outcome ledger](../../../services/core-control-plane/src/fdai/core/workflow/outcome_verification.py), [boundary inventory](../../../config/decision-boundary-inventory.json), [coverage guard](../../../scripts/quality/architecture/check-decision-boundary-coverage.py), and [Azure adapter](../../../services/core-control-plane/src/fdai/delivery/azure/decision_evidence.py) | [contract tests](../../../packages/service-contracts/tests/test_decision_evidence_verification.py), [readiness tests](../../../services/core-control-plane/tests/core/readiness/test_decision_evidence.py), [startup coordinator tests](../../../services/core-control-plane/tests/core/readiness/test_startup_coordinator.py), [operational readiness tests](../../../services/core-control-plane/tests/composition/test_readiness_service.py), [qualification and chat-policy tests](../../../services/core-control-plane/tests/core/conversation_assurance/), [promotion tests](../../../services/core-control-plane/tests/core/measurement/test_operational_promotion.py), [query authority tests](../../../services/core-control-plane/tests/core/ontology_platform/test_query_receipt_authority.py), [state bundle and snapshot tests](../../../services/core-control-plane/tests/core/operational_context/), [analyzer target tests](../../../services/core-control-plane/tests/delivery/test_analyzer_targets.py), [causal closure tests](../../../services/core-control-plane/tests/core/rca/test_hypothesis.py), [effect-model activation tests](../../../services/core-control-plane/tests/assurance_twin/test_model_promotion.py), [workflow gate and outcome tests](../../../services/core-control-plane/tests/core/workflow/), [coverage guard tests](../../../tests/integration/scripts/test_decision_boundary_coverage.py), and [Azure adapter tests](../../../services/core-control-plane/tests/delivery/azure/test_decision_evidence.py) |
| A3-E lifecycle persistence | Core-computed immutable revisions, exact-subject non-reusable approval and verified-evidence bindings, authenticated admit/renew/revoke commands, per-family hash-chained transitions, monotonic fencing, rebuildable projections, atomic PostgreSQL audit, anchored latest-snapshot reads, and an unwired fail-closed primary-store fence check | [revision identity](../../../services/core-control-plane/src/fdai/core/standing_authority/lifecycle_revision.py), [lifecycle](../../../services/core-control-plane/src/fdai/core/standing_authority/lifecycle.py), [fence guard](../../../services/core-control-plane/src/fdai/core/standing_authority/fence.py), [provider seam](../../../services/core-control-plane/src/fdai/shared/providers/standing_authority.py), [PostgreSQL adapter](../../../services/core-control-plane/src/fdai/delivery/persistence/postgres_standing_authority.py), and [migration](../../../service-migrations/branches/core-control-plane/versions/20260829_core_standing_authority_lifecycle.py) | [standing-authority tests](../../../services/core-control-plane/tests/core/standing_authority/) and [persistence tests](../../../services/core-control-plane/tests/persistence/test_postgres_standing_authority.py) |
| ARB observation trace | Replay-stable, runtime-bound observation of the fixed Huginn, Muninn, specialist, Forseti, and Saga boundaries with explicit owner, identity, deadline, duplicate, restart, conflict, and no-authority checks plus retained terminal observer degradation evidence | [observation loop](../../../services/core-control-plane/src/fdai/core/architecture_review/observation_loop.py) and [projection](../../../services/core-control-plane/src/fdai/core/architecture_review/projection.py) | [architecture review tests](../../../services/core-control-plane/tests/core/architecture_review/) |
| Publisher-qualified model resolution | Backward-compatible catalog and quota seams, SKU-qualified Azure capacity lookup, stable version propagation, fallback across versioned preferences, and route suppression for optional capabilities held without a GA version | [resolver schema](../../../services/core-control-plane/src/fdai/rule_catalog/schema/llm_resolver.py), [deployment projection](../../../services/core-control-plane/src/fdai/rule_catalog/schema/llm_endpoint_selection.py), [resolver CLI](../../../services/core-control-plane/src/fdai/rule_catalog/schema/llm_resolver_cli.py), and [Azure queries](../../../services/core-control-plane/src/fdai/delivery/azure/llm/resolver_queries.py) | [resolver tests](../../../services/core-control-plane/tests/rule_catalog/schema/test_llm_resolver.py), [narrator tests](../../../services/core-control-plane/tests/rule_catalog/schema/test_narrator_collection.py), and [Azure query tests](../../../services/core-control-plane/tests/delivery/azure/llm/test_resolver_queries.py) |
| Model-bound privacy minimization | Typed preflight minimization receipts, deterministic redaction before provider transmission, and fail-closed holds for unsafe model or embedding payloads without changing verdict authority | [model_trace.py](../../../services/core-control-plane/src/fdai/delivery/azure/llm/model_trace.py) and [Azure LLM adapters](../../../services/core-control-plane/src/fdai/delivery/azure/llm/) | [model trace tests](../../../services/core-control-plane/tests/delivery/azure/llm/test_model_trace.py), [adapter tests](../../../services/core-control-plane/tests/delivery/azure/llm/test_adapters.py), and [mixed-model cross-check tests](../../../services/core-control-plane/tests/quality_gate/test_mixed_model_cross_check.py) |
| Scheduled Core Job names | Per-Job preservation of valid existing names and environment-scoped compact fallback when Azure's 32-character limit would be exceeded | [compute module](../../../infra/modules/compute/container-apps/) and [root composition](../../../infra/main.tf) | [Job naming tests](../../../tests/integration/infra/test_container_app_job_names.py) |
| Durable scheduler Job entrypoint | One bounded PostgreSQL-backed scheduler pass with abandoned-claim reconciliation, Event Bus publication into the configured ingress topic, duplicate suppression, sanitized retry output, and no execution authority | [scheduler CLI](../../../services/core-control-plane/src/fdai/delivery/scheduler_tick_cli.py), [scheduler service](../../../services/core-control-plane/src/fdai/core/scheduler/service.py), and [PostgreSQL adapters](../../../services/core-control-plane/src/fdai/delivery/persistence/) | [scheduler CLI tests](../../../services/core-control-plane/tests/delivery/test_scheduler_tick_cli.py), [scheduler tests](../../../services/core-control-plane/tests/core/scheduler/), and [persistence tests](../../../services/core-control-plane/tests/persistence/) |
| Executable DB-DR Job | Delivery-owned Azure PostgreSQL point-in-time restore, bounded deterministic table comparison, rolled-back read/write smoke, teardown, durable verifier audit, and a dedicated non-executor identity | [DB-DR CLI](../../../services/core-control-plane/src/fdai/delivery/db_dr_drill_cli.py), [Azure restore adapter](../../../services/core-control-plane/src/fdai/delivery/azure/db_dr_restore.py), [PostgreSQL checks](../../../services/core-control-plane/src/fdai/delivery/db_dr_postgres.py), and [provider-neutral verifier](../../../services/core-control-plane/src/fdai/core/verticals/resilience/db_dr_verifier.py) | [delivery tests](../../../services/core-control-plane/tests/delivery/), [verifier tests](../../../services/core-control-plane/tests/verticals/test_db_dr_verifier.py), and [infrastructure contract tests](../../../tests/integration/infra/test_scheduler_db_dr_jobs.py) |
| Control-plane regional recovery shadow path | Provider-neutral ordered failover and failback rehearsal with expected-epoch fencing, verified single-writer state, bounded evidence receipts, and halt-before-next-action behavior without live provider mutation | [shadow recovery](../../../services/core-control-plane/src/fdai/core/verticals/resilience/shadow_recovery.py) and [recovery provider contract](../../../services/core-control-plane/src/fdai/shared/providers/control_plane_recovery.py) | [shadow recovery tests](../../../services/core-control-plane/tests/core/verticals/test_recovery_plan_shadow.py), [recovery plan tests](../../../services/core-control-plane/tests/core/verticals/test_recovery_plan.py), and [recovery coordinator tests](../../../services/core-control-plane/tests/core/verticals/test_recovery_coordinator.py) |
| Hallucination rubric promotion | Paired immutable baseline/treatment evidence, confidence-aware readiness, independent review binding, strict manifest verification, and per-ActionType fail-closed rubric mode resolution without promotion authority | [rubric promotion core](../../../services/core-control-plane/src/fdai/core/quality_gate/promotion.py) and [manifest adapter](../../../services/core-control-plane/src/fdai/delivery/measurement/rubric_promotion_evidence.py) | [rubric promotion tests](../../../services/core-control-plane/tests/core/quality_gate/test_rubric_promotion.py), [adapter tests](../../../services/core-control-plane/tests/delivery/test_rubric_promotion_evidence.py), and [composition tests](../../../services/core-control-plane/tests/composition/test_rubric_promotion_binding.py) |
| MSCP response-outcome projection and frozen full-loop closure | Strict shadow `ResponseOutcome` projection that stores a target digest instead of a resource reference, holds an observation the contract cannot represent - out of window, not yet recorded, or before dispatch completion - as `unscorable` instead of raising during dispatch, and carries no execution or promotion authority, exercised by the frozen SRE full-loop replay that runs the real control loop on the shipped shadow executor and closes only from an independent authoritative effect observation | [response-outcome projection](../../../services/core-control-plane/src/fdai/core/mscp_profile/response_outcome.py) and [effect verification](../../../services/core-control-plane/src/fdai/core/mscp_profile/effect_verification.py) | [projection tests](../../../services/core-control-plane/tests/core/mscp_profile/test_response_outcome.py) and [frozen full-loop replay](../../../services/core-control-plane/tests/scenarios/test_v2026_07_replay.py) |
| MSCP effect readiness | Restart-safe expected-effect records with exact candidate tuple and deadline, compare-and-set observation leases, stale revision and ownership fencing, deadline-ordered worker recovery, durable verified/mismatch/hold results, provider-failure isolation, candidate-separated reviewed metrics and 95% confidence lower bounds, zero-tolerance guard gaps, default-shadow reviewed profile lifecycle with immediate demotion, exhaustive bounded failure routing without retry or approval fan-out, append-only audit transitions, and no execution, promotion, or activation authority | [pending-effect store](../../../services/core-control-plane/src/fdai/core/mscp_profile/pending_effect_store.py), [observation worker](../../../services/core-control-plane/src/fdai/core/mscp_profile/observation_worker.py), [readiness evaluator](../../../services/core-control-plane/src/fdai/core/mscp_profile/readiness.py), [profile lifecycle](../../../services/core-control-plane/src/fdai/core/mscp_profile/profile_lifecycle.py), and [failure policy](../../../services/core-control-plane/src/fdai/core/mscp_profile/failure_policy.py) | [pending-effect tests](../../../services/core-control-plane/tests/core/mscp_profile/test_pending_effect_store.py), [worker tests](../../../services/core-control-plane/tests/core/mscp_profile/test_observation_worker.py), [readiness tests](../../../services/core-control-plane/tests/core/mscp_profile/test_readiness.py), [lifecycle tests](../../../services/core-control-plane/tests/core/mscp_profile/test_profile_lifecycle.py), and [failure tests](../../../services/core-control-plane/tests/core/mscp_profile/test_failure_policy.py) |
| Execution authorization | Provider-neutral requirement outcomes, least-permissive reduction of non-empty decision sets, canonical request and inventory binding, and rejection of ambiguous identity or unbound grant proposals | [execution_authorization](../../../services/core-control-plane/src/fdai/core/execution_authorization/) | [execution authorization tests](../../../services/core-control-plane/tests/core/execution_authorization/) |
| Ontology safety platform | Exact semantic releases with catalog-loaded Interface and FunctionType declarations, release-aware query profiles and function registration, principal-scoped manifests, verified Resource-to-ResourceType classification, generic and temporal query algebra, bitemporal topology and diffs, immutable direction-generation shadow comparisons with bounded blast-radius deltas, authoritative-inventory rebuild pointers, and distinct-reviewer regression-bound catalog PR proposals, reviewed metric concepts, topology-aware causal joins, cross-source projected-state and telemetry adjudication without value averaging or authority gain, per-Resource freshness-complete graph reads, digest-fenced continuous operating-model replay recovery, evidence-bound reads and copy-on-write scenario branches without production write authority, mutation plans with separate planner-function and operational-plan lineage plus documented fail-closed argument, evidence, target, and effect validation contracts, compact typed effect-reconciliation events, authenticated independent-observer binding, and lease-fenced durable terminal outbox delivery | [ontology_platform](../../../services/core-control-plane/src/fdai/core/ontology_platform/) | [ontology platform tests](../../../services/core-control-plane/tests/core/ontology_platform/) |
| Ontology structural model | Exact ResourceType identity, reviewed ResourceClass aggregation, reviewed Property semantics and capability Interfaces, direct-link roles and semantic traits, exploratory traversal, ordered typed paths, and limitation-preserving graph presentation | [owner design](ontology-structural-model.md), [ontology contracts](../../../services/core-control-plane/src/fdai/shared/contracts/models/ontology.py), [catalog projection](../../../services/core-control-plane/src/fdai/core/ontology_platform/catalog_projection.py), and [query platform](../../../services/core-control-plane/src/fdai/core/ontology_platform/) | [ontology platform tests](../../../services/core-control-plane/tests/core/ontology_platform/), [catalog tests](../../../services/core-control-plane/tests/rule_catalog/), and [Console graph tests](../../../console/src/components/ontology-graph.model.test.ts) |
| Operational instance evidence adapters | Authenticated exact-endpoint runtime-call observations, principal-safe PostgreSQL role evidence, explicit unavailable source state, and verified pre-promotion enrichment through the inventory single writer without action authority | [runtime-call telemetry](../../../services/core-control-plane/src/fdai/core/ontology_platform/runtime_call_telemetry.py), [PostgreSQL role evidence](../../../services/core-control-plane/src/fdai/core/ontology_platform/postgres_role_evidence.py), and [inventory binding](../../../services/core-control-plane/src/fdai/delivery/runtime_call_inventory.py) | [runtime-call telemetry tests](../../../services/core-control-plane/tests/core/ontology_platform/test_runtime_call_telemetry.py), [PostgreSQL role evidence tests](../../../services/core-control-plane/tests/core/ontology_platform/test_postgres_role_evidence.py), and [inventory binding tests](../../../services/core-control-plane/tests/delivery/test_runtime_call_inventory.py) |
| Kubernetes workload evidence | Allowlisted Deployment and Pod observations, exact target selection, independently verified two-hop ownership evidence, reviewed immutable-Pod restart-history metrics, pure freshness- and conflict-aware rollout, same-UID restart, distinct-UID replacement, and content-free exact-Pod diagnosis that never claims root cause or execution authority. Replacement evidence binds cluster, namespace, workload revision, lifecycle ordering, scoped termination, positive container and replica state, and complete desired-replica history; ambiguous candidates remain replayable. Diagnosis joins one exact secured Pod UID to bounded lifecycle and content-free log evidence while preserving explicit source gaps. Query binding waits for durable lifecycle ingestion rather than inferring missing historical observations. | [Kubernetes inventory source](../../../services/core-control-plane/src/fdai/delivery/kubernetes_api_inventory.py), [rollout query](../../../services/core-control-plane/src/fdai/core/ontology_platform/kubernetes_rollout_queries.py), [Pod recovery query](../../../services/core-control-plane/src/fdai/core/ontology_platform/kubernetes_pod_recovery_queries.py), [Pod replacement reducer](../../../services/core-control-plane/src/fdai/core/ontology_platform/kubernetes_pod_replacement_evidence.py), [Pod diagnosis query](../../../services/core-control-plane/src/fdai/core/ontology_platform/kubernetes_pod_diagnosis_queries.py), [content-free log adapter](../../../services/core-control-plane/src/fdai/delivery/kubernetes_pod_log_evidence.py), and [semantic planners](../../../services/core-control-plane/src/fdai/core/conversation/) | [inventory source tests](../../../services/core-control-plane/tests/delivery/test_kubernetes_api_inventory.py), [workload reducer and query tests](../../../services/core-control-plane/tests/core/ontology_platform/), [log adapter tests](../../../services/core-control-plane/tests/delivery/test_kubernetes_pod_log_evidence.py), [planner tests](../../../services/core-control-plane/tests/conversation/), and [composition tests](../../../services/core-control-plane/tests/composition/) |
| Continuous operational instance graph | Validated source policy, adaptive collection, event/delta/snapshot convergence, local/deployed analyzer scheduling parity, publish-once analyzer findings that hold an ambiguous send for reconciliation, typed Kubernetes Pod lifecycle findings bound from an explicit evidence source, a bounded Pod lifecycle projection that keeps current state, failure history, recovery, and evidence gaps separable and withdraws state that outlived its freshness budget, principal-safe health, typed semantic rollups, content-addressed archive lifecycle, five-outcome graph refresh decisions, relationship coverage that gates only snapshots able to state a relationship, safe partial live-evidence write-through, and typed representative competency without action authority | [owner design](continuous-operational-instance-graph.md), [audit contract](../../../config/continuous-operational-instance-graph-audit.json), [analyzer CLI](../../../services/core-control-plane/src/fdai/delivery/analyzer_tick_cli.py), [analyzer runner](../../../services/core-control-plane/src/fdai/delivery/analyzer_tick.py), [publish contract](../../../services/core-control-plane/src/fdai/shared/providers/event_bus.py), [publication ledger](../../../services/core-control-plane/src/fdai/delivery/persistence/postgres_analyzer_publication.py), [Pod lifecycle analyzer](../../../services/core-control-plane/src/fdai/core/investigation/kubernetes_pod.py), [Pod evidence binding](../../../services/core-control-plane/src/fdai/delivery/pod_evidence_binding.py), [Pod lifecycle projection reducer](../../../services/core-control-plane/src/fdai/core/readiness/detection_lifecycle.py), [Pod lifecycle projection state](../../../services/core-control-plane/src/fdai/delivery/detection_lifecycle_state.py), [Operator lifecycle projection](../../../services/operator-service/src/fdai_operator_service/detection_lifecycle_projection.py), [local analyzer task](../../../scripts/deployment/local/run-analyzer-loop.sh), [rollup core](../../../services/core-control-plane/src/fdai/core/ontology_platform/semantic_rollup.py), [archive core](../../../services/core-control-plane/src/fdai/core/ontology_platform/archive_manifest.py), [graph refresh](../../../services/core-control-plane/src/fdai/core/ontology_platform/graph_evidence_refresh.py), [projection coverage](../../../services/core-control-plane/src/fdai/delivery/persistence/postgres_ontology.py), [competency](../../../services/core-control-plane/src/fdai/core/ontology_platform/operational_instance_competency.py), [inventory adapter](../../../services/core-control-plane/src/fdai/delivery/inventory_rollup.py), [live evidence](../../../services/core-control-plane/src/fdai/delivery/inventory_live_evidence.py), [archive persistence](../../../services/core-control-plane/src/fdai/delivery/persistence/postgres_operational_archive.py), and [Core migration](../../../service-migrations/branches/core-control-plane/versions/20260822_core_operational_archive.py) | [analyzer tests](../../../services/core-control-plane/tests/delivery/test_analyzer_tick.py), [publication ledger tests](../../../services/core-control-plane/tests/delivery/test_analyzer_publication_ledger.py), [Pod scenario tests](../../../services/core-control-plane/tests/delivery/test_analyzer_tick_pod_scenario.py), [Pod lifecycle reducer tests](../../../services/core-control-plane/tests/core/readiness/test_detection_lifecycle.py), [Pod lifecycle projection tests](../../../services/operator-service/tests/test_detection_lifecycle_projection.py), [Pod lifecycle end-to-end tests](../../../tests/integration/test_pod_lifecycle_detection_e2e.py), [audit tests](../../../tests/integration/scripts/test_continuous_operational_instance_graph_audit.py), [refresh tests](../../../services/core-control-plane/tests/core/ontology_platform/test_graph_evidence_refresh.py), [competency tests](../../../services/core-control-plane/tests/core/ontology_platform/test_operational_instance_competency.py), [live-evidence tests](../../../services/core-control-plane/tests/delivery/test_inventory_live_evidence.py), [rollup tests](../../../services/core-control-plane/tests/core/ontology_platform/test_semantic_rollup.py), [archive tests](../../../services/core-control-plane/tests/core/ontology_platform/test_archive_manifest.py), [purge tests](../../../services/core-control-plane/tests/delivery/test_operational_archive_purge.py), and [cross-lane tests](../../../tests/integration/test_operational_instance_retention.py) |
| Ontology declaration workbench projections | Exact-release declaration details, topology-backed dependents, sanitized ObjectType evidence health, retained-release compatibility, role/purpose redaction, and deterministic revisions without mutation authority | [ontology_declaration_projection.py](../../../services/core-control-plane/src/fdai/delivery/ontology_declaration_projection.py), [ontology_dependents_projection.py](../../../services/core-control-plane/src/fdai/delivery/ontology_dependents_projection.py), [ontology_evidence_health_projection.py](../../../services/core-control-plane/src/fdai/delivery/ontology_evidence_health_projection.py), and [ontology_release_diff_projection.py](../../../services/core-control-plane/src/fdai/delivery/ontology_release_diff_projection.py) | [delivery projection tests](../../../services/core-control-plane/tests/delivery/) and [catalog materializer tests](../../../tests/integration/scripts/test_materialize_authoritative_catalogs.py) |
| OI-12 operational certification | Exact-release seven-axis aggregate snapshots, read-only PostgreSQL collection, signed storage growth, explicit unavailable evidence, bounded local rollup/archive/restore exercise, and no-authority receipt emission | [certification contract](../../../services/core-control-plane/src/fdai/core/ontology_platform/operational_instance_certification.py), [certification reducer](../../../services/core-control-plane/src/fdai/delivery/operational_instance_certification.py), [PostgreSQL source](../../../services/core-control-plane/src/fdai/delivery/operational_instance_certification_postgres.py), [archive exercise](../../../services/core-control-plane/src/fdai/delivery/operational_instance_certification_archive.py), and [certification CLI](../../../services/core-control-plane/src/fdai/delivery/operational_instance_certification_cli.py) | [contract tests](../../../services/core-control-plane/tests/core/ontology_platform/test_operational_instance_certification.py), [delivery tests](../../../services/core-control-plane/tests/delivery/test_operational_instance_certification.py), and [archive exercise tests](../../../services/core-control-plane/tests/delivery/test_operational_instance_certification_archive.py) |
| Semantic conversation planning | Compact T1 social/operational preflight before manifest loading, whole-turn capability-aware schema proposals for every non-direct result, canonical typed-judgment precedence over later frame proposals, server-owned frame/plan identity, principal-manifest verification, async verified execution, evidence-free typed direct responses, content-free tier/config/confidence/latency/outcome and abstention telemetry, total terminal disposition, deterministic intent graphs, exact-command compatibility cutover, declaration-driven bounded question-universe generation, epistemic-closure release receipts, typed network-versus-application latency investigation with exact service-to-Resource scope and fail-closed Resource state evidence, shape-agnostic resolution of a stated exact Resource identity so no turn asks for a target the utterance already names, and continuous coverage gates without execution authority | [conversation](../../../services/core-control-plane/src/fdai/core/conversation/), [semantic judgment telemetry](../../../services/core-control-plane/src/fdai/core/conversation/semantic_judgment_telemetry.py), [S3 frame normalization](../../../services/core-control-plane/src/fdai/core/conversation/semantic_planning_frame_normalization.py), [target candidate planning](../../../services/core-control-plane/src/fdai/core/conversation/semantic_target_candidate_planning.py), and [investigation planner](../../../services/core-control-plane/src/fdai/core/conversation/semantic_investigation_planning.py) | [conversation tests](../../../services/core-control-plane/tests/conversation/) |
| Durable background-task handoff | Lease-fenced detached read records, atomic terminal outbox, transactional Core-to-Operator snapshot and progress outbox claims with progress-before-terminal delivery, Operator-owned projection ingestion, and single-write completion audit markers without production executor binding | [background_task](../../../services/core-control-plane/src/fdai/core/background_task/), [projection publisher](../../../services/core-control-plane/src/fdai_core_service/background_task_projection.py), [projection feed](../../../services/core-control-plane/src/fdai/delivery/persistence/postgres_background_task_projection_feed.py), and [completion audit adapter](../../../services/core-control-plane/src/fdai/delivery/persistence/background_task_completion_audit.py) | [background-task tests](../../../services/core-control-plane/tests/core/background_task/), [runtime tests](../../../services/core-control-plane/tests/runtime/test_read_investigation_runtime.py), and [completion audit tests](../../../services/core-control-plane/tests/persistence/test_background_task_completion_audit.py) |
| Rule semantic generation closure | Typed activation commands and terminal results, exact target-receipt and expected-prior compare-and-swap, replay-before-provider suppression, atomic StateStore result/outbox persistence, lease fencing, retry scheduling, corruption rejection, and broker-acknowledged publication state without policy or execution authority | [rule_semantic_generation](../../../services/core-control-plane/src/fdai/core/rule_semantic_generation/) | [Rule semantic generation tests](../../../services/core-control-plane/tests/core/rule_semantic_generation/) |
| Ontology semantic generations | Provider-neutral bounded ordered-document manifests, self-verifying generation identity, candidate-only concrete indexes, durable PostgreSQL persistence, expected-prior activation compare-and-swap, full/incremental declaration and deployment-object documents, independent validation receipts, stale detection, and rollback | [catalog_search provider](../../../services/core-control-plane/src/fdai/shared/providers/catalog_search.py) and [catalog_search delivery](../../../services/core-control-plane/src/fdai/delivery/catalog_search/) | [catalog search tests](../../../services/core-control-plane/tests/delivery/catalog_search/) |
| Metric, VM process, and MySQL pressure evidence binding | Alias-free reviewed metric concepts, exact ObjectSet-derived label selectors, dependency-only evidence binding on every object-valued FunctionType input so no plan can substitute a model-authored literal for secured evidence, exact `MetricProvider` windows that distinguish observed zero from provider gaps, bounded per-process VM CPU records, and staged MySQL saturation-versus-demand evidence with no cause or execution authority | [metric_window.py](../../../services/core-control-plane/src/fdai/delivery/metric_window.py), [metric_semantic_catalog.py](../../../services/core-control-plane/src/fdai/runtime/metric_semantic_catalog.py), [VM process contract](../../../services/core-control-plane/src/fdai/core/ontology_platform/vm_process_evidence.py), [Azure Monitor Perf adapter](../../../services/core-control-plane/src/fdai/delivery/azure/vm_process_evidence.py), and [MySQL pressure evidence](../../../services/core-control-plane/src/fdai/core/ontology_platform/mysql_pressure_evidence.py) | [metric semantic catalog tests](../../../services/core-control-plane/tests/runtime/test_metric_semantic_catalog.py), [VM process contract tests](../../../services/core-control-plane/tests/core/ontology_platform/test_vm_process_evidence.py), [Azure adapter tests](../../../services/core-control-plane/tests/delivery/azure/test_vm_process_evidence.py), and [MySQL pressure tests](../../../services/core-control-plane/tests/core/ontology_platform/test_mysql_pressure_evidence.py) |
| Operational Hypothesis Loop | Complete graph Dynamic evidence binding, evidence-floor-aware plan selection, deadline-bounded independent trajectory closure, supervised typed effect reconciliation from ordinary exact-plan execution, deployment-owned Ed25519 authentication for independent VM Scale Set observations, authority-free exact kinetic proposal handoff, immutable multi-effect operational lineage with singular historical reads and plural-only new writes, and Owner-HIL-governed graph-model pointer promotion | [graph evidence](../../../services/core-control-plane/src/fdai/delivery/azure/graph_dynamic_evidence.py), [closure](../../../services/core-control-plane/src/fdai/core/assurance_twin/graph_closure.py), [reconciliation](../../../services/core-control-plane/src/fdai/delivery/reconciliation_runtime.py), [signed observation context](../../../services/core-control-plane/src/fdai/delivery/azure/observation_context.py), [runtime observation binding](../../../services/core-control-plane/src/fdai/runtime/observation_evidence.py), [ordinary request producer](../../../services/core-control-plane/src/fdai/delivery/reconciliation_request.py), [kinetic proposal producer](../../../services/core-control-plane/src/fdai/delivery/kinetic_proposal.py), [Forseti binding](../../../services/core-control-plane/src/fdai/agents/forseti.py), [lineage](../../../services/core-control-plane/src/fdai/core/operational_planning/hypothesis_lineage.py), and [promotion](../../../services/core-control-plane/src/fdai/delivery/graph_model_promotion.py) | [graph evidence tests](../../../services/core-control-plane/tests/delivery/azure/test_graph_dynamic_evidence.py), [closure tests](../../../services/core-control-plane/tests/assurance_twin/test_graph_closure.py), [reconciliation tests](../../../services/core-control-plane/tests/delivery/test_reconciliation_runtime.py), [signed context tests](../../../services/core-control-plane/tests/delivery/azure/test_observation_context.py), [runtime binding tests](../../../services/core-control-plane/tests/runtime/test_observation_evidence.py), [kinetic proposal tests](../../../services/core-control-plane/tests/delivery/test_kinetic_proposal.py), [Forseti tests](../../../services/core-control-plane/tests/agents/test_decision_case_e2e.py), [lineage tests](../../../services/core-control-plane/tests/core/operational_planning/test_hypothesis_lineage.py), and [promotion tests](../../../services/core-control-plane/tests/delivery/test_graph_model_promotion.py) |
| Operational learning delivery | Release-pinned eligible-outcome cases, bounded event-bus candidate publication, independent negative review, content-addressed inert draft publication, and reviewed-replay authority that compares the reviewer principal case-insensitively before it can authorize the durable promotion registry | [eligible outcomes and review](../../../services/core-control-plane/src/fdai/core/operational_learning/), [O3 validator and publisher](../../../services/core-control-plane/src/fdai/delivery/gitops_pr/), [O3 runtime binding](../../../services/core-control-plane/src/fdai/runtime/operational_catalog_review.py), [authoritative registry](../../../services/core-control-plane/src/fdai/delivery/persistence/state_store_action_promotion.py), and [O7 evidence](../../../services/core-control-plane/src/fdai/delivery/measurement/operational_promotion_evidence.py) | [governed loop tests](../../../services/core-control-plane/tests/agents/test_governed_learning_loop.py), [O3 delivery tests](../../../services/core-control-plane/tests/delivery/test_gitops_catalog_validator.py), [O3 runtime tests](../../../services/core-control-plane/tests/runtime/test_operational_catalog_review.py), and [O7 evidence tests](../../../services/core-control-plane/tests/delivery/test_operational_promotion_evidence.py) |
| Autonomous rule-discovery cycle | Bounded interval identity, complete observe-to-integrate persistence, terminal-only replay across concurrent replicas with persisted digest validation, independent-family re-approval, recursive rejection of authority-bearing candidate fields, thresholded override-audit intake, override-aware audited metrics, non-duplicating human shadow review, and policy-escape-preserving bounded dwell evidence before a candidate can be considered for promotion | [discovery cycle](../../../services/core-control-plane/src/fdai/core/operational_learning/discovery_cycle.py), [contracts](../../../services/core-control-plane/src/fdai/core/operational_learning/discovery_contracts.py), [override signals](../../../services/core-control-plane/src/fdai/core/operational_learning/override_signals.py), [persistence](../../../services/core-control-plane/src/fdai/core/operational_learning/discovery_persistence.py), and [shadow dwell](../../../services/core-control-plane/src/fdai/core/operational_learning/shadow_dwell.py) | [cycle tests](../../../services/core-control-plane/tests/core/operational_learning/test_discovery_cycle.py), [override signal tests](../../../services/core-control-plane/tests/core/operational_learning/test_override_signals.py), [shadow dwell tests](../../../services/core-control-plane/tests/core/operational_learning/test_shadow_dwell.py), and [human review tests](../../../services/core-control-plane/tests/agents/test_discovery_shadow_review.py) |
| Operational readiness handoff | Typed ownership-transfer ingest, Forseti-accountable read-only review, replay-safe report delivery, and grounded shadow remediation with no approval or execution authority | [readiness composition](../../../services/core-control-plane/src/fdai/composition/readiness.py), [runtime consumer](../../../services/core-control-plane/src/fdai/runtime/consumers.py), and [task binding](../../../services/core-control-plane/src/fdai/runtime/bootstrap_tasks.py) | [runtime ingest tests](../../../services/core-control-plane/tests/runtime/test_operational_readiness_ingest.py), [readiness service tests](../../../services/core-control-plane/tests/composition/test_readiness_service.py), and [remediation tests](../../../services/core-control-plane/tests/core/readiness/test_remediation.py) |
| Outcome Assurance projection contracts | Read-only typed scope, window, readiness, alignment, outcome, guard, and provenance projections with latest-authoritative correction reduction, explicit finalized-event attribution that preserves unresolved denominator events, and replay-stable JSON decoding | [outcome_assurance.py](../../../services/core-control-plane/src/fdai/core/measurement/outcome_assurance.py) and [measurement package](../../../services/core-control-plane/src/fdai/core/measurement/__init__.py) | [Outcome Assurance tests](../../../services/core-control-plane/tests/core/measurement/test_outcome_assurance.py) |
| Governed baseline and treatment cohort claim | Deterministic fail-closed eligibility for a non-synthetic baseline and treatment cohort, measured against a trusted versioned repository policy that pins every required success metric, every zero-threshold guard, the real frozen scenario-set content digest, and the 30-sample floor, and bound to one caller-supplied immutable full 40- or 64-hex commit revision, distinct per-arm report and provenance digests, confidence intervals with absolute values, and completeness and provenance references. Every evaluated arm fact is canonically hashed, and eligibility needs a per-arm admission bound to that hash plus a cohort-level admission bound to the complete receipt digest, both obtained from an injected trusted provider or a separately verified proof bundle, never from the artifact, whose import origin is itself an evaluator parameter supplied by the trusted importer channel | [claim policy](../../../services/core-control-plane/src/fdai/core/measurement/cohort_claim_policy.py) with its [trusted config](../../../config/sre-cohort-claim-policy.json), [cohort contract](../../../packages/service-contracts/src/fdai_service_contracts/baseline_cohort.py), [admission binding](../../../services/core-control-plane/src/fdai/core/measurement/baseline_cohort_claim.py), [receipt importer](../../../tools/cohort_receipt.py), and [baseline runner](../../../tools/baseline_run.py) | [policy tests](../../../services/core-control-plane/tests/core/measurement/test_cohort_claim_policy.py), [cohort contract tests](../../../packages/service-contracts/tests/test_baseline_cohort.py), [claim tests](../../../services/core-control-plane/tests/core/measurement/test_baseline_cohort_claim.py), and [baseline runner tests](../../../services/core-control-plane/tests/tools/test_baseline_runner.py) |
| Architecture review | Manifest readiness, accepted blocker contracts, provider-backed evidence attestation, an injected UTC evaluation clock for deterministic freshness checks, content-addressed no-execution-authority Decision receipts with independently recorded approvals, control-only Process projection, exact verified-snapshot graph evidence, and the target 15-agent review loop | [architecture review core](../../../services/core-control-plane/src/fdai/core/architecture_review/), [change assessment](../../../services/core-control-plane/src/fdai/core/impact_analysis/change_assessment.py), [owner index](architecture-review-board.md), [ontology-agent loop](architecture-review/ontology-agent-loop.md), [evidence-authority contract](architecture-review/evidence-and-authority.md), and [delivery plan](architecture-review/delivery-plan.md) | [architecture review tests](../../../services/core-control-plane/tests/core/architecture_review/), [change assessment tests](../../../services/core-control-plane/tests/core/impact_analysis/test_change_assessment.py), and [readiness checker tests](../../../tests/integration/scripts/test_check_arb_readiness.py) |
| Operator SRE command path | One operator problem-response request bound to exactly one Incident and one idempotent typed ActionProposal under a single correlation, returning authoritative Incident, Trace, Process, and Approval links | [sre_request.py](../../../services/core-control-plane/src/fdai/core/incident/sre_request.py) and [operator_request.py](../../../services/core-control-plane/src/fdai/shared/providers/operator_request.py) | [SRE request tests](../../../services/core-control-plane/tests/core/incident/test_sre_request.py) |
| Agent pantheon | Fifteen fixed agents and their typed event runtime | [agents](../../../services/core-control-plane/src/fdai/agents/) | [agent tests](../../../services/core-control-plane/tests/agents/) |
| Composition | Provider and runtime dependency injection, including exact-release semantic query assembly, request-role executor factories, paired rubric receipt source and verifier binding, and resource-state activity publication with invocation-scoped opaque correlation | [composition](../../../services/core-control-plane/src/fdai/composition/) | [composition tests](../../../services/core-control-plane/tests/composition/) |
| Core adapters | Provider, persistence, notification, and platform adapters retained by Core. The T2 cache persistence boundary owns exact catalog partitions, TTL reads, promotion and rollback state, and atomic rotation receipts through least-privilege database functions. The legacy inventory tracks `ALTER TABLE ... RENAME TO` so that partition renames (e.g. `t2_cache_default` to `t2_cache_legacy_default`) surface as effective table names at head for ownership validation and schema fingerprinting. Public-web results bind answer spans to exact source digests and a no-authority execution receipt before an Azure adapter can return them. | [delivery](../../../services/core-control-plane/src/fdai/delivery/) and [Core service migrations](../../../service-migrations/branches/core-control-plane/) | [delivery tests](../../../services/core-control-plane/tests/delivery/), [T2 cache persistence tests](../../../services/core-control-plane/tests/persistence/test_postgres_t2_cache.py), and [service migration tests](../../../tests/integration/services/test_service_migration_inventory.py) |
| Operational-history lifecycle Job | Shadow scheduling, bounded PostgreSQL partition evidence, private Blob archive verification, restore sampling, hold evaluation, pressure reporting, receipt-gated purge, and a versionless Key Vault secret URI without a PostgreSQL resource dependency | [operational_history_lifecycle_runner.py](../../../services/core-control-plane/src/fdai/delivery/operational_history_lifecycle_runner.py), [PostgreSQL repository](../../../services/core-control-plane/src/fdai/delivery/persistence/postgres_operational_history_lifecycle_runner.py), and [independently targeted Terraform Job](../../../infra/operational_history_lifecycle_job.tf) | [runner tests](../../../services/core-control-plane/tests/delivery/test_operational_history_lifecycle_runner.py) and [infrastructure contract](../../../tests/integration/infra/test_operational_history_lifecycle_job.py) |
| Rule-catalog profile binding | One startup resolution of the governed `FDAI_PROFILE_ID` into the immutable rule tuple the T0 index and workflow guard validation both read, with fail-closed selection and grading and tenant-free startup diagnostics | [rule_profile.py](../../../services/core-control-plane/src/fdai/runtime/rule_profile.py) | [rule profile tests](../../../services/core-control-plane/tests/runtime/test_rule_profile.py) |
| Runtime | Core process lifecycle with an immutable startup plan, typed active-runtime assembly, container-aware shipped-asset resolution, continuous operating-model subscription, effect reconciliation bound after the ControlLoop exposes its ontology store, focused messaging, incident, semantic, resource-ownership, and task-hook boundaries, explicit shutdown ordering, readiness that separates process-critical state and audit writes from authority-critical full-chain proof, and task supervision | [runtime](../../../services/core-control-plane/src/fdai/runtime/), [bootstrap_plan.py](../../../services/core-control-plane/src/fdai/runtime/bootstrap_plan.py), [bootstrap_core.py](../../../services/core-control-plane/src/fdai/runtime/bootstrap_core.py), [bootstrap_resources.py](../../../services/core-control-plane/src/fdai/runtime/bootstrap_resources.py), [bootstrap_messaging.py](../../../services/core-control-plane/src/fdai/runtime/bootstrap_messaging.py), [bootstrap_incidents.py](../../../services/core-control-plane/src/fdai/runtime/bootstrap_incidents.py), [bootstrap_semantics.py](../../../services/core-control-plane/src/fdai/runtime/bootstrap_semantics.py), and [bootstrap_task_hooks.py](../../../services/core-control-plane/src/fdai/runtime/bootstrap_task_hooks.py) | [runtime tests](../../../services/core-control-plane/tests/runtime/), [bootstrap plan tests](../../../services/core-control-plane/tests/runtime/test_bootstrap_plan.py), [messaging tests](../../../services/core-control-plane/tests/runtime/test_bootstrap_messaging.py), [incident tests](../../../services/core-control-plane/tests/runtime/test_bootstrap_incidents.py), and [shutdown tests](../../../services/core-control-plane/tests/runtime/test_bootstrap_shutdown.py) |
| Core contracts and provider seams | Core-only types, provider Protocols, configuration, streaming, and telemetry | [shared](../../../services/core-control-plane/src/fdai/shared/) | [shared tests](../../../services/core-control-plane/tests/shared/) |
| Rule Catalog pipeline | Catalog schema loading, case-normalized governed scopes, finite parameter-relaxation bounds, reviewed baseline control-set resolution, collection, content-addressed snapshot mirroring, idempotent draft-review publication, validation, distillation, and promotion support | [rule_catalog](../../../services/core-control-plane/src/fdai/rule_catalog/) and [collection delivery](../../../services/core-control-plane/src/fdai/delivery/rule_catalog_delivery.py) | [Rule Catalog tests](../../../services/core-control-plane/tests/rule_catalog/) and [collection delivery tests](../../../services/core-control-plane/tests/delivery/test_rule_catalog_delivery.py) |
| Reviewed Property semantic coverage | Measured coverage of reviewed Property semantics over rule-evaluated references, evidence rules for declared provider paths, a non-regression floor, and a deterministic priority backlog | [check-property-semantic-coverage.py](../../../scripts/quality/architecture/check-property-semantic-coverage.py) and [property-semantics.yaml](../../../rule-catalog/vocabulary/property-semantics.yaml) | [coverage gate tests](../../../tests/integration/scripts/test_property_semantic_coverage.py) |
| Core service entry point | Core distribution startup and service composition | [fdai_core_service](../../../services/core-control-plane/src/fdai_core_service/) | [Core package tests](../../../services/core-control-plane/tests/) |

Inventory relationship convergence is owned by the continuous operational instance graph. Reviewed
provider parents shadow generic containment, and snapshot and ontology stores enforce cardinality.
principal-scoped operational evidence reads bind receipt-verified Context metadata through the
existing bounded response without adding mutation or execution authority.
The Context projection authenticates receipt issuance, compares complete link observation metadata
including source generation and verification lineage, and budgets the bundle and metadata together.
Each evidence path's provenance refs are independently recomputed from, and must equal, the same
secured object's own properties before projection, so an unbound or forged provenance ref is
rejected rather than trusted.
Detection projections similarly expose only source-derived Forecast and Pattern objects; deferred
relationships require exact endpoint identities before catalog restoration.
Their persistence methods are idempotent over the existing ontology instance-store seam.
Analyzer execution selects bus security from the explicit venue and applies the deployed five-minute
tick ceiling to local loops and one-shot runs.
Provider-neutral observation adjudication preserves only properties that distinct providers report
identically and records every contested field without selecting a winner.
Independent-provider comparison requires an injected verifier for every canonical provider in the
exact bounded target generation.
Context reads bind authenticated principal-scoped receipts, while Forecast and Pattern producers
use atomic persistence and authenticated producer attestations.
Secured query receipt verification re-derives completeness from the full digest-covered issued
receipt rather than trusting a relabelled digest.
Context evidence reads reserve response-envelope bytes before building the bounded evidence bundle.
Direction-shadow promotion remains proposal-only unless the comparison pinned exact release identity
on both sides.
Direct API promotion adapters can report a retryable no-mutation failure; the executor records a
failed terminal attempt without consuming the stable retry opportunity.
Operational Context responses are rebound to the exact read request, and topology replay requires
canonical source-receipt digests before it can report complete evidence.
Context snapshots must also match the request's catalog revision, and response byte budgets include
the bundle identity fields they return.
The inventory ontology projector commits graph replacement and its exact-generation manifest and
status markers in one PostgreSQL transaction. Pantheon enforcement preserves the separate fixed
agent roles while binding the resolved autonomy ceiling, authorized expiring approval, Saga-owned
pre-execution receipt, stable idempotency reservation, owner-fenced resource claim, and distributed
resource lock before Thor invokes an executor. Restart ambiguity remains `execution_unknown` until
explicit reconciliation or rollback.
Resource ObjectSet receipts preserve source generation and completeness independently from query
truncation, including zero-result reads.
Relationship traversals pass root_ids without a root_object_types filter so cross-type
roots (resolved by an upstream entity-resolution node) reach the store; `_filter_graph`
narrows the result to the target selector type afterward.
The same projection preserves independently verified `runtime_calls` edges in both directions
without treating mutual service calls as an orientation conflict.

The bounded ARM compute overlay owns VMSS VM and NIC child collection through reviewed parent and
attachment mappings. The Console instance presentation omits role assignments, keeps only the
selected non-scope root's immediate Resource Group, and renders the evidence-backed AKS managed
group, VMSS, VM, and NIC hierarchy without adding provider relationships.

The safety-core coverage floor applies to the deterministic tier and risk gate inside the Core
package. Their tests remain under the Core-owned test tree.

Ontology query execution rechecks the exact release, manifest, role, and purpose at runtime. Its
bounded dependency waves include queue wait in each node deadline, propagate in-flight
cancellation, and skip blocked descendants. Stable handler type, value, and runtime failures remain
`capability_failed`; their structured diagnostic allowlists only `node_kind` and `failure_type`,
without exception text, arguments, node identifiers, provider payloads, or operator data.
Composition issues bounded secured ObjectSet receipts and registers the source-derived network
and Pod telemetry functions in the exact release. Function dependencies resolve only an issued
content digest. Exact-id ObjectSets use fixed indexed batches and stop after the result bound is
decidable. The `catalog.search_rules` function accepts only the active Rule generation bound to
that exact release and its provider-neutral bounded ordered-document manifest. The generation digest
is independently reproducible from the exact ordered document set, so count, chunk, root, or row
drift fails validation. The PostgreSQL adapter serializes each corpus lifecycle and checks the exact
expected prior generation in the activation transaction before replacing the active pointer.
Retrieval returns candidate-only Rules with a `CatalogRetrievalReceipt` and
grants no judgment, approval, or execution authority. The resource-state investigation path keeps promoted
inventory as answer authority, runs the ontology query in shadow, and stores principal-scoped parity
receipts through StateStore. Each actual invocation receives one opaque `correlation_ref` shared by
its live and durable activity lifecycle, while opaque requester and conversation references keep the
logical question `idempotency_key` stable across retries. Separate invocations do not reuse the
correlation.
Current-subscription identity follows the same FunctionType boundary. Schema-validated semantic
judgment selects a no-input plan, and composition registers its Azure reader only when the
server-configured subscription, read identity, and HTTP transport are available. The verified
result contains a masked identifier and content digest; provider failure remains unavailable.
The public composition facade exports only the optional resource-state composer; implementation
types remain in the focused binder so the facade stays below its structural ceiling.
Planner manifests apply identical role and purpose filtering to ObjectType and Interface
properties. Function descriptors are emitted only for declarations whose handlers are registered
in the composed runtime. Readable but unbound function declarations remain in structural coverage
as `runtime_binding_unavailable`; this accounting grants no judgment, approval, mutation,
promotion, or execution authority. Intent evidence preserves a terminal reason while also
disclosing bounded evidence-reference truncation.
The verifier rejects outputs that don't name declared DAG nodes before I/O. Answered turns render
only bounded verified query tables, and transient projection publication retries the same durable
idempotent result before dead-lettering.
Azure semantic planning uses existing `httpx` and `WorkloadIdentity` adapters for two validated
JSON-object proposals. Composition binds resolved narrator or `t1.judge` candidates as the T1
planner and keeps `t2.reasoner.primary` candidates in a separate optional escalation adapter. Core
invokes T2 only after the T1 proposal is unavailable or fails deterministic schema, manifest,
build, or plan verification. Each proposal has a 90-second default budget and retries one
throttled candidate at most once when its bounded `Retry-After` delay fits that budget. Composition
exposes only handlers with bound authoritative providers. A schema-validated `cause` facet prevents
the current-state fast path from replacing structured causal planning, even when the candidate
primary intent is `query.resource_current_state`. An omitted exact-Resource slowness investigation
is completed only from reviewed non-negated causal, symptom, and onset spans outside the target
identifier, no competing change event, exact manifest paths, and registered metric concepts.
Dependency-latency and traffic-load evidence both use the verified relationship path; incomplete
inputs remain held. A missing outer `Resource` type is restored only from one schema-validated
`resource` target that exactly matches the frame target without a conflicting canonical type.
An input-free recovery diagnostic records only fixed failed-precondition names
and their count, without operator text, target values, source-span text, model payloads, or provider
data. A partial causal hold renders each verified hypothesis ID as `unresolved`; it never promotes
unexecuted evidence to a supported or refuted conclusion. When metric comparison completed, the
same hold preserves the measured change and attaches no evidence to synthesized unresolved
hypothesis summaries. The
frame proposal applies the shared wire identifier constraints before Core rebuilds server-owned
digests. Structured diagnostics record only the planning stage, candidate index, failure class,
and input-free validation locations; they omit operator text and provider details. The public composition facade delegates Azure-specific model and catalog binding to
`semantic_query_azure_composition.py` while remaining below the enforced 800-line limit. Its module
contract retains the `composition`, `seam`, and `container` anchors enforced by the package layout
gate. The validated `llm.mode` string selects Azure semantic composition by value, consistent with
every other LLM binder. The ObjectSet handler is rebuilt for each request role,
so a Reader cannot inherit Owner visibility and an Owner is not silently reduced to Reader. Missing
model, release, store, or transport prerequisites
remain explicit startup-readiness failures rather than an implicit `runtime=None`.
Continuous coverage receipts separate deterministic fixture structural validation from production
readiness. Only externally produced `cross_service_e2e` or `live_assurance` question receipts can
set `production_ready`; a committed `deterministic_fixture` keeps it false.
Operational coverage receipts normalize evidence, evaluation, and freshness timestamps to UTC
before digesting so equivalent instants retain one replay identity across service locales.
Azure Monitor alert normalization applies the same UTC rule before deriving Event and idempotency
identity, preventing offset-only provider retries from becoming duplicate incident signals.
Azure composition compiles only reviewed `azure-monitor` live blast-probe manifests when a metric
provider is bound. The control loop measures the action target before execution-authority
evaluation and passes the recorded observation into the existing ceiling. The adapter enforces the
manifest timeout within the schema maximum, while missing, timed-out, failed, active, or overloaded
evidence can only lower authority. Audit records retain the sanitized reason and scalar metrics for
replay without querying Azure again.
Knowledge retrieval rejects non-finite embeddings at the pgvector boundary and assigns zero
similarity in the in-memory reference, preserving deterministic ranking under invalid model output.
Conversation preflight bounds the direct-response profile before social narration and holds
oversized input without exposing operational context or invoking the model.
Runtime bootstrap delegates semantic readiness and vertical workload-identity construction to its
existing lifecycle and binding helpers, keeping the primary composition root below the reviewed
fanout ceiling. A thin bootstrap wrapper preserves the injected identity-builder test and fork seam.
The Operational Hypothesis Loop adds no service or agent. Complete graph prerequisites bind at
composition. Ordinary execution produces an effect-reconciliation request only from an existing
matching exact V2 plan and commits it to a durable outbox before broker publication. Missing
observation or publication failure remains held or pending evidence and never rewrites the executor
outcome. Model pointer changes remain inside the existing governance ActionType, risk, Owner
approval, Thor execution, rollback, and Saga audit path.
The [lineage producer](../../../services/core-control-plane/src/fdai/core/operational_planning/hypothesis_lineage.py)
and [control-loop sink](../../../services/core-control-plane/src/fdai/core/control_loop/_execution.py)
submit one single-effect episode only when authoritative planning records, a completed executor
result, and one matching independent scorable observation are all present. Projection failure leaves
the executor result unchanged, and this producer rejects plural effects instead of fabricating
missing outcomes. Focused lineage and control-loop shadow tests pin both boundaries.

Cross-vertical arbitration reads objective effects rather than recommendation wording. The
[decision-case domain](../../../services/core-control-plane/src/fdai/core/decision_case/domain.py)
owns the frozen `DomainOptionEvidence` contract, which carries one domain's produced
ActionType, its signed objective effects, and the canonical lineage both were read from, and
the pure `conflicting_objective_effects` relation, which reports a conflict only when two
domains hold opposite-signed utilities on the same governed objective. The
[Forseti ingress](../../../services/core-control-plane/src/fdai/agents/_framework/forseti_decision_helpers.py)
admits that evidence through a bounded strict parser and rejects a payload whose only lineage
is a synthetic specialist marker, so the option refs that reach the decision case and the
terminal verdict are the ones the contributing replays produced. Runtime health owns the
availability seam: [`runtime_health`](../../../services/core-control-plane/src/fdai/agents/_framework/runtime_health.py)
derives the unreachable-agent set once and binds it as a probe at composition, which lets
Forseti close an arbitration no owner can answer as a terminal HIL verdict without importing
an agent into the framework.

## Independent service map

| Service | Package responsibility | Package map |
|---------|------------------------|-------------|
| Environment model binding | Shared authority-free policy contract, exact proposal-to-policy join, three-way-CAS Settings projection, unique capability identities, exact GA and TPM/PTU resolution, bounded provider reads, Core-only attested runtime binding, healthy active-revision CAS, policy-bound exact apply, and independent provider readback | [shared contract](../../../packages/service-contracts/src/fdai_service_contracts/model_binding.py), [resolver schema](../../../services/core-control-plane/src/fdai/rule_catalog/schema/model_binding_policy.py), [proposal validator](../../../scripts/deployment/azure/model_binding_proposal.py), [projection workflow](../../../.github/workflows/model-settings-projection.yml), [projection materializer](../../../scripts/deployment/local/materialize-authoritative-settings.py), [service guard](../../../scripts/deployment/service/guard_plan.py), [plan verifier](../../../scripts/deployment/azure/verify-deployment-plan.py), [active revision verifier](../../../scripts/deployment/azure/verify_active_core_revision.py), [provider readback](../../../scripts/deployment/azure/verify_model_deployments.py), [Operator IAM adapter](../../../services/operator-service/src/fdai_operator_service/postgres_iam.py), and [Console editor](../../../console/src/routes/settings-model-binding-policy.tsx) |
| Operator Service | Authenticated route families, loopback-only local Azure CLI session bootstrap through the bounded authentication module, durable semantic bridge, normalized direct-Psycopg connections, exact-release reads, owner-scoped background tasks, and principal-scoped Process state plus atomic transition-proposal admission without execution authority | [authentication boundary](../../../services/operator-service/src/fdai_operator_service/auth.py), [local authentication](../../../services/operator-service/src/fdai_operator_service/local_auth.py), [DSN normalization](../../../services/operator-service/src/fdai_operator_service/postgres_dsn.py), [operations family](../../../services/operator-service/src/fdai_operator_service/families/operations/), [workflow family](../../../services/operator-service/src/fdai_operator_service/families/workflow/), [Process projection](../../../services/operator-service/src/fdai_operator_service/process_transition_projection.py), [approval projection](../../../services/operator-service/src/fdai_operator_service/process_approval_projection.py), [retry admission](../../../services/operator-service/src/fdai_operator_service/process_retry_admission.py), [background-task projections](../../../services/operator-service/src/fdai_operator_service/families/conversation/background_tasks.py), [runtime projection reader](../../../services/operator-service/src/fdai_operator_service/runtime_projection_reader.py), [PostgreSQL family store](../../../services/operator-service/src/fdai_operator_service/postgres_family_store.py), [adapters](../../../services/operator-service/src/fdai_operator_service/adapters/), [streaming](../../../services/operator-service/src/fdai_operator_service/streaming/), and [composition.py](../../../services/operator-service/src/fdai_operator_service/composition.py) |
| FDAI Console background-task inspection | Strict owner-scoped task/progress decoders, bilingual list and selected detail presentation, and explicit refresh without create, cancel, retry, or execute controls | [route](../../../console/src/routes/background-tasks.tsx), [decoder](../../../console/src/routes/background-tasks.model.ts), and [decoder tests](../../../console/src/routes/background-tasks.model.test.ts) |
| FDAI Console Process controls | Strict principal-scoped Process and transition decoders, localized current-step requirements, revision-bound resume/cancel/retry requests, and explicit non-success acceptance | [control decoder](../../../console/src/routes/processes.control.ts), [control panel](../../../console/src/routes/process-control-panel.tsx), [request client](../../../console/src/routes/processes.transitions.ts), and [browser contract](../../../console/tests/e2e/workflow-process-transitions.spec.ts) |
| FDAI Console ontology workbench | Exact declaration routes, strict projection decoders, evidence/dependent/release sections, localized verification state, and snapshot-bound impact/map presentation with no execution controls | [ObjectType workbench](../../../console/src/routes/ontology-object-type-detail.tsx), [impact route](../../../console/src/routes/blast-radius.tsx), [impact decoder](../../../console/src/routes/blast-radius.model.ts), and [ontology contracts](../../../console/src/routes/ontology.types.ts) |
| FDAI Console localization catalogs | Shared shell, Incident, Alerts, and planner-unavailable recovery labels remain in the base bilingual catalog. Route-specific Teams integration and optional Cost Governance labels stay in lazy route catalogs, so specialized guidance does not consume the entry-bundle budget or activate a package. Changes to the base catalogs regenerate the question-bank digests. | [base English catalog](../../../console/src/i18n/messages.en.json), [base Korean catalog](../../../console/src/i18n/messages.ko.json), and [route catalogs](../../../console/src/routes/i18n/) |
| FDAI Console route loading | Named route exports use one typed lazy adapter while shared route modules reuse one loader. The entry-bundle check verifies required lazy boundaries and enforces both raw and gzip budgets without weakening route isolation. | [panel registry](../../../console/src/panels.tsx) and [entry-bundle check](../../../console/scripts/check-entry-bundle.mjs) |
| FDAI Console Dashboard v2 and recorded Resource state | Additive resource-first `/dashboard-v2` route with a bounded honeycomb, one active hover preview, type autocomplete, and shared operational, provisioning, and availability facts from the existing ontology instance reader. Bounded server pages fence the inventory generation to the committed ontology manifest, qualify reviewed provider state paths from immutable snapshot times, and preserve distinct unknown causes. The Dashboard and Instances screens share one decoder and fact view. The existing Dashboard and Cost Governance routes remain unchanged. Authenticated runtime validation remains separate. | [route](../../../console/src/routes/dashboard-v2.tsx), [shared decoder](../../../console/src/recorded-resource-state.ts), [state API](../../../services/operator-service/src/fdai_operator_service/families/operations/instance_states.py), [recorded-state design](../interfaces/recorded-resource-state.md), and [adoption ledger](../../roadmap-implementation/interfaces/console-operations.md) |
| Network topology visualization | Shared network vocabulary, authored static-diagram contract, observed-only Console focus and path presentation, and sanitized export with no execution authority | [shared vocabulary](../../../packages/network-topology-contracts/), [diagram compiler](../../../tools/architecture-diagrams/), [Console architecture components](../../../console/src/components/), and [owner design](../interfaces/network-topology-visualization.md) |
| Document Ingestion API | Upload intake, API-owned transitions, governed preview authorization, and fenced connector state | [package](../../../services/document-ingestion-api/src/fdai_ingestion_api_service/) |
| Document Processing Worker | Durable document processing, process-isolated Korean and English OCR, and restart-safe protection revocation cleanup | [package](../../../services/document-processing-worker/src/fdai_document_worker_service/), [local OCR](../../../services/document-processing-worker/src/fdai_document_worker_service/adapters/local_ocr.py), and [provider policy contract](../../../packages/service-contracts/src/fdai_service_contracts/document_ocr.py) |
| Isolated Executor | Thor-owned command handling, provider effects, receipts, and executor adapters | [package](../../../services/isolated-executor/src/fdai_executor_service/) |

These packages depend only on `fdai-service-contracts`, never another service implementation.
Local composition binds service-owned client lifecycles and loopback adapters, so the Operator
semantic bridge, ingestion publisher, document worker consumer, and isolated Executor preserve the
same logical topics, idempotency, readiness, and receipt boundaries as deployed adapters.
Operator IAM assembly stays behind the focused
[`iam_composition.py`](../../../services/operator-service/src/fdai_operator_service/iam_composition.py)
boundary so channel verification, durable HIL delivery, and database adapters do not widen the
top-level service composition dependency fanout.
The document worker parses native PDFs in a spawned resource-limited process so untrusted
decompression cannot terminate its long-lived service.
Duplex IPC runs through a bounded daemon thread under one monotonic deadline, and the parent
revalidates returned page and character bounds before accepting text.

## Shared contract SDK

[fdai_service_contracts](../../../packages/service-contracts/src/fdai_service_contracts/) owns the
versioned wire descriptors, codecs, compatibility checks, readiness records, document contracts,
operator contracts, and executor contracts shared across processes. It contains no service
composition, provider implementation, database access, or business workflow.
`IncidentPageProjection` keeps the generic `PageProjection` wire shape stable while binding an
Incident roster page to its same-snapshot outcome metrics under one read-only Operator contract.
Its optional `incident_number` is a display-only reference allocated from the current UTC month;
canonical Incident and correlation identities remain unchanged.

The shared SDK also owns the no-authority ontology-query records used across the Core and Operator
boundary: semantic problem frames, bounded query DAGs, intent graphs, task receipts, and structural
coverage receipts. These records contain no provider client, ontology store, planner model, or
execution handler.

Interactive conversation planning uses one schema-validated semantic judgment before capability
selection. When that boundary accepts an unambiguous collection-level Resource state,
Resource Health, or Service Health function that is present in the principal-scoped manifest, Core
builds and verifies the frame deterministically instead of issuing a second frame-model request.
The Operator bridge still persists the request before accepting its projection. A missing request
can retry as a bounded visibility race, while a permanent projection identity conflict is
quarantined once without churning the consumer group. Model timing includes completed judgment,
frame, and plan calls; end-to-end turn timing remains the broader latency authority.
Function dependencies keep decision and presentation authority separate. Decision-bearing use
requires an independent evidence admission; a `Bragi` `operations-review` read can reuse only the
exact process-issued ObjectSet whose role, purpose, release, receipt, and materialization match.
It also owns the versioned, no-authority operational activity record used to carry bounded inventory
scan, ontology projection, and current-state read evidence from Core to Operator surfaces. The
record separates logical agent ownership from the producing process and fixes
`execution_authority=false`.

Version 1.2 of the existing Operator/Core envelopes adds one bounded semantic-turn request and one
evidence-bound terminal result. The request pins authenticated roles, session ordering, purpose,
deadline, and idempotency. An answered result requires exact release, manifest, plan, execution
receipt, and evidence references. The SDK rejects semantic downgrade to N-1 instead of dropping
those fields. Runtime publication and consumption remain service-owned implementations, and the
Operator bridge supervises distinct terminal-projection and progress topics.

Operator continuation lookup materializes result candidates for the exact session and request
candidates for the exact outbox namespace and principal before joining them by `request_id`. The
bounded candidate sets preserve lineage checks without expanding the PostgreSQL join across
unrelated `state_kv` rows.

Semantic-turn requests also preserve a typed screen or resource-group selection with an opaque
server-issued token. Operator resolves the token against the authenticated principal, ordinary
lowercase role scope, purpose, exact release, source generation, completeness, and id set, then
recomputes the selection digest before Core compiles an exact `Resource.id` scope for
`query.contextual_resources`; a client-forged or
recomputed id, missing-after-restart token, or scope mismatch is typed unavailable rather than a
fallback to the principal-visible collection. No context field grants approval or execution
authority.
Explicit utterance predicates are intersected with the token's set, and an incomplete
object-only contextual table holds the semantic turn instead of becoming an answered claim.
This hold is limited to contextual resource plans; other bounded query tables continue to return
their explicit truncation state.
The contextual FunctionType carries its opaque selection token as a scalar schema input while the
object-valued query result remains dependency-only, so a disconnected model node cannot invoke the
specialized read.
Operator instance projections issue the token from the authenticated principal and active
generation, while truncated projections omit the identity entirely.
The shared scope digest uses lowercase ordinary roles (`reader`, `contributor`, `approver`, or
`owner`) and rejects `BreakGlass`. Exact id predicates use batches of at most 128 ids and omit
relationship materialization and relationship-completeness gating for these object-only reads.
The wire contract permits a conservative bounded 512-id context envelope; the general ObjectSet
and store limits remain 1,000.
The context contract rejects mixed incident, screen, and resource-group identities, while exact
selection reads retain the source-generation receipt.
The same 512 bound is enforced by the Operator/Core schema, so oversized client context cannot
enter planning.
The bounded semantic query JSON envelope remains within its existing byte limit for the 512-id
selection without removing the existing row and byte limits on ordinary outputs.

The SDK also owns the logical-topic marker and deterministic consumer-group derivation used when
those two semantic channels share a physical Event Hub. Core and Operator keep separate adapters,
codecs, identities, logical topics, and offset groups; neither imports the other's implementation.
The same contract exports the canonical physical-topic default used when targeted Terraform state
has not yet materialized newly declared outputs.

The SDK also owns the `notification-delivery-receipt` wire schema and canonical logical topic.
Operator authenticates and publishes the observation over the existing multiplexed physical topic;
Core alone applies it to an already accepted delivery. This contract grants no notification target
or execution authority.

The SDK also owns the WARA shadow-assessment topic and Operator consumer-group identifiers. Core
publishes no-authority assessment results through that topic, and the independent Operator service
validates exact active-control coverage before replacing its read projection. The shared contract
contains wire identifiers only; it grants neither service provider-read or execution authority.

The SDK also owns the execution-venue contract: the one resolver for `FDAI_EXECUTION_VENUE` and
the one table of venue-selected capability flags. It lives here rather than in a service because
every process resolves the same variable, and an independent service cannot import the core
control plane. `fdai/runtime/venue.py` re-exports it and declares no binding of its own.

The five service distributions use deployable `0.1.2` images as N-1 and `0.1.3` as N. Their existing contract-set
`1.0.0`/`1.1.0` matrix remains the cross-process compatibility boundary.
Content-addressed live evidence also binds the exact service and observation kind and requires
`observed=true`; recomputing a digest cannot convert an unobserved claim into a live receipt.

The package test tree validates SDK behavior. Cross-service N/N-1 and topology checks remain under
[root integration tests](../../../tests/integration/).
Deployable service images share pinned Alpine Python, OpenSSL, SQLite, and util-linux runtime packages; the image contract and Trivy gate keep all six Dockerfiles on exact available versions without known blocked vulnerabilities.
The document worker adds only its owned Tesseract language data and OCR dependencies.

## Other repository owners

| Path | Responsibility |
|------|----------------|
| [evaluation-sdk/](../../../evaluation-sdk/) | Dormant independently packaged evaluation contracts and runner, preserved by package-scoped CI. |
| [benchmarks/](../../../benchmarks/) | Dormant external-harness driver packages and the explicit independent CyberGym shadow runner. |
| [eval/golden-dataset/](../../../eval/golden-dataset/) | Bilingual cloud-operations semantic questions with locale-neutral ontology traversal and answer oracles. Generated question-bank artifacts are content-addressed against 10 source files. |
| [services/core-control-plane/src/fdai/delivery/golden_question_dataset.py](../../../services/core-control-plane/src/fdai/delivery/golden_question_dataset.py) | Bounded loader for the repository golden dataset and deterministic typed-observation adapter. Missing semantic axes fail certification before release evidence. |
| [extensions/](../../../extensions/) | Optional independently packaged capabilities. |
| [rule-catalog/](../../../rule-catalog/) | Catalog-as-code data. |
| [policies/](../../../policies/) | OPA/Rego policy-as-code. |
| [console/](../../../console/) | Thin operator SPA, including the Knowledge source and governed document-upload routes, localized Guides drawer, and validated Manual Studio catalog boundary. |
| [tools/manual-studio/](../../../tools/manual-studio/) | Independent static guide library, HTML slide viewer, repository-safe media provenance, and focused prototype checks. |
| [teams_workflow_binding.py](../../../services/operator-service/src/fdai_operator_service/teams_workflow_binding.py) | Provider-neutral Teams endpoint persistence: encrypted loopback state locally and one versioned Key Vault secret in deployment. |
| [cli/](../../../cli/) | Operator command-line client. |
| [scripts/agent/design_context.py](../../../scripts/agent/design_context.py) | Record design-context reads, reserve dirty edit paths, hard-block stale context for framework and constitutional edits, guard commit scope and destructive Git, and route repository-wide validation to explicit integration or release boundaries. |

## Related docs

| To learn about | Read |
|----------------|------|
| Physical service and package ownership | [Multi-Service Repository Layout](multi-service-repository-layout.md) |
| Module boundaries and dependency injection | [Project Structure](project-structure.md) |
| Conversation and ontology query implementation sequencing | [Ontology Query Coverage Implementation Plan](../interfaces/ontology-query-coverage-implementation-plan.md) |
| IS work packages and local-first sequencing | [Service Decomposition Execution Plan](service-decomposition-execution-plan.md) |
| Graduation, data ownership, and rollback gates | [Service Graduation and Data Ownership](service-graduation-and-ownership.md) |
| Control-loop authority | [Architecture instructions](../../../.github/instructions/architecture.instructions.md) |
| Agent roles and permissions | [Agent Pantheon](../agents/agent-pantheon.md) |
