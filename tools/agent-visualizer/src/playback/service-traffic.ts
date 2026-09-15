export const DEMO_STREAM_HZ = 24;
export const STREAM_TRAVEL_SECONDS = 0.45;
export type TransportKind = "model" | "stream" | "message";

export interface ServicePacket {
  readonly direction: "outbound" | "inbound";
  readonly progress: number;
}

/** Illustrative adapter traffic, never measured throughput, accepted delivery, or live model calls. */
export function servicePacketsAt(time: number, kind: TransportKind, offset = 0): ServicePacket[] {
  if (!Number.isFinite(time) || !Number.isFinite(offset) || offset < 0) {
    throw new Error("Service traffic requires finite time and a nonnegative offset.");
  }
  const elapsed = Math.max(0, time) + offset;
  const phase = elapsed % 8;
  const packets: ServicePacket[] = [];
  if (kind === "message") {
    if (phase < 0.9) packets.push({ direction: "outbound", progress: phase / 0.9 });
    return packets;
  }
  if (kind === "model" && phase < 0.65) packets.push({ direction: "outbound", progress: phase / 0.65 });
  const first = Math.max(0, Math.ceil((elapsed - STREAM_TRAVEL_SECONDS) * DEMO_STREAM_HZ));
  const last = Math.floor(elapsed * DEMO_STREAM_HZ);
  for (let slot = first; slot <= last; slot++) {
    const born = slot / DEMO_STREAM_HZ;
    const birthPhase = born % 8;
    if (kind === "model" ? birthPhase < 0.8 || birthPhase >= 5.8 : birthPhase >= 6.5) continue;
    packets.push({
      direction: kind === "model" ? "inbound" : "outbound",
      progress: (elapsed - born) / STREAM_TRAVEL_SECONDS,
    });
  }
  return packets;
}
