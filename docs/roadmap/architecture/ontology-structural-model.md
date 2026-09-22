---
title: Ontology Structural Model
---
# Ontology Structural Model

This document defines how FDAI represents exact resource types, taxonomic aggregation,
capabilities, directional relationships, typed paths, and bounded graph presentation. It keeps
classification useful to operators and agents without turning taxonomy into execution authority
or a second source of provider truth.

> **Authority boundary:** Taxonomy, interfaces, link roles, and query paths define meaning only.
> They cannot observe external state, approve an action, select an executor, or raise autonomy.
> Governance review-class tokens colocated with catalog schemas remain change-control metadata,
> not ontology types or autonomy axes. `standing-authority-promotion` cannot change an ActionType
> mode or grant A3-E authority. The Operator promotion-gate view is read-only registry metadata
> outside ontology identity and classification. [Observer setup projections](aks-outbound-connector.md#operator-delivery-contract) likewise reference an existing neutral cluster identity without creating Resource, ObjectType, LinkType or installation authority.
>
> **Compatibility boundary:** Existing `Resource`, `ResourceType`, LinkType identities, stored link
> directions, and historical ontology releases remain valid. New structural surfaces are additive
> and start as read-only capabilities.
>
> Model selection may share a publisher only across distinct families; same-family pairs fail before invocation. Publisher, family, provider, API style, and synthesized routes remain deployment metadata, not ontology identity or authority. Model capability selection may qualify a catalog family by publisher. Resolver enrichment can append narrator or primary-pool candidates only while preserving the complete deployment record, including its binding policy and seal. These fields remain deployment metadata, not ontology identity, and cannot grant model invocation or execution authority. Provider kind and API style remain endpoint metadata under the same boundary.

## Design at a glance

![Design at a glance. The main stages are Resource, ResourceType, ResourceClass, Query, Exploratory traversal, Ordered typed path, LinkType, Forward and reverse roles, Semantic traits.](../../diagrams/generated/fdai-roadmap-architecture-ontology-structural-model-01.en.svg)

The model separates exact identity, aggregation, behavior, language, topology hints, query execution, and presentation. Each concern has one canonical representation and one bounded consumer contract.
Projection-source availability is qualified by `(source, scope_digest)`. This tuple is evidence metadata for one collection scope and does not replace Resource or link identity.
An optional recorded `serving` fact is presentation evidence for one exact data-plane target. It
does not add an ontology type, relationship, or authority edge and never replaces operational,
provisioning, or availability facts. Its source identity, telemetry authority, effective time, and
freshness metadata survive inventory-to-ontology projection in the shared state-fact envelope.
Model-serving source availability uses a separate additive metadata list. Upgraded instance readers
merge it with baseline sources, while older readers continue to consume only the baseline list.
Current instance-detail consumers require explicit runtime-call and PostgreSQL-role source states.
Omitting either state is an invalid projection, not evidence of availability or a measured zero.
Additive identity fields use a fail-closed rollout boundary. A legacy Resource remains queryable,
but consumers cannot project a new exact identity until every field required by that identity is
present.
Bounded structural details keep producer and consumer maxima aligned. A consumer rejects an
oversized sequence rather than converting it into a complete-looking subset.
Reviewed producer and consumer key allowlists also stay aligned. A complete projection cannot
discard a collected field merely because a downstream decoder omitted its key.
Selector semantics distinguish an explicit typed match-all marker from missing or empty generic
data. Match-all relationship projection remains constrained by exact cluster, namespace, source
type, and reviewed mapping.
An AKS diagnostic receipt is typed evidence attached to the selected Resource read response. It does
not create another ObjectType or LinkType, and its content identity cannot replace the Resource UID
or relationship identity.
Every canonical ResourceType also has one explicit recorded-state disposition. Missing state is
never converted into a generic healthy value. The shared Operator workflow adapter may expose an optional `rule.findings-summary` projection with server-recorded counts or explicit `evaluated: false`; that operational summary is not an ontology declaration, relationship, evidence admission, or authority source.
Operator ontology projection and role selection now live with the focused operations family
adapter, while Rule, best-practice, CAF, MCSB, and WARA catalog rendering have separate pure
projection owners. The ownership split changes no declaration identity, relationship direction,
projection revision, evidence admission, or authority.
The per-rule findings read validates the requested identity against the same revisioned Rule catalog. Without a connected findings provider it returns `evaluated: false` and no findings for a known rule; it never derives Resource identities or finding details from summary counts.
Committed inventory invalidation markers coordinate browser rereads without becoming graph state.
Bulk state pages carry the marker watermark bound to their committed generation, and SSE resumes
from that cursor. Clients without a page-bound cursor receive the current marker instead of risking
a missed generation. Bulk Dashboard traversal and the Ontology Instances directory use markers as their primary signal and a five-minute visible-tab fallback while preserving the current server search.
Selected-instance revalidation retains its separate 15-second cadence. Explicit cursor repair uses a negotiated stream epoch: changed epochs require authenticated snapshot reread before acknowledgement, while legacy numeric-only clients receive unavailable. Epoch repair changes no ontology identity, recorded fact, source clock, or execution authority.

[Bounded projection recovery](../interfaces/recorded-resource-state.md#bounded-automatic-recovery) distinguishes missing, pending, and release-mismatched generations without changing graph identity.
The existing inventory owner verifies replay through its atomic manifest and journal; diagnostic receipts remain on their existing path and neither read route gains a writer or restart authority.
A complete reconciliation always retains its fresh generation-specific snapshot receipt. If a
content-only graph digest matches a prior generation whose projection and Resource Event handoff
completed, replay may reference that prior journal generation instead of appending unchanged facts.
That optimization still advances operational-state transition coverage to the fresh snapshot
cutoff; it skips only duplicate topology and journal facts.
Generation and observation-only clocks do not enter this equivalence digest; resource values,
relationship semantics, verification posture, completeness, and conflicts do. Source-state receipts
remain on each fresh snapshot and do not duplicate Resource or Link journal facts. The current
projection still advances from the fresh observation, and any semantic graph change, incomplete
prior handoff, or missing prior journal requires a full new append.
The one-shot inventory coordinator owns its runtime-settings, ontology-status, collection-health,
change-accelerator, and private-cluster proposal stores. It closes them through its asynchronous
lifecycle with provider clients and event transport, so a completed or failed tick leaves no
database-pool worker behind.

An ObjectSet with a predicate that cannot run in the store first evaluates a 1,000-object,
relationship-free candidate window. If that window is truncated and does not prove the requested
result limit, the store can provide one relationship-free candidate snapshot bounded at 50,000
objects. The larger scan uses one connection and one source generation. Relationship-bearing
queries never use this path, and candidate truncation remains explicit.

The [structured cloud-document extension](../interfaces/cloud-resource-knowledge-structured-rag.md)
is under development. Body blocks, excerpt identities, and query bindings describe document provenance,
not new ObjectTypes, LinkTypes, resource identities, or observed topology. Retrieval terms cannot
manufacture classification or applicability.

## Structural concepts

| Concept | Responsibility | Does not do |
|---------|----------------|-------------|
| `ResourceType` | Exact cloud-provider-neutral resource subtype, such as `compute.vm`. | It does not inherit behavior from its identifier or category. |
| `ResourceClass` | Reviewed taxonomic aggregation, such as `NetworkEndpoint` or `DataService`. | It does not grant action eligibility or model capabilities. |
| `InterfaceType` | Shared property, link, and action contract across ObjectTypes. | It does not classify `Resource.type` values in this release. |
| `ResourceTypeQueryGroup` | Reviewed English and Korean aliases for one exact set of ResourceTypes. | It is not ontology identity or a transitive class. |
| `typical_parents` | Authoring hint for expected instance containment. | It is never interpreted as subtype inheritance. |

### ResourceType classification

Every observed `Resource` keeps exactly one reviewed `resource_classified_as` relationship to a
concrete `ResourceType` when the complete inventory generation and mapping digest support it.
Unmapped or unseeded types remain explicit coverage gaps. A name, identifier prefix, embedding,
provider category, or query alias never creates classification.
Broad category query aliases are independent from `ResourceClass` membership. A type may retain a
reviewed data-service class while remaining outside the `database` language group; `search-service`
therefore answers its exact type, not generic database queries.
The reviewed Azure mappings classify `Microsoft.Compute/images` as the storage-class member
`compute.image` and `Microsoft.Network/firewallPolicies` as the network-class member
`network.firewall-policy`. Both preserve exact provider identity without deriving state,
relationships, or authority.

### ResourceClass taxonomy

`ResourceClass` has one reviewed coverage spine plus small, domain-driven aggregation surfaces.
The coverage spine starts at `class.resource` and reaches every shipped neutral ResourceType
through seven broad classes. It does not copy the 3,405 raw Azure provider types into the semantic
ontology. Additional classes are added only when a named competency question needs to select at
least two concrete ResourceTypes under one operational concept.

The taxonomy uses two directed LinkTypes:

| LinkType | Direction | Meaning |
|----------|-----------|---------|
| `resource_type_member_of_class` | concrete `ResourceType` -> `ResourceClass` | The exact type belongs to the reviewed class. |
| `resource_class_specializes` | narrower `ResourceClass` -> broader `ResourceClass` | The narrower class is a true taxonomic specialization. |

Membership is many-to-many. Duplicate membership inside one class is rejected, while membership
across classes represents composition. The specialization graph is acyclic, has a maximum depth of
eight, and remains intentionally shallow. Combination classes created only to join two unrelated
capabilities are not accepted. The shipped root closure is checked against the complete neutral
ResourceType registry so a new semantic type cannot remain outside the coverage spine.

The first release keeps one taxonomic surface. It does not add a generic concept-scheme engine.
Capabilities such as `Operable` and `Observable` remain InterfaceType concerns. ResourceType-level
Interface bindings require a separate safety design because InterfaceType can be an ActionType
target.

## Relationship model

### Direct links

A direct link represents one binary semantic fact whose stable identity is `(from_id, link_type, to_id)`. It is appropriate when the relationship has no independent domain identity or lifecycle.

Direct link properties are limited to an empty mapping or the standardized evidence envelope.
Observation time, mapping identity, verification receipts, completeness, conflicts, and evidence
references describe support for the link. They are not domain attributes of the relationship.

Examples include:

- `contains` for parent-to-child containment;
- `attached_to` for an attached resource and its anchor;
- `depends_on` for an existential prerequisite without independent contract data;
- `routes_to` version 2.0.0 for one verified directed forwarding reference; its many-to-many cardinality retains every observed destination without selecting one target from a provider-observed set;
- `runtime_calls` for one verified telemetry invocation from caller Resource to target Resource;
- `peered_with` as two independently supported directed records;
- `resource_classified_as` for exact reviewed classification.

### Relationship objects

A relationship is modeled as a domain-specific object only when the relationship is itself a
real entity. At least one of these conditions should apply:

- it has an authoritative identity independent from both endpoints;
- it can be created, revised, or closed without replacing either endpoint;
- multiple concurrent instances can connect the same endpoints;
- it has domain attributes such as role, allocation, priority, status, or effective interval;
- policy or an ActionType targets the relationship itself.

Provider verification metadata alone does not justify an object. FDAI reuses existing domain
objects such as observed role-assignment Resources instead of creating a generic `Relationship`
ObjectType or adding UUID identity to every direct link.

### Provider-observed topology

Provider topology enters the graph only through reviewed mappings and one complete inventory
generation. Azure nested resources use an explicitly declared immediate provider parent or
top-level provider root. The bounded ARM source collects AKS AgentPool children that Azure Resource
Graph does not expose as ordinary resources. The same source collects VM Scale Set VM and network
interface children, projects them through the existing `compute.vm` and `network.interface` types,
and retains exact VMSS-to-VM and NIC-to-VM/subnet mappings. Kubernetes API inventory adds
UID-grounded cluster, namespace, node, workload, Ingress, IngressClass, Endpoints, EndpointSlice,
ownership, selector, backend, and scheduling evidence before the same single writer promotes
resources and independently verified links atomically. A Kubernetes Node gains a
`kubernetes_backed_by` link to one VMSS VM only when `spec.providerID` resolves to the exact
provider reference of an observed VM instance. Names and identifier prefixes never substitute for
that identity bridge. The shared inventory enrichment builder resolves subscription-discovered cluster bindings for both scheduled deployment and opted-in local refreshes before this projection.

These producers do not infer topology from names alone. The Kubernetes source binds one exact
cluster Resource identity, keeps namespace and cluster scope checks, and records explicit
unavailability when the API endpoint, CA bundle, or mounted service-account token is not configured.
Catalog declarations remain meaning only and never grant observation or execution authority.
The PostgreSQL instance-store facade delegates pure row and inventory-manifest validation to its
records module so the persistence boundary remains below its enforced size limit without changing
transactions, stored direction, query behavior, or import compatibility.
Snapshot rows and immutable observation lifecycle rows may use bounded set-based PostgreSQL writes.
The writer retains one transaction, the active-generation fence, conflict behavior, and retained
content replay checks; batching changes database round trips, not graph or evidence semantics.

An instance presentation can attach a ResourceType-specific read-only detail object without
creating another ontology identity. For `llm-model-deployment`, the Operator projection binds that
object to the exact ResourceType and allows only model name, model version, deployment SKU, and
normalized TPM. Other ResourceTypes cannot carry it, and raw provider properties remain outside the
Console and conversational screen context.

Kubernetes runtime Resources can carry a separate allowlisted identity and diagnostic detail
object. The Operator validates stable UID and observation revision fields, and the Console renders
only that response. This detail object creates no new ontology identity, relationship, state axis,
diagnosis, or browser authority.

## LinkType semantics

Stored direction remains `from_type -> to_type`. A compatible LinkType revision can add these
reviewed semantic fields:

| Field | Purpose |
|-------|---------|
| `forward_role` | Human and agent-readable role when traversing stored direction. |
| `reverse_role` | Human and agent-readable role when traversing against stored direction. |
| `semantic_traits` | One or more composable meanings such as containment, dependency, attachment, connectivity, traffic, classification, authorization, or evidence. |

Role names are scoped to one LinkType and do not imply another stored edge. Traits express domain
meaning, not colors, layout lanes, or graph coordinates. Existing causal, temporal, transitive,
cardinality, and endpoint contracts remain independent.

Provider relationship mappings also carry a reviewed cardinality. Candidate materialization MUST
match that catalog cardinality, LinkType, endpoint orientation, source property path, and source
schema identity before it can enter a versioned proposal generation; an omitted catalog value uses
only the reviewed LinkType default.

The first implementation applies the fields to `contains`, `attached_to`, `depends_on`,
`routes_to`, `runtime_calls`, `peered_with`, `resource_classified_as`, `resource_type_member_of_class`, and
`resource_class_specializes`. Other LinkTypes remain readable through their exact legacy
declarations until a competency-driven audit promotes them.

## Query algebra

The query contract separates open graph expansion from an ordered semantic path.

Verified query execution may expose bounded node lifecycle observations for presentation. Each
observation preserves the verified node kind, dependency position, status, and evidence references
without provider commands or execution authority. Missing, delayed, or failed observation delivery
does not change the query result; the terminal execution receipt remains authoritative.

Resource-state queries accept only catalog-declared state concepts and exact bounded resource
collections. A concrete state concept takes precedence over the generic observed-state sentinel.
Empty or incomplete results preserve row-count and source limitations and never prove that matching
resources do not exist outside the verified query scope.

The additive `telemetry_recipe` query node accepts one content-addressed `TelemetryEvidenceNeed`.
Its verifier schema permits only a reviewed recipe id and version, exact resource and evidence
cutoff, fixed lookback profile, output schema digest, idempotency key, and query/cost ceilings. Raw
KQL, workspace ids, tables, endpoints, and caller filters are not expressible. Verification precedes
provider I/O, and execution returns only an authority-free completeness, route, row, latency, cost,
and opaque receipt projection under `server_operational_logs` evidence authority.

### Exploratory traversal

An exploratory traversal accepts an allowed LinkType set, one direction, maximum depth, object
limit, and edge limit. Every allowed LinkType may be followed at each depth, subject to its
transitivity contract. The result reports exact truncation reasons and never claims path order.

### Ordered typed path

An ordered typed path contains one or more steps. Each step declares:

- exact LinkType name;
- `outgoing` or `incoming` traversal direction;
- expected endpoint ObjectType;
- bounded repetition only for a LinkType declared transitive.

The verifier checks the complete endpoint chain before store I/O. Runtime executes one step at a
time against the current bounded frontier and validates the reached endpoint types. A tuple of
LinkType names is never interpreted as both an ordered path and an unordered traversal set.

Existing v1 relationship traversal remains compatible and supports one LinkType. Multi-LinkType
ordered paths use the additive typed-path contract and a new exact function or query-node identity.

### Taxonomy closure

The query compiler resolves one `ResourceClass` to a bounded, deterministic set of concrete
ResourceType ids. The closure receipt pins:

- ontology release digest;
- requested ResourceClass id;
- ordered class and ResourceType ids;
- closure digest and truncation state.

The resulting Resource query uses exact `Resource.type` values. Runtime never expands a class from
natural-language terms, identifier prefixes, or provider fields.

## Completeness and presentation

Graph consumers preserve four independent limitation families:

| Family | Example |
|--------|---------|
| Source coverage | A referenced endpoint was not observed in the complete provider generation. |
| Query truncation | A depth, object, edge, or result bound was reached. |
| Access redaction | The principal cannot read an endpoint, property, or evidence field. |
| Presentation omission | The Console focus view intentionally hides bounded response items. |

An ObjectType detail preserves every property declared by its exact catalog version. Server-owned role and purpose filtering may remove properties and report that redaction, but no projection or Console view may discard a declared property or present an omitted property set as complete. Shipped ObjectTypes keep the normalized ontology key `id` even when a runtime store uses a domain-specific identifier name. Adding required semantic fields uses a new major declaration version and preserves the earlier release for replay.

### Relationship coverage accounting

Relationship coverage uses five independent measures. A single percentage cannot combine provider
support, one bounded query, source readiness, and browser presentation without creating a false
completeness claim.

| Measure | Complete result |
|---------|-----------------|
| Candidate accounting | Every discovered candidate is materialized, assigned a reviewed unavailable reason, or access-redacted. |
| Supported materialization | Every candidate inside the reviewed provider and evidence profile, excluding reviewed unavailable and redacted candidates, becomes one verified link. |
| Query completeness | The requested depth, object, edge, and result bounds are not reached. |
| Source readiness | Every evidence source required by the selected competency profile is available and current. |
| Presentation accounting | Every returned item is shown in the focus graph, retained in the full bounded Inspector, delegated to a purpose-specific surface such as IAM, access-redacted, or counted as a presentation omission. |

The candidate-accounting receipt keeps materialized, reviewed-unavailable, redacted, and
unclassified counts separate. An unclassified candidate or a sum that does not equal the discovered
candidate total makes the receipt incomplete. Supported materialization reaches 100% only for an
explicit provider, release, source, principal, scope, and competency profile. It never means every
possible relationship in an open cloud-provider schema.

Provider-native type coverage remains separate from relationship candidate accounting and ontology
classification. The active snapshot reports reconciled mapped and unmapped object counts and
bounded unknown provider type names. The Operator and Console validate and present that evidence,
but an unknown type remains `unclassified-resource`; the report cannot create a ResourceType,
classification link, catalog revision, or execution authority.

A bounded exploratory response reports returned Resource and link counts, the exact requested
limits, and per-reason truncation. When a bound is reached, the response stays incomplete and the
operator narrows the link types, depth, or root. Local Inspector paging covers only relationships
already returned by the server and is never presented as a server continuation. The Console reports
response, presentation, focus-graph, Inspector-only, purpose-delegated, redacted, and omitted counts
without overlapping those disposition buckets. Layout selection never changes the authoritative
response count.

The Console opens `/ontology` on the observed Resource instance workspace. Declaration, action
contract, semantic-model, and Catalog topology views remain available through one labeled
disclosure and retain their existing deep links. The declaration graph is loaded only after an
operator enters one of those reference views, so its latency or unavailability cannot block the
instance directory. This navigation and loading boundary changes no evidence, graph, query, or
execution authority.

The selected-instance view consumes a durable authenticated inventory-invalidation SSE stream and
revalidates its bounded response after each committed watermark. A monotonic 15-second countdown
drives fallback polling while SSE is unavailable. Focus, online, and visible-state recovery trigger
an immediate revalidation. Overlapping requests coalesce, refresh failure preserves the last
verified response, and stale data is never silently treated as current. Neither SSE nor polling is
provider observation. A Resource or relationship changes only after the inventory authority records
new evidence. Provider-reported states remain exact values and use text-bearing semantic badges;
color never becomes the only state signal.

Capacity is an observed Resource fact, not a count inferred from visible graph children. The
Operator projection exposes it only for reviewed scalable types: AKS AgentPool
`properties.count` is labeled as node count, and VM Scale Set `sku.capacity` is labeled as instance
count. Missing, negative, non-integral, or unsupported values remain absent. During a scale
operation, the value is the latest committed provider observation; it is neither desired capacity
nor proof that the same number of Kubernetes Nodes is Ready.

Operator projections preserve source generation, ontology release, query bounds, relationship
coverage, and exact limitation codes. The Console may build containment, dependency, connectivity,
authorization, classification, and evidence views from semantic traits. It also provides an
`All bounded relationships` inspection surface and reports its own omitted node and edge counts by
reason. A bounded multi-hop response is never described as one hop. For a selected VM, the Console
may summarize only ordered network paths whose stored edges and reviewed mapping evidence are
present in the response. A missing path remains unknown when relationship coverage is incomplete
or the required backend association is not modeled. Browser layout never changes completeness or
authority.

Impact traversal carries one evidence object per edge rather than assigning a blanket verification
value to the query. Configuration-observed and independently verified evidence remain distinct from
availability, and query completeness never repairs stale or incomplete relationship coverage.
`runtime_calls` retains caller-to-target stored direction and requires the exact active generation
and ontology release before the Console can present the bounded path.

The instance graph legend shows `contains`, `attached_to`, and `depends_on` by default. Operators
can expand the legend to inspect every relationship type in the bounded response. This presentation
choice does not remove links, change relationship counts, or narrow the Inspector.

The default instance presentation omits `authorization.role-assignment` Resources from selection,
the graph, relationship inspection, and conversational screen context. IAM projections retain the
underlying evidence. The instance directory applies this omission before it applies its bound, so
the bounded page counts only Resources an operator can select. A Resource Group remains selectable
as a bounded scope overview. For any
non-scope root, the graph shows only that root's immediate owning Resource Group and does not add
Resource Groups that belong only to indirect peers or branch nodes. Scope membership never proves
traffic or dependency.

The directory bound is a presentation limit, never a completeness claim. When the active generation
holds more Resources than the bound, the surface states the bound as its own notice and directs the
operator to narrow the search. Search runs against the authoritative directory rather than the
already-bounded page, so a Resource beyond the bound stays reachable. A query the recorded
identifiers cannot contain is refused as unmatchable instead of returning an empty result that would
read as an absent Resource, and no query is translated or rewritten before it reaches the directory.
A valid search with no matching Resource returns a complete empty page without issuing a contextual
selection capability because there is no object identity to bind.

A Resource type icon is presentation only. It never carries object identity, type authority, or
evidence. An unmapped type resolves to an explicit generic glyph instead of a lookalike, and a
glyph shared by two types groups them without asserting that they are the same object.

The converse also holds. A layered graph may draw one Resource more than once to keep every
relationship directed, so each repeated node states how many times that single Resource is drawn
rather than reading as separate objects. For a cluster root, the graph adds a bounded,
declared-workload-first sample of what each namespace holds, because a namespace drawn as a leaf
asserts an empty namespace it never observed. The Resource an operating scope manages on the
selected Resource's behalf is labeled as managed, so it does not read as a peer scope alongside the
scope that owns the selection.

Layout consumes the viewport it has rather than a fixed box, and fills rows before it adds a
column, so hop depth rather than row packing decides the width. Zoom stops at the scale of the
first render because a smaller scale only shrinks nodes and never adds a relationship. A layout
bound never doubles as a completeness bound: how much of a scope a root summarizes stays an
independent decision.
Direction-region backgrounds belong to the viewport surface rather than the bounded graph
geometry. When the rendered SVG is shorter than the viewport, those regions continue through the
complete scroll surface without moving nodes, edges, labels, or pan and zoom coordinates.
Supporting metadata follows the same graph-first hierarchy. The directory bound and current
refresh state stay in the search toolbar, while presentation coverage and graph-legend details
start collapsed behind native disclosures. Compact presentation never removes a limitation,
relationship meaning, evidence count, or recovery state.
Reviewed Resource glyphs resolve through static asset URLs without importing every glyph as a
runtime module. The graph requests only glyph files used by rendered nodes, and the generic glyph
remains explicit for an unmapped ResourceType.
When scaled graph geometry is shorter than its viewport, a presentation-only stage centers it
vertically while the direction regions continue through the full viewport. Taller geometry keeps
its ordinary scroll range. AKS end-to-end evidence starts collapsed as a native disclosure so the
graph remains primary, and operators can expand the stored-link status lanes when needed.

Containment leaves a Resource from its underside while attachment leaves from its side, and a
contained Resource follows its owner's order within a column. What a Resource is attached to is
drawn above it and what it contains is drawn below it, with a visible break between the two groups.
A layered layout can only guarantee that order for the selected Resource, so an owner that a deeper
level draws below its own child keeps the side port instead of claiming a hierarchy the placement
does not show. The port a line uses and the row a Resource occupies are reading aids only. Neither
creates, removes, reorients, or re-evidences a relationship.

A layered layout reaches its limit there: it can order one root above its children but cannot show a
hierarchy several levels deep without degenerating into an indented outline. Containment is
therefore drawn as nesting rather than as an edge, because a box drawn inside another box cannot
point the wrong way. The model computes box sizes bottom-up, gives each column its own width, and
reports per-owner how many children a bound left out, so a box that hides children never reads as a
complete owner. An owner keeps its own card inside its box, so nesting removes a line without
removing that Resource's status or evidence. Column count favours height over width, because width
is the axis the direction bands and the surrounding Resources already compete for. Nesting removes
the line for every containment relationship it absorbs; a measured cluster resolves 190 of 385
relationships that way. Ordering inside a box follows the same declared-workload-first rank the
layered layout uses, so a bound removes derived Resources before declared ones. A bound then takes
one Resource of every kind before a second of any, because ranking and truncating lets the most
numerous kind consume the whole bound: a namespace holding fourteen DaemonSets behind seven
Deployments would report only Deployments and read as though it holds nothing else. A count of what
was left out cannot repair a sample that misstates composition. Nesting is a reading
arrangement only. It never asserts containment the evidence did not report, never adds a Resource
the layout left out, and never places a Resource with no owning `contains` relationship inside a box
to make the drawing tidy.

One fact earns one encoding. Once a box states a Resource's distance by position, the drawing does
not also fade it, because a second encoding of the same fact costs legibility without adding meaning
and lands hardest on the Resources nesting exists to reveal. Emphasis by distance is kept where
position says nothing, which is outside every box.

A management scope becomes a box only when it is the selected Resource. Nesting begins at the
selected Resource and follows what it contains, so a scope that merely holds it stays an ordinary
relationship. The ontology already separates the two: `azure.resource-group-contains-resource` is a
distinct mapping from `kubernetes.namespace-contains-resource` and `azure.vnet-contains-subnet`, and
it accounts for 46 of 190 containment relationships in a measured subscription. Scope membership
states where a Resource is billed and administered rather than what it runs inside, and a box that
enclosed the selected Resource would make the subject of the view an occupant of its own context.
Selecting the scope reverses that: the question is then what the scope holds, and its membership is
the answer.

An absent state is reported as unreported rather than as unobserved. Most Kubernetes ResourceClasses
are inventoried without a projected state, so naming that absence an observation would assert a
check that never ran and imply the state is missing in the cluster. The same holds for a record
field a ResourceClass never carries, such as an Azure location on a Kubernetes workload. Reporting
absence is only truthful when it names the right absence.

When a relationship cannot be placed, the recovery has to satisfy the rule that rejected it. Some
relationships are drawn between levels and some, such as a scale set interface and the virtual
machine it serves, are drawn on the same level. A recovery that always added the missing occurrence
one level to the right could never satisfy the same-level rule, and the graph refused to draw rather
than draw a false direction.

A relationship a box carries is still a relationship the drawing shows. Counting only the lines made
the graph report less coverage than it presents once nesting removed them, which understates the
evidence an operator is looking at just as surely as overstating it would.

## Migration and rollout

1. Add the structural declarations, loaders, and validators without changing the visible query
   path.
2. Add ordered typed-path execution and taxonomy closure behind read-only exact-release functions.
3. Shadow-compare existing one-hop traversal, impact, network, and classification results.
4. Add LinkType roles and traits through compatible declaration revisions. Preserve every prior
   release for replay.
5. Expose limitation families and semantic views through additive Operator and Console contracts.
6. Promote only after focused competency, replay, bilingual, and no-authority checks pass.

A direction, endpoint, cardinality, or persisted-identity correction still requires a LinkType
major version or explicit graph migration. No rollout rewrites historical context snapshots.
## Related docs

| To learn about | Read |
|----------------|------|
| Delivery status and remaining work | [Implementation ledger](../../roadmap-implementation/architecture/ontology-structural-model.md) |
| Declaration kinds, direction, state, and context | [Operating Ontology Metamodel](operating-ontology-metamodel.md) |
| Domain objects, relationships, identity, and time | [FDAI Operating Ontology](operating-ontology.md) |
| Interfaces, ObjectSets, functions, and exact releases | [Ontology Safety Infrastructure](operating-ontology-platform.md) |
| Continuous graph freshness and completeness | [Continuous Operational Instance Graph](continuous-operational-instance-graph.md) |
| Verified query coverage and cutover | [Ontology Query Coverage Implementation Plan](../interfaces/ontology-query-coverage-implementation-plan.md) |
