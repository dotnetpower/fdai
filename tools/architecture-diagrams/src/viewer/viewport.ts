export interface ViewBox {
  x: number;
  y: number;
  width: number;
  height: number;
}

export function contentViewBox(full: ViewBox, topInset = 88): ViewBox {
  const inset = Math.min(Math.max(0, topInset), full.height / 3);
  return {
    x: full.x,
    y: full.y + inset,
    width: full.width,
    height: full.height - inset,
  };
}

export function constrainViewBox(view: ViewBox, bounds: ViewBox): ViewBox {
  const x =
    view.width >= bounds.width
      ? bounds.x + (bounds.width - view.width) / 2
      : Math.min(
          bounds.x + bounds.width - view.width,
          Math.max(bounds.x, view.x),
        );
  const y =
    view.height >= bounds.height
      ? bounds.y + (bounds.height - view.height) / 2
      : Math.min(
          bounds.y + bounds.height - view.height,
          Math.max(bounds.y, view.y),
        );
  return { ...view, x, y };
}

export function fitViewBox(
  bounds: ViewBox,
  viewportWidth: number,
  viewportHeight: number,
): ViewBox {
  if (viewportWidth <= 0 || viewportHeight <= 0) return { ...bounds };
  const viewportAspect = viewportWidth / viewportHeight;
  const boundsAspect = bounds.width / bounds.height;
  if (viewportAspect >= boundsAspect) return { ...bounds };
  return {
    x: bounds.x,
    y: bounds.y,
    width: bounds.height * viewportAspect,
    height: bounds.height,
  };
}

export function interactiveInitialViewBox(
  bounds: ViewBox,
  viewportWidth: number,
  viewportHeight: number,
  compact: boolean,
): ViewBox {
  if (!compact) return { ...bounds };
  const fitted = fitViewBox(bounds, viewportWidth, viewportHeight);
  return zoomViewBox(fitted, bounds, 0.82, 0, 0);
}

export function zoomViewBox(
  view: ViewBox,
  bounds: ViewBox,
  factor: number,
  anchorX = 0.5,
  anchorY = 0.5,
): ViewBox {
  const viewAspect = view.width / view.height;
  let nextWidth = Math.min(
    bounds.width,
    Math.max(bounds.width / 8, view.width * factor),
  );
  let nextHeight = nextWidth / viewAspect;
  if (nextHeight > bounds.height) {
    nextHeight = bounds.height;
    nextWidth = nextHeight * viewAspect;
  }
  return constrainViewBox(
    {
      x: view.x + (view.width - nextWidth) * anchorX,
      y: view.y + (view.height - nextHeight) * anchorY,
      width: nextWidth,
      height: nextHeight,
    },
    bounds,
  );
}

export function panViewBox(
  view: ViewBox,
  bounds: ViewBox,
  deltaX: number,
  deltaY: number,
): ViewBox {
  return constrainViewBox(
    { ...view, x: view.x + deltaX, y: view.y + deltaY },
    bounds,
  );
}

export function zoomPercentage(view: ViewBox, bounds: ViewBox): number {
  return Math.round((bounds.width / view.width) * 100);
}
