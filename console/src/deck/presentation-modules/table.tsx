import type { PresentationTableData } from "../backend-types";
import type { PresentationModuleProps } from "./types";
import { PresentationValue } from "./value";

export function TableModule({ block }: PresentationModuleProps) {
  if (block.kind !== "table" && block.kind !== "threshold_table") return null;
  return <PresentationTable data={block.data} />;
}

export function PresentationTable({ data }: { readonly data: PresentationTableData }) {
  return (
    <table class="deck-presentation-table">
      <thead>
        <tr>{data.columns.map((column) => (
          <th
            key={column.key}
            scope="col"
            data-column={column.key}
            data-field={presentationFieldRole(column.label)}
          >
            {column.label}
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
                  {column.label}
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
  );
}

export function presentationFieldRole(label: string): string | undefined {
  const leaf = label.trim().split(".").at(-1)?.toLowerCase();
  return leaf === "name" || leaf === "type" || leaf === "location" ? leaf : undefined;
}

function statusTone(value: string | undefined): "neutral" | "positive" | "warning" {
  const normalized = value?.toLowerCase() ?? "";
  if (normalized.includes("unavailable") || normalized.includes("unknown") ||
      normalized.includes("초과") || normalized.includes("degraded")) return "warning";
  if (normalized.includes("within") || normalized.includes("이내") ||
      normalized === "available") return "positive";
  return "neutral";
}
