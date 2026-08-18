import type {
  PresentationArtifact,
  PresentationBlock,
  PresentationChartItem,
} from "./backend-types";
import { getLocale, t } from "../i18n";
import { Tooltip } from "../components/tooltip";
import {
  presentationActivity,
  presentationActor,
  presentationActors,
  presentationDuration,
  presentationSeverity,
  presentationTimestamp,
} from "./presentation-value";
import "./structured-reply.css";

export function StructuredReply({ artifact }: { readonly artifact: PresentationArtifact }) {
  return (
    <div class="deck-presentation" data-layout={artifact.layout}>
      {artifact.blocks.map((block) => (
        <PresentationBlockView key={block.slotId} block={block} />
      ))}
    </div>
  );
}

function PresentationBlockView({ block }: { readonly block: PresentationBlock }) {
  const body = <PresentationBlockBody block={block} />;
  if (block.collapsed) {
    return (
      <details class="deck-presentation-block is-collapsible" data-emphasis={block.emphasis}>
        <summary>{block.title}</summary>
        <div class="deck-presentation-block-body">{body}</div>
      </details>
    );
  }
  const headingId = `deck-presentation-${block.slotId}`;
  return (
    <section
      class="deck-presentation-block"
      data-kind={block.kind}
      data-emphasis={block.emphasis}
      aria-labelledby={headingId}
    >
      <h4 id={headingId}>{block.title}</h4>
      {body}
    </section>
  );
}

function PresentationBlockBody({ block }: { readonly block: PresentationBlock }) {
  if (block.kind === "summary") {
    const timestamps = block.data.items
      .map((item) => item.value)
      .filter((value) => presentationTimestamp(value) !== null);
    const observedSpan = timestamps.length >= 2
      ? presentationDuration(timestamps[0]!, timestamps[timestamps.length - 1]!)
      : null;
    return (
      <dl class="deck-presentation-summary">
        {block.data.items.map((item) => (
          <div
            key={item.label}
            data-tone={item.tone}
            data-value-kind={presentationValueKind(item.label, item.value)}
          >
            <dt>{item.label}</dt>
            <dd><PresentationValue value={item.value} label={item.label} /></dd>
          </div>
        ))}
        {observedSpan ? (
          <div class="deck-presentation-derived" data-value-kind="duration">
            <dt>{t("deck.presentation.observedSpan")}</dt>
            <dd>{observedSpan}</dd>
          </div>
        ) : null}
      </dl>
    );
  }
  if (block.kind === "callout") {
    return (
      <ul class="deck-presentation-callout" data-tone={block.data.tone}>
        {block.data.lines.map((line) => <li key={line}>{line}</li>)}
      </ul>
    );
  }
  if (block.kind === "table" || block.kind === "threshold_table") {
    return <PresentationTable block={block} />;
  }
  if (block.kind === "list") {
    return (
      <div class="deck-presentation-list">
        {block.data.rows.map((row, index) => (
          <dl key={index}>
            {block.data.columns.map((column) => (
              <div key={column.key}>
                <dt>{column.label}</dt>
                <dd>{row[column.key] ?? ""}</dd>
              </div>
            ))}
          </dl>
        ))}
      </div>
    );
  }
  if (block.kind === "coverage" || block.kind === "bar") {
    return <PresentationBars items={block.data.items} proportional={block.kind === "coverage"} />;
  }
  return (
    <dl class="deck-presentation-evidence">
      {block.data.items.map((item) => (
        <div key={item.label}>
          <dt>{item.label}</dt>
          <dd>{item.value}</dd>
        </div>
      ))}
    </dl>
  );
}

