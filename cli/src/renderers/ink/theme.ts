/**
 * Ink palette: semantic `Tone` -> terminal hex. The only place the CLI surface
 * decides what a tone looks like. Aligned with the mock and the "Calm Slate"
 * kit (mocks/ui-cli, ../ui).
 */

import type { Tone } from "../../view-model/blocks.js";

const HEX: Record<Tone, string | undefined> = {
  neutral: undefined,
  dim: "#7C848B",
  t0: "#63A69C",
  t1: "#6E9BCB",
  t2: "#A896CE",
  low: "#7FB077",
  medium: "#D6925F",
  high: "#D07A7A",
  good: "#7FB077",
  warn: "#D6925F",
  danger: "#D07A7A",
  accent: "#63A69C",
};

export function toneHex(tone?: Tone): string | undefined {
  return tone ? HEX[tone] : undefined;
}
