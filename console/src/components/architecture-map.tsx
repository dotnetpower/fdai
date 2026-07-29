import { forwardRef } from "preact/compat";
import { t } from "../routes/i18n/architecture";
import { architectureResourceFromValue } from "./architecture-map.geometry";
import {
  ARCHITECTURE_LAYERS,
  DEFAULT_ARCHITECTURE_DISPLAY_OPTIONS,
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

const LAYER_LABEL_KEYS: Readonly<Record<ArchitectureLayer, string>> = {
  scope: "layer.scopeAndBoundaries",
  network: "layer.network",
  security: "layer.security",
  runtime: "layer.runtime",
  data: "layer.data",
  messaging: "layer.messaging",
  observability: "layer.observability",
};

export function architectureMapLayerLabel(layer: ArchitectureLayer): string {
  return t(LAYER_LABEL_KEYS[layer]);
}

export function architectureMapAriaLabel(resourceCount: number): string {
  return t("mapAriaLabel", { count: resourceCount });
}

export function architectureMapSelectLabel(): string {
  return t("selectArchitectureResource");
}

export function architectureMapSelectOptionLabel(): string {
  return t("selectResourceOption");
}

export const ArchitectureMap = forwardRef<ArchitectureMapHandle, Props>(function ArchitectureMap({
  graph,
  selectedId = null,
  highlightedIds,
  onSelect,
  className = "",
  options = DEFAULT_ARCHITECTURE_DISPLAY_OPTIONS,
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
        aria-label={architectureMapAriaLabel(graph.resources.length)}
        aria-describedby={descriptionId}
      />
      <label class="architecture-resource-picker">
        <span class="sr-only">{architectureMapSelectLabel()}</span>
        <select
          aria-label={architectureMapSelectLabel()}
          value={selectedId ?? ""}
          disabled={onSelect === undefined}
          onChange={(event) => onSelect?.(
            architectureResourceFromValue(graph.resources, event.currentTarget.value),
          )}
        >
          <option value="">{architectureMapSelectOptionLabel()}</option>
          {ARCHITECTURE_LAYERS.map((layer) => {
            const resources = graph.resources
              .filter((resource) => layerOf(resource) === layer)
              .sort((first, second) => first.name.localeCompare(second.name));
            if (resources.length === 0) return null;
            return (
              <optgroup label={architectureMapLayerLabel(layer)}>
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
