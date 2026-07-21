import { CopyButton } from "./ui";
import { routeHref } from "../router";
import {
  RESOURCE_COLOR_TOKENS,
  layerOf,
  resourceColorTokenOf,
  type ArchitectureCameraView,
  type ArchitectureDisplayOptions,
  type InventoryGraphResponse,
  type InventoryLink,
  type InventoryResource,
} from "./architecture-map.model";

interface Props {
  readonly graph: InventoryGraphResponse;
  readonly selected: InventoryResource | null;
  readonly onSelect: (resource: InventoryResource | null) => void;
  readonly cameraView: ArchitectureCameraView;
  readonly onCameraViewChange: (view: ArchitectureCameraView) => void;
  readonly displayOptions: ArchitectureDisplayOptions;
  readonly onToggleDisplay: (key: keyof ArchitectureDisplayOptions) => void;
}

const CAMERA_LABELS: Readonly<Record<ArchitectureCameraView, string>> = {
  top: "Top",
  iso: "Iso",
  front: "Front",
};

const LAYER_LABELS = {
  scope: "Scope",
  network: "Network",
  security: "Security",
  runtime: "Runtime",
  data: "Data",
  messaging: "Messaging",
  observability: "Observability",
} as const;

export function architectureRelationshipLabel(
  link: InventoryLink,
  selectedId: string,
): string {
  if (link.type === "contains") return link.source === selectedId ? "Contains" : "Contained by";
  if (link.type === "attached_to") return "Attached to";
  return link.source === selectedId ? "Depends on" : "Required by";
}

export function architectureStatusLabel(status: string): string {
  if (status.trim().toLowerCase() === "unknown") return "Status unavailable";
  return status.replaceAll(/[._-]+/g, " ").replace(/^./, (character) => character.toUpperCase());
}

export function ArchitectureInspector({
  graph,
  selected,
  onSelect,
  cameraView,
  onCameraViewChange,
  displayOptions,
  onToggleDisplay,
}: Props) {
  const byId = new Map(graph.resources.map((resource) => [resource.id, resource]));
  const parent = selected?.parent_id ? byId.get(selected.parent_id) ?? null : null;
  const relationships = selected
    ? graph.links.filter((link) => link.source === selected.id || link.target === selected.id)
    : [];
  const colorTokens = [...new Set(graph.resources.map(resourceColorTokenOf))];

  return (
    <aside class="architecture-inspector" aria-label="Architecture details">
      <section class="architecture-selection-section" aria-live="polite">
        {selected ? (
          <>
            <span class="eyebrow">{LAYER_LABELS[layerOf(selected)]}</span>
            <h3>{selected.name}</h3>
            <div class={`architecture-resource-status${selected.status.toLowerCase() === "unknown" ? " is-unknown" : ""}`}>
              <span aria-hidden="true" />
              {architectureStatusLabel(selected.status)}
            </div>
            {selected.status.toLowerCase() === "unknown" ? (
              <p class="architecture-status-note">The inventory did not report a status for this resource.</p>
            ) : null}
            <dl class="architecture-resource-summary">
              <dt>Resource type</dt>
              <dd>{RESOURCE_COLOR_TOKENS[resourceColorTokenOf(selected)].label}</dd>
              <dt>Parent boundary</dt>
              <dd>
                {parent ? (
                  <button type="button" class="architecture-text-button" onClick={() => onSelect(parent)}>
                    {parent.name}
                  </button>
                ) : "Tenant"}
              </dd>
            </dl>
            <a class="btn architecture-primary-action" href={routeHref("blast-radius", { params: { target: selected.id, view: graph.active_view } })}>
              View impact scope
            </a>
            <section class="architecture-relationships" aria-labelledby="selected-relationships-title">
              <h4 id="selected-relationships-title">Direct relationships</h4>
              {relationships.length > 0 ? (
                <ul>
                  {relationships.map((link) => {
                    const relatedId = link.source === selected.id ? link.target : link.source;
                    const related = byId.get(relatedId);
                    if (!related) return null;
                    return (
                      <li key={`${link.source}:${link.type}:${link.target}`}>
                        <span>{architectureRelationshipLabel(link, selected.id)}</span>
                        <button type="button" onClick={() => onSelect(related)}>{related.name}</button>
                      </li>
                    );
                  })}
                </ul>
              ) : <p>No direct relationships were reported.</p>}
            </section>
            <details class="architecture-technical-details">
              <summary>Technical details</summary>
              <dl>
                <dt>Canonical type</dt><dd><code>{selected.type}</code></dd>
                <dt>Resource ID</dt>
                <dd>
                  <code>{selected.id}</code>
                  <CopyButton text={selected.id} label="Copy resource ID" />
                </dd>
              </dl>
            </details>
          </>
        ) : (
          <div class="architecture-empty-inspector">
            <strong>Select a resource</strong>
            <p>Resource status, boundary, and direct relationships appear here.</p>
          </div>
        )}
      </section>
      <details class="architecture-map-settings">
        <summary>Map display</summary>
        <h4>View</h4>
        <div class="architecture-camera-control" role="group" aria-label="Camera view">
          {(["top", "iso", "front"] as const).map((view) => (
            <button
              type="button"
              class={cameraView === view ? "is-active" : ""}
              aria-pressed={cameraView === view}
              onClick={() => onCameraViewChange(view)}
            >
              {CAMERA_LABELS[view]}
            </button>
          ))}
        </div>
        <h4>Display</h4>
        <div class="architecture-display-options">
          {([
            ["showConnections", "Relationships"],
            ["showLabels", "Labels"],
            ["showReflections", "Reflections"],
            ["showGrid", "Grid points"],
          ] as const).map(([key, label]) => (
            <label><input type="checkbox" checked={displayOptions[key]} onChange={() => onToggleDisplay(key)} />{label}</label>
          ))}
        </div>
        <h4>Resource legend</h4>
        <div class="architecture-color-legend" aria-label="Resource type colors">
          {colorTokens.map((token) => (
            <span>
              <i style={{ backgroundColor: RESOURCE_COLOR_TOKENS[token].color }} aria-hidden="true" />
              {RESOURCE_COLOR_TOKENS[token].label}
            </span>
          ))}
        </div>
      </details>
    </aside>
  );
}
