# Rule Catalog

This directory is FDAI's catalog-as-code data plane. It contains versioned rules, ontology
declarations, actions, workflows, prompts, probes, reports, source material, and governance data.
Runtime and collection code lives under
[`services/core-control-plane/src/fdai/rule_catalog/`](../services/core-control-plane/src/fdai/rule_catalog/README.md).

> Catalog data declares meaning, policy inputs, and proposal contracts. It does not observe live
> cloud state, grant approval, or execute a resource mutation. Runtime instances and evidence stay
> in their authoritative stores.

## Layout

| Area | Purpose |
|------|---------|
| [`catalog/`](catalog/) | Normalized atomic Rule instances used by deterministic evaluation. |
| [`action-types/`](action-types/) | Upstream ActionType declarations and their safety envelopes. |
| [`action-types-custom/`](action-types-custom/) and [`action-types-overrides/`](action-types-overrides/) | Fork-only additions and narrowing overlays. |
| [`vocabulary/`](vocabulary/) | Canonical ObjectType, LinkType, resource, signal, property, purpose, and investigation vocabulary. |
| [`workflows/`](workflows/) | Versioned Workflow definitions compiled into Process instances. |
| [`best-practices/`](best-practices/) and [`rule-sets/`](rule-sets/) | Framework controls and version-pinned initiatives over atomic rules. |
| [`probes/`](probes/) and [`operational-insights/`](operational-insights/) | Read-only live-blast probes and deterministic insight recipes. |
| [`remediation/`](remediation/) | Provider-neutral remediation templates rendered by governed delivery paths. |
| [`prompts/`](prompts/) | Versioned prompt fragments, task packs, scenarios, and tool descriptors. |
| [`reports/`](reports/), [`operator-console/`](operator-console/), and [`views/`](views/) | Read-only report, console descriptor, and projection definitions. |
| [`chaos-scenarios/`](chaos-scenarios/) | Reviewed chaos and detection-validation scenario catalog with promotion evidence. |
| [`sources/`](sources/), [`collected/`](collected/), and [`compliance/`](compliance/) | Source registry, pinned collected material, and compliance mappings. |
| [`profiles/`](profiles/) and [`profiles-overrides/`](profiles-overrides/) | Named rule bundles and fork narrowing overlays. |
| [`schema/`](schema/) | Schemas owned directly by extension-kit and skill-bundle catalog surfaces. Other schemas remain with their owning contracts or catalog directories. |
| [`exemptions/`](exemptions/) | Time-bounded governed exceptions that never erase underlying findings. |

## Authoring and Validation

- Follow [`RULE_AUTHORING_GUIDE.md`](RULE_AUTHORING_GUIDE.md) for atomic rules and multi-evidence
  Best Practices.
- Treat ids, versions, references, and provenance hashes as stable governance contracts. A rename
  can require migration of rules, profiles, workflows, and persisted instances.
- Keep upstream data customer-agnostic. Deployment identifiers, endpoints, secrets, and observed
  values do not belong in this tree.
- Use the owning loader and focused tests documented in each subdirectory README. Catalog loading
  fails closed on schema, provenance, duplicate-id, and cross-reference errors.

See [Rule Catalog Collection](../docs/roadmap/rules-and-detection/rule-catalog-collection.md),
[Rule Governance](../docs/roadmap/rules-and-detection/rule-governance.md), and the
[FDAI Operating Ontology](../docs/roadmap/architecture/operating-ontology.md) for the full source,
promotion, semantic, and authority contracts.
