import type { ComponentChildren } from "preact";
import { Tooltip } from "./tooltip";
import "./graph-control-bar.css";

export type GraphLegendSwatchKind =
  | "solid"
  | "dashed"
  | "dotted"
  | "thick"
  | "arrow"
  | "double";

export interface GraphLegendSwatchProps {
  readonly kind?: GraphLegendSwatchKind;
  readonly stroke?: string;
  readonly width?: number;
  readonly className?: string;
}

/**
 * Accessible inline SVG line/arrow marker for graph legends.
 * Replaces CSS border-top / border-left colored line hacks.
 */
export function GraphLegendSwatch({
  kind = "solid",
  stroke = "currentColor",
  width = 22,
  className,
}: GraphLegendSwatchProps) {
  const height = 12;
  const midY = 6;
  const classes = className ? `cs-graph-legend-swatch ${className}` : "cs-graph-legend-swatch";
  const strokeWidth = kind === "thick" ? 3.5 : 2;
  const strokeDasharray = kind === "dashed"
    ? "4 2.5"
    : kind === "dotted"
      ? "1.8 2.5"
      : undefined;

  return (
    <svg
      class={classes}
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      fill="none"
      aria-hidden="true"
    >
      {kind === "double" ? (
        <>
          <line x1="0" y1="4" x2={width} y2="4" stroke={stroke} stroke-width="1.5" />
          <line x1="0" y1="8" x2={width} y2="8" stroke={stroke} stroke-width="1.5" />
        </>
      ) : kind === "arrow" ? (
        <>
          <line x1="0" y1={midY} x2={Math.max(4, width - 6)} y2={midY} stroke={stroke} stroke-width="2" />
          <path
            d={`M ${width - 6} 2.5 L ${width} ${midY} L ${width - 6} 9.5 Z`}
            fill={stroke}
          />
        </>
      ) : (
        <line
          x1="0"
          y1={midY}
          x2={width}
          y2={midY}
          stroke={stroke}
          stroke-width={strokeWidth}
          stroke-dasharray={strokeDasharray}
          stroke-linecap={kind === "dotted" ? "round" : "butt"}
        />
      )}
    </svg>
  );
}

export interface GraphLegendItem {
  readonly id: string;
  readonly label: string;
  readonly kind?: GraphLegendSwatchKind;
  readonly stroke?: string;
  readonly count?: string;
}

export interface GraphControlBarProps {
  readonly ariaLabel: string;
  readonly scale?: number;
  readonly minScale?: number;
  readonly maxScale?: number;
  readonly onZoomOut?: () => void;
  readonly onZoomIn?: () => void;
  readonly onFit?: () => void;
  readonly zoomOutLabel?: string;
  readonly zoomInLabel?: string;
  readonly zoomLevelLabel?: string;
  readonly fitLabel?: string;
  readonly fitAriaLabel?: string;
  readonly fullscreen?: boolean;
  readonly onToggleFullscreen?: () => void;
  readonly fullscreenLabel?: string;
  readonly exitFullscreenLabel?: string;
  readonly inspectorOpen?: boolean;
  readonly onToggleInspector?: () => void;
  readonly inspectorLabel?: string;
  readonly filters?: ComponentChildren;
  readonly legendItems?: readonly GraphLegendItem[];
  readonly legendAriaLabel?: string;
  readonly className?: string;
}

/**
 * Shared zoom, fit, fullscreen, inspector, and SVG legend toolbar for
 * Ontology, Blast Radius, and Architecture graph surfaces.
 */
