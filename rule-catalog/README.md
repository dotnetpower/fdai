# `rule-catalog/`

Rule catalog (catalog-as-code) - normalized, versioned rules, Best Practices, and governance data.

Data-only YAML tree. Pipeline code lives in
[src/fdai/rule_catalog/](../src/fdai/rule_catalog/README.md).
Full design: [docs/roadmap/rules-and-detection/rule-catalog-collection.md](../docs/roadmap/rules-and-detection/rule-catalog-collection.md).

- [`RULE_AUTHORING_GUIDE.md`](RULE_AUTHORING_GUIDE.md) - canonical
  procedure to author a new rule or multi-evidence Best Practice.
- [`best-practices/`](best-practices/) - framework controls whose typed
  requirements resolve to rules, probes, evidence, metrics, drills, and
  accountable approvals.
- [`rule-sets/`](rule-sets/) - version-pinned governance initiatives for
  the atomic rules that implement framework controls.
- [`sources/registry.yaml`](sources/registry.yaml) - normative sources
  the seed catalog draws from and their license / redistribution posture.
