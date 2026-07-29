import { CopyButton } from "./ui";
import { routeHref } from "../router";
import { t } from "../routes/i18n/architecture";
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
  top: "camera.top",
  iso: "camera.iso",
  front: "camera.front",
};

const LAYER_LABELS = {
  scope: "layer.scope",
  network: "layer.network",
  security: "layer.security",
  runtime: "layer.runtime",
  data: "layer.data",
  messaging: "layer.messaging",
  observability: "layer.observability",
} as const;

export function architectureRelationshipLabel(
  link: InventoryLink,
  selectedId: string,
): string {
  if (link.type === "contains") return t(link.source === selectedId ? "relationship.contains" : "relationship.containedBy");
  if (link.type === "attached_to") return t("relationship.attachedTo");
  return t(link.source === selectedId ? "relationship.dependsOn" : "relationship.requiredBy");
}

export function architectureStatusLabel(status: string): string {
  if (status.trim().toLowerCase() === "unknown") return t("statusUnavailable");
  return status.replaceAll(/[._-]+/g, " ").replace(/^./, (character) => character.toUpperCase());
}

export function architectureOntologyMapHref(resourceId: string): string {
  return routeHref("ontology", { params: { view: "map", root: resourceId } });
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

  return (
    <aside class="architecture-inspector" aria-label={t("details")}>
      <section class="architecture-selection-section" aria-live="polite">
        {selected ? (
          <>
            <span class="eyebrow">{t(LAYER_LABELS[layerOf(selected)])}</span>
            <h3>{selected.name}</h3>
            <div class={`architecture-resource-status${selected.status.toLowerCase() === "unknown" ? " is-unknown" : ""}`}>
              <span aria-hidden="true" />
              {architectureStatusLabel(selected.status)}
            </div>
            {selected.status.toLowerCase() === "unknown" ? (
              <p class="architecture-status-note">{t("statusNotReported")}</p>
            ) : null}
            <dl class="architecture-resource-summary">
              <dt>{t("resourceType")}</dt>
              <dd>{RESOURCE_COLOR_TOKENS[resourceColorTokenOf(selected)].label}</dd>
              <dt>{t("parentBoundary")}</dt>
              <dd>
                {parent ? (
                  <button type="button" class="architecture-text-button" onClick={() => onSelect(parent)}>
                    {parent.name}
                  </button>
                ) : t("tenant")}
              </dd>
            </dl>
            <div class="architecture-resource-actions">
              <a class="btn architecture-primary-action" href={routeHref("blast-radius", { params: { target: selected.id, view: graph.active_view } })}>
                {t("viewImpactScope")}
              </a>
              <a class="btn architecture-primary-action" href={architectureOntologyMapHref(selected.id)}>
                {t("openOntologyMap")}
              </a>
            </div>
            <section class="architecture-relationships" aria-labelledby="selected-relationships-title">
              <h4 id="selected-relationships-title">{t("directRelationships")}</h4>
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
              ) : <p>{t("noDirectRelationships")}</p>}
            </section>
            <details class="architecture-technical-details">
              <summary>{t("technicalDetails")}</summary>
              <dl>
                <dt>{t("canonicalType")}</dt><dd><code>{selected.type}</code></dd>
                <dt>{t("resourceId")}</dt>
                <dd>
                  <code>{selected.id}</code>
                  <CopyButton text={selected.id} label={t("copyResourceId")} />
                </dd>
              </dl>
            </details>
          </>
        ) : (
          <div class="architecture-empty-inspector">
            <strong>{t("selectResource")}</strong>
            <p>{t("selectionHint")}</p>
          </div>
        )}
      </section>
      <details class="architecture-map-settings">
        <summary>{t("mapDisplay")}</summary>
        <h4>{t("view")}</h4>
        <div class="architecture-camera-control" role="group" aria-label={t("cameraView")}>
          {(["top", "iso", "front"] as const).map((view) => (
            <button
              type="button"
              class={cameraView === view ? "is-active" : ""}
              aria-pressed={cameraView === view}
              onClick={() => onCameraViewChange(view)}
            >
              {t(CAMERA_LABELS[view])}
            </button>
          ))}
        </div>
        <h4>{t("display")}</h4>
        <div class="architecture-display-options">
          {([
            ["showConnections", "displayOption.relationships"],
            ["showLabels", "displayOption.labels"],
            ["showReflections", "displayOption.reflections"],
            ["showGrid", "displayOption.gridPoints"],
          ] as const).map(([key, label]) => (
            <label><input type="checkbox" checked={displayOptions[key]} onChange={() => onToggleDisplay(key)} />{t(label)}</label>
          ))}
        </div>
      </details>
    </aside>
  );
}