function PresentationTable({
  block,
}: {
  readonly block: Extract<PresentationBlock, { kind: "table" | "threshold_table" }>;
}) {
  return (
    <table class="deck-presentation-table">
      <thead>
        <tr>{block.data.columns.map((column) => (
          <th key={column.key} scope="col" data-column={column.key}>{column.label}</th>
        ))}</tr>
      </thead>
      <tbody>
        {block.data.rows.map((row, rowIndex) => (
          <tr key={rowIndex}>
            {block.data.columns.map((column) => (
              <td key={column.key} data-column={column.key}>
                <span class="deck-presentation-cell-label" aria-hidden="true">
                  {column.label}
                </span>
                {block.data.statusKey !== null && column.key === block.data.statusKey ? (
                  <span class="deck-presentation-status" data-tone={statusTone(row[column.key])}>
                    <PresentationValue
                      value={row[column.key] ?? ""}
                      columnKey={column.key}
                      label={column.label}
                    />
                  </span>
                ) : (
                  <PresentationValue
                    value={row[column.key] ?? ""}
                    columnKey={column.key}
                    label={column.label}
                  />
                )}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function PresentationValue({
  value,
  columnKey = "",
  label = "",
}: {
  readonly value: string;
  readonly columnKey?: string;
  readonly label?: string;
}) {
  const timestamp = presentationTimestamp(
    value,
    getLocale() === "ko" ? "ko-KR" : "en-US",
  );
  if (timestamp) {
    return (
      <Tooltip content={t("deck.presentation.recordedValue", { value })}>
        <time class="deck-presentation-timestamp" dateTime={timestamp.dateTime}>
          <span>{timestamp.date}</span>
          <span>{timestamp.time}</span>
        </time>
      </Tooltip>
    );
  }
  if (isActorField(columnKey, label)) {
    const actors = presentationActors(value);
    return (
      <Tooltip content={value}>
        <span class="deck-presentation-actors">
          {actors.visible.map((actor) => (
            <span key={actor}>{presentationActor(actor)}</span>
          ))}
          {actors.hiddenCount > 0 ? (
            <span class="deck-presentation-more">
              +{actors.hiddenCount}
              <span class="sr-only"> {t("deck.presentation.moreActors", {
                count: actors.hiddenCount,
              })}</span>
            </span>
          ) : null}
        </span>
      </Tooltip>
    );
  }
  if (isSeverityField(columnKey, label)) {
    return (
      <Tooltip content={value}>
        <span>{presentationSeverity(value)}</span>
      </Tooltip>
    );
  }
  if (isCanonicalTokenField(columnKey, label)) {
    return (
      <Tooltip content={value}>
        <span class="deck-presentation-token">{presentationActivity(value)}</span>
      </Tooltip>
    );
  }
  if (isReferenceField(columnKey, label)) {
    return <code class="deck-presentation-ref">{value}</code>;
  }
  return <span>{value}</span>;
}

function presentationValueKind(label: string, value: string): string {
  if (presentationTimestamp(value)) return "timestamp";
  if (isActorField("", label)) return "actors";
  if (isCanonicalTokenField("", label)) return "token";
  return "text";
}

function isActorField(key: string, label: string): boolean {
  return /actor/i.test(key) || /actor|주체|행위자/i.test(label);
}

function isCanonicalTokenField(key: string, label: string): boolean {
  return /^(activity|mode|status|kind|tier)$/i.test(key) ||
    /^(activity|mode|status|kind|tier|활동|모드|상태|종류|티어)$/i.test(label);
}

function isSeverityField(key: string, label: string): boolean {
  return /^severity$/i.test(key) || /^(severity|심각도)$/i.test(label);
}

function isReferenceField(key: string, label: string): boolean {
  return /(?:ref|reference)$/i.test(key) || /reference|참조/i.test(label);
}

function PresentationBars({
  items,
  proportional,
}: {
  readonly items: readonly PresentationChartItem[];
  readonly proportional: boolean;
}) {
  const denominator = proportional
    ? Math.max(1, items.reduce((sum, item) => sum + item.value, 0))
    : Math.max(1, ...items.map((item) => item.value));
  return (
    <div class="deck-presentation-bars">
      {items.map((item) => {
        const width = item.value === 0 ? 0 : Math.max(2, (item.value / denominator) * 100);
        return (
          <div key={item.label} class="deck-presentation-bar-row" data-tone={item.tone}>
            <span class="deck-presentation-bar-label">
              {item.tone === "warning" ? (
                <span class="deck-presentation-tone-mark" aria-hidden="true">!</span>
              ) : item.tone === "positive" ? (
                <span class="deck-presentation-tone-mark" aria-hidden="true">OK</span>
              ) : null}
              {item.label}
            </span>
            <span class="deck-presentation-bar-track" aria-hidden="true">
              <span style={{ width: `${width}%` }} />
            </span>
            <strong>{item.value}</strong>
          </div>
        );
      })}
    </div>
  );
}

function statusTone(value: string | undefined): "neutral" | "positive" | "attention" | "warning" {
  const normalized = value?.toLowerCase() ?? "";
  if (normalized.includes("unavailable") || normalized.includes("unknown") ||
      normalized.includes("초과") || normalized.includes("degraded")) return "warning";
  if (normalized.includes("within") || normalized.includes("이내") || normalized === "available") {
    return "positive";
  }
  return "neutral";
}
