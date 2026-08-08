# `rule-catalog/vocabulary/`

Canonical CSP-neutral vocabularies referenced from the catalog data.
Currently one artifact:

- [`resource-types.yaml`](resource-types.yaml) - the enumerated list of
  `resource_type` identifiers a rule may target. See
  [../../docs/roadmap/rules-and-detection/rule-catalog-collection.md#collection-sources](../../docs/roadmap/rules-and-detection/rule-catalog-collection.md#collection-sources)
  and [../../docs/roadmap/architecture/llm-strategy.md#ontology-foundation](../../docs/roadmap/architecture/llm-strategy.md#ontology-foundation).

Adding or renaming an entry is a **governance PR** - the identifier is
quoted from every matching rule's `resource_type` field, so a rename is a
catalog-wide migration.

CI validates every entry against the JSON Schema shipped inside the
Python package at
[`services/core-control-plane/src/fdai/rule_catalog/schema/resource_types.schema.json`](../../services/core-control-plane/src/fdai/rule_catalog/schema/resource_types.schema.json).
