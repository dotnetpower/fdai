import type {
  PresentationArtifact,
  PresentationBlock,
  PresentationChartItem,
} from "./backend-types";
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
    return (
      <dl class="deck-presentation-summary">
        {block.data.items.map((item) => (
          <div key={item.label} data-tone={item.tone}>
            <dt>{item.label}</dt>
            <dd>{item.value}</dd>
          </div>
        ))}
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
          <th key={column.key} scope="col">{column.label}</th>
        ))}</tr>
      </thead>
      <tbody>
        {block.data.rows.map((row, rowIndex) => (
          <tr key={rowIndex}>
            {block.data.columns.map((column) => (
              <td key={column.key}>
                <span class="deck-presentation-cell-label" aria-hidden="true">
                  {column.label}
                </span>
                {block.data.statusKey !== null && column.key === block.data.statusKey ? (
                  <span class="deck-presentation-status" data-tone={statusTone(row[column.key])}>
                    {row[column.key] ?? ""}
                  </span>
                ) : (
                  <span>{row[column.key] ?? ""}</span>
                )}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
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
