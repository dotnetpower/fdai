/**
 * Ontology graph shared data model - node / edge shapes returned by
 * `/ontology/graph`, the semantic cluster palette, and the small pure
 * helpers that classify a type name or format a cardinality.
 *
 * SRP: data + classification only. No Preact, SVG, or I/O.
 */

import type { ViewEntityLifecycle } from "../deck/context";

// ---------------------------------------------------------------------------
// Public API (surfaced through `ontology-graph.tsx` for import stability)
// ---------------------------------------------------------------------------

export interface OntologyNode {
  readonly name: string;
  readonly key: string;
  readonly property_count: number;
  readonly properties: readonly string[];
  readonly description: string | null;
  readonly lifecycle?: Omit<ViewEntityLifecycle, "entity_kind" | "entity_id"> | null;
}

export interface OntologyEdge {
  readonly name: string;
  readonly from_type: string;
  readonly to_type: string;
  readonly cardinality: string;
  readonly is_transitive: boolean;
  readonly is_causal: boolean;
  readonly temporal_order: boolean;
  readonly description: string | null;
}

// ---------------------------------------------------------------------------
// Semantic clustering + colour palette
// ---------------------------------------------------------------------------

export type Cluster = "sensor" | "brain" | "action" | "target" | "record" | "other";

export interface ClusterMeta {
  readonly id: Cluster;
  readonly label: string;
  readonly hex: string;
}

// Deep, saturated jewel tones - reads as "glass over anodized metal"
// rather than the washed-out pastels that made cards feel disabled.
export const CLUSTERS: Readonly<Record<Cluster, ClusterMeta>> = {
  sensor: { id: "sensor", label: "Sensors", hex: "#0e9bad" },
  brain: { id: "brain", label: "Knowledge", hex: "#3b82f6" },
  action: { id: "action", label: "Decisions", hex: "#e07b39" },
  target: { id: "target", label: "Targets", hex: "#16a34a" },
  record: { id: "record", label: "Records", hex: "#8b5cf6" },
  other: { id: "other", label: "Other", hex: "#64748b" },
};

export function clusterOf(name: string): Cluster {
  if (/^(Signal|SecurityEvent|Metric|Event)$/i.test(name)) return "sensor";
  if (/^(Rule|Agent|RuleCandidate|Conversation)$/i.test(name)) return "brain";
  if (/^(Finding|Action|HandoffEscalation|Issue|Verdict|Decision)$/i.test(name))
    return "action";
  if (/^(Resource|Cluster|Deployment|Service|Subscription)$/i.test(name))
    return "target";
  if (/^(ChangeSummary|AuditEntry|Report|Trace|Bitemporal|Snapshot)$/i.test(name))
    return "record";
  return "other";
}

export function shortCard(c: string): string {
  const s = c.toLowerCase();
  if (s.includes("many_to_many")) return "*..*";
  if (s.includes("one_to_many")) return "1..*";
  if (s.includes("many_to_one")) return "*..1";
  if (s.includes("one_to_one")) return "1..1";
  return c;
}
