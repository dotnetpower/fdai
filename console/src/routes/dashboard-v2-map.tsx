import type { JSX } from "preact";
import { useId, useRef, useState } from "preact/hooks";
import { Tooltip } from "../components/tooltip";
import {
  dashboardResourceState,
  STATE_STYLE,
  type DashboardLens,
  type DashboardResource,
  type DashboardSnapshot,
  type DashboardState,
} from "./dashboard-v2.model";
import "./dashboard-v2-map.css";

/** A bounded resource page and its owning snapshot; selection carries no operational authority. */
export interface DashboardResourceMapProps {
  readonly resources: readonly DashboardResource[];
  readonly snapshot: DashboardSnapshot;
  readonly lens: DashboardLens;
  readonly density: "dense" | "comfortable";
  readonly columns: number;
  readonly selectedId: string | null;
  readonly onSelect: (id: string) => void;
  readonly labels: {
    readonly operation: string;
    readonly availability: string;
    readonly observation: string;
    readonly observedAt: string;
    readonly snapshotAt: string;
    readonly missing: string;
    readonly state: (key: DashboardState) => string;
  };
}

const HEXAGON = "12,1 23,7.5 23,20.5 12,27 1,20.5 1,7.5";

function resourceTooltip(
  resource: DashboardResource,
  snapshot: DashboardSnapshot,
  labels: DashboardResourceMapProps["labels"],
) {
  const scope = [
    resource.subscriptionLabel ?? resource.subscription ?? labels.missing,
    resource.groupLabel ?? resource.group ?? labels.missing,
  ].join(" / ");
  const lenses: readonly DashboardLens[] = ["operation", "availability", "observation"];
  return (
    <span class="dashboard-v2-map-tooltip">
      <strong class="dashboard-v2-map-tooltip-name">{resource.name}</strong>
      <code class="dashboard-v2-map-tooltip-type">{resource.type}</code>
      <span class="dashboard-v2-map-tooltip-scope">{scope}</span>
      {snapshot.scope ? <span class="dashboard-v2-map-tooltip-scope">{snapshot.scope}</span> : null}
      <span class="dashboard-v2-map-tooltip-facts">
        {lenses.map((lens) => (
          <span class="dashboard-v2-map-tooltip-fact" key={lens}>
            <span>{labels[lens]}</span>
            <span class="dashboard-v2-map-tooltip-value">
              <span>{labels.state(dashboardResourceState(resource, snapshot, lens))}</span>
              {lens === "operation"
                ? <code>{resource.status.trim() ? resource.status : labels.missing}</code> : null}
            </span>
          </span>
        ))}
        <span class="dashboard-v2-map-tooltip-fact">
          <span>{labels.observedAt}</span>
          {resource.observedAt
            ? <time dateTime={resource.observedAt}>{resource.observedAt}</time>
            : <span>{labels.missing}</span>}
        </span>
        <span class="dashboard-v2-map-tooltip-fact">
          <span>{labels.snapshotAt}</span>
          <time dateTime={snapshot.at}>{snapshot.at}</time>
        </span>
      </span>
    </span>
  );
}

/**
 * Renders only the supplied page as individually selectable resource-state glyphs.
 * Arrow keys move focus spatially; Home/End reach the page boundaries without selecting.
 * Pointer selection never programmatically moves focus or scrolls the map.
 */
export function DashboardResourceMap({
  resources, snapshot, lens, density, columns, selectedId, onSelect, labels,
}: DashboardResourceMapProps) {
  const id = useId();
  const mapRef = useRef<HTMLDivElement | null>(null);
  const [focusedId, setFocusedId] = useState<string | null>(null);
  const columnCount = Number.isSafeInteger(columns) && columns > 0 ? columns : 1;
  const tabStop = resources.find((resource) => resource.id === focusedId)?.id
    ?? resources.find((resource) => resource.id === selectedId)?.id
    ?? resources[0]?.id;

  function onKeyDown(event: JSX.TargetedKeyboardEvent<HTMLButtonElement>, index: number): void {
    let next = index;
    switch (event.key) {
      case "ArrowLeft": next = Math.max(0, index - 1); break;
      case "ArrowRight": next = Math.min(resources.length - 1, index + 1); break;
      case "ArrowUp": next = index >= columnCount ? index - columnCount : index; break;
      case "ArrowDown":
        if (Math.floor(index / columnCount) < Math.floor((resources.length - 1) / columnCount)) {
          next = Math.min(resources.length - 1, index + columnCount);
        }
        break;
      case "Home": next = 0; break;
      case "End": next = resources.length - 1; break;
      default: return;
    }
    event.preventDefault();
    if (next === index) return;
    mapRef.current?.querySelectorAll<HTMLButtonElement>(".dashboard-v2-map-cell")[next]?.focus();
  }

  return (
    <div
      ref={mapRef}
      class="dashboard-v2-map"
      role="group"
      aria-label={labels[lens]}
      data-density={density}
      style={{ "--dashboard-v2-map-columns": String(columnCount) }}
    >
      <svg class="dashboard-v2-map-definitions" aria-hidden="true" focusable="false">
        <defs>
          <pattern id={`${id}-unknown`} width="4" height="4" patternUnits="userSpaceOnUse">
            <path d="M-1 1 1-1 M0 4 4 0 M3 5 5 3" fill="none" stroke="currentColor" stroke-width=".5" />
          </pattern>
          <pattern id={`${id}-na`} width="4" height="4" patternUnits="userSpaceOnUse">
            <circle cx="2" cy="2" r=".6" fill="currentColor" />
          </pattern>
        </defs>
      </svg>
      {resources.map((resource, index) => {
        const state = dashboardResourceState(resource, snapshot, lens);
        const style = STATE_STYLE[state];
        const row = Math.floor(index / columnCount);
        const pattern = style.tone === "unknown" ? `${id}-unknown`
          : style.tone === "na" ? `${id}-na` : null;
        return (
          <Tooltip
            key={resource.id}
            anchorClassName={`dashboard-v2-map-slot${row % 2 ? " is-offset" : ""}`}
            anchorStyle={{ gridColumn: index % columnCount + 1, gridRow: row + 1 }}
            content={resourceTooltip(resource, snapshot, labels)}
            placement="top"
          >
            <button
              type="button"
              class="dashboard-v2-map-cell"
              data-resource-id={resource.id}
              data-tone={style.tone}
              data-state={state}
              aria-label={`${resource.name}, ${resource.type}, ${labels[lens]}: ${labels.state(state)}`}
              aria-pressed={resource.id === selectedId}
              tabIndex={resource.id === tabStop ? 0 : -1}
              onFocus={() => setFocusedId(resource.id)}
              onKeyDown={(event: JSX.TargetedKeyboardEvent<HTMLButtonElement>) => onKeyDown(event, index)}
              onClick={() => onSelect(resource.id)}
            >
              <svg viewBox="0 0 24 28" aria-hidden="true" focusable="false">
                <polygon class="dashboard-v2-map-surface" points={HEXAGON} />
                {pattern
                  ? <polygon class="dashboard-v2-map-pattern" points={HEXAGON} fill={`url(#${pattern})`} />
                  : null}
                <polygon class="dashboard-v2-map-outline" points={HEXAGON} fill="none" />
                <text class="dashboard-v2-map-symbol" x="12" y="14" text-anchor="middle" dominant-baseline="central">
                  {style.symbol}
                </text>
              </svg>
            </button>
          </Tooltip>
        );
      })}
    </div>
  );
}
