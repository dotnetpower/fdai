export interface PackedItem<T> {
  readonly item: T;
  readonly x: number;
  readonly y: number;
}

export interface RectangleItem {
  readonly width: number;
  readonly height: number;
}

export function packArchitectureRectangles<T extends RectangleItem>(
  items: readonly T[],
  targetWidth: number,
  gap: number,
): { readonly items: readonly PackedItem<T>[]; readonly width: number; readonly height: number } {
  const placements: PackedItem<T>[] = [];
  let x = 0;
  let y = 0;
  let rowHeight = 0;
  let maximumRight = 0;
  for (const item of [...items].sort((first, second) =>
    second.width * second.height - first.width * first.height)) {
    if (x > 0 && x + item.width > targetWidth) {
      x = 0;
      y += rowHeight + gap;
      rowHeight = 0;
    }
    placements.push({ item, x, y });
    maximumRight = Math.max(maximumRight, x + item.width);
    rowHeight = Math.max(rowHeight, item.height);
    x += item.width + gap;
  }
  return {
    items: placements,
    width: maximumRight,
    height: placements.length === 0 ? 0 : y + rowHeight,
  };
}

export function architectureLayoutTargetWidth(
  items: readonly RectangleItem[],
  aspect = 1.8,
): number {
  if (items.length === 0) return 0;
  return Math.max(
    ...items.map((item) => item.width),
    Math.sqrt(items.reduce((total, item) => total + item.width * item.height, 0)) * aspect,
  );
}
