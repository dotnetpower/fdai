/**
 * Terminal bar-chart helper shared by the Ink and plain-text renderers.
 *
 * Turns a numeric series + sparse axis labels into aligned monospace rows.
 * Returns structure (gutter vs bars split) so a color renderer can dim the
 * axis and tint the bars; a plain renderer just concatenates them.
 */

export interface ChartRow {
  gutter: string;
  bars: string;
}

export interface AsciiChart {
  rows: ChartRow[];
  axis: string;
  labels: string;
}

const FULL = "\u2588"; // full block

export function asciiBarChart(
  series: readonly number[],
  axisLabels: ReadonlyArray<{ at: number; text: string }>,
  height = 6,
): AsciiChart {
  const cols = series.length;
  const max = Math.max(1, ...series);
  const heights = series.map((v) => Math.max(1, Math.round((v / max) * height)));

  const rows: ChartRow[] = [];
  for (let row = height; row >= 1; row--) {
    const gutter =
      row === height
        ? `${String(max).padStart(5)} \u2524` // top row shows the max, then a tick
        : row === 1
          ? `${"0".padStart(5)} \u2524`
          : `${" ".repeat(5)} \u2502`;
    let bars = "";
    for (let c = 0; c < cols; c++) bars += heights[c] >= row ? FULL : " ";
    rows.push({ gutter, bars });
  }

  const axis = `${" ".repeat(6)}\u2514${"\u2500".repeat(cols)}`;

  const labelChars = Array<string>(cols).fill(" ");
  for (const { at, text } of axisLabels) {
    for (let i = 0; i < text.length; i++) {
      if (at + i < cols) labelChars[at + i] = text[i]!;
    }
  }
  const labels = `${" ".repeat(7)}${labelChars.join("")}`;

  return { rows, axis, labels };
}
