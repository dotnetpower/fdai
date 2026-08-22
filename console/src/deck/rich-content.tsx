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
import { AgentActivityTimeline } from "./agent-activity-timeline";
import {
  injectCiteMarks,
  parseAnswer,
  parseInline,
  parseStreamingAnswer,
  type ChartSpec,
  type InlineCiteMark,
  type ListItem,
} from "./rich-parse";
import { Tooltip } from "../components/tooltip";
import { ComparisonBarChart, TrendChart } from "../components/charts";

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

function TextBlock({
  text,
  caret = false,
  citeMarks,
}: {
  readonly text: string;
  readonly caret?: boolean;
  readonly citeMarks?: readonly InlineCiteMark[] | undefined;
}) {
  const lines = text.split("\n");
  return (
    <>
      {lines.map((line, i) => (
        <p key={i} class="deck-turn-line">
          <InlineContent text={line} citeMarks={citeMarks} />
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

function CiteChip({ n, hint }: { readonly n: number; readonly hint: string }) {
  return (
    <Tooltip content={hint}>
      <span class="deck-cite-chip" role="note" aria-label={`${t("deck.grounded.sourceAria")} ${n}`}>
        {n}
      </span>
    </Tooltip>
  );
}

function InlineContent({
  text,
  citeMarks,
}: {
  readonly text: string;
  readonly citeMarks?: readonly InlineCiteMark[] | undefined;
}) {
  const runs = citeMarks && citeMarks.length > 0
    ? injectCiteMarks(parseInline(text), citeMarks)
    : parseInline(text);
  return (
    <>
      {runs.map((run, index) =>
        run.t === "code" ? (
          <code key={index} class="deck-inline-code">{run.s}</code>
        ) : run.t === "strong" ? (
          <strong key={index}>{run.s}</strong>
        ) : run.t === "emphasis" ? (
          <em key={index}>{run.s}</em>
        ) : run.t === "strike" ? (
          <del key={index}>{run.s}</del>
        ) : run.t === "cite" ? (
          <CiteChip key={index} n={run.n} hint={run.title} />
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

function TableCellContent({ text }: { readonly text: string }) {
  return (
    <>
      {text.split("\n").map((line, index) => (
        <span key={index}>
          {index > 0 ? <br /> : null}
          <InlineContent text={line} />
        </span>
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
    <div class="deck-table-block">
      <div class="deck-table-wrap">
        <table class="deck-table">
          <thead>
            <tr>
              {headers.map((h, i) => (
                <th key={i} scope="col">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, r) => (
              <tr key={r}>
                {headers.map((_, c) => (
                  <td key={c}>
                    <span class="deck-table-cell-label" aria-hidden="true">
                      {headers[c] ?? ""}
                    </span>
                    <span class="deck-table-cell-value">
                      <TableCellContent text={row[c] ?? ""} />
                    </span>
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
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

export function CodeBlock({
  lang,
  code,
  pending,
  copyLabel,
}: {
  readonly lang: string;
  readonly code: string;
  readonly pending: boolean;
  readonly copyLabel?: string;
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
            {copied ? t("deck.tooltip.copied") : (copyLabel ?? t("deck.tooltip.copyReply"))}
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
      <figcaption class="deck-chart-pending-cap">{t("deck.rich.preparingChartProgress")}</figcaption>
    </figure>
  );
}

function MiniChart({ spec }: { readonly spec: ChartSpec }) {
  const max = Math.max(...spec.data.map((d) => Math.abs(d.value)), 1);
  // A word unit ("rules") reads better with a space; a symbol unit ("%", "$")
  // stays attached to the number.
  const unit = spec.unit ?? "";
  const sep = /^[A-Za-z]/.test(unit) ? " " : "";
  const fmt = (value: number) => `${value}${sep}${unit}`;
  return (
    <figure class="deck-chart">
      {spec.title ? <figcaption class="deck-chart-title">{spec.title}</figcaption> : null}
      <ComparisonBarChart
        label={spec.title ?? t("deck.rich.barChart")}
        items={spec.data.map((datum) => ({ label: datum.label, value: Math.abs(datum.value) }))}
        maximum={max}
        formatValue={fmt}
      />
    </figure>
  );
}

function LineChart({ spec }: { readonly spec: ChartSpec }) {
  const unit = spec.unit ?? "";
  const sep = /^[A-Za-z]/.test(unit) ? " " : "";
  return (
    <TrendChart
      className="deck-chart"
      title={spec.title ?? t("deck.rich.lineChart")}
      points={spec.data}
      formatValue={(value) => `${value}${sep}${unit}`}
      summary={`${spec.data.at(-1)!.value}${sep}${unit}`}
      referenceLabel={t("deck.rich.median")}
      compact
    />
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
  citeMarks,
}: {
  readonly text: string;
  readonly streaming?: boolean;
  readonly suppressCode?: boolean;
  /** Numbered inline citation anchors. Injected only into settled prose (never
   *  while streaming, to avoid chips flickering mid-token). */
  readonly citeMarks?: readonly InlineCiteMark[] | undefined;
}) {
  const segments = streaming ? parseStreamingAnswer(text) : parseAnswer(text);
  if (segments.length === 0) {
    return streaming ? <span class="deck-gr-caret" aria-hidden="true" /> : null;
  }
  const marks = streaming ? undefined : citeMarks;
  const lastIsText = segments[segments.length - 1]?.kind === "text";
  return (
    <div class={`deck-rich${streaming ? " is-streaming" : ""}`}>
      {segments.map((seg, i) => {
        const isLast = i === segments.length - 1;
        if (seg.kind === "text") {
          return (
            <TextBlock key={i} text={seg.text} caret={streaming && isLast} citeMarks={marks} />
          );
        }
        if (seg.kind === "agent-activity") {
          return <AgentActivityTimeline key={i} items={seg.items} locale={seg.locale} />;
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
