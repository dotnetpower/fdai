import type { PresentationTableData } from "../backend-types";
import type { PresentationModuleProps } from "./types";
import { PresentationValue } from "./value";

export function TableModule({ block }: PresentationModuleProps) {
  if (block.kind !== "table" && block.kind !== "threshold_table") return null;
  return <PresentationTable data={block.data} />;
}

export function PresentationTable({ data }: { readonly data: PresentationTableData }) {
  const layout = presentationTableLayout(data.columns.length);
  return (
    <div class="deck-presentation-table-wrap" data-layout={layout}>
      <table class="deck-presentation-table" data-layout={layout}>
        <thead>
          <tr>{data.columns.map((column) => (
            <th
              key={column.key}
              scope="col"
              data-column={column.key}
              data-field={presentationFieldRole(column.label)}
            >
              {presentationColumnLabel(column.label)}
            </th>
          ))}</tr>
        </thead>
        <tbody>
          {data.rows.map((row, rowIndex) => (
            <tr key={rowIndex}>
              {data.columns.map((column) => (
                <td
                  key={column.key}
                  data-column={column.key}
                  data-field={presentationFieldRole(column.label)}
                >
                  <span class="deck-presentation-cell-label" aria-hidden="true">
                    {presentationColumnLabel(column.label)}
                  </span>
                  {data.statusKey !== null && column.key === data.statusKey ? (
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
    </div>
  );
}

export function presentationFieldRole(label: string): string | undefined {
  const leaf = label.trim().split(".").at(-1)?.toLowerCase();
  if (leaf === "name" || leaf === "type" || leaf === "location") return leaf;
  if (leaf?.endsWith("_at") || leaf === "recorded") return "timestamp";
  if (leaf?.includes("concept")) return "concept";
  if (leaf?.includes("state") || leaf === "status") return "state";
  return undefined;
}

export function presentationColumnLabel(label: string): string {
  return label.trim().replace(/[._]+/g, " ");
}

export function presentationTableLayout(columnCount: number): "balanced" | "compact" | "wide" {
  if (columnCount <= 3) return "compact";
  return columnCount === 4 ? "balanced" : "wide";
}

function statusTone(value: string | undefined): "neutral" | "positive" | "warning" {
  const normalized = value?.toLowerCase() ?? "";
  if (normalized.includes("unavailable") || normalized.includes("unknown") ||
      normalized.includes("초과") || normalized.includes("degraded")) return "warning";
  if (normalized.includes("within") || normalized.includes("이내") ||
      normalized === "available") return "positive";
  return "neutral";
}
