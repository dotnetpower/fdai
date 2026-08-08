# Governance Rule Sets

This directory contains versioned governance initiatives over atomic rules. Each RuleSet pins the
exact id and version of every member so a framework assessment can be replayed without resolving a
newer rule implicitly.

## Contract

- One YAML file declares one `kind: rule-set` artifact with a stable id and version.
- Member rules are version-pinned and unique within the set.
- Optional default effects remain bounded by the member Rule, ActionType, policy, and environment
  authority ceilings.
- A RuleSet groups controls; it does not evaluate evidence or execute remediation.

The governance loader in
[`governance_catalog.py`](../../services/core-control-plane/src/fdai/rule_catalog/schema/governance_catalog.py)
loads RuleSets before assignments and validates member references with
[`governance_loader.py`](../../services/core-control-plane/src/fdai/rule_catalog/schema/governance_loader.py).
