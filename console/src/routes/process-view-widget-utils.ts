export type DataRow = Readonly<Record<string, unknown>>;

export function asRecord(value: unknown): DataRow {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as DataRow
    : {};
}

export function asRows(value: unknown): readonly DataRow[] {
  return Array.isArray(value)
    ? value.filter((item): item is DataRow => item !== null && typeof item === "object" && !Array.isArray(item))
    : [];
}

export function finiteNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export function boundedRatio(value: unknown): number | null {
  const number = finiteNumber(value);
  return number === null ? null : Math.max(0, Math.min(1, number));
}

export function percent(value: unknown): string {
  const ratio = boundedRatio(value);
  return ratio === null ? "-" : `${(ratio * 100).toFixed(1)}%`;
}

export function deriveColumns(rows: readonly DataRow[]): readonly string[] {
  const names = new Set<string>();
  rows.forEach((row) => Object.keys(row).forEach((key) => names.add(key)));
  return [...names].slice(0, 20);
}

export function numericPoints(value: unknown): readonly (readonly [number, number])[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((point) =>
    Array.isArray(point) && point.length >= 2 && point.every((entry) => finiteNumber(entry) !== null)
      ? [[point[0] as number, point[1] as number] as const]
      : [],
  );
}

export function sparkline(
  points: readonly (readonly [number, number])[],
  width: number,
  height: number,
): string {
  if (points.length === 0) return "";
  const xs = points.map(([x]) => x);
  const ys = points.map(([, y]) => y);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const rangeX = maxX - minX || 1;
  const rangeY = maxY - minY || 1;
  return points.map(([x, y]) =>
    `${(((x - minX) / rangeX) * width).toFixed(1)},${(height - ((y - minY) / rangeY) * height).toFixed(1)}`,
  ).join(" ");
}

export function normalizedPointPositions(
  rows: readonly DataRow[],
): readonly { readonly x: number; readonly y: number; readonly row: DataRow }[] {
  const valid = rows.flatMap((row) => {
    const x = finiteNumber(row["x"]);
    const y = finiteNumber(row["y"]);
    return x === null || y === null ? [] : [{ x, y, row }];
  });
  if (valid.length === 0) return [];
  const minX = Math.min(...valid.map((point) => point.x));
  const maxX = Math.max(...valid.map((point) => point.x));
  const minY = Math.min(...valid.map((point) => point.y));
  const maxY = Math.max(...valid.map((point) => point.y));
  const xRange = maxX - minX || 1;
  const yRange = maxY - minY || 1;
  return valid.map((point) => ({
    x: 8 + ((point.x - minX) / xRange) * 304,
    y: 88 - ((point.y - minY) / yRange) * 80,
    row: point.row,
  }));
}
