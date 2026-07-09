/**
 * rich-parse - pure parser that splits a deck answer string into renderable
 * segments (prose, markdown table, fenced code, or a ```chart JSON block).
 *
 * Kept dependency-free (no preact, no highlight.js) so it is trivially
 * unit-testable and the rendering module (`rich-content.tsx`) imports the
 * types and `parseAnswer` from here. Parsing is defensive: a malformed chart
 * block degrades to text, never throws.
 */

export interface ChartDatum {
  readonly label: string;
  readonly value: number;
  /** Optional explicit bar color; only a safe hex value is accepted. */
  readonly color?: string;
}

export interface ChartSpec {
  readonly type: "bar" | "line";
  readonly title?: string;
  readonly unit?: string;
  readonly data: readonly ChartDatum[];
}

export type Segment =
  | { readonly kind: "text"; readonly text: string }
  | { readonly kind: "table"; readonly headers: readonly string[]; readonly rows: readonly string[][] }
  | { readonly kind: "code"; readonly lang: string; readonly code: string }
  | { readonly kind: "chart"; readonly spec: ChartSpec };

const TABLE_ROW = /^\s*\|(.+)\|\s*$/;
// A markdown header/body separator: pipes plus dashes (and optional colons).
const TABLE_SEP = /^\s*\|?[\s:|-]*-{2,}[\s:|-]*\|?\s*$/;
// Any fenced block open, capturing the info string (language / "chart").
const FENCE_OPEN = /^\s*```([\w+#.-]*)\s*$/;
const FENCE_CLOSE = /^\s*```\s*$/;
// A safe CSS hex color (#rgb or #rrggbb); anything else is rejected to keep
// untrusted chart JSON from injecting arbitrary style values.
const SAFE_HEX = /^#(?:[0-9a-f]{3}|[0-9a-f]{6})$/i;

function splitCells(line: string): string[] {
  const m = line.match(TABLE_ROW);
  const inner = m?.[1] ?? line;
  return inner.split("|").map((c) => c.trim());
}

function parseChart(raw: string): ChartSpec | null {
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return null;
  }
  if (typeof parsed !== "object" || parsed === null) return null;
  const o = parsed as Record<string, unknown>;
  if ((o.type !== "bar" && o.type !== "line") || !Array.isArray(o.data)) return null;
  const data: ChartDatum[] = [];
  for (const d of o.data) {
    if (d && typeof d === "object") {
      const r = d as Record<string, unknown>;
      if (typeof r.label === "string" && typeof r.value === "number" && Number.isFinite(r.value)) {
        const color = typeof r.color === "string" && SAFE_HEX.test(r.color) ? r.color : undefined;
        data.push({ label: r.label, value: r.value, ...(color ? { color } : {}) });
      }
    }
  }
  if (data.length === 0) return null;
  return {
    type: o.type,
    data,
    ...(typeof o.title === "string" ? { title: o.title } : {}),
    ...(typeof o.unit === "string" ? { unit: o.unit } : {}),
  };
}

/** Parse a raw answer into renderable segments. Pure and defensive. */
export function parseAnswer(text: string): Segment[] {
  const lines = text.split("\n");
  const segments: Segment[] = [];
  let buffer: string[] = [];

  const flushText = () => {
    if (buffer.join("").trim() !== "") {
      segments.push({ kind: "text", text: buffer.join("\n").trim() });
    }
    buffer = [];
  };

  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i] ?? "";

    const fence = line.match(FENCE_OPEN);
    if (fence) {
      const lang = (fence[1] ?? "").toLowerCase();
      const body: string[] = [];
      i += 1;
      while (i < lines.length && !FENCE_CLOSE.test(lines[i] ?? "")) {
        body.push(lines[i] ?? "");
        i += 1;
      }
      const raw = body.join("\n");
      const spec = parseChart(raw);
      // Render as a chart when the block holds a valid chart spec and the fence
      // is chart/json/none - the narrator sometimes wraps a chart spec in a
      // ```json fence instead of ```chart. A real ```<lang> code block (yaml,
      // bash, ...) or non-chart json stays a highlighted code block.
      const chartish = lang === "chart" || lang === "json" || lang === "";
      if (spec && chartish) {
        flushText();
        segments.push({ kind: "chart", spec });
      } else if (lang === "chart") {
        // Declared a chart but the JSON was invalid - show it as text.
        buffer.push("```chart", ...body, "```");
      } else {
        flushText();
        segments.push({ kind: "code", lang, code: raw });
      }
      continue;
    }

    if (TABLE_ROW.test(line) && i + 1 < lines.length && TABLE_SEP.test(lines[i + 1] ?? "")) {
      const headers = splitCells(line);
      i += 2; // consume header + separator
      const rows: string[][] = [];
      while (i < lines.length && TABLE_ROW.test(lines[i] ?? "")) {
        rows.push(splitCells(lines[i] ?? ""));
        i += 1;
      }
      i -= 1; // the for-loop will advance past the last consumed line
      flushText();
      segments.push({ kind: "table", headers, rows });
      continue;
    }

    buffer.push(line);
  }
  flushText();
  return segments;
}

/** One inline run within a prose line. */
export interface InlineRun {
  readonly t: "text" | "code" | "strong";
  readonly s: string;
}

// Inline markdown: `code` or **strong**. Non-greedy, no nesting.
const INLINE = /(`[^`]+`|\*\*[^*]+\*\*)/g;

/**
 * Split one prose line into inline runs (plain text, `code`, **strong**).
 * Pure; always returns at least one run so a line never renders empty.
 */
export function parseInline(line: string): InlineRun[] {
  const runs: InlineRun[] = [];
  let last = 0;
  for (const m of line.matchAll(INLINE)) {
    const idx = m.index ?? 0;
    if (idx > last) runs.push({ t: "text", s: line.slice(last, idx) });
    const tok = m[0];
    if (tok.startsWith("`")) {
      runs.push({ t: "code", s: tok.slice(1, -1) });
    } else {
      runs.push({ t: "strong", s: tok.slice(2, -2) });
    }
    last = idx + tok.length;
  }
  if (last < line.length) runs.push({ t: "text", s: line.slice(last) });
  if (runs.length === 0) runs.push({ t: "text", s: line });
  return runs;
}
