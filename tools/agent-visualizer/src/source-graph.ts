import snapshot from "./generated/code-graph.json";
import { agentById } from "./agents";
import type { AgentId } from "./model";
import type { ServiceId } from "./scene/service-layout";

export interface PythonFunction {
  readonly id: string;
  readonly name: string;
  readonly file: string;
  readonly line: number;
  readonly end_line: number;
  readonly async: boolean;
  readonly owners: readonly string[];
  readonly direct_owners: readonly string[];
  readonly service?: string;
  readonly unresolved: readonly { readonly symbol: string; readonly line: number }[];
}

/** Generated source definitions are separate from the synthetic activity clock. */
export const pythonFunctions: readonly PythonFunction[] = snapshot.functions;
export const codeGraph = { ...snapshot, functions: pythonFunctions };
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
  if (fn.service) return null;
  return fn.direct_owners.find(isAgentId) ?? fn.owners.find(isAgentId) ?? null;
}

/** Service grouping is visual context, never ownership of an agent or runtime authority. */
export function serviceFor(fn: PythonFunction): ServiceId | null {
  switch (fn.service) {
    case undefined: return null;
    case "azure-resource-graph": case "azure-openai": case "channels": return fn.service;
    default: throw new Error(`Unknown source service group: ${fn.service}`);
  }
}

export const sourceServices = codeGraph.services;

export function functionsFor(agent: AgentId | null, query = "") {
  const lower = query.toLowerCase().trim();
  return pythonFunctions.filter((fn) => (!agent || fn.owners.includes(agent))
    && (!lower || fn.id.toLowerCase().includes(lower)))
    .sort((a, b) => Number(b.direct_owners.includes(agent ?? "")) - Number(a.direct_owners.includes(agent ?? ""))
      || a.id.localeCompare(b.id));
}
