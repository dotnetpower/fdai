export const ARCHITECTURE_TOPOLOGY_NODE_WIDTH = 2.4;
export const ARCHITECTURE_TOPOLOGY_NODE_HEIGHT = 1.45;
export const ARCHITECTURE_TOPOLOGY_NODE_MIN_RENDER_SCALE = .72;
export const ARCHITECTURE_TOPOLOGY_NODE_MAX_RENDER_SCALE = 1.25;
export const ARCHITECTURE_TOPOLOGY_HIT_TARGET_SIZE = 2.5;
export const ARCHITECTURE_TOPOLOGY_COLUMN_PITCH =
  Math.max(
    ARCHITECTURE_TOPOLOGY_NODE_WIDTH * ARCHITECTURE_TOPOLOGY_NODE_MAX_RENDER_SCALE,
    ARCHITECTURE_TOPOLOGY_HIT_TARGET_SIZE,
  ) + .3;
export const ARCHITECTURE_TOPOLOGY_ROW_PITCH =
  Math.max(
    ARCHITECTURE_TOPOLOGY_NODE_HEIGHT * ARCHITECTURE_TOPOLOGY_NODE_MAX_RENDER_SCALE,
    ARCHITECTURE_TOPOLOGY_HIT_TARGET_SIZE,
  ) + .3;

export function architectureTopologyNodeRenderScale(renderScale = 1): number {
  return Math.max(
    ARCHITECTURE_TOPOLOGY_NODE_MIN_RENDER_SCALE,
    Math.min(ARCHITECTURE_TOPOLOGY_NODE_MAX_RENDER_SCALE, renderScale),
  );
}

export function architectureTopologyNodeDimensions(renderScale = 1): {
  readonly width: number;
  readonly height: number;
} {
  const scale = architectureTopologyNodeRenderScale(renderScale);
  return {
    width: ARCHITECTURE_TOPOLOGY_NODE_WIDTH * scale,
    height: ARCHITECTURE_TOPOLOGY_NODE_HEIGHT * scale,
  };
}
