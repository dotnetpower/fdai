import { MathUtils } from "three";
import { BUS_FANOUT_DELAY, type eventFlowAt } from "./event-flow";

export const LAUNCH_LABEL_SECONDS = 1.8;
export const BUS_LAUNCH_LABEL = "event-launch:bus";

export interface LaunchAnnotation {
  readonly id: string;
  readonly origin: string;
  readonly text: string;
  readonly opacity: number;
}

/** Fade on the scenario clock, so pause and reverse seeks reproduce the same annotation. */
export function launchOpacity(age: number): number {
  if (!Number.isFinite(age)) throw new Error("Event annotation age must be finite.");
  if (age <= 0 || age >= LAUNCH_LABEL_SECONDS) return 0;
  return MathUtils.smoothstep(age, 0, 0.12) * (1 - MathUtils.smoothstep(age, 1, LAUNCH_LABEL_SECONDS));
}

/** Annotate actual illustrated departures, never independent function activity or direct agent RPC. */
export function eventLaunchAnnotations(flow: ReturnType<typeof eventFlowAt>, reduced: boolean): LaunchAnnotation[] {
  if (reduced) return [];
  const result: LaunchAnnotation[] = [];
  for (const broadcast of flow.broadcasts) {
    const opacity = launchOpacity(broadcast.age);
    if (opacity > 0) result.push({
      id: `event-launch:${broadcast.topic.id}`,
      origin: broadcast.topic.publisher,
      text: broadcast.topic.id,
      opacity,
    });
  }
  const bus = flow.broadcasts
    .filter((broadcast) => broadcast.subscribers.length && launchOpacity(broadcast.age - BUS_FANOUT_DELAY) > 0)
    .sort((a, b) => a.age - b.age || a.topic.id.localeCompare(b.topic.id));
  if (bus.length) {
    const topics = bus.slice(0, 2).map((broadcast) => broadcast.topic.id);
    if (bus.length > 2) topics.push(`+${bus.length - 2}`);
    result.push({
      id: BUS_LAUNCH_LABEL,
      origin: "EVENT BUS",
      text: topics.join("\n"),
      opacity: Math.max(...bus.map((broadcast) => launchOpacity(broadcast.age - BUS_FANOUT_DELAY))),
    });
  }
  return result;
}
