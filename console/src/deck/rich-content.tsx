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
import { useTransientFlag } from "../hooks/use-transient-flag";
import { t } from "../i18n";
import {
  parseAnswer,
  parseInline,
  type ChartDatum,
  type ChartSpec,
  type ListItem,
} from "./rich-parse";

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

function TextBlock({ text, caret = false }: { readonly text: string; readonly caret?: boolean }) {
  const lines = text.split("\n");
  return (
    <>
      {lines.map((line, i) => (
        <p key={i} class="deck-turn-line">
          <InlineContent text={line} />
          {caret && i === lines.length - 1 ? (
            <span class="deck-gr-caret" aria-hidden="true" />
          ) : null}
        </p>
      ))}
    </>
  );
}

function HeadingBlock({ level, text }: { readonly level: number; readonly text: string }) {
  const content = <InlineContent text={text} />;
  if (level <= 1) return <h3 class="deck-rich-heading is-level-1">{content}</h3>;
  if (level === 2) return <h4 class="deck-rich-heading is-level-2">{content}</h4>;
  return <h5 class="deck-rich-heading is-level-3">{content}</h5>;
}

function InlineContent({ text }: { readonly text: string }) {
  return (
    <>
      {parseInline(text).map((run, index) =>
        run.t === "code" ? (
          <code key={index} class="deck-inline-code">{run.s}</code>
        ) : run.t === "strong" ? (
          <strong key={index}>{run.s}</strong>
        ) : run.t === "emphasis" ? (
          <em key={index}>{run.s}</em>
        ) : run.t === "strike" ? (
          <del key={index}>{run.s}</del>
        ) : run.t === "link" ? (
          <a
            key={index}
            href={run.href}
            target="_blank"
            rel="noreferrer noopener"
            aria-label={`${run.s} (${t("tooltip.opensNewTab")})`}
          >
            {run.s}
          </a>
        ) : (
          <span key={index}>{run.s}</span>
        ))}
    </>
  );
}

function ListBlock({ ordered, items }: {
  readonly ordered: boolean;
  readonly items: readonly ListItem[];
}) {
  const content = items.map((item, index) => (
    <li key={index} class={item.checked !== undefined ? "is-task" : undefined}>
      {item.checked !== undefined ? (
        <span class={`deck-task-mark ${item.checked ? "is-checked" : ""}`} aria-hidden="true">
          {item.checked ? "\u2713" : ""}
        </span>
      ) : null}
      <InlineContent text={item.text} />
    </li>
  ));
  return ordered ? (
    <ol class="deck-rich-list is-ordered">{content}</ol>
  ) : (
    <ul class="deck-rich-list">{content}</ul>
  );
}

