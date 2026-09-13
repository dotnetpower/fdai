import snapshot from "./generated/code-graph.json";
import { agentById } from "./agents";
import type { AgentId } from "./model";

export interface PythonFunction {
  readonly id: string;
  readonly name: string;
  readonly file: string;
  readonly line: number;
  readonly end_line: number;
  readonly async: boolean;
  readonly owners: readonly string[];
  readonly direct_owners: readonly string[];
  readonly unresolved: readonly { readonly symbol: string; readonly line: number }[];
}

/** Generated source definitions are separate from the synthetic activity clock. */
export const codeGraph = snapshot;
export const pythonFunctions: readonly PythonFunction[] = codeGraph.functions;
export const functionById = new Map(pythonFunctions.map((fn) => [fn.id, fn]));
export const callsFrom = new Map<string, Set<string>>();
export const callsTo = new Map<string, Set<string>>();
for (const call of codeGraph.calls) {
  if (!callsFrom.has(call.source)) callsFrom.set(call.source, new Set());
  if (!callsTo.has(call.target)) callsTo.set(call.target, new Set());
  callsFrom.get(call.source)!.add(call.target);
  callsTo.get(call.target)!.add(call.source);
}

export function isAgentId(id: string): id is AgentId {
  return agentById.has(id as AgentId);
}

export function homeAgent(fn: PythonFunction): AgentId | null {
  return fn.direct_owners.find(isAgentId) ?? fn.owners.find(isAgentId) ?? null;
}

export function functionsFor(agent: AgentId | null, query = "") {
  const lower = query.toLowerCase().trim();
  return pythonFunctions.filter((fn) => (!agent || fn.owners.includes(agent))
    && (!lower || fn.id.toLowerCase().includes(lower)))
    .sort((a, b) => Number(b.direct_owners.includes(agent ?? "")) - Number(a.direct_owners.includes(agent ?? ""))
      || a.id.localeCompare(b.id));
}
