// action-ontology.ts - curated, English-only dataset backing the
// ActionOntologyExplorer component.
//
// SOURCE OF TRUTH: this is a *curated showcase* of the shipped
// ActionType catalog, not a live load of it. Every field value below is
// copied from the real YAML under rule-catalog/action-types/*.yaml and
// the schema in docs/roadmap/decisioning/action-ontology.md, so the explorer stays
// accurate without coupling the docs-site build to the catalog (a
// mid-edit malformed YAML must never break the site). When the catalog
// changes materially, refresh this file.
//
// Scope: the shipped catalog is entirely `remediation` (rule-fired,
// PR-native, shadow-first). The ontology also spans `ops` and
// `governance` categories in the spec; those are noted in the UI and
// linked to action-ontology.md rather than invented here.

export type RollbackContract =
  | "pr_revert"
  | "scripted"
  | "pitr"
  | "snapshot_restore"
  | "state_forward_only";

export type BlastKind = "static" | "graph";

export interface ActionType {
  /** Ontology id (snake+dot), the audit key. */
  name: string;
  /** Short display name (id without the category prefix). */
  short: string;
  category: "remediation" | "ops" | "governance";
  /** operation enum from the schema (tag | disable | delete | ...). */
  operation: string;
  triggerKind: "rule_violation" | "operator_request" | "both";
  executionPath: "pr_native" | "direct_api" | "pr_manual";
  rollbackContract: RollbackContract;
  irreversible: boolean;
  defaultMode: "shadow" | "enforce";
  blastKind: BlastKind;
  /** Human-readable blast radius. */
  blast: string;
  /** Real English catalog description. */
  description: string;
}

/** Accent colour + label per rollback contract, used by the facet
 *  filter and the node dots. Kept here so the component and the legend
 *  stay in sync. */
export const ROLLBACK_META: Record<
  RollbackContract,
  { label: string; color: string }
> = {
  pr_revert: { label: "pr_revert", color: "#2EA043" },
  state_forward_only: { label: "state_forward_only", color: "#D08600" },
  snapshot_restore: { label: "snapshot_restore", color: "#0078D4" },
  pitr: { label: "pitr", color: "#17A9C9" },
  scripted: { label: "scripted", color: "#8B5CF6" },
};

export const ACTION_TYPES: ActionType[] = [
  {
    name: "remediate.tag-add",
    short: "tag-add",
    category: "remediation",
    operation: "tag",
    triggerKind: "rule_violation",
    executionPath: "pr_native",
    rollbackContract: "pr_revert",
    irreversible: false,
    defaultMode: "shadow",
    blastKind: "static",
    blast: "1 resource",
    description:
      "Attach required tags (owner, cost-center, environment) when they are missing. Control-plane only; safe idempotent rewrite; PR-native rollback undoes the tag mutation.",
  },
  {
    name: "remediate.disable-public-access",
    short: "disable-public-access",
    category: "remediation",
    operation: "disable",
    triggerKind: "rule_violation",
    executionPath: "pr_native",
    rollbackContract: "state_forward_only",
    irreversible: false,
    defaultMode: "shadow",
    blastKind: "graph",
    blast: "<= 5 resources (graph-derived)",
    description:
      "Turn off unauthenticated public access on a resource without deleting it. Reverses via a paired enable-public-access action registered through governance - no destructive undo.",
  },
  {
    name: "remediate.rotate-secret",
    short: "rotate-secret",
    category: "remediation",
    operation: "rotate",
    triggerKind: "rule_violation",
    executionPath: "pr_native",
    rollbackContract: "snapshot_restore",
    irreversible: false,
    defaultMode: "shadow",
    blastKind: "graph",
    blast: "<= 20 resources (graph-derived)",
    description:
      "Rotate a secret / certificate held in a secret-store. Cross-resource because every depends_on consumer must pick up the new version; the executor coordinates locks per consumer. Rollback pins the prior version.",
  },
  {
    name: "remediate.remove-orphan-resource",
    short: "remove-orphan-resource",
    category: "remediation",
    operation: "delete",
    triggerKind: "rule_violation",
    executionPath: "pr_native",
    rollbackContract: "pitr",
    irreversible: false,
    defaultMode: "shadow",
    blastKind: "static",
    blast: "1 resource",
    description:
      "Delete a resource proven orphaned (unattached disk, unassociated public IP). Fires only when attached_to and depends_on are both absent. Rollback uses the provider PITR / soft-delete window; if it has expired the safety check requires human approval.",
  },
  {
    name: "remediate.enable-purge-protection",
    short: "enable-purge-protection",
    category: "remediation",
    operation: "enable",
    triggerKind: "rule_violation",
    executionPath: "pr_native",
    rollbackContract: "state_forward_only",
    irreversible: true,
    defaultMode: "shadow",
    blastKind: "static",
    blast: "1 resource",
    description:
      "Turn on purge protection on a secret-store. Irreversible: once on, the provider does not allow turning it off. The safety check requires human approval and quorum until the promotion gate is measured on the frozen scenario set.",
  },
  {
    name: "remediate.right-size",
    short: "right-size",
    category: "remediation",
    operation: "scale",
    triggerKind: "rule_violation",
    executionPath: "pr_native",
    rollbackContract: "pr_revert",
    irreversible: false,
    defaultMode: "shadow",
    blastKind: "graph",
    blast: "<= 10 resources (graph-derived)",
    description:
      "Adjust compute count or SKU to match observed utilization (Cost Governance). Non-destructive; rollback is a PR to the prior spec. Runs after observation mode only after the scenario set proves it never degrades a dependent.",
  },
  {
    name: "remediate.restrict-network-access",
    short: "restrict-network-access",
    category: "remediation",
    operation: "update",
    triggerKind: "rule_violation",
    executionPath: "pr_native",
    rollbackContract: "state_forward_only",
    irreversible: false,
    defaultMode: "shadow",
    blastKind: "graph",
    blast: "<= 15 resources (graph-derived)",
    description:
      "Tighten network access - remove wide inbound NSG rules (SSH/RDP from any), require a private endpoint, disable public network access. Asymmetric rollback: widening back to any-source is a separate governance-gated action.",
  },
  {
    name: "remediate.enable-encryption",
    short: "enable-encryption",
    category: "remediation",
    operation: "enable",
    triggerKind: "rule_violation",
    executionPath: "pr_native",
    rollbackContract: "state_forward_only",
    irreversible: false,
    defaultMode: "shadow",
    blastKind: "static",
    blast: "1 resource",
    description:
      "Turn on data-at-rest / in-transit encryption on a resource. Forward-only: once encryption is enabled, disabling it is a separate governance-gated ActionType - this one never turns it off.",
  },
  {
    name: "remediate.set-tls-policy",
    short: "set-tls-policy",
    category: "remediation",
    operation: "update",
    triggerKind: "rule_violation",
    executionPath: "pr_native",
    rollbackContract: "pr_revert",
    irreversible: false,
    defaultMode: "shadow",
    blastKind: "static",
    blast: "1 resource",
    description:
      "Raise the TLS floor on a resource (min TLS version, HTTPS-only) by updating the IaC-declared property. Rollback via PR revert since the setting is a declarative property.",
  },
];
