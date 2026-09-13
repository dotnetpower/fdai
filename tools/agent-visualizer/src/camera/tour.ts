export type Point3 = readonly [number, number, number];
export type TourShot = "overview" | "broadcast" | "function" | "azure";

export interface TourSubjects {
  readonly bus: Point3;
  readonly source: Point3;
  readonly azure: Point3;
}

const SHOTS: readonly TourShot[] = ["overview", "broadcast", "function", "azure"];

function smooth(value: number) {
  const t = Math.max(0, Math.min(1, value));
  return t * t * t * (t * (t * 6 - 15) + 10);
}

function mix(a: Point3, b: Point3, amount: number): Point3 {
  return [a[0] + (b[0] - a[0]) * amount, a[1] + (b[1] - a[1]) * amount, a[2] + (b[2] - a[2]) * amount];
}

/** Two closed camera tours per scenario. Pose depends only on time, not frame history. */
export function sampleTour(time: number, duration: number, aspect: number, subjects: TourSubjects) {
  if (!Number.isFinite(time) || !Number.isFinite(duration) || duration <= 0 || !Number.isFinite(aspect) || aspect <= 0) {
    throw new Error("Tour requires finite time, a positive duration, and a positive aspect ratio.");
  }
  const progress = ((Math.max(0, time) / duration * 8) % 4);
  const index = Math.floor(progress);
  const phase = progress - index;
  const shot = SHOTS[index]!;
  const next = SHOTS[(index + 1) % SHOTS.length]!;
  const poses: Record<TourShot, { position: Point3; target: Point3 }> = {
    overview: { position: [5, 9, Math.max(67, 64 / aspect)], target: [0, 2, 0] },
    broadcast: { position: [15, 9, Math.max(51, 48 / aspect)], target: subjects.bus },
    function: {
      position: [subjects.source[0] + 9, subjects.source[1] + 5, subjects.source[2] + Math.max(24, 28 / aspect)],
      target: subjects.source,
    },
    azure: {
      position: [subjects.azure[0] + 10, subjects.azure[1] + 5, subjects.azure[2] + Math.max(32, 35 / aspect)],
      target: subjects.azure,
    },
  };
  const blend = smooth((phase - 0.45) / 0.55);
  return {
    shot: blend < 0.5 ? shot : next,
    position: mix(poses[shot].position, poses[next].position, blend),
    target: mix(poses[shot].target, poses[next].target, blend),
  };
}

/** The label follows the same normalized edit clock as the camera, including seeks and loops. */
export function tourShotAt(time: number, duration: number): TourShot {
  return sampleTour(time, duration, 1, { bus: [0, 0, 0], source: [0, 0, 0], azure: [0, 0, 0] }).shot;
}
