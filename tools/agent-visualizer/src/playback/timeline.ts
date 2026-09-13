import type { Activity, AgentId, Scenario } from "../model";

export const DEFAULT_PLAYBACK_SPEED = 1;

/** Scenario speed never multiplies the independent 3 req/s visual transport budget. */
export function advancePlayback(time: number, transportTime: number, delta: number, speed: number, duration: number, loop: boolean) {
  const elapsed = loop ? Math.max(0, delta) : Math.min(Math.max(0, delta), Math.max(0, duration - time) / speed);
  return { time: advanceTime(time, elapsed, speed, duration, loop), transportTime: transportTime + elapsed };
}

/** Pure time projection makes pausing, scrubbing, reverse seeks, and loops reproducible. */
export function projectTimeline(scenario: Scenario, time: number) {
  const at = Math.max(0, Math.min(scenario.duration, time));
  const occurred = scenario.events.filter((event) => event.at <= at);
  const active = occurred.filter((event) => at < event.at + event.duration);
  const latest = occurred.at(-1) ?? null;
  return { at, occurred, active, latest };
}

export function activityEnergy(events: readonly Activity[], time: number, agent: AgentId): number {
  return Math.min(1, events.reduce((energy, event) => {
    if (event.agent !== agent || time < event.at) return energy;
    const elapsed = time - event.at;
    if (elapsed > event.duration + 4) return energy;
    const attack = Math.min(1, elapsed / 0.6);
    const release = Math.exp(-Math.max(0, elapsed - event.duration * 0.45) / 2);
    return energy + attack * release;
  }, 0));
}

export function advanceTime(time: number, delta: number, speed: number, duration: number, loop: boolean) {
  const next = time + Math.max(0, delta) * speed;
  return loop ? next % duration : Math.min(duration, next);
}

export function formatTime(time: number): string {
  const seconds = Math.floor(Math.max(0, time));
  return `${Math.floor(seconds / 60).toString().padStart(2, "0")}:${(seconds % 60).toString().padStart(2, "0")}`;
}
