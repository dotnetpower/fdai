export const TABLE_PREVIEW_ROW_COUNT = 20;

export function tableRowsForDisplay<T>(
  rows: readonly T[],
  expanded: boolean,
): { readonly visibleRows: readonly T[]; readonly hiddenCount: number } {
  if (expanded || rows.length <= TABLE_PREVIEW_ROW_COUNT) {
    return { visibleRows: rows, hiddenCount: 0 };
  }
  return {
    visibleRows: rows.slice(0, TABLE_PREVIEW_ROW_COUNT),
    hiddenCount: rows.length - TABLE_PREVIEW_ROW_COUNT,
  };
}
