import { describe, expect, test } from "vitest";
import { TABLE_PREVIEW_ROW_COUNT, tableRowsForDisplay } from "./table-presentation";

describe("tableRowsForDisplay", () => {
  const rows = Array.from({ length: 442 }, (_, index) => index);

  test("renders only the bounded preview until explicitly expanded", () => {
    const presentation = tableRowsForDisplay(rows, false);
    expect(presentation.visibleRows).toHaveLength(TABLE_PREVIEW_ROW_COUNT);
    expect(presentation.hiddenCount).toBe(422);
  });

  test("renders all rows after explicit expansion", () => {
    expect(tableRowsForDisplay(rows, true)).toEqual({ visibleRows: rows, hiddenCount: 0 });
  });
});