function QuoteBlock({ text }: { readonly text: string }) {
  return (
    <blockquote class="deck-rich-quote">
      <TextBlock text={text} />
    </blockquote>
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

function CodeBlock({
  lang,
  code,
  pending,
}: {
  readonly lang: string;
  readonly code: string;
  readonly pending: boolean;
}) {
  const [copied, showCopied] = useTransientFlag(1200);
  const html = pending ? null : highlightCode(code, lang);
  const copy = () => {
    void navigator.clipboard?.writeText(code).then(
      () => {
        showCopied();
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
        {pending ? (
          <span class="deck-code-streaming">{t("deck.rich.streaming")}</span>
        ) : (
          <button type="button" class="deck-code-copy" onClick={copy}>
            {copied ? t("deck.rich.copied") : t("deck.rich.copy")}
          </button>
        )}
      </figcaption>
      <pre class="deck-code-pre">
        {html === null ? (
          <code class="hljs deck-code-pending-text">
            {code}
            <span class="deck-gr-caret" aria-hidden="true" />
          </code>
        ) : (
          // hljs escapes the input; its output HTML is safe to inject.
          <code class="hljs" dangerouslySetInnerHTML={{ __html: html }} />
        )}
      </pre>
    </figure>
  );
}

// Distinct hues so a multi-category chart is readable; rotated by bar index.
const CHART_PALETTE = [
  "#4c8dff",
  "#22c55e",
  "#f5a623",
  "#a855f7",
  "#ec4899",
  "#14b8a6",
  "#e5484d",
  "#64748b",
];

// Domain labels that carry a conventional color (severity, gate decision,
// outcome). Matched as a whole word or substring of the bar label.
const SEVERITY_COLORS: Record<string, string> = {
  critical: "#e5484d",
  high: "#f5a623",
  medium: "#4c8dff",
  low: "#8b98a5",
  error: "#e5484d",
  warning: "#f5a623",
  deny: "#e5484d",
  hil: "#f5a623",
  abstain: "#64748b",
  auto: "#22c55e",
  ok: "#22c55e",
  pass: "#22c55e",
  fail: "#e5484d",
};

function barColor(d: ChartDatum, i: number): string {
  if (d.color) return d.color;
  const key = d.label.toLowerCase().trim();
  for (const [word, color] of Object.entries(SEVERITY_COLORS)) {
    if (key === word || key.includes(word)) return color;
  }
  return CHART_PALETTE[i % CHART_PALETTE.length] ?? "#4c8dff";
}

function ChartPending() {
  return (
    <figure class="deck-chart deck-chart-pending" aria-label={t("deck.rich.preparingChart")}>
      <div class="deck-chart-bars">
        {[68, 42, 84].map((w, i) => (
          <div key={i} class="deck-chart-row">
            <span class="deck-chart-skel-label" />
            <span class="deck-chart-track">
              <span class="deck-chart-skel-fill" style={{ width: `${w}%` }} />
            </span>
          </div>
        ))}
      </div>
      <figcaption class="deck-chart-pending-cap">{t("deck.rich.preparingChartEllipsis")}</figcaption>
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
            >
              <span class="deck-chart-label">{d.label}</span>
              <span class="deck-chart-track">
                <span
                  class="deck-chart-fill"
                  style={{ width: `${pct}%`, background: barColor(d, i) }}
                />
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

function LineChart({ spec }: { readonly spec: ChartSpec }) {
  const [hover, setHover] = useState<number | null>(null);
  const data = spec.data;
  const n = data.length;
  const values = data.map((d) => d.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const unit = spec.unit ?? "";
  const sep = /^[A-Za-z]/.test(unit) ? " " : "";
  const W = 300;
  const H = 96;
  const padX = 10;
  const padTop = 12;
  const padBottom = 22;
  const innerW = W - padX * 2;
  const innerH = H - padTop - padBottom;
  const span = Math.max(1, n - 1);
  const x = (i: number) => padX + (n <= 1 ? innerW / 2 : (i / span) * innerW);
  const y = (v: number) =>
    padTop + innerH - (max === min ? innerH / 2 : ((v - min) / (max - min)) * innerH);
  const pts = data.map((d, i) => `${x(i)},${y(d.value)}`).join(" ");
  const showLabels = n <= 8;
  return (
    <figure class="deck-chart">
      {spec.title ? <figcaption class="deck-chart-title">{spec.title}</figcaption> : null}
      <svg viewBox={`0 0 ${W} ${H}`} class="deck-line-svg" role="img" aria-label={spec.title ?? t("deck.rich.lineChart")}>
        <polyline
          class="deck-line-path"
          points={pts}
          fill="none"
          vector-effect="non-scaling-stroke"
        />
        {data.map((d, i) => (
          <g
            key={i}
            onMouseEnter={() => setHover(i)}
            onMouseLeave={() => setHover((h) => (h === i ? null : h))}
          >
            <rect
              x={x(i) - innerW / (2 * span)}
              y={padTop}
              width={innerW / span}
              height={innerH}
              fill="transparent"
            />
            <circle
              cx={x(i)}
              cy={y(d.value)}
              r={hover === i ? 4 : 2.5}
              class="deck-line-dot"
              vector-effect="non-scaling-stroke"
            />
            {hover === i ? (
              <text x={x(i)} y={y(d.value) - 6} class="deck-line-tip" text-anchor="middle">
                {`${d.value}${sep}${unit}`}
              </text>
            ) : null}
            {showLabels ? (
              <text x={x(i)} y={H - 7} class="deck-line-xlabel" text-anchor="middle">
                {d.label.length > 7 ? `${d.label.slice(0, 7)}` : d.label}
              </text>
            ) : null}
          </g>
        ))}
      </svg>
    </figure>
  );
}

/**
 * Render an answer string as prose + tables + charts + code. When `streaming`,
 * a caret trails the content (inline on a prose tail, on its own line when the
 * tail is a still-building table / code / chart) so a partially arrived table
 * renders live and grows row by row instead of showing raw markdown until the
 * turn completes.
 */
export function RichContent({
  text,
  streaming = false,
  suppressCode = false,
}: {
  readonly text: string;
  readonly streaming?: boolean;
  readonly suppressCode?: boolean;
}) {
  const segments = parseAnswer(text);
  if (segments.length === 0) {
    return streaming ? <span class="deck-gr-caret" aria-hidden="true" /> : null;
  }
  const lastIsText = segments[segments.length - 1]?.kind === "text";
  return (
    <div class="deck-rich">
      {segments.map((seg, i) => {
        const isLast = i === segments.length - 1;
        if (seg.kind === "text") {
          return <TextBlock key={i} text={seg.text} caret={streaming && isLast} />;
        }
        if (seg.kind === "heading") {
          return <HeadingBlock key={i} level={seg.level} text={seg.text} />;
        }
        if (seg.kind === "list") {
          return <ListBlock key={i} ordered={seg.ordered} items={seg.items} />;
        }
        if (seg.kind === "quote") {
          return <QuoteBlock key={i} text={seg.text} />;
        }
        if (seg.kind === "divider") {
          return <hr key={i} class="deck-rich-divider" />;
        }
        if (seg.kind === "table") {
          return <TableBlock key={i} headers={seg.headers} rows={seg.rows} />;
        }
        if (seg.kind === "code") {
          return suppressCode ? null : (
            <CodeBlock key={i} lang={seg.lang} code={seg.code} pending={seg.pending} />
          );
        }
        if (seg.kind === "chart-pending") return <ChartPending key={i} />;
        if (seg.spec.type === "line") return <LineChart key={i} spec={seg.spec} />;
        return <MiniChart key={i} spec={seg.spec} />;
      })}
      {streaming && !lastIsText ? <span class="deck-gr-caret" aria-hidden="true" /> : null}
    </div>
  );
}
