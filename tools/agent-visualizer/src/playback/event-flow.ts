import { codeGraph, isAgentId } from "../source-graph";
import type { AgentId, Scenario } from "../model";
import { projectTimeline } from "./timeline";
import { independentActivityAt } from "./workloads";

const schedules = [
  { id: "object.event", period: 7.1, offset: 0 },
  { id: "object.anomaly", period: 9.3, offset: 1.4 },
  { id: "object.verdict", period: 13.1, offset: 2.8 },
  { id: "object.action-run", period: 11.7, offset: 3.1 },
  { id: "object.audit-entry", period: 8.9, offset: 0.9 },
] as const;
export const broadcastTopics = schedules.map(({ id }) => {
  const topic = codeGraph.topics.find((candidate) => candidate.id === id);
  if (!topic || !isAgentId(topic.publisher)) throw new Error(`Missing canonical broadcast topic: ${id}`);
  return topic;
});
export const ARG_VISUAL_HZ = codeGraph.arg.requests_per_second;

/** Each publisher owns an independent demo clock; multiple topics can be in flight at once. */
export function eventFlowAt(time: number, scenario: Scenario) {
  const active = new Set<AgentId>(projectTimeline(scenario, time).active.map((event) => event.agent));
  const independent = independentActivityAt(time);
  independent.filter((work) => work.active).forEach((work) => active.add(work.agent));
  const broadcasts = schedules.flatMap((schedule, index) => {
    const age = (Math.max(0, time) + schedule.offset) % schedule.period;
    if (age >= 5.4) return [];
    const topic = broadcastTopics[index]!;
    const subscribers = topic.subscribers.filter(isAgentId);
    if (age < 1.8 && isAgentId(topic.publisher)) active.add(topic.publisher);
    if (age >= 0.7) subscribers.forEach((agent) => active.add(agent));
    return [{ topic, subscribers, age, phase: age < 0.7 ? "publishing" : age < 2 ? "broadcasting" : "processing" } as const];
  });
  return { broadcasts, independent, active };
}

/** Request slots use active display seconds, separately from the faster scenario clock. */
export function argSlotsBetween(start: number, end: number): number[] {
  const result: number[] = [];
  for (let slot = Math.ceil(start * ARG_VISUAL_HZ); slot < end * ARG_VISUAL_HZ; slot++) result.push(slot);
  return result;
}
