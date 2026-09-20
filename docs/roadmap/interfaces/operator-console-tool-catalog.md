# Operator Console Tool Catalog

This companion owns the governed tool catalog exposed through the Operator Console. The parent document retains channel architecture, runtime behavior, safety invariants, and rollout boundaries.

## Design at a glance

This focused owner preserves the detailed contract formerly embedded in [operator-console.md](operator-console.md).

## 3. Tool catalog

Tools are **pipeline-stage views**. A core tool has a stable name, bounded `argument_hint`, RBAC
floor, side-effect class, and documented failure surface. Web/provider-specific tools can add
their own typed request contracts. New tools are additive; they never override a rule or policy.

`RuntimeToolDiscovery` provides search and describe over installed narrator schemas. It intersects schema metadata with the actually installed tool names, applies the same RBAC ladder as the coordinator, and returns only name, verb, description, argument hint, RBAC floor, and side-effect class. A lower-role principal cannot discover a higher-role tool, and descriptors contain no handler or invocation capability. If an explicit request still resolves to a tool above the principal's role, the deterministic refusal names the tool, required role, and current role and confirms that no tool was called. Discovery improves navigation; it grants no new authority.

The same projection is available through the deterministic channel verbs `search_tools` and
`describe_tool`, and typed read RPC methods `tools.search` and `tools.describe`. Channel calls use
the resolved `Principal`; RPC calls derive the role from server-authorized scopes, never from a
caller-supplied role parameter. Both surfaces return descriptors only and cannot invoke the target. Before agent delegation, the server derives ownership only from canonical primary and secondary intents and exact owned ObjectType targets. Requested facets constrain answer and evidence shape; they cannot select or outscore an agent. If those ownership inputs do not resolve an accountable agent, the turn abstains or remains held instead of treating an output facet as routing authority.
### 3.1 Day-1 tool set (read-only + explain)
| Tool | Purpose | RBAC floor | Delegates to |
|------|---------|-----------|--------------|
| `describe_event(payload)` | Run one event through `EventIngest → TrustRouter → T0Engine` in memory (no PR, no audit write); return the resulting routing decision + candidate rule ids. | Reader | `EventIngest`, `TrustRouter`, `T0Engine` |
| `explain_verdict(event_id)` | Read the audit trail for one already-processed event; return the tier, decision, citing rule ids, verifier report, mode. | Reader | `StateStore.query_audit()` |
| `explore_catalog(query)` | Search the shipped rule catalog / action-type catalog / ontology vocabulary by id, keyword, or resource_type. | Reader | Loaded catalogs (no I/O) |
| `query_audit(filters)` | Structured audit query: by event id, actor, decision, mode, time window. Paginated. | Reader | `StateStore.query_audit()` |
| `query_llm_usage(group_by, lookback_days, usage_scope)` | Read measured LLM token usage by day, model, workload scope, or mode for a bounded 1-90 day window. The independent Operator Service serves the same token-only projection from `llm_invocation` through a SELECT-only runtime role; record and conversation ledgers are capped at 500 while aggregate counts remain exact. The tool can narrow to operator-chat records, never estimates money without measured pricing evidence, and returns deterministic prose, table, or chart output. `LlmCostPanel` declares this tool through `conversation_tool`; a chat-enabled composition fails startup if the declared capability is absent. | Reader | `MeteringReader` |
| `query_inventory(resource_type, filter)` | Server-owned Azure inventory count, list, type, location, resource-group, name, status, and relationship queries. The schema-validated `inventory-query-language.yaml` catalog owns natural-language terms, state and operation semantics, evidence authority, grouping, projection, scope defaults, and freshness requirements; Python performs generic token matching and typed query assembly without question-specific aliases. Resource types come from the separate canonical resource-type catalog. The typed query owns scope, grouping, projection, workload intent, state-history intent, and freshness before evidence retrieval, so rendering never reinterprets the prompt. Unqualified cross-screen inventory reads use the server-owned subscription root; explicit current-view wording keeps the active architecture view. Current-state questions wait on the provider refresh barrier and return unavailable rather than confirming stale evidence. Degraded or unavailable resource questions are routed by catalog authority to `query_subscription_health`; a concrete resource-family filter remains attached and excludes findings from other types. Results expose bounded allowlisted fields, exact scope, snapshot source/freshness, and only records satisfying every predicate. Explicit semantic state groups remain separate and can show a grounded zero-result group. State-filtered answers also disclose that normalized current operational status does not prove the absence of deployment or Activity Log failures. The stream exposes the verifier-accepted canonical `query_inventory` operation with redacted server scope plus bounded result metadata. Provider failure renders unavailable. AKS results stay cluster-only unless a server-owned workload provider is explicitly bound to an inventory-matching cluster; a valid binding adds bounded Deployment and Pod readiness, while other matched clusters remain an explicit coverage gap. A current snapshot never establishes when a workload entered a state; the answer keeps that transition time unconfirmed until Kubernetes events or another history authority is connected. | Reader | `InventoryGraphProvider`, `KubernetesWorkloadProvider` |
| `query_subscription_scope()` | After schema-validated semantic judgment selects `subscription_scope_identity`, run a deterministic no-input read of the server-configured subscription from Azure Resource Manager. The verified answer includes display name, state, observation time, evidence digest, and a masked subscription ID; browser or model output cannot supply scope. | Reader | `SubscriptionScopeProvider` |
| `query_subscription_health()` | Inspect the server-configured Azure reader scope for explicit subscription checks, general service-outage questions, and catalog-selected degraded or unavailable resource collections. The provider defaults to the resource-group allowlist; an explicit composition-owned subscription mode aligns interactive local health with its subscription inventory. Query Resource Graph inventory and Resource Health, fall back to current Resource Health status for the configured scope when ARG is empty, then run bounded representative metric checks. Preserve requested state groups, including grounded empty groups. Normalize name, provider type, and resource group from a scope-validated Resource Health target when its display name is absent; don't expose the raw target ID. Return findings, cause classification, coverage gaps, freshness, and truncation without allowing caller-supplied scope or mode. | Reader | `SubscriptionHealthProvider` |
| `query_detection_readiness()` | Read Heimdall's latest AKS readiness decisions from Muninn StateSnapshots, including six-axis coverage gaps and the authority ceiling. It does not probe Azure or recompute readiness. | Reader | `DetectionReadinessReader` |
| `query_t2_recovery()` | Read sanitized proposer attempt receipts from the server StateStore. Return the retained attempt count, recovery state, route roles, failure class, observation time, and explicit legacy-detail gaps without exposing provider error text. | Reader | `T2RecoveryStateReader` |
| `query_configuration_baseline()` | Read one server-configured frozen configuration baseline, its current scoped observation, and the exact integrity-pinned DOCX citation. The caller cannot select scope, version, digest, document, or a mutation operation. Missing structured topology remains unknown. | Reader | `ConfigurationDriftService` + `KnowledgeSource` |
| `capture_browser_evidence(policy_id, policy_version, source_url, stable_selectors)` | Submit a credential-free bounded capture under an exact server-owned policy. Returns an immutable artifact receipt; never returns a page or interaction API. | Reader | `BrowserEvidenceCaptureService` |
| `query_operator_memory(scope_kind, scope_ref)` | Return active (non-superseded, non-expired) governed operator-memory entries for a bounded scope. Read-only. | Reader | `OperatorMemoryStore` |

