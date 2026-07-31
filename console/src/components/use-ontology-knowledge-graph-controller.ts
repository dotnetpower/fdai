import type { RefObject } from "preact";
import { useEffect, useLayoutEffect, useRef } from "preact/hooks";
import {
  cloneOntologyKnowledgeGraph,
  fitOntologyKnowledgeGraph,
  hitTestOntologyNode,
  indexOntologyKnowledgeGraph,
  ontologyScreenToWorld,
  type KnowledgeGraphCamera,
} from "./ontology-knowledge-graph.geometry";
import type {
  OntologyKnowledgeEdgeKind,
  OntologyKnowledgeGraph,
} from "./ontology-knowledge-graph.model";
import {
  renderOntologyKnowledgeGraph,
  type OntologyKnowledgeGraphPalette,
} from "./ontology-knowledge-graph.renderer";

interface ControllerOptions {
  readonly graph: OntologyKnowledgeGraph;
  readonly selectedId: string | null;
  readonly enabledEdges: ReadonlySet<OntologyKnowledgeEdgeKind>;
  readonly onSelect: (id: string | null) => void;
}

export interface OntologyKnowledgeGraphController {
  readonly canvasRef: RefObject<HTMLCanvasElement>;
  readonly viewportRef: RefObject<HTMLDivElement>;
  readonly fit: () => void;
  readonly zoomIn: () => void;
  readonly zoomOut: () => void;
  readonly focusNode: (id: string) => void;
}

type Gesture =
  | { readonly mode: "pan"; readonly startX: number; readonly startY: number; readonly cameraX: number; readonly cameraY: number; moved: boolean }
  | { readonly mode: "node"; readonly startX: number; readonly startY: number; readonly nodeId: string; readonly nodeX: number; readonly nodeY: number; moved: boolean };

interface ControllerActions {
  fit: () => void;
  zoomIn: () => void;
  zoomOut: () => void;
  focusNode: (id: string) => void;
}

const NOOP_ACTIONS: ControllerActions = {
  fit: () => undefined,
  zoomIn: () => undefined,
  zoomOut: () => undefined,
  focusNode: () => undefined,
};

function paletteFor(element: HTMLElement): OntologyKnowledgeGraphPalette {
  const styles = getComputedStyle(element);
  const dark = document.documentElement.getAttribute("data-theme") === "dark";
  const token = (name: string, fallback: string) => styles.getPropertyValue(name).trim() || fallback;
  return {
    background: token("--bg", dark ? "#15191d" : "#fbfaf9"),
    foreground: token("--fg", dark ? "#f0f2f4" : "#2c333a"),
    muted: token("--fg-muted", dark ? "#a8b0b8" : "#59616a"),
    selected: token("--accent-strong", dark ? "#8bb7df" : "#44688e"),
    hovered: dark ? "#c5d0da" : "#5f6b75",
    labelBackground: dark ? "rgba(21,25,29,.92)" : "rgba(255,255,255,.90)",
    nodeStroke: dark ? "rgba(21,25,29,.95)" : "rgba(255,255,255,.95)",
    grid: dark ? "rgba(139,183,223,.075)" : "rgba(68,104,142,.055)",
    hull: dark ? "rgba(139,183,223,.035)" : "rgba(68,104,142,.025)",
    hullStroke: dark ? "rgba(139,183,223,.20)" : "rgba(68,104,142,.16)",
    selectedHull: dark ? "rgba(139,183,223,.10)" : "rgba(68,104,142,.07)",
  };
}

