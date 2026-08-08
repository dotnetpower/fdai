# Ontology Vocabulary

This directory contains FDAI's canonical cloud-provider-neutral vocabulary declarations. It names
the object, relationship, resource, signal, property, purpose, and investigation concepts that
catalog and runtime records can reference.

> This directory is not the ontology metamodel or the runtime ontology database. It declares the
> standard vocabulary using schemas defined elsewhere, and it contains no observed deployment
> instances or current cloud truth.

## Contract Boundary

The ontology has four distinct layers:

| Layer | Responsibility | Location or artifact |
|-------|----------------|----------------------|
| Metamodel and schema | Defines which declaration shapes, property types, cardinalities, lifecycle fields, and provenance fields are valid. | [`services/core-control-plane/src/fdai/shared/contracts/ontology/`](../../services/core-control-plane/src/fdai/shared/contracts/ontology/) and [`models/ontology.py`](../../services/core-control-plane/src/fdai/shared/contracts/models/ontology.py) |
| Canonical vocabulary | Declares which standard concepts FDAI recognizes and what their relationships mean. | This directory |
| Ontology release | Validates and content-addresses one exact set of declarations for compatibility and replay. | `OntologyRelease` produced by the catalog and ontology-platform loaders |
| Runtime instances | Records actual resources, observations, changes, findings, and links from a deployment. | Deployment-owned ontology projections and instance stores |

For example, [`object-types/ConfigurationDriftFinding.yaml`](object-types/ConfigurationDriftFinding.yaml)
declares the shape and meaning of a drift finding. A finding that reports an actual disk SKU
difference is a runtime instance of that declaration and does not belong in this directory.

## Layout

| Path | Contents |
|------|----------|
| [`object-types/`](object-types/) | Canonical ObjectType declarations such as `Resource`, `Change`, and `ConfigurationDriftFinding`. |
| [`link-types/`](link-types/) | Directed LinkType declarations, endpoint types, cardinality, and causal or temporal semantics. |
| [`resource-types.yaml`](resource-types.yaml) | Resource type identifiers that rules and inventory records may reference. |
| [`signal-types.yaml`](signal-types.yaml) | Signal type identifiers used by rule and event semantics. |
| [`property-semantics.yaml`](property-semantics.yaml) | Reviewed property meaning, type, unit, normalization, authority, and freshness metadata. |
| [`inventory-query-language.yaml`](inventory-query-language.yaml) | Bounded inventory query vocabulary. |
| [`investigation-intents.yaml`](investigation-intents.yaml) | Canonical investigation intent identifiers. |
| [`purposes.yaml`](purposes.yaml) | Purpose identifiers used to constrain ontology reads and evidence access. |

ActionType declarations are also ontology data, but they live under
[`../action-types/`](../action-types/) because they carry separate execution and safety governance.
Runtime state and evidence remain outside the catalog even when they conform to these declarations.

## Change Rules

- Treat an addition or rename as a governance change. Identifiers are stable references, and a
  rename can require a catalog and persisted-instance migration.
- Keep declarations customer-agnostic. Do not add tenant identifiers, resource ids, endpoints,
  secrets, live values, or deployment-specific instances.
- Update canonical provenance hashes whenever a declaration changes. Catalog loading fails closed
  on a stale hash, invalid endpoint, duplicate name, or incompatible declaration.
- Keep provider-specific source paths in reviewed mapping or property-semantic data. Do not turn a
  provider field name into a new core ontology concept when a provider-neutral meaning exists.
- Adding vocabulary does not create runtime sensing, judgment, approval, remediation, or execution
  authority. Those behaviors require separately reviewed providers, composition, policy, and tests.

See the [FDAI Operating Ontology](../../docs/roadmap/architecture/operating-ontology.md),
[Operating Ontology Metamodel](../../docs/roadmap/architecture/operating-ontology-metamodel.md),
and [Ontology Safety Infrastructure](../../docs/roadmap/architecture/operating-ontology-platform.md)
for the complete semantic, release, projection, and authority boundaries.
