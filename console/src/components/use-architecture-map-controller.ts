import type { Ref } from "preact";
import { useEffect, useImperativeHandle, useRef } from "preact/hooks";
import {
  applyCameraView,
  architectureZoomScale,
  clamp,
  fitCamera,
  pickResource,
  type Camera,
} from "./architecture-map.geometry";
import type {
  ArchitectureDisplayOptions,
  InventoryGraphResponse,
  InventoryResource,
} from "./architecture-map.model";
import { constrainGraph } from "./architecture-map.model";
import {
  DEFAULT_ARCHITECTURE_MAP_PALETTE,
  renderMap,
  type ArchitectureMapPalette,
} from "./architecture-map-renderer";
import type { ArchitectureMapHandle } from "./architecture-map";

interface ControllerOptions {
  readonly graph: InventoryGraphResponse;
  readonly selectedId: string | null;
  readonly highlightedIds: ReadonlySet<string> | undefined;
  readonly onSelect: ((resource: InventoryResource | null) => void) | undefined;
  readonly options: ArchitectureDisplayOptions;
  readonly onZoomChange: ((percent: number) => void) | undefined;
  readonly forwardedRef: Ref<ArchitectureMapHandle>;
}

export function useArchitectureMapController({
  graph,
  selectedId,
  highlightedIds,
  onSelect,
  options,
  onZoomChange,
  forwardedRef,
}: ControllerOptions) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const cameraRef = useRef<Camera>({
    yaw: Math.PI / 4,
    pitch: .58,
    scale: 42,
    panX: 0,
    panY: 0,
  });
  const fitScaleRef = useRef(42);
  const dragRef = useRef<{
    startX: number;
    startY: number;
    lastX: number;
    lastY: number;
  } | null>(null);
  const stateRef = useRef({
    graph: constrainGraph(graph),
    selectedId,
    highlightedIds,
    onSelect,
    options,
  });
  const drawRef = useRef<(() => void) | null>(null);
  stateRef.current = {
    graph: constrainGraph(graph),
    selectedId,
    highlightedIds,
    onSelect,
    options,
  };

  const notifyZoom = () => onZoomChange?.(
    Math.round((cameraRef.current.scale / fitScaleRef.current) * 100),
  );

  useImperativeHandle(forwardedRef, () => ({
    setView(view) {
      applyCameraView(cameraRef.current, view);
      fitCamera(
        cameraRef.current,
        canvasRef.current?.clientWidth ?? 1,
        canvasRef.current?.clientHeight ?? 1,
      );
      fitScaleRef.current = cameraRef.current.scale;
      drawRef.current?.();
      notifyZoom();
    },
    zoomIn() {
      cameraRef.current.scale = architectureZoomScale(cameraRef.current.scale, "in");
      drawRef.current?.();
      notifyZoom();
    },
    zoomOut() {
      cameraRef.current.scale = architectureZoomScale(cameraRef.current.scale, "out");
      drawRef.current?.();
      notifyZoom();
    },
    fit() {
      fitCamera(
        cameraRef.current,
        canvasRef.current?.clientWidth ?? 1,
        canvasRef.current?.clientHeight ?? 1,
      );
      fitScaleRef.current = cameraRef.current.scale;
      drawRef.current?.();
      notifyZoom();
    },
  }), [onZoomChange]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const context = canvas.getContext("2d");
    if (!context) return;

    const draw = () => {
      const state = stateRef.current;
      renderMap(
        context,
        canvas.clientWidth,
        canvas.clientHeight,
        cameraRef.current,
        state.graph,
        state.selectedId,
        state.highlightedIds,
        state.options,
        architectureMapPalette(canvas),
      );
    };
    const resize = () => {
      const ratio = window.devicePixelRatio || 1;
      const width = canvas.clientWidth;
      const height = canvas.clientHeight;
      canvas.width = Math.round(width * ratio);
      canvas.height = Math.round(height * ratio);
      context.setTransform(ratio, 0, 0, ratio, 0, 0);
      fitCamera(cameraRef.current, width, height);
      fitScaleRef.current = cameraRef.current.scale;
      draw();
      notifyZoom();
    };
    drawRef.current = draw;
    const observer = new ResizeObserver(resize);
    observer.observe(canvas);
    const themeObserver = new MutationObserver(draw);
    themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });

    const localPoint = (event: PointerEvent | WheelEvent) => {
      const rect = canvas.getBoundingClientRect();
      return { x: event.clientX - rect.left, y: event.clientY - rect.top };
    };
    const pointerDown = (event: PointerEvent) => {
      canvas.setPointerCapture(event.pointerId);
      const point = localPoint(event);
      dragRef.current = {
        startX: point.x,
        startY: point.y,
        lastX: point.x,
        lastY: point.y,
      };
    };
    const pointerMove = (event: PointerEvent) => {
      const previous = dragRef.current;
      if (!previous) return;
      const current = localPoint(event);
      cameraRef.current.panX += current.x - previous.lastX;
      cameraRef.current.panY += current.y - previous.lastY;
      dragRef.current = { ...previous, lastX: current.x, lastY: current.y };
      draw();
    };
    const pointerUp = (event: PointerEvent) => {
      const previous = dragRef.current;
      dragRef.current = null;
      const point = localPoint(event);
      if (!previous || Math.hypot(point.x - previous.startX, point.y - previous.startY) > 6) {
        return;
      }
      const state = stateRef.current;
      state.onSelect?.(pickResource(
        state.graph,
        cameraRef.current,
        canvas.clientWidth,
        canvas.clientHeight,
        point.x,
        point.y,
      ));
    };
    const pointerCancel = () => {
      dragRef.current = null;
    };
    const wheel = (event: WheelEvent) => {
      event.preventDefault();
      cameraRef.current.scale = architectureZoomScale(
        cameraRef.current.scale,
        event.deltaY < 0 ? "in" : "out",
      );
      draw();
      notifyZoom();
    };
    canvas.addEventListener("pointerdown", pointerDown);
    canvas.addEventListener("pointermove", pointerMove);
    canvas.addEventListener("pointerup", pointerUp);
    canvas.addEventListener("pointercancel", pointerCancel);
    canvas.addEventListener("wheel", wheel, { passive: false });
    resize();
    return () => {
      observer.disconnect();
      themeObserver.disconnect();
      canvas.removeEventListener("pointerdown", pointerDown);
      canvas.removeEventListener("pointermove", pointerMove);
      canvas.removeEventListener("pointerup", pointerUp);
      canvas.removeEventListener("pointercancel", pointerCancel);
      canvas.removeEventListener("wheel", wheel);
      drawRef.current = null;
    };
  }, []);

  useEffect(() => { drawRef.current?.(); }, [selectedId, highlightedIds, options]);
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !drawRef.current) return;
    fitCamera(cameraRef.current, canvas.clientWidth, canvas.clientHeight);
    fitScaleRef.current = cameraRef.current.scale;
    drawRef.current();
    notifyZoom();
  }, [graph]);

  return canvasRef;
}

function architectureMapPalette(canvas: HTMLCanvasElement): ArchitectureMapPalette {
  const styles = getComputedStyle(canvas);
  const color = (name: string, fallback: string) => styles.getPropertyValue(name).trim() || fallback;
  return {
    background: color("--architecture-map-background", DEFAULT_ARCHITECTURE_MAP_PALETTE.background),
    surface: color("--architecture-map-surface", DEFAULT_ARCHITECTURE_MAP_PALETTE.surface),
    surfaceBorder: color("--architecture-map-surface-border", DEFAULT_ARCHITECTURE_MAP_PALETTE.surfaceBorder),
    labelBackground: color("--architecture-map-label-background", DEFAULT_ARCHITECTURE_MAP_PALETTE.labelBackground),
    selectedLabelBackground: color("--architecture-map-selected-label-background", DEFAULT_ARCHITECTURE_MAP_PALETTE.selectedLabelBackground),
    labelText: color("--architecture-map-label-text", DEFAULT_ARCHITECTURE_MAP_PALETTE.labelText),
    selectedLabelText: color("--architecture-map-selected-label-text", DEFAULT_ARCHITECTURE_MAP_PALETTE.selectedLabelText),
  };
}