export function useOntologyKnowledgeGraphController({
  graph,
  selectedId,
  enabledEdges,
  onSelect,
}: ControllerOptions): OntologyKnowledgeGraphController {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const viewportRef = useRef<HTMLDivElement>(null);
  const selectedIdRef = useRef(selectedId);
  const enabledEdgesRef = useRef(enabledEdges);
  const onSelectRef = useRef(onSelect);
  const requestDrawRef = useRef<() => void>(() => undefined);
  const actionsRef = useRef<ControllerActions>(NOOP_ACTIONS);
  selectedIdRef.current = selectedId;
  enabledEdgesRef.current = enabledEdges;
  onSelectRef.current = onSelect;

  useEffect(() => requestDrawRef.current(), [selectedId, enabledEdges]);

  useLayoutEffect(() => {
    const canvas = canvasRef.current;
    const viewport = viewportRef.current;
    const context = canvas?.getContext("2d");
    if (!canvas || !viewport || !context) return undefined;

    const mutableGraph = cloneOntologyKnowledgeGraph(graph);
    const index = indexOntologyKnowledgeGraph(mutableGraph);
    const camera: KnowledgeGraphCamera = { x: 0, y: 0, scale: 1 };
    let hoveredId: string | null = null;
    let gesture: Gesture | null = null;
    let pendingPointer: { readonly x: number; readonly y: number } | null = null;
    let drawFrame: number | null = null;
    let pointerFrame: number | null = null;

    const draw = () => {
      drawFrame = null;
      const rect = viewport.getBoundingClientRect();
      renderOntologyKnowledgeGraph(context, rect.width, rect.height, {
        graph: mutableGraph,
        index,
        camera,
        selectedId: selectedIdRef.current,
        hoveredId,
        enabledEdges: enabledEdgesRef.current,
        palette: paletteFor(viewport),
      });
    };
    const requestDraw = () => {
      if (drawFrame === null) drawFrame = requestAnimationFrame(draw);
    };
    requestDrawRef.current = requestDraw;

    const fit = () => {
      Object.assign(camera, fitOntologyKnowledgeGraph(mutableGraph, viewport.clientWidth, viewport.clientHeight));
      requestDraw();
    };
    const zoomAt = (factor: number, screenX: number, screenY: number) => {
      const world = ontologyScreenToWorld({ x: screenX, y: screenY }, camera);
      const scale = Math.max(.18, Math.min(4, camera.scale * factor));
      camera.x = screenX - world.x * scale;
      camera.y = screenY - world.y * scale;
      camera.scale = scale;
      requestDraw();
    };
    const focusNode = (id: string) => {
      const node = index.nodeById.get(id);
      if (!node) return;
      camera.scale = Math.max(1.05, camera.scale);
      camera.x = viewport.clientWidth / 2 - node.x * camera.scale;
      camera.y = viewport.clientHeight / 2 - node.y * camera.scale;
      onSelectRef.current(id);
      requestDraw();
    };
    actionsRef.current = {
      fit,
      zoomIn: () => zoomAt(1.25, viewport.clientWidth / 2, viewport.clientHeight / 2),
      zoomOut: () => zoomAt(.8, viewport.clientWidth / 2, viewport.clientHeight / 2),
      focusNode,
    };

    const resize = () => {
      const ratio = Math.min(2, window.devicePixelRatio || 1);
      const rect = viewport.getBoundingClientRect();
      canvas.width = Math.max(1, Math.round(rect.width * ratio));
      canvas.height = Math.max(1, Math.round(rect.height * ratio));
      canvas.style.width = `${rect.width}px`;
      canvas.style.height = `${rect.height}px`;
      context.setTransform(ratio, 0, 0, ratio, 0, 0);
    };
    const pointFor = (event: PointerEvent | WheelEvent) => {
      const rect = viewport.getBoundingClientRect();
      return { x: event.clientX - rect.left, y: event.clientY - rect.top };
    };
    const applyPendingPointer = () => {
      pointerFrame = null;
      if (!gesture || !pendingPointer) return;
      const deltaX = pendingPointer.x - gesture.startX;
      const deltaY = pendingPointer.y - gesture.startY;
      gesture.moved ||= Math.abs(deltaX) + Math.abs(deltaY) > 3;
      if (gesture.mode === "node") {
        const node = index.nodeById.get(gesture.nodeId);
        if (node) {
          node.x = gesture.nodeX + deltaX / camera.scale;
          node.y = gesture.nodeY + deltaY / camera.scale;
        }
      } else {
        camera.x = gesture.cameraX + deltaX;
        camera.y = gesture.cameraY + deltaY;
      }
      pendingPointer = null;
      requestDraw();
    };
    const pointerDown = (event: PointerEvent) => {
      if (event.button !== 0) return;
      const point = pointFor(event);
      const hit = hitTestOntologyNode(mutableGraph, camera, point);
      gesture = hit
        ? { mode: "node", nodeId: hit.id, nodeX: hit.x, nodeY: hit.y, startX: event.clientX, startY: event.clientY, moved: false }
        : { mode: "pan", cameraX: camera.x, cameraY: camera.y, startX: event.clientX, startY: event.clientY, moved: false };
      viewport.setPointerCapture(event.pointerId);
      viewport.classList.add("is-dragging");
    };
    const pointerMove = (event: PointerEvent) => {
      if (gesture) {
        pendingPointer = { x: event.clientX, y: event.clientY };
        if (pointerFrame === null) pointerFrame = requestAnimationFrame(applyPendingPointer);
        return;
      }
      const hit = hitTestOntologyNode(mutableGraph, camera, pointFor(event));
      const nextHovered = hit?.id ?? null;
      if (nextHovered !== hoveredId) {
        hoveredId = nextHovered;
        requestDraw();
      }
    };
    const pointerUp = (event: PointerEvent) => {
      applyPendingPointer();
      if (gesture && !gesture.moved) {
        onSelectRef.current(gesture.mode === "node" ? gesture.nodeId : null);
      }
      gesture = null;
      pendingPointer = null;
      viewport.classList.remove("is-dragging");
      if (viewport.hasPointerCapture(event.pointerId)) viewport.releasePointerCapture(event.pointerId);
      requestDraw();
    };
    const pointerCancel = () => {
      gesture = null;
      pendingPointer = null;
      viewport.classList.remove("is-dragging");
    };
    const wheel = (event: WheelEvent) => {
      event.preventDefault();
      const point = pointFor(event);
      zoomAt(event.deltaY < 0 ? 1.12 : .89, point.x, point.y);
    };

    viewport.addEventListener("pointerdown", pointerDown);
    viewport.addEventListener("pointermove", pointerMove);
    viewport.addEventListener("pointerup", pointerUp);
    viewport.addEventListener("pointercancel", pointerCancel);
    viewport.addEventListener("wheel", wheel, { passive: false });
    const observer = new ResizeObserver(() => {
      resize();
      if (selectedIdRef.current === null) {
        Object.assign(camera, fitOntologyKnowledgeGraph(mutableGraph, viewport.clientWidth, viewport.clientHeight));
      }
      draw();
    });
    observer.observe(viewport);
    resize();
    Object.assign(camera, fitOntologyKnowledgeGraph(mutableGraph, viewport.clientWidth, viewport.clientHeight));
    draw();

    return () => {
      observer.disconnect();
      viewport.removeEventListener("pointerdown", pointerDown);
      viewport.removeEventListener("pointermove", pointerMove);
      viewport.removeEventListener("pointerup", pointerUp);
      viewport.removeEventListener("pointercancel", pointerCancel);
      viewport.removeEventListener("wheel", wheel);
      if (drawFrame !== null) cancelAnimationFrame(drawFrame);
      if (pointerFrame !== null) cancelAnimationFrame(pointerFrame);
      requestDrawRef.current = () => undefined;
      actionsRef.current = NOOP_ACTIONS;
    };
  }, [graph]);

  return {
    canvasRef,
    viewportRef,
    fit: () => actionsRef.current.fit(),
    zoomIn: () => actionsRef.current.zoomIn(),
    zoomOut: () => actionsRef.current.zoomOut(),
    focusNode: (id) => actionsRef.current.focusNode(id),
  };
}