Receipt-derived answer authority and typed holds are defined in [Operator Console Progressive Conversations](operator-console-progressive-conversations.md#receipt-bound-answer-authority).
Matched inventory result sets are sorted before the 40-record bound is applied. Lists use resource
name order by default; an explicit status, type, or location grouping uses that grouping field and
then resource name. The same order drives rendered rows and durable ordinal follow-ups.
Future VM shutdown questions use the catalog-owned `scheduled_shutdown` query kind and the
`compute.vm-shutdown-schedule` resource type. The query pins one aware server reference time and a
closed `today_evening` window. Provider adapters project only validated
`ComputeVmShutdownTask` records and expose the target VM name and resource group, enabled state,
daily local time, and provider timezone without exposing the target ARM id. The deterministic
projection includes only enabled occurrences from 18:00 through 23:59 that have not passed in the
schedule timezone. Disabled schedules are not results. A truncated snapshot, missing production
coverage for the schedule type, malformed schedule, or unsupported timezone returns unavailable
instead of proving that no VM will shut down.
A concrete resource-type query with no complete lexical state match can use semantic retrieval only
to propose state or operation candidates. Model and embedding candidates never execute a provider
query in that turn. An exact or promoted catalog mapping, or a separately verified operator
confirmation receipt, is required before the server can produce a complete typed query.
If semantic planning is unavailable, ambiguous, or omits the required state, the server returns a
typed interpretation hold with the deterministic query skeleton. It does not execute that
type-only skeleton or drop the unresolved modifier to widen the result set.
Negative state candidates use the bounded `not_in` operator over canonical catalog states. Provider
grounding resolves excluded values against the same snapshot; negation never becomes an
unsupported positive-state guess.
Exact catalog terms remain a T0 latency optimization, not the only entry gate. When production has
the existing T1 embedding binding, the same credential path retrieves state and operation
descriptions and examples. A retrieved concept remains `candidate_only` and causes a localized
clarification without querying inventory. If the embedder is absent or fails, the resolver returns
no candidate and the deterministic hold remains authoritative. The resolver rejects empty prompts, control characters, and text over 4,096 characters before building catalog vectors or calling the query embedder.
Inventory semantic retrieval and Rule-catalog search are controlled independently; disabling
Rule search does not silently disable inventory semantic retrieval.
The clarification is not a dead end. A later operator turn that selects an exact promoted catalog
expression recompiles deterministically and can perform the provider read. The earlier model or
embedding arguments are never reused as query authority.
Intent-graph planning cannot override a complete deterministic inventory query. Planner-supplied
status concepts are still checked against the canonical catalog; invalid values are rejected, and
execution uses the deterministic query. A required semantic status that is omitted remains held.
An unfiltered summary still preserves every provider-observed resource, groups by provider-native type, and separates resource-group containers and topology-derived records from the resource total.
The catalog-owned `scope_counts` query kind returns provider-native resource and resource-group
totals from one fresh snapshot without narrowing the query to resource groups. It retains the same
container, derived-record, truncation, freshness, and verification disclosures as type summaries.
Architecture publishes at most one selected resource in its bounded screen digest. A current-screen
service-summary question may use a selected resource-group name only as a selector hint; the server
inventory re-resolves that group and its members before returning canonical service-type counts.
Missing, malformed, or non-group selection does not create scope authority.
Selected-group detail requests use the same boundary. Named Architecture projections retain only
allowlisted location, resource-group, and provider-type fields after dropping raw properties.
Observed operational or power state takes precedence; provisioning state is the final displayed
state fallback. The deterministic list excludes the resource-group container itself and
topology-derived records that lack a provider type.
Inventory records preserve the displayed state's provenance independently. The catalog-owned
`state_coverage` result treats operational and power evidence as directly observed, while
provisioning-only and unknown evidence remain operationally unavailable. A selected-screen
continuation reuses only the bounded group selector and rechecks all records in server inventory.
The catalog-owned `inventory_coverage` result reports checked provider types separately from
skipped and failed types. A complete atomic snapshot can prove zero skipped and zero failed types;
a truncated snapshot leaves skipped coverage unknown. Operational-state limitations remain a
separate coverage class and are never relabeled as inventory read failures.
After schema-validated judgment selects subscription or platform health, deterministic tool planning
has precedence over a public-web plan. Resource Health cause classification separates platform impact from
customer-initiated state before narration. Broad platform-impact reads disable representative
metrics, query active Service Health events and impacted resources, separate outages from planned
maintenance and advisories, and enrich missing availability causes from bounded Resource Health
annotations. An unavailable or truncated Service Health or annotation query remains a partial
coverage gap and cannot prove zero platform impact.
Catalog-owned resource-health history intent has the same deterministic precedence. It caps a
parsed lookback at 24 hours, merges availability statuses and annotations chronologically, reports
customer-initiated, status-only, and platform-initiated counts, and never substitutes current ARM
status for missing historical evidence.
A complete history answer can return its latest verified event resource as the next-turn selector
hint. Attribution and history follow-ups must re-resolve that resource in server scope and collect
fresh Activity Log or Resource Health evidence; the hint never becomes evidence authority.
Catalog matching preserves Korean query terms when common case or conjunction particles, including
`와` and `과`, are attached, so compound comparisons retain every requested semantic class.

**Reader-floor tools are provably side-effect-free.** `describe_event`
runs `EventIngest -> TrustRouter -> T0Engine` **in memory only**: it does
not invoke T1 embedding lookups, T2 models, external adapters, or any
mutation surface, and it writes no PR and no audit entry. Its
`side_effect_class` is `read`, and a shadow-mode test asserts it never
touches the executor, the PR adapter, or the state store. This is what
keeps it safe at the Reader floor. Browser capture and its Reader-only v2 workspace follow [Browser evidence collection](browser-evidence.md); admitted scalar custody metadata, identity-free withheld counts, and exact filters, cursors, and Audit or Trace links remain read-only and cannot request capture, reveal captured material, or grant promotion, approval, or execution authority. Bragi never receives a browser handle.
### 3.2 Week-1 additions (write / approve / runbook)

| Tool | Purpose | RBAC floor | Notes |
|------|---------|-----------|-------|
| `simulate_change(scenario)` | End-to-end `ControlLoop.process()` in **shadow** mode; return the executor outcome + generated PR intent without publishing. | Contributor | Shadow-only; still writes an audit entry so the operator can find it in `query_audit`. |
| `approve_hil(approval_id, decision, justification)` | Resolve one queued HIL item. Verifier + `no_self_approval` invariant re-checked. | Approver | Approver group; same principal as PR gate enforcement in [security-and-identity.md](../architecture/security-and-identity.md). |
| `list_hil()` | Return currently queued HIL items visible to the caller's role. | Approver | Reader-visible would leak intent to non-approvers; kept Approver-scoped. |
| `run_runbook(name, params, dry_run)` | Execute one runbook under `docs/runbooks/`. `dry_run=true` requires Contributor; `dry_run=false` requires Owner. | Contributor / Owner | Concrete runbook adapters (e.g. `db_dr_drill_cli`) are already shipped; this tool routes by name. |
| `activate_break_glass(reason, expiry)` | Validate TTL/reason and create Owner-page and audit receipts. | Reader | The current implementation does not change the session principal/role or grant elevation. |

Two clarifications on the write set:

- **`simulate_change` writing an audit entry does not violate "shadow
  never mutates".** The audit log is append-only; recording *that a
  simulation ran* is not a mutation of any managed resource. The
  shadow-mode property test asserts no executor / PR / state-store write,
  and explicitly allows the audit append.
- **`list_hil` (Approver) vs the read-console HIL view (Reader) are
  different surfaces.** The read-only Console SPA shows Reader the
  *existence and count* of queued HIL items (dashboard tile); `list_hil`
  returns the *full item detail* (target, proposed action, requester),
  which can reveal sensitive intent, so it stays Approver-scoped. The two
  are intentionally not the same visibility.
### 3.3 Month-1 additions (observation depth)

| Tool | Purpose | RBAC floor | Depends on |
|------|---------|-----------|-------------|
| `query_log(query, window)` | Bounded, single-workspace Log Analytics KQL query. | Reader | new `AzureMonitorAdapter` |
| `query_metric(namespace, metric, window, aggregation)` | Azure Monitor metrics API. | Reader | new `AzureMonitorAdapter` |
| `query_deployments(window)` | Git + ARM deployment-history join. | Reader | new `DeploymentHistoryAdapter` |
| `correlate_incident(incident_id)` | Multi-signal correlation over ingest events + audit + inventory + logs + metrics for one incident id. | Reader | Above three + `event_ingest` |

`query_log` accepts explicit bounded KQL only as an exact operator command. It is absent from every narrator-visible tool schema, read plan, and Pantheon tool, so a model cannot author or select raw KQL. Natural-language diagnostic shapes use separate server-owned templates. Failed-request summaries group `AppRequests` by operation and result code without claiming that the grouping proves root cause. Error-signature timelines and related-log requests require an exact signature or selected context; missing context returns a clarification without calling the provider or narrator. Representative error samples use a fixed multi-table template, cap the requested window at 24 hours, and redact secret assignments, bearer values, resource identifiers, GUIDs, email addresses, URLs, and IP addresses before rendering any cell. Additional fixed templates rank spans in the slowest observed distributed trace, aggregate dependency latency, and list slow database dependency calls. These results do not by themselves prove root cause, causal contribution, or that a database call explains a CPU increase. Prompt text never becomes executable KQL. When the workspace provider is not configured, the same tool returns a typed unavailable result and does not fall through to current-screen, incident, web, or narrator evidence.
Context-free questions about a proposal, approval, execution, outcome verification, retry, or idempotency use a deterministic action-context hold. The operator must supply an exact ActionType, target resource, proposal, approval, or action receipt before the Console can verify lifecycle claims. Current-screen, repository, incident, and narrator evidence never substitute for that governed record, and the hold performs no mutation or model call.
The exact configuration-baseline filename selects the read-only baseline tool before action-context classification. A negative instruction such as "do not call mitigation tools" cannot turn the document read into an action-lifecycle question. The deterministic answer cites the pinned DOCX in every section and reports unavailable relationships as unknown instead of inferring them from prose. Generic baseline wording stays on the validated semantic planning path instead of creating another keyword router.
The Month-1 additions bring the console close to a multi-signal
incident-response experience, but they still surface
**already-correlated** results; the correlator lives in Layer 1, not
inside the narrator.
### 3.4 Tool discovery contract

Each tool declares:

- `name` - CLI-friendly snake_case verb (no `describe-*` / `explore-*`
  prefix taxonomy; the verb itself is the category).
- `description` - one sentence, English, no marketing language.
- `argument_hint` - bounded argument shape expected by the canonical verb parser. Each tool
  reapplies typed and bounded validation before invocation; invalid arguments never become a
  partial call.
- `rbac_floor` - the lowest role that MAY call the tool.
- `side_effect_class` - `read` / `simulate` / `approve` / `execute` /
  `breakglass`. The audit entry carries this class so downstream analytics
  can slice cheaply.
- `failure_modes` - typed error surface documented in the tool's docstring.

`RuntimeToolDiscovery` and `tools.search`/`tools.describe` return descriptors without handlers or
invocation capability. The narrator sees only the same descriptors allowed by the principal role.

### 3.5 Public web evidence

Public web search routing, retrieval, alternative discovery, safety boundaries, and regression
coverage are defined in [operator-console-web-evidence.md](operator-console-web-evidence.md).

## Related docs

| To learn about | Read |
|----------------|------|
| Parent design | [Operator Console](operator-console.md) |
| Delivery status and remaining work | [Implementation ledger](../../roadmap-implementation/interfaces/operator-console-tool-catalog.md) |
