import { forwardRef } from "preact/compat";
import { architectureResourceFromValue } from "./architecture-map.geometry";
import {
  ARCHITECTURE_LAYERS,
  RESOURCE_COLOR_TOKENS,
  layerOf,
  resourceColorTokenOf,
  type ArchitectureCameraView,
  type ArchitectureDisplayOptions,
  type ArchitectureLayer,
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
  readonly descriptionId?: string;
}

export interface ArchitectureMapHandle {
  readonly setView: (view: ArchitectureCameraView) => void;
  readonly zoomIn: () => void;
  readonly zoomOut: () => void;
  readonly fit: () => void;
}

const DEFAULT_OPTIONS: ArchitectureDisplayOptions = {
  showConnections: true,
  showReflections: false,
  showLabels: true,
  showGrid: false,
};

const LAYER_LABELS: Readonly<Record<ArchitectureLayer, string>> = {
  scope: "Scope and boundaries",
  network: "Network",
  security: "Security",
  runtime: "Runtime",
  data: "Data",
  messaging: "Messaging",
  observability: "Observability",
};

export const ArchitectureMap = forwardRef<ArchitectureMapHandle, Props>(function ArchitectureMap({
  graph,
  selectedId = null,
  highlightedIds,
  onSelect,
  className = "",
  options = DEFAULT_OPTIONS,
  onZoomChange,
  descriptionId,
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
      <canvas
        ref={canvasRef}
        class="architecture-map"
        role="img"
        aria-label={`Resource architecture map with ${graph.resources.length} resources`}
        aria-describedby={descriptionId}
      />
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
          {ARCHITECTURE_LAYERS.map((layer) => {
            const resources = graph.resources
              .filter((resource) => layerOf(resource) === layer)
              .sort((first, second) => first.name.localeCompare(second.name));
            if (resources.length === 0) return null;
            return (
              <optgroup label={LAYER_LABELS[layer]}>
                {resources.map((resource) => (
                  <option key={resource.id} value={resource.id}>
                    {resource.name} - {RESOURCE_COLOR_TOKENS[resourceColorTokenOf(resource)].label}
                  </option>
                ))}
              </optgroup>
            );
          })}
        </select>
      </label>
    </div>
  );
});
