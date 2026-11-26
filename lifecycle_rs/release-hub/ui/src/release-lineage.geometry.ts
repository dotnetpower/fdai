export const CARD_WIDTH = 176;
export const CARD_HEIGHT = 108;
export const BADGE_HEIGHT = 24;
export const COL_GAP = 28;
export const ROW_GAP = 24;
export const PAD_X = 10;
export const PAD_Y = 12;

export function buildConnectorGeometry(edge: {
  startX: number;
  startY: number;
  endX: number;
  endY: number;
}): {
  portCx: number;
  portCy: number;
  pathD: string;
  arrowD: string;
} {
  const portCx = edge.startX + 3.5;
  const portCy = edge.startY;
  const lineStartX = portCx + 3.5;
  const sy = edge.startY;
  const arrowTipX = edge.endX - 2.5;
  const ey = edge.endY;
  const lineEndX = arrowTipX - 0.5;
  const arrowD = `M ${arrowTipX - 6.5} ${ey - 4.2} L ${arrowTipX} ${ey} L ${arrowTipX - 6.5} ${ey + 4.2}`;

  if (Math.abs(ey - sy) < 1) {
    return {
      portCx,
      portCy,
      pathD: `M ${lineStartX} ${sy} L ${lineEndX} ${ey}`,
      arrowD,
    };
  }

  const dir = ey > sy ? 1 : -1;
  const horizontalSpan = Math.max(12, lineEndX - lineStartX);
  const midX = Math.round(lineStartX + horizontalSpan * 0.44);
  const r = Math.max(
    0,
    Math.min(
      8,
      Math.abs(ey - sy) / 2,
      Math.max(0, Math.abs(midX - lineStartX) - 2),
      Math.max(0, Math.abs(lineEndX - 7 - midX) - 2),
    ),
  );
  if (r < 1) {
    return {
      portCx,
      portCy,
      pathD: `M ${lineStartX} ${sy} L ${midX} ${sy} L ${midX} ${ey} L ${lineEndX} ${ey}`,
      arrowD,
    };
  }
  const pathD = [
    `M ${lineStartX} ${sy}`,
    `L ${midX - r} ${sy}`,
    `Q ${midX} ${sy} ${midX} ${sy + dir * r}`,
    `L ${midX} ${ey - dir * r}`,
    `Q ${midX} ${ey} ${midX + r} ${ey}`,
    `L ${lineEndX} ${ey}`,
  ].join(" ");

  return {
    portCx,
    portCy,
    pathD,
    arrowD,
  };
}
