import type { PresentationModuleProps } from "./types";
import { PresentationValue } from "./value";

export function ListModule({ block }: PresentationModuleProps) {
  if (block.kind !== "list") return null;
  return (
    <div class="deck-presentation-list">
      {block.data.rows.map((row, index) => (
        <dl key={index}>
          {block.data.columns.map((column) => (
            <div key={column.key}>
              <dt>{column.label}</dt>
              <dd>
                <PresentationValue
                  value={row[column.key] ?? ""}
                  columnKey={column.key}
                  label={column.label}
                />
              </dd>
            </div>
          ))}
        </dl>
      ))}
    </div>
  );
}
