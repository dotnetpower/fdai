/**
 * rich-parse - pure parser that splits a deck answer string into renderable
 * segments (prose, markdown table, fenced code, or a ```chart JSON block).
 *
 * Kept dependency-free (no preact, no highlight.js) so it is trivially
 * unit-testable and the rendering module (`rich-content.tsx`) imports the
 * types and `parseAnswer` from here. Parsing is defensive: a malformed chart
 * block degrades to text, never throws.
 */

import {
  parseAgentActivityBlock,
  type AgentActivityItem,
} from "./agent-activity-block";

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

export interface ListItem {
  readonly text: string;
  readonly checked?: boolean;
}

export type Segment =
  | { readonly kind: "text"; readonly text: string }
  | {
      readonly kind: "agent-activity";
      readonly locale: "en" | "ko";
      readonly items: readonly AgentActivityItem[];
    }
  | { readonly kind: "heading"; readonly level: number; readonly text: string }
  | { readonly kind: "list"; readonly ordered: boolean; readonly items: readonly ListItem[] }
  | { readonly kind: "quote"; readonly text: string }
  | { readonly kind: "divider" }
  | { readonly kind: "table"; readonly headers: readonly string[]; readonly rows: readonly string[][] }
  | { readonly kind: "code"; readonly lang: string; readonly code: string; readonly pending: boolean }
  | { readonly kind: "chart"; readonly spec: ChartSpec }
  | { readonly kind: "chart-pending" };

const TABLE_ROW = /^\s*\|(.+)\|\s*$/;
// A markdown header/body separator: pipes plus dashes (and optional colons).
const TABLE_SEP = /^\s*\|?[\s:|-]*-{2,}[\s:|-]*\|?\s*$/;
// Any fenced block open, capturing the info string (language / "chart").
const FENCE_OPEN = /^\s*```([\w+#.-]*)\s*$/;
const FENCE_CLOSE = /^\s*```\s*$/;
const HEADING = /^\s*(#{1,6})\s+(.+?)\s*#*\s*$/;
const UNORDERED_ITEM = /^\s*[-+*]\s+(.+)$/;
const ORDERED_ITEM = /^\s*\d+[.)]\s+(.+)$/;
const CHECK_ITEM = /^\[([ xX])\]\s+(.+)$/;
const QUOTE = /^\s*>\s?(.*)$/;
const THEMATIC_BREAK = /^\s{0,3}(?:(?:\*\s*){3,}|(?:-\s*){3,}|(?:_\s*){3,})$/;
// A safe CSS hex color (#rgb or #rrggbb); anything else is rejected to keep
// untrusted chart JSON from injecting arbitrary style values.
const SAFE_HEX = /^#(?:[0-9a-f]{3}|[0-9a-f]{6})$/i;

function splitCells(line: string): string[] {
  const m = line.match(TABLE_ROW);
  const inner = m?.[1] ?? line;
  return inner.split("|").map((c) => c.trim());
}

function parseChartValue(parsed: unknown, strict: boolean): ChartSpec | null {
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) return null;
  const o = parsed as Record<string, unknown>;
  if ((o.type !== "bar" && o.type !== "line") || !Array.isArray(o.data)) return null;
  if (o.data.length === 0 || o.data.length > 100) return null;
  if (o.title !== undefined && (typeof o.title !== "string" || o.title.length > 256)) return null;
  if (o.unit !== undefined && (typeof o.unit !== "string" || o.unit.length > 32)) return null;
  const data: ChartDatum[] = [];
  for (const datum of o.data) {
    if (!datum || typeof datum !== "object" || Array.isArray(datum)) {
      if (strict) return null;
      continue;
    }
    const row = datum as Record<string, unknown>;
    const valid = typeof row.label === "string" &&
      row.label.length > 0 && row.label.length <= 128 &&
      typeof row.value === "number" && Number.isFinite(row.value);
    if (!valid) {
      if (strict) return null;
      continue;
    }
    if (strict && Object.keys(row).some((key) => !["label", "value", "color"].includes(key))) {
      return null;
    }
    const color = typeof row.color === "string" && SAFE_HEX.test(row.color)
      ? row.color
      : undefined;
    if (strict && row.color !== undefined && color === undefined) return null;
    data.push({
      label: row.label as string,
      value: row.value as number,
      ...(color ? { color } : {}),
    });
  }
  if (data.length === 0) return null;
  return {
    type: o.type,
    data,
    ...(typeof o.title === "string" ? { title: o.title } : {}),
    ...(typeof o.unit === "string" ? { unit: o.unit } : {}),
  };
}

function parseChart(raw: string): ChartSpec | null {
  try {
    return parseChartValue(JSON.parse(raw), false);
  } catch {
    return null;
  }
}