export function GraphControlBar({
  ariaLabel,
  scale,
  minScale,
  maxScale,
  onZoomOut,
  onZoomIn,
  onFit,
  zoomOutLabel = "Zoom out",
  zoomInLabel = "Zoom in",
  zoomLevelLabel = "Zoom level",
  fitLabel = "Fit",
  fitAriaLabel = "Fit graph to view",
  fullscreen = false,
  onToggleFullscreen,
  fullscreenLabel = "Fullscreen",
  exitFullscreenLabel = "Exit fullscreen",
  inspectorOpen,
  onToggleInspector,
  inspectorLabel = "Toggle inspector",
  filters,
  legendItems,
  legendAriaLabel,
  className,
}: GraphControlBarProps) {
  const hasZoomControls = Boolean(onZoomOut || onZoomIn || onFit || scale !== undefined);
  const resolvedFullscreenLabel = fullscreen ? exitFullscreenLabel : fullscreenLabel;

  return (
    <div
      class={className ? `cs-graph-control-bar ${className}` : "cs-graph-control-bar"}
      role="toolbar"
      aria-label={ariaLabel}
    >
      {filters ? <div class="cs-graph-control-filters">{filters}</div> : null}

      {hasZoomControls ? (
        <div class="cs-graph-control-group">
          {onZoomOut ? (
            <Tooltip content={zoomOutLabel}>
              <button
                type="button"
                class="cs-graph-control-btn"
                aria-label={zoomOutLabel}
                disabled={scale !== undefined && minScale !== undefined && scale <= minScale}
                onClick={onZoomOut}
              >
                -
              </button>
            </Tooltip>
          ) : null}
          {scale !== undefined ? (
            <output class="cs-graph-control-zoom" aria-label={zoomLevelLabel}>
              {`${Math.round(scale * 100)}%`}
            </output>
          ) : null}
          {onZoomIn ? (
            <Tooltip content={zoomInLabel}>
              <button
                type="button"
                class="cs-graph-control-btn"
                aria-label={zoomInLabel}
                disabled={scale !== undefined && maxScale !== undefined && scale >= maxScale}
                onClick={onZoomIn}
              >
                +
              </button>
            </Tooltip>
          ) : null}
          {onFit ? (
            <Tooltip content={fitAriaLabel}>
              <button
                type="button"
                class="cs-graph-control-btn"
                aria-label={fitAriaLabel}
                onClick={onFit}
              >
                {fitLabel}
              </button>
            </Tooltip>
          ) : null}
        </div>
      ) : null}

      {(onToggleInspector || onToggleFullscreen) ? (
        <div class="cs-graph-control-group">
          {onToggleInspector ? (
            <Tooltip content={inspectorLabel}>
              <button
                type="button"
                class="cs-graph-control-btn"
                aria-label={inspectorLabel}
                aria-pressed={inspectorOpen}
                onClick={onToggleInspector}
              >
                <svg
                  width="14"
                  height="14"
                  viewBox="0 0 16 16"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="1.5"
                  aria-hidden="true"
                >
                  <rect x="2" y="2.5" width="12" height="11" rx="1.5" />
                  <line x1="10" y1="2.5" x2="10" y2="13.5" />
                </svg>
              </button>
            </Tooltip>
          ) : null}
          {onToggleFullscreen ? (
            <Tooltip content={resolvedFullscreenLabel}>
              <button
                type="button"
                class="cs-graph-control-btn"
                aria-label={resolvedFullscreenLabel}
                aria-pressed={fullscreen}
                onClick={onToggleFullscreen}
              >
                <span aria-hidden="true">{fullscreen ? "x" : "[]"}</span>
              </button>
            </Tooltip>
          ) : null}
        </div>
      ) : null}

      {legendItems && legendItems.length > 0 ? (
        <ul class="cs-graph-legend-list" aria-label={legendAriaLabel ?? ariaLabel}>
          {legendItems.map((item) => (
            <li key={item.id} class="cs-graph-legend-item">
              <GraphLegendSwatch
                {...(item.kind !== undefined ? { kind: item.kind } : {})}
                {...(item.stroke !== undefined ? { stroke: item.stroke } : {})}
              />
              <strong>{item.label}</strong>
              {item.count ? <span>{item.count}</span> : null}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
