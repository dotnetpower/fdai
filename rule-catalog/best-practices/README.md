# Best Practices

This directory contains framework-level controls that group several typed evidence requirements
into one reviewable Best Practice. A Best Practice references atomic rules, probes, metrics,
drills, documents, and approvals; it does not replace those authoritative artifacts.

## Contract

- One YAML file declares one stable control id and version.
- Requirements use typed evidence references and resolve against the loaded rule and evidence
  catalogs.
- A Best Practice is reference and assessment data. It does not execute remediation or promote a
  rule.
- Upstream entries remain customer-agnostic. Deployment-specific scope and evidence stay outside
  this directory.

The loader in
[`best_practice_catalog.py`](../../services/core-control-plane/src/fdai/rule_catalog/schema/best_practice_catalog.py)
validates schema, duplicate ids, provenance, and cross-references. Follow
[`../RULE_AUTHORING_GUIDE.md`](../RULE_AUTHORING_GUIDE.md) when adding or revising a control.
