# Governance Overrides

This directory is the catalog location for reviewed governance override artifacts - the human
control surface above the automated quality gate. The upstream distribution intentionally ships
no active override.

## Safety Contract

- An override narrows, downgrades, or disables one rule (`target_rule`) at
  resource-group-equivalent scope or narrower. An organization- or account-wide `scope` is
  rejected - disabling a rule everywhere is a rule retirement, which goes through the catalog
  pipeline, not an override.
- Permitted modes: `disabled`, `severity-downgrade` (requires `severity_downgrade_to`), and
  `parameter-relaxation` (requires `parameter_overrides`). A `parameter-relaxation` override's
  keys and value bounds MUST also be allow-listed in the separately reviewed
  [`override-parameter-bounds.yaml`](../override-parameter-bounds.yaml); an unlisted key or an
  out-of-bound value fails the catalog load closed.
- `expires_at` is optional - unlike an exemption, an override MAY be permanent. When set, a past
  `expires_at` stops the override from applying (it does not silently outlive its own stated
  boundary).
- `requested_by` MUST differ from `approver` (no self-override).
- Overrides never stack: at most one per `(target_rule, scope)` pair. A second override on the
  same pair fails the catalog load; replace the existing file instead.
- An override never edits the target rule's text, never suppresses the audit record of the
  underlying finding, and never stops shadow evaluation - it only suppresses *execution* on the
  scope it covers. Removing the override file restores the rule automatically.
- Customer and deployment overrides belong in governed deployment configuration or a downstream
  distribution, not the generic upstream catalog.

Validate override YAML with
[`load_override_from_mapping`](../../services/core-control-plane/src/fdai/rule_catalog/schema/governance_loader.py)
and the owning
[`override.schema.json`](../../services/core-control-plane/src/fdai/rule_catalog/schema/override.schema.json).
See [Overrides](../../docs/roadmap/rules-and-detection/rule-governance.md#overrides) for the full
design and precedence rules.
