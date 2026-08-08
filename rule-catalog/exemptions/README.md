# Policy Exemptions

This directory is the catalog location for reviewed, time-bounded policy exemption artifacts. The
upstream distribution intentionally ships no active exemption.

## Safety Contract

- An exemption targets one rule assignment at resource-group-equivalent scope or narrower.
- It records justification, accountable owner, distinct approver, creation time, and expiry.
- It may suppress enforcement inside its exact scope, but it does not erase the underlying finding,
  stop shadow evaluation, or alter the rule declaration.
- Customer and deployment exemptions belong in governed deployment configuration or a downstream
  distribution, not the generic upstream catalog.

Validate exemption JSON with
[`exemption_cli.py`](../../services/core-control-plane/src/fdai/rule_catalog/schema/exemption_cli.py)
and the owning
[`exemption.schema.json`](../../services/core-control-plane/src/fdai/rule_catalog/schema/exemption.schema.json).
See the [Exemption Workflow](../../docs/runbooks/exemption-workflow.md) for lifecycle guidance.
