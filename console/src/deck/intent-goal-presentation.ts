export type IntentGoalInstruction =
  | "aggregate"
  | "compareMetrics"
  | "compareTopology"
  | "combineEvidence"
  | "inspectEvidence"
  | "inspectMetrics"
  | "inspectRelationships"
  | "inspectTargets"
  | "inspectTopology"
  | "shapeResults"
  | "verifyCapability";

const INSTRUCTION_BY_INTENT: Readonly<Record<string, IntentGoalInstruction>> = {
  aggregate: "aggregate",
  evidence_join: "combineEvidence",
  function: "verifyCapability",
  intersection: "shapeResults",
  metric_comparison: "compareMetrics",
  metric_scope_series: "inspectMetrics",
  metric_series: "inspectMetrics",
  object_set: "inspectTargets",
  order: "shapeResults",
  project: "shapeResults",
  relationship_traversal: "inspectRelationships",
  subtraction: "shapeResults",
  topology_at: "inspectTopology",
  topology_diff: "compareTopology",
  union: "shapeResults",
};

/** Map a verified query-node intent to a bounded operator-facing instruction. */
export function intentGoalInstruction(intent: string): IntentGoalInstruction {
  return INSTRUCTION_BY_INTENT[intent] ?? "inspectEvidence";
}
