import type { ComponentChildren } from "preact";
import { useEffect, useState } from "preact/hooks";
import { Tooltip } from "./tooltip";
import { CopyButton } from "./ui";
import { routeHref } from "../router";
import { t } from "../routes/i18n/architecture";
import {
  RESOURCE_COLOR_TOKENS,
  layerOf,
  resourceColorTokenOf,
  type ArchitecturePresentationMode,
  type InventoryGraphResponse,
  type InventoryLink,
  type InventoryResource,
} from "./architecture-map.model";
import "./architecture-inspector.css";

interface Props {
  readonly graph: InventoryGraphResponse;
  readonly displayedGraph: InventoryGraphResponse;
  readonly selected: InventoryResource | null;
  readonly onSelect: (resource: InventoryResource | null) => void;
  readonly mode: ArchitecturePresentationMode;
  readonly sourceLabel: string;
  readonly pathContent: ComponentChildren;
  readonly hidden: boolean;
  readonly onToggle: () => void;
}

type InspectorView = "overview" | "relationships" | "path" | "sources";

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
  if (link.type === "peered_with") return t("relationship.peersWith");
  return t(link.source === selectedId ? "relationship.dependsOn" : "relationship.requiredBy");
}

export function architectureStatusLabel(status: string): string {
  if (status.trim().toLowerCase() === "unknown") return t("statusUnavailable");
  return status.replaceAll(/[._-]+/g, " ").replace(/^./, (character) => character.toUpperCase());
}

export function ArchitectureInspector({
  graph,
  displayedGraph,
  selected,
  onSelect,
  mode,
  sourceLabel,
  pathContent,
  hidden,
  onToggle,
}: Props) {
  const [view, setView] = useState<InspectorView>(
    mode === "network" ? "path" : "overview",
  );
  const byId = new Map(graph.resources.map((resource) => [resource.id, resource]));
  const parent = selected?.parent_id ? byId.get(selected.parent_id) ?? null : null;
  const relationships = selected
    ? graph.links.filter((link) => link.source === selected.id || link.target === selected.id)
    : [];
  useEffect(() => {
    setView(mode === "network" ? "path" : "overview");
  }, [mode]);

  return (
    <aside
      id="architecture-inspector"
      class="architecture-inspector"
      aria-label={t("details")}
      hidden={hidden}
    >
      <header class="architecture-inspector-header">
        <strong>{t("inspector.title")}</strong>
        <Tooltip content={t("inspector.hide")}>
          <button
            type="button"
            class="architecture-inspector-toggle"
            aria-label={t("inspector.hide")}
            aria-expanded={true}
            aria-controls="architecture-inspector"
            onClick={onToggle}
          >
            <span aria-hidden="true" />
          </button>
        </Tooltip>
      </header>
      <nav class="architecture-inspector-tabs" aria-label={t("inspector.views")}>
        {(["overview", "relationships", ...(mode === "network" ? ["path"] as const : []), "sources"] as const)
          .map((item) => (
            <button
              type="button"
              class={view === item ? "is-active" : undefined}
              aria-pressed={view === item}
              onClick={() => setView(item)}
            >
              {t(`inspector.${item}`)}
            </button>
          ))}
      </nav>
      {view === "overview" ? <section class="architecture-inspector-section" aria-live="polite">
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
            </div>
          </>
        ) : (
          <>
            <span class="eyebrow">{t("inspector.scopeOverview")}</span>
            <h3>{t("inspector.scopeTitle")}</h3>
            <p class="architecture-inspector-copy">{t("inspector.scopeDescription")}</p>
            <dl class="architecture-resource-summary">
              <dt>{t("resources")}</dt><dd>{graph.resources.length.toLocaleString()}</dd>
              <dt>{t("relationships")}</dt><dd>{graph.links.length.toLocaleString()}</dd>
              <dt>{t("scope")}</dt><dd>{graph.active_view ?? graph.scope ?? t("inspector.defaultScope")}</dd>
            </dl>
          </>
        )}
      </section> : null}
      {view === "relationships" ? (
        <section class="architecture-inspector-section architecture-relationships">
          <h3>{t("directRelationships")}</h3>
          {!selected ? <p>{t("inspector.selectForRelationships")}</p> : relationships.length > 0 ? (
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
      ) : null}
      {view === "path" && mode === "network" ? pathContent : null}
      {view === "sources" ? (
        <section class="architecture-inspector-section">
          <h3>{t("inspector.sources")}</h3>
          <dl class="architecture-source-facts">
            <div><dt>{t("source")}</dt><dd>{sourceLabel}</dd></div>
            <div><dt>{t("inspector.snapshotTime")}</dt><dd><time dateTime={graph.snapshot_at}>{graph.snapshot_at}</time></dd></div>
            <div><dt>{t("inspector.freshness")}</dt><dd>{graph.freshness}</dd></div>
            <div><dt>{t("inspector.displayedResources")}</dt><dd>{displayedGraph.resources.length.toLocaleString()} / {graph.resources.length.toLocaleString()}</dd></div>
            <div><dt>{t("inspector.displayedRelationships")}</dt><dd>{displayedGraph.links.length.toLocaleString()} / {graph.links.length.toLocaleString()}</dd></div>
            <div><dt>{t("inspector.completeness")}</dt><dd>{graph.truncated ? t("inspector.partial") : t("inspector.complete")}</dd></div>
            <div><dt>{t("inspector.relationshipTypes")}</dt><dd>{graph.included_link_types.join(", ") || t("unavailable")}</dd></div>
          </dl>
          {graph.truncated ? (
            <p class="architecture-source-warning">{t("partialDescription")}</p>
          ) : null}
          {selected ? (
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
          ) : null}
        </section>
      ) : null}
    </aside>
  );
}
