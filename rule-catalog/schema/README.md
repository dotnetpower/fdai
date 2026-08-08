# Catalog Extension Schemas

This directory contains JSON Schemas owned directly by optional catalog extension surfaces. It is
not the single schema root for every file under `rule-catalog/`.

## Files

| Schema | Validates |
|--------|-----------|
| [`extension-kit.schema.json`](extension-kit.schema.json) | Extension-kit package metadata and bounded catalog integration declarations. |
| [`skill-bundle.schema.json`](skill-bundle.schema.json) | Governed skill-bundle metadata consumed by the catalog pipeline. |

Schemas stay with their owning contract when another package or catalog surface owns the wire
format. Examples include:

- Rule contracts under
	[`shared/contracts/rule/`](../../services/core-control-plane/src/fdai/shared/contracts/rule/).
- Ontology ObjectType, LinkType, and ActionType contracts under
	[`shared/contracts/ontology/`](../../services/core-control-plane/src/fdai/shared/contracts/ontology/).
- Probe manifests under [`../probes/probe.schema.json`](../probes/probe.schema.json).
- Chaos scenarios under [`../chaos-scenarios/schema/`](../chaos-scenarios/schema/).
- Prompt scenarios and tools under their respective [`../prompts/`](../prompts/) subdirectories.

The owning loader is authoritative for schema validation, normalized model validation, provenance,
duplicate identities, and cross-references. A valid JSON document alone is not sufficient when the
loader requires additional semantic checks.
