export interface LabelCandidate {
  readonly id: string;
  readonly x: number;
  readonly y: number;
  readonly width: number;
  readonly height: number;
  readonly priority: number;
  readonly compact?: boolean;
  readonly nearOrigin?: boolean;
}

export interface LabelPlacement extends LabelCandidate {
  readonly left: number;
  readonly top: number;
}

function overlaps(a: LabelPlacement, b: LabelPlacement): boolean {
  const gap = 4;
  return a.left < b.left + b.width + gap && a.left + a.width + gap > b.left
    && a.top < b.top + b.height + gap && a.top + a.height + gap > b.top;
}

/** Deterministic screen-space decluttering. Focused labels are packed before optional labels. */
export function placeLabels(candidates: readonly LabelCandidate[], width: number, height: number): LabelPlacement[] {
  const placed: LabelPlacement[] = [];
  const cells = new Map<string, LabelPlacement[]>();
  const cellKeys = (label: LabelPlacement) => {
    const keys: string[] = [];
    for (let x = Math.floor((label.left - 4) / 80); x <= Math.floor((label.left + label.width + 4) / 80); x++) {
      for (let y = Math.floor((label.top - 4) / 40); y <= Math.floor((label.top + label.height + 4) / 40); y++) keys.push(`${x}:${y}`);
    }
    return keys;
  };
  for (const candidate of [...candidates].sort((a, b) => b.priority - a.priority || a.id.localeCompare(b.id))) {
    const { width: w, height: h, x, y } = candidate;
    if (w > width - 8 || h > height - 8) continue;
    const offsets = [
      [-w / 2, 14], [-w / 2, -h - 14], [14, -h / 2], [-w - 14, -h / 2],
      [14, 14], [-w - 14, 14], [14, -h - 14], [-w - 14, -h - 14],
    ];
    if (!candidate.compact && !candidate.nearOrigin) {
      for (let ring = 2; ring <= 5; ring++) offsets.push([-w / 2, ring * (h + 6)], [-w / 2, -ring * (h + 6)]);
    }
    for (const [dx, dy] of candidate.compact ? offsets.slice(0, 2) : offsets) {
      const proposal: LabelPlacement = {
        ...candidate,
        left: Math.max(4, Math.min(width - w - 4, x + dx!)),
        top: Math.max(4, Math.min(height - h - 4, y + dy!)),
      };
      const keys = cellKeys(proposal);
      if (keys.some((key) => cells.get(key)?.some((other) => overlaps(proposal, other)))) continue;
      placed.push(proposal);
      for (const key of keys) {
        if (!cells.has(key)) cells.set(key, []);
        cells.get(key)!.push(proposal);
      }
      break;
    }
  }
  return placed;
}
