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
import { parseAnswer, parseInline, type ChartDatum, type ChartSpec } from "./rich-parse";

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

function TextBlock({ text }: { readonly text: string }) {
  return (
    <>
      {text.split("\n").map((line, i) => (
        <p key={i} class="deck-turn-line">
          {parseInline(line).map((run, j) =>
            run.t === "code" ? (
              <code key={j} class="deck-inline-code">
                {run.s}
              </code>
            ) : run.t === "strong" ? (
              <strong key={j}>{run.s}</strong>
            ) : (
              <span key={j}>{run.s}</span>
            ),
          )}
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
