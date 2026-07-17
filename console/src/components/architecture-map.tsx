import { forwardRef } from "preact/compat";
import { architectureResourceFromValue } from "./architecture-map.geometry";
import {
  type ArchitectureCameraView,
  type ArchitectureDisplayOptions,
  type InventoryGraphResponse,
  type InventoryResource,
} from "./architecture-map.model";
import { useArchitectureMapController } from "./use-architecture-map-controller";

export { architectureResourceFromValue } from "./architecture-map.geometry";

interface Props {
  readonly graph: InventoryGraphResponse;
  readonly selectedId?: string | null;
  readonly highlightedIds?: ReadonlySet<string>;
  readonly onSelect?: (resource: InventoryResource | null) => void;
  readonly className?: string;
  readonly options?: ArchitectureDisplayOptions;
  readonly onZoomChange?: (percent: number) => void;
}

export interface ArchitectureMapHandle {
  readonly setView: (view: ArchitectureCameraView) => void;
  readonly zoomIn: () => void;
  readonly zoomOut: () => void;
  readonly fit: () => void;
}

const DEFAULT_OPTIONS: ArchitectureDisplayOptions = {
  showConnections: true,
  showReflections: true,
  showLabels: true,
  showGrid: true,
};

export const ArchitectureMap = forwardRef<ArchitectureMapHandle, Props>(function ArchitectureMap({
  graph,
  selectedId = null,
  highlightedIds,
  onSelect,
  className = "",
  options = DEFAULT_OPTIONS,
  onZoomChange,
}, forwardedRef) {
  const canvasRef = useArchitectureMapController({
    graph,
    selectedId,
    highlightedIds,
    onSelect,
    options,
    onZoomChange,
    forwardedRef,
  });

  return (
    <div class={`architecture-map-frame ${className}`}>
      <canvas ref={canvasRef} class="architecture-map" aria-label="Resource architecture map" />
      <label class="architecture-resource-picker">
        <span class="sr-only">Select architecture resource</span>
        <select
          aria-label="Select architecture resource"
          value={selectedId ?? ""}
          disabled={onSelect === undefined}
          onChange={(event) => onSelect?.(
            architectureResourceFromValue(graph.resources, event.currentTarget.value),
          )}
        >
          <option value="">Select resource</option>
          {graph.resources.map((resource) => (
            <option key={resource.id} value={resource.id}>
              {resource.name} - {resource.type}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
});
