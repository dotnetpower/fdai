/**
 * RichContent - renders a deck answer as a sequence of segments instead of
 * flat text: prose, markdown tables, and inline bar charts with hover
 * tooltips. This gives the narrator's reply expressive variety (a comparison
 * table, a numeric breakdown chart) while staying honest - every table cell
 * and every bar value is text the backend actually returned, grounded in the
 * screen snapshot. Nothing here fetches or fabricates data.
 *
 * The narrator opts into a table (standard markdown) or a chart (a single
 * ```chart fenced JSON block) when it aids the answer; otherwise the whole
 * reply is plain prose. Parsing is defensive: a malformed chart block falls
 * back to being shown as text, never throws.
 *
 * Single responsibility: turn one answer string into rendered segments. No
 * I/O, no privileged calls; the only state is per-chart hover.
 */

import { useState } from "preact/hooks";
import hljs from "highlight.js/lib/core";
import bash from "highlight.js/lib/languages/bash";
import dockerfile from "highlight.js/lib/languages/dockerfile";
import ini from "highlight.js/lib/languages/ini";
import json from "highlight.js/lib/languages/json";
import python from "highlight.js/lib/languages/python";
import sql from "highlight.js/lib/languages/sql";
import typescript from "highlight.js/lib/languages/typescript";
import xml from "highlight.js/lib/languages/xml";
import yaml from "highlight.js/lib/languages/yaml";

// Register the languages that plausibly appear in FDAI answers (config, IaC,
// policy, glue). Unregistered languages fall back to auto-detect, then plain.
hljs.registerLanguage("json", json);
hljs.registerLanguage("yaml", yaml);
hljs.registerLanguage("yml", yaml);
hljs.registerLanguage("bash", bash);
hljs.registerLanguage("sh", bash);
hljs.registerLanguage("shell", bash);
hljs.registerLanguage("python", python);
hljs.registerLanguage("py", python);
hljs.registerLanguage("typescript", typescript);
hljs.registerLanguage("ts", typescript);
hljs.registerLanguage("sql", sql);
hljs.registerLanguage("ini", ini);
hljs.registerLanguage("toml", ini);
hljs.registerLanguage("dockerfile", dockerfile);
hljs.registerLanguage("xml", xml);
hljs.registerLanguage("html", xml);

export interface ChartDatum {
  readonly label: string;
  readonly value: number;
}

export interface ChartSpec {
  readonly type: "bar";
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
  if (o.type !== "bar" || !Array.isArray(o.data)) return null;
  const data: ChartDatum[] = [];
  for (const d of o.data) {
    if (d && typeof d === "object") {
      const r = d as Record<string, unknown>;
      if (typeof r.label === "string" && typeof r.value === "number" && Number.isFinite(r.value)) {
        data.push({ label: r.label, value: r.value });
      }
    }
  }
  if (data.length === 0) return null;
  return {
    type: "bar",
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
      if (lang === "chart") {
        const spec = parseChart(raw);
        if (spec) {
          flushText();
          segments.push({ kind: "chart", spec });
        } else {
          buffer.push("```chart", ...body, "```");
        }
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

function TextBlock({ text }: { readonly text: string }) {
  return (
    <>
      {text.split("\n").map((line, i) => (
        <p key={i} class="deck-turn-line">
          {line}
        </p>
      ))}
    </>
  );
}

function TableBlock({
  headers,
  rows,
}: {
  readonly headers: readonly string[];
  readonly rows: readonly string[][];
}) {
  return (
    <div class="deck-table-wrap">
      <table class="deck-table">
        <thead>
          <tr>
            {headers.map((h, i) => (
              <th key={i}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, r) => (
            <tr key={r}>
              {headers.map((_, c) => (
                <td key={c}>{row[c] ?? ""}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function highlightCode(code: string, lang: string): string {
  if (lang && hljs.getLanguage(lang)) {
    try {
      return hljs.highlight(code, { language: lang }).value;
    } catch {
      /* fall through to auto-detect */
    }
  }
  try {
    return hljs.highlightAuto(code).value;
  } catch {
    return code.replace(/[&<>]/g, (c) => (c === "&" ? "&amp;" : c === "<" ? "&lt;" : "&gt;"));
  }
}

function CodeBlock({ lang, code }: { readonly lang: string; readonly code: string }) {
  const [copied, setCopied] = useState(false);
  const html = highlightCode(code, lang);
  const copy = () => {
    void navigator.clipboard?.writeText(code).then(
      () => {
        setCopied(true);
        window.setTimeout(() => setCopied(false), 1200);
      },
      () => {
        /* clipboard blocked - ignore */
      },
    );
  };
  return (
    <figure class="deck-code">
      <figcaption class="deck-code-head">
        <span class="deck-code-lang">{lang || "code"}</span>
        <button type="button" class="deck-code-copy" onClick={copy}>
          {copied ? "copied" : "copy"}
        </button>
      </figcaption>
      <pre class="deck-code-pre">
        {/* hljs escapes the input; its output HTML is safe to inject. */}
        <code class="hljs" dangerouslySetInnerHTML={{ __html: html }} />
      </pre>
    </figure>
  );
}

function MiniChart({ spec }: { readonly spec: ChartSpec }) {
  const [hover, setHover] = useState<number | null>(null);
  const max = Math.max(...spec.data.map((d) => Math.abs(d.value)), 1);
  // A word unit ("rules") reads better with a space; a symbol unit ("%", "$")
  // stays attached to the number.
  const unit = spec.unit ?? "";
  const sep = /^[A-Za-z]/.test(unit) ? " " : "";
  const fmt = (d: ChartDatum) => `${d.value}${sep}${unit}`;
  return (
    <figure class="deck-chart">
      {spec.title ? <figcaption class="deck-chart-title">{spec.title}</figcaption> : null}
      <div class="deck-chart-bars">
        {spec.data.map((d, i) => {
          const pct = Math.max(2, Math.round((Math.abs(d.value) / max) * 100));
          return (
            <div
              key={i}
              class={`deck-chart-row${hover === i ? " is-hover" : ""}`}
              onMouseEnter={() => setHover(i)}
              onMouseLeave={() => setHover((h) => (h === i ? null : h))}
              title={`${d.label}: ${fmt(d)}`}
            >
              <span class="deck-chart-label" title={d.label}>
                {d.label}
              </span>
              <span class="deck-chart-track">
                <span class="deck-chart-fill" style={{ width: `${pct}%` }} />
              </span>
              <span class="deck-chart-val">{fmt(d)}</span>
              {hover === i ? (
                <span class="deck-chart-tip" role="tooltip">
                  {d.label}: {fmt(d)}
                </span>
              ) : null}
            </div>
          );
        })}
      </div>
    </figure>
  );
}

/** Render an answer string as prose + tables + charts. */
export function RichContent({ text }: { readonly text: string }) {
  const segments = parseAnswer(text);
  if (segments.length === 0) return null;
  return (
    <div class="deck-rich">
      {segments.map((seg, i) => {
        if (seg.kind === "text") return <TextBlock key={i} text={seg.text} />;
        if (seg.kind === "table") {
          return <TableBlock key={i} headers={seg.headers} rows={seg.rows} />;
        }
        if (seg.kind === "code") return <CodeBlock key={i} lang={seg.lang} code={seg.code} />;
        return <MiniChart key={i} spec={seg.spec} />;
      })}
    </div>
  );
}
