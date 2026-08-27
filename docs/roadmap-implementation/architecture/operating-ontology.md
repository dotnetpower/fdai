# Operating ontology implementation ledger

This internal ledger keeps detailed delivery state for the operating ontology design. The roadmap
owner remains focused on normative design while this record preserves reviewable implementation
scope, append-only transitions, and resumable work.

## Implementation status

### Current implementation notes

> **Recorded baseline (2026-08-08):** O1-O4 implement semantic declarations, immutable context,
> Forseti ceiling wiring, decision-case selection, response closure, and Muninn/Norns learning
> intake. `OperatingModelProvider` projects bounded deployment instances; context snapshots retain
> typed evidence paths, revisions, effective time, provenance, and complete freshness receipts.
> M3 adds immutable `StateFactMetadata` for observed, derived, desired, and execution lanes.
> Optional inventory link observation metadata survives ontology projection and operational-context
> materialization, contributes to snapshot identity, and lowers the snapshot ceiling when evidence
> is stale, incomplete, conflicting, synthetic, future-cutoff, or unverified.
> Verified links require an independent verifier, a trusted verification method, and an immutable
> verification receipt. Required source freshness, trusted UTC clock identity, recorded time, and
> skew-bounded future checks also contribute to context safety and replay identity.
> Wave 2 provides a content-addressed `OperationalEvidenceBundle` runtime read path that keeps
> secured ontology paths, authoritative state facts, catalog references, and governed document
> excerpts in separate authority lanes. Admission requires content-addressed source receipts that
> pin the ontology release, catalog and document revisions, authenticated source, purpose, scope,
> redaction summary, and typed temporal scope. Deterministic claim and citation validation, exact
> typed-claim contradiction detection, and final-body byte and item budgets emit hold evidence and
> can only preserve or lower the bundle's autonomy ceiling. The optional source is dependency
> injected into semantic runtime composition. Every result remains `SHADOW_ONLY` with no mutation
> or execution authority.
> Change management adds planned-change evidence to `Change`, a reviewed `ChangeWindow`, and typed
> links from target and decision through impact, process, outcome, and recovery. These declarations
> are semantic evidence only and grant no approval or execution authority. Huginn now carries the
> same normalized Change on its causal Event and owner topic. Forseti computes a bounded
> `ChangeAssessment`, preserves it on Verdict and DecisionCase evidence, and requires human review
> for stale, incomplete, failed, or review-required assessment. The runtime reads exact-release
> active-inventory freshness receipts under the PostgreSQL promotion lock and clears this gate only
> for a fresh, complete, exact-target observed generation.
> M5 adds the catalog-declared `routes_to` and `peered_with` Resource links to inventory projection
> and read-only deterministic network and Pod telemetry functions. A composition-owned bounded
> issuer records secured ObjectSet results, and exact Function handlers resolve only the issued
> dependency digest. The verifier authenticates role, purpose, exact release, and projected-result
> digest against the contextual invocation and opaque trust context. Unissued and self-minted
> receipts are rejected. Evaluation time equals
> the trusted receipt cutoff; future effective, evidence, or recorded times and unbounded freshness
> stay unverified. It preserves stored edge direction and requires two directed peering records with
> distinct direction-bound observation and verification receipt lineage. Missing endpoints,
> incomplete queries, or absent paths remain unknown, never a claim that traffic cannot flow.
> Inventory projection rejects endpoint-type conflicts against observed resources. The function
> uses a source-derived artifact digest, emits exact-release invocation receipts, and has no
> provider I/O or execution authority.
> Current Azure projection now emits directed `routes_to` only when the provider supplies an exact
> ARM resource next-hop id. IP addresses, prefixes, DNS names, and route absence never become
> Resource identities or reachability claims. Both snapshot and real-time inventory projections
> persist the reviewed peering and routing link vocabulary.
> The inventory ontology projector now supports the catalog-declared `resource_classified_as`
> relationship from each observed Resource to one reviewed ResourceType. Classification pins the
> complete inventory generation and a replay-stable digest of the ResourceType registry entry.
> An unmapped type makes classification coverage incomplete and activates no replacement graph.
> A reviewed mapping whose ResourceType instance is not yet seeded records
> `unseeded_resource_type`, omits only that classification edge, and still writes the rest of a
> complete inventory generation. Other relationship and endpoint validation failures remain
> blocking.
> The production inventory job injects the already loaded registry digest map, so promoted complete
> generations persist this relationship in live projections.
> Azure SQL databases also carry a reviewed `contains` candidate from the logical SQL server
> encoded as their immediate ARM provider parent. For that same database child, this exact mapping
> shadows the wildcard resource-group candidate so `contains` keeps one parent and
> `Resource.parent_id` names the same logical server. Complete-generation verification must observe
> both the server and database before activating the logical-parent edge.
> Repeated authoritative observations of one resource identity inside a generation are now
> adjudicated deterministically instead of failing the whole projection. Agreement collapses to one
> object and keeps the earliest observation time; disagreement stays an explicit state-fact conflict
> that withholds the contested value and demotes every existing consumer. Cross-authority
> adjudication between independent sources is not implemented.

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| O1 semantic spine and catalog integrity | implemented | [`test_ontology_catalog.py`](../../../services/core-control-plane/tests/rule_catalog/test_ontology_catalog.py), [`test_ontology_provenance.py`](../../../services/core-control-plane/tests/rule_catalog/test_ontology_provenance.py) | The integrated catalog validates the operating semantic spine, provenance, references, and cardinality. |
| O2 bounded context and current-state projection | in-progress | [`ontology_instance.py`](../../../services/core-control-plane/src/fdai/shared/providers/ontology_instance.py), [`console_projection.py`](../../../services/core-control-plane/src/fdai/core/operational_context/console_projection.py), focused instance and Context projection tests | Typed current-state objects and links exist. A secured receipt can now produce bounded no-authority Context metadata only when purpose, release, cutoff, and graph coverage match. Principal-scoped transport and authenticated runtime evidence remain open. |
| O3-O5 decision, outcome, and governed-learning loops | in-progress | [Delivery plan](../../roadmap/architecture/operating-ontology.md#delivery-plan), [`test_ontology_alignment.py`](../../../services/core-control-plane/tests/agents/test_ontology_alignment.py) | Core slices exist, but effect closure and governed learning are not complete across every production path. |
| Decision-and-learning writers | in-progress | [`hypothesis_lineage.py`](../../../services/core-control-plane/src/fdai/core/operational_planning/hypothesis_lineage.py), [`_execution.py`](../../../services/core-control-plane/src/fdai/core/control_loop/_execution.py), and focused lineage and independent-outcome checks | `OperationalOutcomeLineageProducer` closes one single-effect episode only when Forseti-owned prospective records already exist. The actual ControlLoop call site supplies the runtime `Action`, exact ActionType version, captured executor start and end, terminal status and receipt, and a scorable `ResponseOutcome` produced after `IndependentEffectObserver`. Missing prospective records write nothing, and the producer records `telemetry_complete=false` because the response contract carries no completeness receipt. No composition root binds the source, sink, or projector. The remaining prospective fields, multi-effect independent outcomes, and explicit telemetry completeness still need named authoritative producers before composition. |
| Multi-effect operational lineage contract | implemented | [`hypothesis_lineage.py`](../../../services/core-control-plane/src/fdai/core/operational_planning/hypothesis_lineage.py), [`ActionOption.yaml`](../../../rule-catalog/vocabulary/object-types/ActionOption.yaml), focused lineage and competency checks | New lineage writes preserve the ordered complete expected-effect set and require one independent outcome per effect. Singular-only stored records read as one effect, while dual-field ambiguity fails closed. |
| Wave 2 evidence, change, Property, and topology foundations | in-progress | [Implementation status narrative](../../roadmap/architecture/operating-ontology.md#fdai-operating-ontology), [Operating Ontology Platform](../../roadmap/architecture/operating-ontology-platform.md), [`check-property-semantic-coverage.py`](../../../scripts/quality/architecture/check-property-semantic-coverage.py) | Reviewed foundations exist; the evidence bundle is not composed into runtime, planned changes cannot auto-clear graph freshness, reviewed Property coverage is measured but partial, and broader platform delivery remains open. |
| Console semantic-band declaration completeness | implemented | [`Forecast.yaml`](../../../rule-catalog/vocabulary/object-types/Forecast.yaml), [`Pattern.yaml`](../../../rule-catalog/vocabulary/object-types/Pattern.yaml), [`test_ontology_console_projection.py`](../../../services/core-control-plane/tests/delivery/test_ontology_console_projection.py) | Every object type named by a Console band is declared by the shipped release, so no band member is dropped silently. Both declarations are semantics only and add no instance path. |
| Operating-scope `unknown_service` coverage | validated | [`operating_scope.py`](../../../services/core-control-plane/src/fdai/core/operational_context/operating_scope.py), [`postgres_inventory_snapshot.py`](../../../services/core-control-plane/src/fdai/delivery/persistence/postgres_inventory_snapshot.py), and focused consumer checks (`4 passed`) | The authenticated inventory graph projection annotates every bounded response Resource with one reviewed service or `unknown_service`, returns aggregate completeness, and degrades on unmapped or truncated scope. |
| Provider-native unclassified identities | validated | [`inventory.py`](../../../services/core-control-plane/src/fdai/shared/providers/inventory.py), [`arg_query.py`](../../../services/core-control-plane/src/fdai/delivery/azure/arg_query.py), focused checks (`259 passed`), and [Issue #217](https://github.com/dotnetpower/fdai/issues/217) | A reviewed reserved ResourceType keeps unsupported provider identities visible without inventing type-specific semantics. The promoted local snapshot and ontology retain exact provider identity coverage with no realtime overlay residual. |
| Operating-intent runtime instances | implemented | [`operating_model.py`](../../../services/core-control-plane/src/fdai/runtime/operating_model.py), [`test_operating_model.py`](../../../services/core-control-plane/tests/runtime/test_operating_model.py), and the six catalog declarations | The deployment-supplied snapshot validates and projects all six exact intent types, and a focused fixture fails if any one is absent. Deployment values remain external. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-19 | validated | Promoted and measured the identity-complete provider graph after the service-owned inventory entry point gained composition parity. The provider fence reports 533 native objects: 476 reviewed mappings and 57 reserved unclassified identities across 68 provider types, with `provider_identity_complete=true`. Snapshot and ontology each retain 573 Resources, their identity sets have zero difference, and the realtime overlay contains zero Resources and zero links. | [Issue #217](https://github.com/dotnetpower/fdai/issues/217); coverage schema `1.1.0`; final local observation reports fresh inventory with 1,215 aggregate graph records. | Deployment-reviewed service mappings may reduce `unknown_service`; no provider identity, projection parity, or realtime-overlay residual remains. |
| 2026-08-19 | validated | Bound `project_operating_scope` to the PostgreSQL-backed authenticated inventory graph response. Two bounded reverse link reads resolve only service paths ending at response Resources; every Resource carries `service_ref`, and incomplete input or unmapped scope becomes an explicit coverage gap instead of a healthy absence claim. | [Issue #217](https://github.com/dotnetpower/fdai/issues/217); 4 focused consumer tests and strict mypy pass; a read-only loopback measurement returned 213/213 response Resources annotated, `input_complete=true`, `complete=false`, and `operating_scope_unmapped`. | Supply reviewed BusinessService and Workload mappings to reduce the measured `unknown_service` set; no consumer wiring remains. |
| 2026-08-19 | implemented | Added the reviewed `unclassified-resource` ResourceType and exact provider-identity reconciliation. An undeclared native type is no longer absent from a complete generation, but it gains no query terms, type-specific Rule, or action eligibility. | [Issue #217](https://github.com/dotnetpower/fdai/issues/217); focused inventory, ontology, catalog, and semantic value-domain checks pass within the 259-case slice; Ruff and strict mypy pass. | Promote a fresh generation, then bind operating-scope coverage to one read-only operator consumer. |
| 2026-08-13 | in-progress | Adopted the implementation ledger without reconstructing earlier provenance. | Current source, tests, and delivery plan listed in the scope table. | Complete the observable exit conditions below. |
| 2026-08-14 | implemented | Added a bounded Context presentation projector that rejects mismatched secured receipts and omits raw object properties. | `current change`; `test_console_projection.py` passed 5 focused cases. | Bind the projector only through a principal-scoped evidence response and retain authenticated Console evidence. |
| 2026-08-15 | implemented | Removed the undeclared `predicts_breach_of` and `learned_as` rows from the relationship contract, recorded their blocking ObjectTypes, and pinned the table against the shipped LinkType catalog and stored link direction. | `current change`; `test_ontology_catalog.py` and `test_ontology_instance.py` focused cases. | Restore either relationship only together with its endpoint ObjectType and the competency question it answers. |
| 2026-08-15 | implemented | Judged `Pattern` and `PatternObservation` to be one layer from the compiler and publish path, corrected the review claim, marked both undeclared object types in place, and recorded that the decision-and-learning lineage projector has no production caller. | `current change`; `test_ontology_catalog.py` document-consistency cases. | Construct `OperationalHypothesisLineageProjector` from a composition root so a governed episode writes and can replay `considers`, `expects`, `executed_as`, and `resulted_in`; then either publish `PatternObservation` from Norns with a live consumer or retire it, its topic, and its `PANTHEON_SPECS` and pantheon-document rows in one change. |
| 2026-08-15 | implemented | Corrected the agent-ownership section to name the two independent ownership registries, replaced the prose ownership claims with the exact `lifecycle.owner` type list, and replaced the unsupported "authority class, freshness policy, retention, allowed purposes" claim with the fields the schema actually declares. | `current change`; `test_object_type_catalog.py::test_documented_semantic_write_owners_match_the_catalog`. | Decide per ObjectType whether an absent `lifecycle` block should gain a declared owner; do not add one to fill the field. |
| 2026-08-15 | implemented | Added deterministic adjudication of repeated authoritative observations of one resource identity, so `StateFactMetadata.conflicts` has a production producer instead of only test fixtures. Benign repetition no longer fails the whole generation. | `current change`; `test_observation_adjudication.py` 15 focused cases and `test_inventory_projection.py` conflict-demotion cases passed; 354 focused ontology, inventory, and runtime cases passed. | Adjudicate genuinely independent authorities against each other; inventory projection versus live discovery is the next pair. |
| 2026-08-15 | implemented | Adjudicated the first genuinely independent pair: the live provider read against the inventory-projected graph state. A state or identity disagreement becomes a `derived` cross-source conflict that is retained in the receipt digest and makes the hook abstain from asserting a state and degrade its activity; an observation-time difference alone is explicitly not a conflict. | `current change`; `test_resource_state_shadow.py` 6 added adjudication cases and `test_wire_read_investigation.py::test_cross_source_state_conflict_lowers_the_answer_and_activity` with a non-vacuous agreeing control. | Adjudicate two independent providers, and projected state against telemetry. |
| 2026-08-15 | implemented | Added a measured Property semantic coverage gate, disclosed the coverage and its consequence in both language pairs, corrected the `public_access` value type against the shipped Rego comparison, and added six evidence-grounded semantics. | `current change`; `check-property-semantic-coverage.py` reports 14/62 reviewed references; `test_property_semantic.py`, `test_ontology_catalog.py`, `test_catalog_projection.py`, and `test_property_semantic_coverage.py` focused cases. | Collection-valued references stay uncovered until bounded canonical JSON Property semantics exist. |
| 2026-08-16 | implemented | Restored the 2026-08-15 `Pattern` and `PatternObservation` row to the text it was recorded with, moved it back ahead of the rows a later merge interleaved before it, and records the work that had overwritten it here instead, because the implementation history is append-only. That work adopted the shipped `Forecast` and `Pattern` declarations, unified the owned learning object on `Pattern` across spec, topic, and tables, added the `unknown_service` scope-coverage marker, and recorded that both deferred relationships are blocked because neither endpoint pair is producible. | `current change`; `rule-catalog/vocabulary/object-types/{Forecast,Pattern}.yaml`, `operating_scope.py`, `test_ontology_catalog.py` document-consistency cases, `test_shipped_catalog_accepts_and_traverses_one_lineage`, and `test_shipped_catalog_rejects_a_lineage_missing_a_required_property`; a reversed `resulted_in` direction now fails, which the previous fake-store test could not detect; the focused catalog, context, projection, alignment, instance, explorer, and release suites passed. | Supply the missing `DecisionCase`, `ActionOption`, `ExpectedEffect`, and `ActionRun` properties from real producers, then construct `OperationalHypothesisLineageProjector` from a composition root; supply a producer for either deferred relationship before restoring it; publish `Pattern` from Norns with a live consumer or retire its topic; bind scope coverage to one consumer and pin operating-intent instances. |
| 2026-08-18 | implemented | Made the lane and authority separation exhaustively executable. Every lane and authority pair is now asserted, an `execution_ledger` fact is rejected in the `observed`, `derived`, and `desired` lanes, and a lane with no matrix row fails closed with the documented rejection instead of a latent `KeyError`. | `current change`; `test_state_evidence.py` 39 focused cases passed. | Bind the same separation at every projection write site so a future writer cannot persist a state fact without constructing `StateFactMetadata`. |
| 2026-08-24 | implemented | Reconciled the ActionOption effect property with the one-to-many `expects` and `resulted_in` links. New lineage writes require all expected-effect ids in deterministic order and one independent outcome per effect. Singular-only stored records read as one effect, dual-field ambiguity fails closed, and cross-type object-id collisions are rejected before storage. | `current change`; `hypothesis_lineage.py`; `ActionOption.yaml`; focused lineage and competency checks passed 15 cases. | Supply the remaining real producer properties and construct the projector only after the complete episode is available. |
| 2026-08-24 | in-progress | Added the first real decision-lineage producer segment. A one-effect closure joins only an exact runtime Action and independently observed scorable ResponseOutcome to pre-existing prospective records, appends the complete episode, and replays idempotently. The ControlLoop captures execution timestamps at the executor boundary and invokes an optional sink only after the outcome audit succeeds. | `current change`; `hypothesis_lineage.py`; `core/control_loop/{orchestrator,_execution}.py`; focused lineage checks passed 14 cases and MSCP shadow call-site checks passed 15 cases. | Produce the Forseti prospective records, multi-effect outcome set, and telemetry completeness evidence, then bind composition only when one complete runtime episode exists. |
| 2026-08-27 | implemented | Replaced the planned-change freshness boolean with a content-addressed receipt over the active PostgreSQL inventory generation and exact ontology release. Missing, stale, future, mixed-release, target-mismatched, truncated, pending-overlay, failed-successor, incomplete-provider, incomplete-link, and unavailable-source states all lower the assessment to review. | `current change`; `change_assessment.py`; `postgres_graph_freshness.py`; focused impact, persistence-decoder, change-chain, lineage, and pantheon-layout checks (`64 passed`); Ruff and strict mypy. | Retain one deployed exact-release receipt separately before raising this path from implemented to validated. |
| 2026-08-27 | implemented | Pinned all six operating-intent ObjectTypes through the deployment-supplied operating-model path, with no tenant values in the fixture. | `current change`; `test_operating_model.py` (`7 passed`); Ruff. | Retain deployment-specific instances separately as operational evidence. |
| 2026-08-27 | implemented | Hardened planned-change freshness by verifying persisted inventory and operating-model manifests, rejecting all pending resource and link overlays, double-reading the receipt around traversal, and classifying configured PostgreSQL failures as unavailable. | `current change`; focused freshness, impact, persistence-decoder, change-chain, and pantheon checks (`49 passed`); Ruff and strict mypy. | Preserve ordinary execution-time RiskGate revalidation and retain deployed receipt evidence separately. |
| 2026-08-27 | implemented | Required matching non-empty operating-model status and manifest revisions before a freshness receipt can be complete. | `current change`; focused freshness and pantheon checks (`52 passed`); Ruff and strict mypy. | Retain deployed exact-revision evidence separately. |

### Remaining work

- [x] Compose `OperationalEvidenceBundle` into a bounded runtime read path and retain admission,
  contradiction, citation, and final-budget receipts without granting action authority.
- [x] Supply and verify graph-freshness authority for planned-change assessment before allowing any
  automated clearance, including stale, incomplete, conflicting, mixed-release, target-mismatched,
  future, truncated, pending-overlay, and unavailable negative cases.
- [ ] Complete production bindings and replay evidence for the remaining context, outcome-closure,
  and governed-learning paths on one pinned ontology release.
- [ ] Produce `OperationalProspectiveLineage` from Forseti-owned values with explicit
  `DecisionCase.uncertainty`, option arguments and preconditions, effect direction and predictor
  version, then bind its source and the projector only after one complete runtime episode exists.
- [ ] Extend independent closure from one matched effect to the complete multi-effect set and carry
  an authoritative telemetry-completeness receipt; a scorable `ResponseOutcome` alone continues to
  project `telemetry_complete=false`.
- [ ] Bind receipt-verified Context metadata through an existing principal-scoped evidence response;
  prove wrong-principal, wrong-purpose, wrong-release, stale, and truncated cases remain unavailable.
- [ ] Keep the operating ontology and platform ledgers synchronized as topology, temporal,
  reconciliation, and graph-wide Dynamic delivery reaches its focused exit conditions.
- [x] Bind `project_operating_scope` to the authenticated read-only inventory graph response so
  `unknown_service` reaches an operator surface; focused consumer checks pass 4 cases.
- [ ] Supply a producer for the `Forecast` and `Pattern` endpoint pairs before restoring
  `predicts_breach_of` and `learned_as`. Both ObjectTypes now ship, so the blocker is that no
  runtime path writes either endpoint, not that the catalog would reject the declaration.
- [x] Project the six operating-intent types from a deployment-supplied source and pin them with a
  focused test that fails when an intent type produces no instance (`7 passed`).
- [ ] Review the shipped ObjectTypes that carry no `lifecycle` block and record, per type, whether an
  agent single-writer is required or whether catalog-as-code, a projection, or the event-bus
  registry is the correct authority ([#130](https://github.com/dotnetpower/fdai/issues/130)).
- [ ] Adjudicate two independent cloud providers against each other, and projected state against
  telemetry. Today only repeated observations inside one generation and the live-read against
  inventory-projection pair are decided.
- [ ] Decide whether an adjudicated cross-source conflict should also reach an autonomy ceiling
  outside the read path, and which writer may carry it without breaking single-writer ownership of
  the projected subgraph.
- [ ] Support bounded canonical JSON Property semantics; the coverage gate ranks the blocked reads.