export function chartArtifactText(raw: unknown): string | null {
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) return null;
  const artifact = raw as Record<string, unknown>;
  const expected = ["schema_version", "type", "title", "unit", "data", "evidence_refs"];
  if (Object.keys(artifact).some((key) => !expected.includes(key))) return null;
  if (artifact.schema_version !== 1 || !Array.isArray(artifact.evidence_refs)) return null;
  if (
    artifact.evidence_refs.length === 0 ||
    artifact.evidence_refs.length > 8 ||
    !artifact.evidence_refs.every((ref) =>
      typeof ref === "string" && ref.startsWith("metering:") && ref.length <= 1024
    )
  ) return null;
  const spec = parseChartValue(artifact, true);
  return spec === null ? null : `\`\`\`chart\n${JSON.stringify(spec)}\n\`\`\``;
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

    const agentActivity = parseAgentActivityBlock(lines, i);
    if (agentActivity) {
      flushText();
      segments.push({
        kind: "agent-activity",
        locale: agentActivity.locale,
        items: agentActivity.items,
      });
      i = agentActivity.nextIndex - 1;
      continue;
    }

    const fence = line.match(FENCE_OPEN);
    if (fence) {
      const lang = (fence[1] ?? "").toLowerCase();
      const body: string[] = [];
      i += 1;
      while (i < lines.length && !FENCE_CLOSE.test(lines[i] ?? "")) {
        body.push(lines[i] ?? "");
        i += 1;
      }
      // `terminated` is false when the closing ``` has not arrived yet (a block
      // still streaming in).
      const terminated = i < lines.length;
      const raw = body.join("\n");
      const spec = parseChart(raw);
      // Render as a chart when the block holds a valid chart spec and the fence
      // is chart/json/none - the narrator sometimes wraps a chart spec in a
      // ```json fence instead of ```chart. A real ```<lang> code block (yaml,
      // bash, ...) or non-chart json stays a highlighted code block.
      const chartish = lang === "chart" || lang === "line" || lang === "json" || lang === "";
      if (spec && chartish) {
        flushText();
        segments.push({ kind: "chart", spec });
      } else if (!terminated && chartish && /"type"\s*:/.test(raw)) {
        // A chart spec is still streaming in - show a placeholder rather than
        // raw, half-arrived JSON.
        flushText();
        segments.push({ kind: "chart-pending" });
      } else if (lang === "chart") {
        // Declared a chart but the JSON was invalid - show it as text.
        buffer.push("```chart", ...body, "```");
      } else {
        flushText();
        segments.push({ kind: "code", lang, code: raw, pending: !terminated });
      }
      continue;
    }

    const heading = line.match(HEADING);
    if (heading) {
      flushText();
      segments.push({
        kind: "heading",
        level: heading[1]?.length ?? 1,
        text: heading[2] ?? "",
      });
      continue;
    }

    if (THEMATIC_BREAK.test(line)) {
      flushText();
      segments.push({ kind: "divider" });
      continue;
    }

    const unordered = line.match(UNORDERED_ITEM);
    const ordered = line.match(ORDERED_ITEM);
    if (unordered || ordered) {
      flushText();
      const isOrdered = ordered !== null;
      const pattern = isOrdered ? ORDERED_ITEM : UNORDERED_ITEM;
      const items: ListItem[] = [];
      while (i < lines.length) {
        const item = (lines[i] ?? "").match(pattern);
        if (!item) break;
        const raw = item[1] ?? "";
        const check = !isOrdered ? raw.match(CHECK_ITEM) : null;
        items.push(
          check
            ? { text: check[2] ?? "", checked: check[1]?.toLowerCase() === "x" }
            : { text: raw },
        );
        i += 1;
      }
      i -= 1;
      segments.push({ kind: "list", ordered: isOrdered, items });
      continue;
    }

    const quote = line.match(QUOTE);
    if (quote) {
      flushText();
      const quoted: string[] = [];
      while (i < lines.length) {
        const part = (lines[i] ?? "").match(QUOTE);
        if (!part) break;
        quoted.push(part[1] ?? "");
        i += 1;
      }
      i -= 1;
      segments.push({ kind: "quote", text: quoted.join("\n").trim() });
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

/** Parse only the stable prefix of a streaming answer. Completed table
 * structure renders immediately; an unfinished header, separator, or row stays
 * hidden until its closing pipe arrives. */
export function parseStreamingAnswer(text: string): Segment[] {
  const lines = text.split("\n");
  const lastIndex = lines.length - 1;
  const tail = lines[lastIndex] ?? "";
  const beforeTail = lines[lastIndex - 1] ?? "";
  const tableStarted = hasTableStart(lines.slice(0, lastIndex));
  const headerCellCount = streamingTableHeaderCellCount(lines.slice(0, lastIndex));
  const tableStartsAtTail = TABLE_ROW.test(beforeTail) &&
    TABLE_ROW.test(tail) && TABLE_SEP.test(tail) &&
    splitCells(beforeTail).length === splitCells(tail).length;

  if (!tableStartsAtTail && tail.trimStart().startsWith("|") && !TABLE_ROW.test(tail)) {
    lines.pop();
    if (!tableStarted && TABLE_ROW.test(beforeTail)) lines.pop();
  } else if (!tableStartsAtTail && TABLE_ROW.test(tail) && !tableStarted) {
    lines.pop();
  } else if (tableStarted && TABLE_ROW.test(tail) &&
      headerCellCount !== null && splitCells(tail).length !== headerCellCount) {
    lines.pop();
  }
  return parseAnswer(lines.join("\n"));
}

function streamingTableHeaderCellCount(lines: readonly string[]): number | null {
  for (let index = lines.length - 2; index >= 0; index -= 1) {
    const header = lines[index] ?? "";
    const separator = lines[index + 1] ?? "";
    if (TABLE_ROW.test(header) && TABLE_SEP.test(separator)) {
      return splitCells(header).length;
    }
  }
  return null;
}

function hasTableStart(lines: readonly string[]): boolean {
  return lines.some((line, index) =>
    TABLE_ROW.test(line) && TABLE_SEP.test(lines[index + 1] ?? ""),
  );
}

/** One inline run within a prose line. The `cite` variant is never produced by
 *  `parseInline`; it is injected afterwards by `injectCiteMarks` to render a
 *  numbered `[n]` grounding chip after a cited value. */
export type InlineRun =
  | { readonly t: "text" | "code" | "strong" | "emphasis" | "strike"; readonly s: string }
  | { readonly t: "link"; readonly s: string; readonly href: string }
  | { readonly t: "cite"; readonly n: number; readonly title: string };

/** One inline citation anchor: place a `[n]` chip after the first occurrence
 *  of `value` in the answer text. Mirrors `CiteMark` in grounded-sources.ts
 *  (kept local so rich-parse stays dependency-free). */
export interface InlineCiteMark {
  readonly n: number;
  readonly value: string;
  readonly title: string;
}

/**
 * Weave numbered `[n]` citation chips into already-parsed inline runs. Only
 * plain `text` runs are scanned (never inside code / links), each mark is
 * placed at most once at its first occurrence, and the surrounding text is
 * preserved verbatim. Pure; returns the input unchanged when no mark matches.
 */
export function injectCiteMarks(
  runs: readonly InlineRun[],
  marks: readonly InlineCiteMark[],
): InlineRun[] {
  if (marks.length === 0) return [...runs];
  const placed = new Set<number>();
  const out: InlineRun[] = [];
  for (const run of runs) {
    if (run.t !== "text") {
      out.push(run);
      continue;
    }
    let rest = run.s;
    let guard = 0;
    while (guard++ < 64) {
      let bestIdx = -1;
      let bestEnd = -1;
      let best: InlineCiteMark | null = null;
      for (const mark of marks) {
        if (placed.has(mark.n)) continue;
        const idx = rest.indexOf(mark.value);
        if (idx < 0) continue;
        if (best === null || idx < bestIdx) {
          bestIdx = idx;
          bestEnd = idx + mark.value.length;
          best = mark;
        }
      }
      if (best === null) break;
      out.push({ t: "text", s: rest.slice(0, bestEnd) });
      out.push({ t: "cite", n: best.n, title: best.title });
      placed.add(best.n);
      rest = rest.slice(bestEnd);
    }
    if (rest.length > 0) out.push({ t: "text", s: rest });
  }
  return out;
}

// Inline markdown: `code`, **strong**, or [label](safe-url). Non-greedy, no nesting.
const INLINE = /(`[^`]+`|\*\*[^*]+\*\*|~~[^~]+~~|\[[^\]]+\]\((?:[^()]|\([^()]*\))*\)|\*[^*]+\*|_[^_]+_)/g;
const LINK = /^\[([^\]]+)\]\(((?:[^()]|\([^()]*\))*)\)$/;

function safeHref(raw: string): string | null {
  const href = raw.trim();
  if (href.startsWith("/") || href.startsWith("#")) return href;
  try {
    const parsed = new URL(href);
    return parsed.protocol === "https:" || parsed.protocol === "http:" ? href : null;
  } catch {
    return null;
  }
}

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
    } else if (tok.startsWith("**")) {
      runs.push({ t: "strong", s: tok.slice(2, -2) });
    } else if (tok.startsWith("~~")) {
      runs.push({ t: "strike", s: tok.slice(2, -2) });
    } else if (tok.startsWith("*") || tok.startsWith("_")) {
      runs.push({ t: "emphasis", s: tok.slice(1, -1) });
    } else {
      const link = tok.match(LINK);
      const href = safeHref(link?.[2] ?? "");
      runs.push(
        link && href
          ? { t: "link", s: link[1] ?? href, href }
          : { t: "text", s: tok },
      );
    }
    last = idx + tok.length;
  }
  if (last < line.length) runs.push({ t: "text", s: line.slice(last) });
  if (runs.length === 0) runs.push({ t: "text", s: line });
  return runs;
}
