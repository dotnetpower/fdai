/**
 * Unicode sparkline for compact surfaces (Slack, Teams) where a full
 * multi-row ASCII chart would be too tall.
 */

const RAMP = "\u2581\u2582\u2583\u2584\u2585\u2586\u2587\u2588"; // one-row block ramp

export function sparkline(series: readonly number[]): string {
  const max = Math.max(1, ...series);
  return series
    .map((v) => RAMP[Math.min(RAMP.length - 1, Math.round((v / max) * (RAMP.length - 1)))]!)
    .join("");
}
